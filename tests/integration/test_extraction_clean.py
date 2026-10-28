"""NOTE-016: a pasted profile and an assistant-drafted letter aren't the user's knowledge.

Seven chats start with the same custom-instruction profile, full of words
the preference rules react to. One chat has the assistant draft a letter
full of promises and suggestions. Without the cleaner the rule extractors
take requirements, actions and suggestions from both; with it, none.
"""

from __future__ import annotations

import json
from functools import partial
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from knowledge_engine.documents.rich_note import rich_conversation_note
from knowledge_engine.extraction import actions, decisions, preferences
from knowledge_engine.extraction.clean import workspace_cleaner
from knowledge_engine.extraction.records import KnowledgeRecord
from knowledge_engine.extraction.runner import RuleExtractor, run
from knowledge_engine.extraction.store import KnowledgeRecordRow
from knowledge_engine.extraction.text import segment_extraction_messages
from knowledge_engine.graph.offsets import quote_hash
from knowledge_engine.importer.records import ConversationRow
from knowledge_engine.importer.run import run_import
from knowledge_engine.infrastructure.db import create_sqlite_engine, database_path
from knowledge_engine.rendering.markdown import render_note
from knowledge_engine.rendering.transcript import load_conversation
from knowledge_engine.segmentation.overrides import load_segments
from knowledge_engine.settings import Settings

PROFILE = (
    "About me: I prefer British spelling. Answers must be short and must cite sources. "
    "I hate filler words."
)
LETTER = (
    "Here is a draft you can send:\n\n"
    "Dear Ms Synthetic,\n\n"
    "I will send the signed lease by Friday. You should check the boiler before winter, "
    "and I suggest we meet on Monday.\n\n"
    "Kind regards,\nSam\n\n"
    "Tell me if it needs a different tone."
)


def _chat(cid: str, turns: list[tuple[str, str]]) -> dict[str, Any]:
    mapping: dict[str, Any] = {"root": {"id": "root", "parent": None, "children": []}}
    parent = "root"
    for i, (role, text) in enumerate(turns):
        node = f"{cid}-{i}"
        mapping[node] = {
            "id": node,
            "parent": parent,
            "children": [],
            "message": {
                "id": node,
                "author": {"role": role},
                "create_time": 1704067200.0 + 60 * i,
                "content": {"content_type": "text", "parts": [text]},
                "metadata": {},
            },
        }
        mapping[parent]["children"].append(node)
        parent = node
    return {
        "id": cid,
        "title": f"Synthetic {cid}",
        "create_time": 1704067200.0,
        "mapping": mapping,
        "current_node": parent,
    }


@pytest.fixture
def session(tmp_path: Path) -> Any:
    chats = [
        _chat(
            f"topic{n}",
            [
                ("user", f"{PROFILE}\n\nWhat is a good name for synthetic plant number {n}?"),
                ("assistant", f"Try Fern {n}."),
            ],
        )
        for n in range(7)
    ]
    chats.append(
        _chat(
            "letter",
            [("user", "Write my landlord a short letter about the lease."), ("assistant", LETTER)],
        )
    )
    export = tmp_path / "export"
    export.mkdir()
    (export / "conversations.json").write_text(json.dumps(chats), encoding="utf-8")
    settings = Settings(workspace_root=tmp_path / "ws")
    run_import(export, "acct", format_id=None, settings=settings)
    engine = create_sqlite_engine(database_path(settings))
    with Session(engine) as s:
        yield s
    engine.dispose()


def _extract(session: Session, *, clean: bool) -> list[KnowledgeRecord]:
    cleaner = workspace_cleaner(session) if clean else None
    chats = [
        load_conversation(session, c)
        for c in session.scalars(select(ConversationRow.conversation_id))
    ]
    segments = []
    for chat in chats:
        for segment in load_segments(session, chat):
            messages = segment_extraction_messages(chat, segment)
            segments.append((segment.segment_id, cleaner.clean(messages) if cleaner else messages))
    revisions = [r for chat in chats for r in chat.revisions.values()]
    occurrences = actions.load_occurrences(session, revisions)
    run(
        session,
        segments,
        [
            RuleExtractor("decisions", decisions.EXTRACTOR_VERSION, decisions.extract_decisions),
            RuleExtractor(
                "preferences", preferences.EXTRACTOR_VERSION, preferences.extract_preferences
            ),
            RuleExtractor(
                "actions",
                actions.EXTRACTOR_VERSION,
                partial(actions.extract_actions, occurrences=occurrences),
            ),
        ],
    )
    return [
        KnowledgeRecord.model_validate_json(r.record_json)
        for r in session.scalars(select(KnowledgeRecordRow))
    ]


