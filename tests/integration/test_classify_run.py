"""`ke classify run`: label chats under a published taxonomy through request files.

The same dry-run shape as NOTE-004: the engine writes requests, a "session"
(this test) appends answers, the next run collects, validates and stores them.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from knowledge_engine.classification.store import ClassificationRow
from knowledge_engine.cli.main import main
from knowledge_engine.importer import import_source
from knowledge_engine.importer.records import ConversationRow
from knowledge_engine.infrastructure.db import create_sqlite_engine, database_path
from knowledge_engine.settings import load_settings
from knowledge_engine.taxonomy.registry import Dimension, TaxonomyRegistry, TermStatus

CASE = Path(__file__).resolve().parents[1] / "fixtures" / "chatgpt" / "extraction_rules"
_MESSAGE = re.compile(r"\[m:([^\]]+)\]")


def _cli(capsys: pytest.CaptureFixture[str], *args: str) -> tuple[int, dict[str, Any]]:
    capsys.readouterr()
    code = main(["--json", *args])
    return code, json.loads(capsys.readouterr().out)


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, str]:
    monkeypatch.setenv("KE_WORKSPACE_ROOT", str(tmp_path / "ws"))
    monkeypatch.setenv("KE_MODEL_BATCH_ROOT", str(tmp_path / "private" / "model-batches"))
    settings = load_settings()
    import_source(CASE / "export", "fixture", settings=settings)
    engine = create_sqlite_engine(database_path(settings))
    with Session(engine) as session:
        registry = TaxonomyRegistry(session)
        home = registry.add_term(Dimension.DOMAIN, "Home", status=TermStatus.APPROVED)
        registry.publish("tax-1", author="owner")
        session.commit()
        term = home.term_id
    engine.dispose()
    return tmp_path, term


def _answer(line: dict[str, Any], term: str) -> dict[str, Any]:
    first = _MESSAGE.search(line["input_text"])
    assert first is not None
    return {
        "domain": [
            {"term_id": term, "rank": "primary", "confidence": 0.8, "evidence": [first.group(1)]}
        ]
    }


def test_needs_a_published_version_and_egress(
    workspace: tuple[Path, str], capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    code, payload = _cli(capsys, "classify", "run", "--all", "--taxonomy", "tax-9", "--run-id", "x")
    assert (code, payload["error"]["code"]) == (2, "no_taxonomy")
    code, payload = _cli(capsys, "classify", "run", "--all", "--taxonomy", "tax-1", "--run-id", "x")
    assert (code, payload["error"]["code"]) == (2, "egress_off")
    assert not (workspace[0] / "private").exists()


def test_requests_then_answers_then_stored_labels(
    workspace: tuple[Path, str], capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    root, term = workspace
    monkeypatch.setenv("KE_EGRESS__TEXT_LLM", "true")
    args = ("classify", "run", "--all", "--taxonomy", "tax-1", "--run-id", "gold")

    code, first = _cli(capsys, *args)
    assert code == 0 and first["data"]["done"] == 0
    segments = first["data"]["segments"]
    assert first["data"]["pending"] == segments > 0

    run_dir = root / "private" / "model-batches" / "gold"
    for request_file in sorted(run_dir.glob("*.request.jsonl")):
        lines = [json.loads(x) for x in request_file.read_text("utf-8").splitlines() if x.strip()]
        response = request_file.with_name(request_file.name.replace(".request.", ".response."))
        with response.open("a", encoding="utf-8") as out:
            for line in (x for x in lines if "request_id" in x):
                answer = {
                    "request_id": line["request_id"],
                    "output": _answer(line, term),
                    "served_model": "dry-run",
                    "session_ref": "test-session",
                }
                out.write(json.dumps(answer) + "\n")

    code, second = _cli(capsys, *args)
    assert second["data"]["done"] == segments and second["data"]["pending"] == 0

    settings = load_settings()
    engine = create_sqlite_engine(database_path(settings))
    with Session(engine) as session:
        rows = session.scalars(select(ClassificationRow)).all()
        assert len(rows) == segments
        assert {r.taxonomy_version for r in rows} == {"tax-1"}
        assert {r.state for r in rows} == {"done"}
        chats = session.scalars(select(ConversationRow.conversation_id)).all()
    engine.dispose()

    # A chosen list of chats, from a file, asks only for those.
    ids = root / "private" / "ids.txt"
    ids.write_text(f"# one per line\n{chats[0]}\n", encoding="utf-8")
    code, third = _cli(
        capsys, "classify", "run", "--ids-file", str(ids), "--taxonomy", "tax-1", "--run-id", "gold"
    )
    assert third["data"]["chats"] == 1 and third["data"]["pending"] == 0
