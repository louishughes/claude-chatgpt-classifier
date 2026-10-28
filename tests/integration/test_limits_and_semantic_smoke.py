"""OPS-002 limits and the EVAL-011 semantic batch smoke test."""

from __future__ import annotations

import zipfile
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from knowledge_engine.evaluation.semantic_smoke import Faults, run_semantic_smoke
from knowledge_engine.evaluation.synthetic import write_generated
from knowledge_engine.importer import import_source
from knowledge_engine.infrastructure.db import create_sqlite_engine, database_path
from knowledge_engine.infrastructure.logs import EventLog, search
from knowledge_engine.infrastructure.migrations import upgrade_to_head
from knowledge_engine.ingestion.chatgpt_export import ChatGPTExportAdapter
from knowledge_engine.ingestion.source import SourceTooLargeError
from knowledge_engine.orchestration.limits import RunBudget
from knowledge_engine.providers.base import FakeProvider, ModelRequest
from knowledge_engine.providers.ledger import (
    LIMIT_CALLS,
    LIMIT_TOKENS,
    TIMEOUT,
    ModelRequestRow,
    ModelStageRunner,
)
from knowledge_engine.settings import EgressPolicy, Limits, Settings


class Answer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ok: bool


def _request(n: int, text: str = "Synthetic.") -> ModelRequest:
    return ModelRequest(f"stg_{n:064x}", "test.stage.v1", "Synthetic.", text, Answer, "p1", "s1")


def test_synthetic_overload_exits_with_recorded_capped_failures(tmp_path: Path) -> None:
    limits = Limits(
        max_model_calls_per_run=5, max_requests_per_batch=2, max_input_tokens_per_request=100
    )
    log = EventLog(tmp_path / "logs")
    engine = create_sqlite_engine(tmp_path / "k.db")
    upgrade_to_head(engine)
    bad_first = {_request(2).request_id}

    def answer(request: ModelRequest) -> str:
        broken = request.attempt == 1 and request.request_id in bad_first
        return "Synthetic not json" if broken else '{"ok": true}'

    provider = FakeProvider(answer)
    requests = [_request(n) for n in range(1, 11)] + [_request(99, "x" * 1000)]
    with Session(engine) as session:
        budget = RunBudget(limits, log=log)
        runner = ModelStageRunner(
            session, provider, EgressPolicy(text_llm=True), log=log, budget=budget
        )
        sent = runner.submit(requests)
        # 10 small requests want calls, the budget allows 5, in batches of 2.
        assert len(sent.submitted) == 5 and len(sent.capped) == 5
        oversize = session.get(ModelRequestRow, _request(99).request_id)
        assert oversize is not None and (oversize.state, oversize.last_error) == (
            "review_required",
            LIMIT_TOKENS,
        )
        got = runner.collect(requests)
        # Request 2 answered badly, but the budget is spent: no repair call.
        assert got.review_required == [_request(2).request_id]
        row = session.get(ModelRequestRow, _request(2).request_id)
        assert row is not None and row.last_error == LIMIT_CALLS
        assert len(provider.submitted) == 5  # never more calls than the cap
    engine.dispose()
    submitted = search(tmp_path / "logs", event="model.submitted")
    per_batch = Counter(str(e["batch_id"]) for e in submitted)
    assert sorted(per_batch.values()) == [1, 2, 2]  # never more than 2 at once
    reached = [e["limit_name"] for e in search(tmp_path / "logs", event="limit.reached")]
    assert reached == [
        "max_input_tokens_per_request",
        "max_model_calls_per_run",
        "max_model_calls_per_run",
    ]


def test_a_silent_provider_times_out_and_is_recorded(tmp_path: Path) -> None:
    limits = Limits(max_model_calls_per_run=10, provider_timeout_s=60)
    engine = create_sqlite_engine(tmp_path / "k.db")
    upgrade_to_head(engine)
    with Session(engine) as session:
        runner = ModelStageRunner(
            session,
            FakeProvider(lambda r: None),
            EgressPolicy(text_llm=True),
            budget=RunBudget(limits),
        )
        runner.submit([_request(1)])
        assert runner.collect([_request(1)]).pending == [_request(1).request_id]
        later = datetime.now(UTC) + timedelta(seconds=61)
        runner.clock = lambda: later
        assert runner.collect([_request(1)]).review_required == [_request(1).request_id]
        row = session.get(ModelRequestRow, _request(1).request_id)
        assert row is not None and (row.state, row.last_error) == ("review_required", TIMEOUT)
    engine.dispose()


