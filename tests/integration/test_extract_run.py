"""NOTE-015 `ke extract run` and NOTE-020 `ke digest run --taxonomy`, through request files.

The same dry-run shape as NOTE-004: the engine writes requests, a "session"
(this test) appends answers, and the next run collects and stores them.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from knowledge_engine.cli.main import main
from knowledge_engine.extraction.store import KnowledgeRecordRow
from knowledge_engine.importer import import_source
from knowledge_engine.infrastructure.db import create_sqlite_engine, database_path
from knowledge_engine.settings import load_settings
from knowledge_engine.taxonomy.registry import Dimension, TaxonomyRegistry, TermStatus

CASE = Path(__file__).resolve().parents[1] / "fixtures" / "chatgpt" / "extraction_rules"
_TAG = re.compile(r"^\[m:([^\]]+)\] (\w+):\n(.+)$", re.M)


def _cli(capsys: pytest.CaptureFixture[str], *args: str) -> tuple[int, dict[str, Any]]:
    capsys.readouterr()
    code = main(["--json", *args])
    return code, json.loads(capsys.readouterr().out)


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("KE_WORKSPACE_ROOT", str(tmp_path / "ws"))
    monkeypatch.setenv("KE_MODEL_BATCH_ROOT", str(tmp_path / "private" / "model-batches"))
    import_source(CASE / "export", "fixture", settings=load_settings())
    return tmp_path


def _answer_all(run_dir: Path, answer: Any) -> int:
    """Append an answer for every request not yet answered; return how many requests exist."""
    asked = 0
    for request_file in sorted(run_dir.glob("*.request.jsonl")):
        lines = [json.loads(x) for x in request_file.read_text("utf-8").splitlines() if x.strip()]
        requests = [x for x in lines if "request_id" in x]
        asked += len(requests)
        response = request_file.with_name(request_file.name.replace(".request.", ".response."))
        answered = set()
        if response.exists():
            answered = {
                json.loads(x)["request_id"]
                for x in response.read_text("utf-8").splitlines()
                if x.strip()
            }
        with response.open("a", encoding="utf-8") as out:
            for line in requests:
                if line["request_id"] in answered:
                    continue
                out.write(
                    json.dumps(
                        {
                            "request_id": line["request_id"],
                            "output": answer(line),
                            "served_model": "dry-run",
                            "session_ref": "test-session",
                        }
                    )
                    + "\n"
                )
    return asked


def _question(line: dict[str, Any]) -> dict[str, Any]:
    """One user question per request, quoting the first user message's opening words."""
    users = [(m, t) for m, role, t in _TAG.findall(line["input_text"]) if role == "user"]
    if not users:
        return {"records": []}
    message_id, text = users[0]
    return {
        "records": [
            {
                "record_type": "question",
                "assertion": "Synthetic: what the user asked",
                "actor": "user",
                "acceptance": "not_applicable",
                "quotes": [{"message_id": message_id, "text": " ".join(text.split()[:2])}],
            }
        ]
    }


def test_extract_needs_egress(workspace: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, payload = _cli(capsys, "extract", "run", "--all", "--run-id", "x")

    assert (code, payload["error"]["code"]) == (2, "egress_off")
    assert not (workspace / "private").exists()


def test_extract_requests_then_records_then_nothing_new(
    workspace: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("KE_EGRESS__TEXT_LLM", "true")
    args = ("extract", "run", "--all", "--run-id", "gold")

    code, first = _cli(capsys, *args)
    assert code == 0 and first["data"]["done"] == 0 and first["data"]["records"] == 0
    assert first["data"]["pending"] == first["data"]["segments"] > 0

    run_dir = workspace / "private" / "model-batches" / "gold"
    asked = _answer_all(run_dir, _question)
    assert asked > 0

    code, second = _cli(capsys, *args)
    assert second["data"]["pending"] == 0 and second["data"]["failed"] == 0
    assert second["data"]["done"] == first["data"]["segments"]
    assert second["data"]["records"] > 0

    engine = create_sqlite_engine(database_path(load_settings()))
    with Session(engine) as session:
        rows = session.scalars(select(KnowledgeRecordRow)).all()
        made = [json.loads(r.record_json) for r in rows]
    engine.dispose()
    model_made = [r for r in made if (r.get("provenance") or {}).get("prompt_version")]
    assert model_made and {r["record_type"] for r in model_made} == {"question"}

    # Identical material: no new request and no new record.
    code, third = _cli(capsys, *args)
    assert third["data"]["already_done"] == first["data"]["segments"]
    assert third["data"]["done"] == third["data"]["pending"] == third["data"]["records"] == 0
    assert _answer_all(run_dir, _question) == asked


def _digest(line: dict[str, Any]) -> dict[str, Any]:
    tags = _TAG.findall(line["input_text"])
    first_id, _, first_text = tags[0]
    quotes = [{"message_id": first_id, "text": " ".join(first_text.split()[:3])}]
    return {
        "summary": [{"text": "The user opened with a request.", "quotes": quotes}],
        "purpose": {"text": "Work something out.", "quotes": quotes},
        "status": {"value": "open", "quotes": quotes},
        "intent": {"value": "decide", "text": "Choose an approach.", "quotes": quotes},
    }


def test_digest_notes_use_the_newest_taxonomy_or_the_one_asked_for(
    workspace: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("KE_EGRESS__TEXT_LLM", "true")
    engine = create_sqlite_engine(database_path(load_settings()))
    with Session(engine) as session:
        registry = TaxonomyRegistry(session)
        registry.add_term(Dimension.DOMAIN, "Home", status=TermStatus.APPROVED)
        registry.publish("tax-1", author="owner")
        session.commit()
    engine.dispose()
    vault = workspace / "vault"

    code, bad = _cli(capsys, "digest", "run", "--all", "--run-id", "d", "--taxonomy", "tax-9")
    assert (code, bad["error"]["code"]) == (2, "no_taxonomy")

    _cli(capsys, "digest", "run", "--all", "--run-id", "d", "--vault", str(vault))
    _answer_all(workspace / "private" / "model-batches" / "d", _digest)
    code, done = _cli(capsys, "digest", "run", "--all", "--run-id", "d", "--vault", str(vault))
    assert code == 0 and done["data"]["notes"] == done["data"]["chats"] > 0
    assert "labels under tax-1" in done["message"]

    notes = sorted((vault / "Knowledge").glob("*.md"))
    assert len(notes) == done["data"]["chats"]
    for note in notes:
        assert "\ntaxonomy_version: tax-1\n" in note.read_text(encoding="utf-8")
