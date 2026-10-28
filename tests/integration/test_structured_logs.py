"""OPS-001: structured logs hold IDs and numbers, never private text or secrets."""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

import pytest
from pydantic import BaseModel, ConfigDict, SecretStr
from sqlalchemy import select
from sqlalchemy.orm import Session

from knowledge_engine.extraction import decisions
from knowledge_engine.extraction.records import CandidateRecord
from knowledge_engine.extraction.runner import RuleExtractor, run
from knowledge_engine.extraction.text import ExtractionMessage, segment_extraction_messages
from knowledge_engine.importer import import_source
from knowledge_engine.importer.records import ConversationRow
from knowledge_engine.infrastructure.db import create_sqlite_engine, database_path
from knowledge_engine.infrastructure.logs import (
    SECRET,
    EventLog,
    event_log,
    scrub,
    search,
    totals,
)
from knowledge_engine.infrastructure.migrations import upgrade_to_head
from knowledge_engine.providers.base import FakeProvider, ModelRequest
from knowledge_engine.providers.ledger import ModelStageRunner
from knowledge_engine.rendering.transcript import load_conversation
from knowledge_engine.segmentation.segmenter import segment_conversation
from knowledge_engine.settings import EgressPolicy, Settings

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "chatgpt"
# Built at run time so no secret-shaped literal sits in the repository.
FAKE_KEY = "sk-ant-" + "x1" * 20


def _log_text(directory: Path) -> str:
    return "".join(p.read_text("utf-8") for p in sorted(directory.glob("*.jsonl")))


def test_only_allowed_plain_fields_are_written(tmp_path: Path) -> None:
    log = EventLog(tmp_path)
    with pytest.raises(ValueError, match="not allowed"):
        log.emit("import.done", text="Synthetic private words")
    with pytest.raises(ValueError, match="plain value"):
        log.emit("import.done", count=[1, 2])  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="dotted identifier"):
        log.emit("Synthetic free text as an event name")
    assert not list(tmp_path.glob("*.jsonl"))  # refused events leave nothing behind


def test_secrets_are_scrubbed(tmp_path: Path) -> None:
    configured = "plain-looking-configured-value"
    log = EventLog(tmp_path, secrets=(configured,))
    line = log.emit(
        "model.stored",
        model=f"served with {FAKE_KEY}",
        batch_id=f"Bearer {'t' * 24}",
        provider_id=f"x {configured} y",
        version="api_key=abc123",
        stage_id="s" * 500,
    )
    text = _log_text(tmp_path)
    for leaked in (FAKE_KEY, "t" * 24, configured, "abc123"):
        assert leaked not in text
    assert line["model"] == f"served with {SECRET}"
    assert len(str(line["stage_id"])) == 200
    assert scrub("ghp_" + "a" * 30) == SECRET
    settings = Settings(
        workspace_root=tmp_path / "ws", anthropic_api_key=SecretStr("another-configured-value")
    )
    event_log(settings).emit("model.stored", model="another-configured-value")
    assert "another-configured-value" not in _log_text(tmp_path / "ws" / "logs")


def test_extraction_runs_are_logged_without_text_and_errors_by_type(tmp_path: Path) -> None:
    settings = Settings(workspace_root=tmp_path / "ws")
    import_source(FIXTURES / "extraction_rules" / "export", "fixture", settings=settings)
    engine = create_sqlite_engine(database_path(settings))
    log = event_log(settings)

    def broken(messages: Sequence[ExtractionMessage], *, segment_id: str) -> list[CandidateRecord]:
        raise RuntimeError(f"Synthetic crash quoting {messages[0].text}")

    with Session(engine) as session:
        segments = []
        for conversation_id in session.scalars(select(ConversationRow.conversation_id)).all():
            conv = load_conversation(session, conversation_id)
            segments += [
                (seg.segment_id, segment_extraction_messages(conv, seg))
                for seg in segment_conversation(conv)
            ]
        extractors = [
            RuleExtractor("decisions", decisions.EXTRACTOR_VERSION, decisions.extract_decisions),
            RuleExtractor("broken", "broken-v1", broken),
        ]
        report = run(session, segments, extractors, log=log)
        run(session, segments, extractors, log=log)  # done runs are skipped, not logged
    engine.dispose()
    directory = settings.workspace_root / "logs"
    text = _log_text(directory)
    assert "Synthetic" not in text  # no message text, no exception message
    failed = search(directory, event="extract.run", extractor="broken")
    assert len(failed) == 2 * len(segments)  # two tries each so far
    assert {(e["state"], e["error_type"]) for e in failed} == {("failed", "RuntimeError")}
    [first] = report.done[:1]
    lineage = search(directory, stage_key=first)
    assert [(e["event"], e["state"], e["outcome"]) for e in lineage] == [
        ("extract.run", "done", "ok")
    ]
    assert isinstance(lineage[0]["duration_ms"], float)


class Answer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ok: bool


def test_model_stage_lineage_is_searchable(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from knowledge_engine.cli.main import main

    settings = Settings(workspace_root=tmp_path / "ws")
    engine = create_sqlite_engine(tmp_path / "k.db")
    upgrade_to_head(engine)
    calls = {"n": 0}

    def answer(request: ModelRequest) -> str:
        calls["n"] += 1
        return "Synthetic not json" if calls["n"] == 1 else '{"ok": true}'

    request = ModelRequest(
        "stg_" + "c" * 64, "test.stage.v1", "Synthetic.", "Synthetic.", Answer, "p1", "s1"
    )
    with Session(engine) as session:
        runner = ModelStageRunner(
            session, FakeProvider(answer), EgressPolicy(text_llm=True), log=event_log(settings)
        )
        runner.submit([request])
        runner.collect([request])  # bad answer: one repair goes out
        runner.collect([request])  # the repair is stored
        runner.submit([request])  # now answered from the cache
    engine.dispose()
    directory = settings.workspace_root / "logs"
    lineage = search(directory, stage_key=request.request_id)
    assert [e["event"] for e in lineage] == [
        "model.submitted",
        "model.repair",
        "model.stored",
        "model.cached",
    ]
    assert totals(lineage)["characters"] > 0
    assert "Synthetic" not in _log_text(directory)
    monkeypatch.setenv("KE_WORKSPACE_ROOT", str(settings.workspace_root))
    assert main(["--json", "logs", "--stage-key", request.request_id]) == 0
    data = json.loads(capsys.readouterr().out)["data"]
    assert data["count"] == 4 and data["events"][0]["event"] == "model.submitted"
    with pytest.raises(ValueError, match="cannot search"):
        search(directory, text="anything")