KINDS = {"requirement", "preference", "proposal", "recommendation", "action", "decision"}


def test_without_the_cleaner_the_profile_and_letter_become_knowledge(session: Session) -> None:
    # The baseline: proves the fixture really triggers the extractors.
    found = {r.record_type for r in _extract(session, clean=False)}
    assert {"requirement", "preference"} <= found
    assert found & {"action", "proposal", "recommendation"}


def test_with_the_cleaner_neither_becomes_knowledge(session: Session) -> None:
    records = [r for r in _extract(session, clean=True) if r.record_type in KINDS]
    assert records == [], [(r.record_type, r.assertion) for r in records]


def test_hidden_text_keeps_every_offset(session: Session) -> None:
    cleaner = workspace_cleaner(session)
    [cid] = session.scalars(
        select(ConversationRow.conversation_id).where(
            ConversationRow.native_conversation_id == "letter"
        )
    ).all()
    chat = load_conversation(session, cid)
    [segment] = load_segments(session, chat)
    original = segment_extraction_messages(chat, segment)
    cleaned = cleaner.clean(original)
    for before, after in zip(original, cleaned, strict=True):
        assert len(before.text) == len(after.text)
    letter = cleaned[-1].text
    assert "lease" not in letter and "Dear" not in letter
    # What stays is at the same place, so its quote still matches the archive.
    tail = "Tell me if it needs a different tone."
    at = letter.index(tail)
    assert original[-1].text[at : at + len(tail)] == tail
    assert quote_hash(letter[at : at + len(tail)]) == quote_hash(tail)


def test_an_untaken_suggestion_is_not_shown_as_supported(session: Session) -> None:
    _extract(session, clean=False)  # keep the letter's suggestions: none was answered
    [cid] = session.scalars(
        select(ConversationRow.conversation_id).where(
            ConversationRow.native_conversation_id == "letter"
        )
    ).all()
    text = render_note(rich_conversation_note(session, cid).model)
    suggestions = text.split("\n## Suggestions\n", 1)[1].split("\n## ", 1)[0]
    assert "Suggested by the assistant" in suggestions
    assert "supported" not in suggestions
    assert "not taken up" in suggestions


def test_extract_run_sends_the_model_cleaned_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from knowledge_engine.cli.main import main

    # The same chats, through `ke extract run` (NOTE-015): its requests must
    # not carry the profile or the drafted letter to the model.
    chats = [
        _chat(f"topic{n}", [("user", f"{PROFILE}\n\nName synthetic plant {n}?")]) for n in range(7)
    ]
    chats.append(_chat("letter", [("user", "Write my landlord a letter."), ("assistant", LETTER)]))
    export = tmp_path / "export"
    export.mkdir()
    (export / "conversations.json").write_text(json.dumps(chats), encoding="utf-8")
    monkeypatch.setenv("KE_WORKSPACE_ROOT", str(tmp_path / "ws"))
    monkeypatch.setenv("KE_MODEL_BATCH_ROOT", str(tmp_path / "private" / "batches"))
    monkeypatch.setenv("KE_EGRESS__TEXT_LLM", "true")
    run_import(export, "acct", format_id=None, settings=Settings(workspace_root=tmp_path / "ws"))

    assert main(["--json", "extract", "run", "--all", "--run-id", "r1"]) == 0, capsys.readouterr()
    sent = [
        json.loads(line)["input_text"]
        for request_file in (tmp_path / "private" / "batches" / "r1").glob("*.request.jsonl")
        for line in request_file.read_text("utf-8").splitlines()
        if line.strip() and "input_text" in line
    ]
    assert sent, "no requests were written"
    assert not any("British spelling" in text or "Dear Ms Synthetic" in text for text in sent)
    assert any("Name synthetic plant" in text for text in sent)  # the real question still goes
