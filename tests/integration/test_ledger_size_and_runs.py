"""LEG-006 and LEG-007: an oversize request is recorded, and a waiting request finds its run.

Found on the owner's PC: one message bigger than a request file stopped a
whole classify run, and pending rows from an earlier run could not be
collected once a new ``--run-id`` was used. All texts are synthetic.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Literal

import pytest
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from knowledge_engine.infrastructure.db import create_sqlite_engine
from knowledge_engine.infrastructure.migrations import upgrade_to_head
from knowledge_engine.orchestration.stage_keys import stage_key
from knowledge_engine.providers.base import ModelRequest
from knowledge_engine.providers.file_batch import FileBatchProvider
from knowledge_engine.providers.ledger import (
    LIMIT_PROVIDER,
    PENDING,
    REVIEW_REQUIRED,
    ModelRequestRow,
    ModelStageRunner,
    not_answered,
)
from knowledge_engine.settings import EgressPolicy

ON = EgressPolicy(text_llm=True)


class Label(BaseModel):
    model_config = ConfigDict(extra="forbid")

    domain: Literal["work", "home"]


def _request(text: str) -> ModelRequest:
    key = stage_key(
        "test.label.v1",
        hashlib.sha256(text.encode()).hexdigest(),
        {"code": "1", "prompt": "p1", "schema": "s1"},
    )
    return ModelRequest(key, "test.label.v1", "Label it.", text, Label, "p1", "s1")


def _answer(folder: Path, batch: str, request_id: str) -> None:
    line = {"request_id": request_id, "output": {"domain": "work"}, "served_model": "m"}
    (folder / f"{batch}.response.jsonl").write_text(json.dumps(line) + "\n", encoding="utf-8")


@pytest.fixture
def session(tmp_path: Path) -> Iterator[Session]:
    engine = create_sqlite_engine(tmp_path / "k.db")
    upgrade_to_head(engine)
    with Session(engine) as db:
        yield db
    engine.dispose()


def test_a_request_too_big_for_a_batch_is_recorded_and_the_run_carries_on(
    tmp_path: Path, session: Session
) -> None:
    provider = FileBatchProvider(tmp_path, "run1", ON, max_characters=500)
    small, huge = _request("Synthetic small"), _request("Synthetic " + "word " * 200)
    report = ModelStageRunner(session, provider, ON).submit([small, huge])

    assert report.submitted == [small.request_id]
    assert report.review_required == [huge.request_id] == report.too_big
    sent = (tmp_path / "run1" / "batch-00001.request.jsonl").read_text(encoding="utf-8")
    assert small.request_id in sent and huge.request_id not in sent
    row = session.get(ModelRequestRow, huge.request_id)
    assert row is not None and row.state == REVIEW_REQUIRED
    assert row.last_error == LIMIT_PROVIDER and row.characters == 0  # nothing was sent
    assert not_answered(session)["too_big"] == 1
    # Asked again, it is still too big, and is said to be, not re-sent.
    again = ModelStageRunner(session, provider, ON).submit([small, huge])
    assert again.too_big == [huge.request_id] and again.submitted == []


def test_a_waiting_request_is_collected_from_its_own_run(tmp_path: Path, session: Session) -> None:
    first = FileBatchProvider(tmp_path, "run-a", ON)
    ask = _request("Synthetic waiting")
    ModelStageRunner(session, first, ON).submit([ask])
    row = session.get(ModelRequestRow, ask.request_id)
    assert row is not None and row.run_id == "run-a"

    _answer(tmp_path / "run-a", "batch-00001", ask.request_id)
    later = FileBatchProvider(tmp_path, "run-b", ON)
    report = ModelStageRunner(session, later, ON).collect([ask])
    assert report.outputs == {ask.request_id: Label(domain="work")}
    assert not (tmp_path / "run-b").exists()  # nothing asked again


def test_a_request_whose_batch_files_are_gone_is_asked_again(
    tmp_path: Path, session: Session
) -> None:
    first = FileBatchProvider(tmp_path, "run-a", ON)
    lost, kept = _request("Synthetic lost"), _request("Synthetic kept")
    runner = ModelStageRunner(session, first, ON)
    runner.submit([lost])
    runner.submit([kept])
    for path in (tmp_path / "run-a").glob("batch-00001.*"):
        path.unlink()  # the owner tidied the folder

    later = FileBatchProvider(tmp_path, "run-b", ON)
    report = ModelStageRunner(session, later, ON).collect([lost, kept])
    assert report.resent == [lost.request_id]
    assert report.pending == [kept.request_id]  # its batch is still there: just waiting
    row = session.get(ModelRequestRow, lost.request_id)
    assert row is not None and row.state == PENDING and row.run_id == "run-b"
    assert lost.request_id in (tmp_path / "run-b" / "batch-00001.request.jsonl").read_text(
        encoding="utf-8"
    )
    _answer(tmp_path / "run-b", "batch-00001", lost.request_id)
    done = ModelStageRunner(session, later, ON).collect([lost])
    assert done.outputs == {lost.request_id: Label(domain="work")}
