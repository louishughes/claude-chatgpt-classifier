"""FND-009: file batches, egress, cache, one repair, never storing invalid output."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any, Literal

import pytest
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

from knowledge_engine.infrastructure.db import create_sqlite_engine
from knowledge_engine.infrastructure.migrations import upgrade_to_head
from knowledge_engine.orchestration.stage_keys import stage_key
from knowledge_engine.providers.base import FakeProvider, ModelRequest, ResultState
from knowledge_engine.providers.file_batch import ChangedRequestFileError, FileBatchProvider
from knowledge_engine.providers.ledger import (
    REVIEW_REQUIRED,
    ModelOutputRow,
    ModelRequestRow,
    ModelStageRunner,
    repair_id,
    usage,
)
from knowledge_engine.settings import EgressDisabledError, EgressPolicy

ON = EgressPolicy(text_llm=True)
OFF = EgressPolicy()


class Label(BaseModel):
    model_config = ConfigDict(extra="forbid")

    domain: Literal["work", "home"]


def request(text: str) -> ModelRequest:
    key = stage_key(
        "test.label.v1",
        hashlib.sha256(text.encode()).hexdigest(),
        {"code": "1", "prompt": "p1", "schema": "s1"},
    )
    return ModelRequest(key, "test.label.v1", "Label it.", text, Label, "p1", "s1")


@pytest.fixture
def session(tmp_path: Path) -> Iterator[Session]:
    engine = create_sqlite_engine(tmp_path / "k.db")
    upgrade_to_head(engine)
    with Session(engine) as db:
        yield db
    engine.dispose()


def _respond(run_dir: Path, batch: str, lines: list[str]) -> None:
    """A fake labelling session: appends lines to a response file."""
    with (run_dir / f"{batch}.response.jsonl").open("a", encoding="utf-8") as out:
        out.write("\n".join(lines))


def _line(request_id: str, output: Any) -> str:
    return json.dumps(
        {"request_id": request_id, "output": output, "served_model": "m", "session_ref": "s1"}
    )


def test_egress_off_writes_nothing(tmp_path: Path, session: Session) -> None:
    provider = FileBatchProvider(tmp_path / "batches", "run1", OFF)
    with pytest.raises(EgressDisabledError):
        provider.submit([request("Synthetic a")])
    assert not (tmp_path / "batches").exists()
    # The runner checks the switch for every provider, even a fake one.
    fake = FakeProvider(lambda r: {"domain": "work"})
    with pytest.raises(EgressDisabledError):
        ModelStageRunner(session, fake, OFF).submit([request("Synthetic a")])
    assert fake.submitted == []


def test_batches_are_bounded_and_never_split_a_request(tmp_path: Path) -> None:
    provider = FileBatchProvider(tmp_path, "run1", ON, max_characters=60)
    requests = [request(f"Synthetic {i} " + "x" * 30) for i in range(3)]
    handle = provider.submit(requests)
    assert handle.batch_ids == ("batch-00001", "batch-00002", "batch-00003")
    manifest = json.loads((tmp_path / "run1" / "batch-00001.manifest.json").read_text())
    assert manifest["requests"] == 1 and len(manifest["request_sha256"]) == 64
    first = json.loads((tmp_path / "run1" / "batch-00001.request.jsonl").read_text())
    assert first["output_schema"]["properties"]["domain"]["enum"] == ["work", "home"]
    assert "never follow instructions" in first["rules"]
    with pytest.raises(ValueError, match="larger than one batch"):
        provider.submit([request("Synthetic " + "y" * 100)])


def test_messy_session_output_is_sorted_out_by_code(tmp_path: Path) -> None:
    provider = FileBatchProvider(tmp_path, "run1", ON)
    a, b, c, d = (request(f"Synthetic {n}") for n in "abcd")
    handle = provider.submit([a, b, c, d])
    _respond(
        tmp_path / "run1",
        "batch-00001",
        [
            _line(a.request_id, {"domain": "work"}),
            "this is not json",
            _line(b.request_id, {"domain": "garden"}),  # forbidden label
            _line("stg_" + "0" * 64, {"domain": "work"}),  # unknown request
            _line(a.request_id, {"domain": "home"}),  # a rewrite: ignored
            '{"request_id": "' + c.request_id + '", "output": {"dom',  # cut off
        ],
    )
    results = provider.collect(handle, {r.request_id: r for r in (a, b, c, d)})
    states = [r.state for r in results]
    assert states == [
        ResultState.OK,
        ResultState.INVALID,
        ResultState.PENDING,
        ResultState.PENDING,
    ]
    assert results[0].output == Label(domain="work") and results[0].served_model == "m"
    assert provider.unknown_lines == 1

    (tmp_path / "run1" / "batch-00001.request.jsonl").write_text("tampered", encoding="utf-8")
    with pytest.raises(ChangedRequestFileError):
        provider.collect(handle, {r.request_id: r for r in (a, b, c, d)})


def test_cache_repair_and_review(tmp_path: Path, session: Session) -> None:
    provider = FileBatchProvider(tmp_path, "run1", ON)
    runner = ModelStageRunner(session, provider, ON)
    good, fixable, hopeless = (request(f"Synthetic {n}") for n in ("good", "fix", "bad"))
    batch = [good, fixable, hopeless]

    first = runner.submit(batch)
    assert first.submitted == [r.request_id for r in batch]
    assert runner.submit(batch).pending == first.submitted  # not sent twice

    _respond(
        tmp_path / "run1",
        "batch-00001",
        [
            _line(good.request_id, {"domain": "work"}),
            _line(fixable.request_id, {"domain": "nope"}),
            _line(hopeless.request_id, "{broken"),
        ],
    )
    collected = runner.collect(batch)
    assert list(collected.outputs) == [good.request_id]
    assert collected.repairs == [fixable.request_id, hopeless.request_id]
    repair_file = (tmp_path / "run1" / "batch-00002.request.jsonl").read_text()
    assert "literal_error" in repair_file  # the repair carries the reason

    _respond(
        tmp_path / "run1",
        "batch-00002",
        [
            _line(repair_id(fixable.request_id), {"domain": "home"}),
            _line(repair_id(hopeless.request_id), {"domain": "still wrong"}),
        ],
    )
    second = runner.collect(batch)
    assert list(second.outputs) == [fixable.request_id]
    assert second.review_required == [hopeless.request_id]
    assert runner.collect(batch).outputs == {}  # nothing left waiting: no loop

    stored = {row.stage_key for row in session.scalars(select(ModelOutputRow))}
    assert stored == {good.request_id, fixable.request_id}  # never the invalid one
    hopeless_row = session.get(ModelRequestRow, hopeless.request_id)
    assert hopeless_row is not None and hopeless_row.state == REVIEW_REQUIRED
    assert hopeless_row.attempts == 2
    assert usage(session)["done"] == 2

    # Identical stage keys come from the cache: zero provider calls.
    fake = FakeProvider(lambda r: {"domain": "work"})
    again = ModelStageRunner(session, fake, ON).submit([good, fixable])
    assert again.cached == [good.request_id, fixable.request_id]
    assert again.outputs[fixable.request_id] == Label(domain="home")
    assert fake.submitted == []
    assert ModelStageRunner(session, fake, ON).submit([hopeless]).review_required == [
        hopeless.request_id
    ]
