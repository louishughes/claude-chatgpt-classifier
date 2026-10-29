"""NOTE-031: a chat with no user or assistant text is never sent for a digest.

Every chat here is synthetic and written by the test.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from knowledge_engine.cli.main import main
from knowledge_engine.digest.stage import DigestStage, stored_digest
from knowledge_engine.documents.rich_note import NO_CONTENT, rich_conversation_note
from knowledge_engine.evaluation.note_checks import check_note
from knowledge_engine.importer import import_source
from knowledge_engine.importer.records import ConversationRow
from knowledge_engine.infrastructure.db import create_sqlite_engine, database_path
from knowledge_engine.providers.base import FakeProvider, ModelRequest
from knowledge_engine.providers.ledger import ModelRequestRow, ModelStageRunner
from knowledge_engine.rendering.markdown import render_note
from knowledge_engine.rendering.transcript import StoredConversation, load_conversation
from knowledge_engine.settings import EgressPolicy, Settings, load_settings


def _node(cid: str, n: int, role: str, text: str, parent: str) -> dict[str, Any]:
    return {
        "id": f"{cid}-{n}",
        "message": {
            "id": f"{cid}-{n}",
            "author": {"role": role, "name": None, "metadata": {}},
            "create_time": 1704067200.0 + n,
            "content": {"content_type": "text", "parts": [text]},
            "status": "finished_successfully",
            "metadata": {},
        },
        "parent": parent,
        "children": [],
    }


def _chat(cid: str, title: str, messages: list[tuple[str, str]]) -> dict[str, Any]:
    root = f"{cid}-root"
    mapping: dict[str, Any] = {root: {"id": root, "message": None, "parent": None, "children": []}}
    parent = root
    for n, (role, text) in enumerate(messages):
        node = _node(cid, n, role, text, parent)
        mapping[parent]["children"].append(node["id"])
        mapping[node["id"]] = node
        parent = node["id"]
    return {
        "id": cid,
        "conversation_id": cid,
        "title": title,
        "create_time": 1704067200.0,
        "update_time": 1704067300.0,
        "mapping": mapping,
        "current_node": parent,
    }


EMPTY = _chat(
    "c0310000-0000-4000-8000-000000000001",
    "Synthetic empty chat",
    [("system", ""), ("system", "Synthetic system setup."), ("user", ""), ("assistant", "  ")],
)
SPOKEN = _chat(
    "c0310000-0000-4000-8000-000000000002",
    "Synthetic one-line chat",
    [("system", ""), ("user", "Synthetic: how long do I boil an egg?")],
)


@pytest.fixture
def chats(tmp_path: Path) -> Iterator[tuple[Session, dict[str, StoredConversation]]]:
    export = tmp_path / "export"
    export.mkdir()
    (export / "conversations.json").write_text(json.dumps([EMPTY, SPOKEN]), encoding="utf-8")
    settings = Settings(workspace_root=tmp_path / "ws")
    import_source(export, "fixture", settings=settings)
    engine = create_sqlite_engine(database_path(settings))
    with Session(engine) as session:
        found = {}
        for cid in session.scalars(select(ConversationRow.conversation_id)):
            chat = load_conversation(session, cid)
            found[chat.title or ""] = chat
        yield session, found
    engine.dispose()


def _good(request: ModelRequest) -> dict[str, Any]:
    cite = [{"message_id": f"[m:{SPOKEN['current_node']}]", "text": "Synthetic"}]
    return {
        "summary": [{"text": "The user asked about eggs.", "quotes": cite}],
        "status": {"value": "open", "quotes": cite},
        "intent": {"value": "learn", "text": "Find out.", "quotes": cite},
    }


def _rows(session: Session) -> int:
    return session.scalar(select(func.count()).select_from(ModelRequestRow)) or 0


def test_a_chat_with_no_text_is_no_content_with_zero_requests(
    chats: tuple[Session, dict[str, StoredConversation]],
) -> None:
    session, found = chats
    provider = FakeProvider(_good)
    stage = DigestStage(ModelStageRunner(session, provider, EgressPolicy(text_llm=True)))

    outcome = stage.run(found["Synthetic empty chat"])

    assert outcome.state == "no_content" and outcome.digest is None
    assert outcome.request_ids == ()
    assert provider.submitted == [] and _rows(session) == 0
    # Re-running adds nothing, and nothing is asked even with egress off.
    off = DigestStage(ModelStageRunner(session, FakeProvider(_good), EgressPolicy()))
    assert off.run(found["Synthetic empty chat"]).state == "no_content"
    assert _rows(session) == 0
    assert stored_digest(session, found["Synthetic empty chat"]) is None


def test_a_chat_with_one_user_sentence_is_still_asked(
    chats: tuple[Session, dict[str, StoredConversation]],
) -> None:
    session, found = chats
    provider = FakeProvider(_good)
    stage = DigestStage(ModelStageRunner(session, provider, EgressPolicy(text_llm=True)))

    empty, spoken = stage.run_all([found["Synthetic empty chat"], found["Synthetic one-line chat"]])

    assert empty.state == "no_content"
    assert spoken.state == "done"
    assert len(provider.submitted) == 1 and _rows(session) == 1


def test_the_note_says_there_is_nothing_to_summarise(
    chats: tuple[Session, dict[str, StoredConversation]],
) -> None:
    session, found = chats
    empty = found["Synthetic empty chat"].conversation_id
    text = render_note(rich_conversation_note(session, empty).model)

    assert NO_CONTENT in text
    assert "Not written yet" not in text
    assert "digest: no_content" in text
    report = check_note(session, empty, text)
    assert not [f for f in report.findings if "cites no message" in " ".join(f.problems)]
    # A chat that has text but no digest yet still says it's waiting.
    spoken = found["Synthetic one-line chat"].conversation_id
    waiting = render_note(rich_conversation_note(session, spoken).model)
    assert NO_CONTENT not in waiting and "Not written yet" in waiting


def test_digest_run_counts_empty_chats_apart_and_writes_their_note(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    export = tmp_path / "export"
    export.mkdir()
    (export / "conversations.json").write_text(json.dumps([EMPTY]), encoding="utf-8")
    monkeypatch.setenv("KE_WORKSPACE_ROOT", str(tmp_path / "ws"))
    monkeypatch.setenv("KE_MODEL_BATCH_ROOT", str(tmp_path / "private" / "model-batches"))
    monkeypatch.setenv("KE_EGRESS__TEXT_LLM", "true")
    import_source(export, "fixture", settings=load_settings())
    vault = tmp_path / "vault"

    capsys.readouterr()
    code = main(["--json", "digest", "run", "--all", "--run-id", "empty", "--vault", str(vault)])
    payload = json.loads(capsys.readouterr().out)

    assert code == 0
    assert payload["data"] == {
        "done": 0,
        "pending": 0,
        "review_required": 0,
        "no_content": 1,
        "notes": 1,
        "chats": 1,
    }
    assert not list((tmp_path / "private" / "model-batches").rglob("*.request.jsonl"))
    [note] = (vault / "Knowledge").glob("*.md")
    assert NO_CONTENT in note.read_text("utf-8")