def test_zip_with_too_many_members_is_refused(tmp_path: Path) -> None:
    archive = tmp_path / "export.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("conversations.json", "[]")
        for n in range(5):
            zf.writestr(f"file-{n}.txt", "Synthetic")
    adapter = ChatGPTExportAdapter()
    assert adapter.open(archive, max_bytes=1000).files  # within the default limit
    with pytest.raises(SourceTooLargeError, match="over 3 members"):
        adapter.open(archive, max_bytes=1000, max_entries=3)


@pytest.mark.parametrize("count", [50, 100])
def test_semantic_smoke_at_50_and_100(tmp_path: Path, count: int) -> None:
    source = write_generated(tmp_path / "src", count, seed=11) / "export"
    settings = Settings(workspace_root=tmp_path / "ws")
    import_source(source, "smoke", settings=settings)
    log = EventLog(settings.workspace_root / "logs")
    engine = create_sqlite_engine(database_path(settings))
    limits = Limits(max_model_calls_per_run=10_000, max_requests_per_batch=25)
    with Session(engine) as session:
        report = run_semantic_smoke(
            session,
            limit=count,
            limits=limits,
            faults=Faults(invalid_every=7, silent_every=13),
            log=log,
        )
    engine.dispose()
    assert report["passed"], report["checks"]
    assert report["conversations"] == count
    classification = report["classification"]
    assert classification["timeouts"] > 0 and classification["schema"]["repaired"] > 0
    assert classification["done"] + classification["review_required"] == report["segments"]
    assert report["extraction"]["interrupted"]["deferred"] > 0
    assert report["extraction"]["resumed"]["repeated"] == 0
    assert report["unvalidated_outputs"] == 0 and report["stability"] == 1.0
    assert "Synthetic" not in (settings.workspace_root / "logs").joinpath(
        next((settings.workspace_root / "logs").glob("*.jsonl")).name
    ).read_text("utf-8")


def test_semantic_smoke_under_a_tight_budget_stops_recorded(tmp_path: Path) -> None:
    source = write_generated(tmp_path / "src", 20, seed=12) / "export"
    settings = Settings(workspace_root=tmp_path / "ws")
    import_source(source, "smoke", settings=settings)
    engine = create_sqlite_engine(database_path(settings))
    with Session(engine) as session:
        report = run_semantic_smoke(
            session, limit=20, limits=Limits(max_model_calls_per_run=10), faults=Faults()
        )
    engine.dispose()
    assert report["passed"], report["checks"]
    assert report["classification"]["capped"] > 0
    assert report["classification"]["model_calls"] == 10
    assert "max_model_calls_per_run" in report["classification"]["limits_reached"]


def test_cli_runs_on_a_scratch_copy(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    import json

    from knowledge_engine.cli.main import main

    source = write_generated(tmp_path / "src", 10, seed=13) / "export"
    settings = Settings(workspace_root=tmp_path / "ws")
    import_source(source, "smoke", settings=settings)
    before = database_path(settings).read_bytes()
    monkeypatch.setenv("KE_WORKSPACE_ROOT", str(settings.workspace_root))
    assert main(["--json", "eval", "semantic", "--limit", "10"]) == 0
    data = json.loads(capsys.readouterr().out)["data"]
    assert data["passed"] and data["conversations"] == 10
    assert database_path(settings).read_bytes() == before  # the real database is untouched
    # A tight budget still ends with every outcome recorded.
    assert main(["--json", "eval", "semantic", "--limit", "10", "--max-calls", "3"]) == 0
    assert json.loads(capsys.readouterr().out)["data"]["classification"]["capped"] > 0
