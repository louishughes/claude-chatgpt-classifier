"""NOTE-004: a dry run on 3 synthetic chats, end to end, as a Claude session would do it.

request files -> a "session" (this test) appends answers -> collect -> rich notes.
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
from knowledge_engine.importer import import_source
from knowledge_engine.importer.records import ConversationRow
from knowledge_engine.infrastructure.db import create_sqlite_engine, database_path
from knowledge_engine.settings import load_settings

CASE = Path(__file__).resolve().parents[1] / "fixtures" / "chatgpt" / "extraction_rules"
_TAG = re.compile(r"^\[m:([^\]]+)\] (\w+):\n(.+)$", re.M)


def _cli(capsys: pytest.CaptureFixture[str], *args: str) -> tuple[int, dict[str, Any]]:
    capsys.readouterr()
    code = main(["--json", *args])
    return code, json.loads(capsys.readouterr().out)


def _answer(line: dict[str, Any]) -> dict[str, Any]:
    """What a careful session writes: short exact quotes from the messages shown."""
    tags = _TAG.findall(line["input_text"])
    first_id, _, first_text = tags[0]
    last_id, _, last_text = tags[-1]
    start = [{"message_id": first_id, "text": " ".join(first_text.split()[:3])}]
    end = [{"message_id": last_id, "text": " ".join(last_text.split()[:3])}]
    return {
        "summary": [
            {"text": "The user opened with a request.", "quotes": start},
            {"text": "The chat ended here.", "quotes": end},
        ],
        "purpose": {"text": "Work something out.", "quotes": start},
        "status": {"value": "settled", "quotes": end},
        "intent": {"value": "decide", "text": "Choose an approach.", "quotes": start},
        "insights": [{"text": "A point worth keeping.", "quotes": end}],
        "next_steps": [{"text": "Try it and report back.", "quotes": end}],
    }


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("KE_WORKSPACE_ROOT", str(tmp_path / "ws"))
    monkeypatch.setenv("KE_MODEL_BATCH_ROOT", str(tmp_path / "private" / "model-batches"))
    import_source(CASE / "export", "fixture", settings=load_settings())
    return tmp_path


def test_egress_off_writes_no_request_file(
    workspace: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, payload = _cli(capsys, "digest", "run", "--all", "--run-id", "dry")

    assert (code, payload["error"]["code"]) == (2, "egress_off")
    assert not (workspace / "private").exists()


def test_three_chats_end_to_end(
    workspace: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("KE_EGRESS__TEXT_LLM", "true")
    vault = workspace / "vault"

    # 1. The engine writes the request files and waits.
    code, first = _cli(capsys, "digest", "run", "--all", "--run-id", "dry", "--vault", str(vault))
    assert code == 0
    assert first["data"] == {"done": 0, "pending": 3, "review_required": 0, "notes": 0, "chats": 3}
    run_dir = workspace / "private" / "model-batches" / "dry"
    [request_file] = sorted(run_dir.glob("*.request.jsonl"))

    # 2. The session answers each line, appending to the response file.
    lines = [json.loads(x) for x in request_file.read_text("utf-8").splitlines() if x.strip()]
    requests = [x for x in lines if "request_id" in x]
    assert len(requests) == 3
    response = request_file.with_name(request_file.name.replace(".request.", ".response."))
    with response.open("a", encoding="utf-8") as out:
        for line in requests:
            answer = {
                "request_id": line["request_id"],
                "output": _answer(line),
                "served_model": "dry-run",
                "session_ref": "test-session",
            }
            out.write(json.dumps(answer) + "\n")

    # 3. Run again: answers are collected, checked, and the notes written.
    code, second = _cli(capsys, "digest", "run", "--all", "--run-id", "dry", "--vault", str(vault))
    assert second["data"] == {"done": 3, "pending": 0, "review_required": 0, "notes": 3, "chats": 3}
    notes = sorted((vault / "Knowledge").glob("*.md"))
    assert len(notes) == 3
    for note in notes:
        text = note.read_text("utf-8")
        assert "Summary · generated, every sentence cited" in text
        assert "The user opened with a request." in text
        assert "digest step hasn't run" not in text
        assert "digest: generated, not scored" in text

    # 4. A third run asks nothing new: every answer comes from the cache.
    code, third = _cli(capsys, "digest", "run", "--all", "--run-id", "dry")
    assert third["data"]["done"] == 3
    assert len(list(run_dir.glob("*.request.jsonl"))) == 1


def test_docs_chat_uses_a_collected_digest(
    workspace: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("KE_EGRESS__TEXT_LLM", "true")
    _cli(capsys, "digest", "run", "--all", "--run-id", "dry")
    [request_file] = (workspace / "private" / "model-batches" / "dry").glob("*.request.jsonl")
    lines = [json.loads(x) for x in request_file.read_text("utf-8").splitlines() if x.strip()]
    response = request_file.with_name(request_file.name.replace(".request.", ".response."))
    response.write_text(
        "".join(
            json.dumps({"request_id": x["request_id"], "output": _answer(x)}) + "\n"
            for x in lines
            if "request_id" in x
        ),
        encoding="utf-8",
    )
    _cli(capsys, "digest", "run", "--all", "--run-id", "dry")

    # Later, with model access off again, a note still shows the stored digest.
    monkeypatch.setenv("KE_EGRESS__TEXT_LLM", "false")
    vault = workspace / "vault"
    engine = create_sqlite_engine(database_path(load_settings()))
    with Session(engine) as session:
        chat = session.scalars(select(ConversationRow.conversation_id)).first()
    engine.dispose()
    assert chat is not None
    code, _ = _cli(capsys, "docs", "chat", chat, "--vault", str(vault), "--template", "v2")
    assert code == 0
    [note] = (vault / "Knowledge").glob("*.md")
    assert "The chat ended here." in note.read_text("utf-8")
