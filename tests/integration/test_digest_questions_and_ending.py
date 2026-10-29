"""NOTE-032 and NOTE-033: open questions checked against the whole chat, and a
long chat's summary keeps how it ended.

The NOTE-013 step 2 score found repeated questions, offers called "not
answered" that the user accepted later, and long-chat summaries that stopped
before the end. Every chat is synthetic; the fake model's answers are built
from the tags of each request.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from knowledge_engine.digest.contract import ConversationDigest
from knowledge_engine.digest.stage import DigestStage, chat_messages, digest_parts
from knowledge_engine.documents.rich_note import rich_conversation_note
from knowledge_engine.importer.records import ConversationRow
from knowledge_engine.importer.run import run_import
from knowledge_engine.infrastructure.db import create_sqlite_engine, database_path
from knowledge_engine.providers.base import FakeProvider, ModelRequest
from knowledge_engine.providers.ledger import ModelStageRunner
from knowledge_engine.rendering.markdown import render_note
from knowledge_engine.rendering.transcript import StoredConversation, load_conversation
from knowledge_engine.settings import EgressPolicy, Settings

_TAG = re.compile(r"^\[m:([^\]]+)\] (\w+):\n(.+)$", re.M)
OFFER = "Want me to draft a synthetic letter to the council?"
CHATS: dict[str, list[tuple[str, str]]] = {
    "accepted": [
        ("user", "My synthetic hedge blocks the path."),
        ("assistant", f"You could ask the council to trim it. {OFFER}"),
        ("user", "Yes, go ahead."),
        ("assistant", "Here is a short synthetic letter to the council."),
    ],
    "ignored": [
        ("user", "My synthetic hedge blocks the path."),
        ("assistant", f"You could ask the council to trim it. {OFFER}"),
        ("user", "Which tool trims a hedge best?"),
        ("assistant", "Synthetic shears work well for a small hedge."),
    ],
    "offered": [
        turn
        for step in range(1, 7)
        for turn in (
            (
                "user",
                "Yes, go ahead with the planting plan."
                if step == 4
                else f"Synthetic step {step}: what should happen with the garden bed now?",
            ),
            (
                "assistant",
                "Mulch it today. Want me to draft a synthetic planting plan for the bed?"
                if step == 3
                else f"Synthetic step {step}: water the garden bed and add mulch today.",
            ),
        )
    ],
    "long": [
        turn
        for step in range(1, 10)
        for turn in (
            ("user", f"Synthetic step {step}: what should happen with the garden bed now?"),
            ("assistant", f"Synthetic step {step}: water the garden bed and add mulch today."),
        )
    ],
}


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
    return {"id": cid, "title": f"Synthetic {cid}", "create_time": 1704067200.0,
            "mapping": mapping, "current_node": parent}  # fmt: skip


@pytest.fixture
def session(tmp_path: Path) -> Iterator[Session]:
    export = tmp_path / "export"
    export.mkdir()
    chats = [_chat(cid, turns) for cid, turns in CHATS.items()]
    (export / "conversations.json").write_text(json.dumps(chats), encoding="utf-8")
    settings = Settings(workspace_root=tmp_path / "ws")
    run_import(export, "acct", format_id=None, settings=settings)
    engine = create_sqlite_engine(database_path(settings))
    with Session(engine) as s:
        yield s
    engine.dispose()


def _load(session: Session, native: str) -> StoredConversation:
    cid = session.scalar(
        select(ConversationRow.conversation_id).where(
            ConversationRow.native_conversation_id == native
        )
    )
    assert cid is not None
    return load_conversation(session, cid)


def _cite(tag: tuple[str, str, str]) -> list[dict[str, str]]:
    return [{"message_id": tag[0], "text": tag[2].split()[0]}]


def _answer(
    questions: Callable[[list[tuple[str, str, str]]], list[dict[str, Any]]],
) -> Callable[[ModelRequest], Any]:
    def answer(request: ModelRequest) -> dict[str, Any]:
        tags = _TAG.findall(request.input_text)
        return {
            "summary": [
                {"text": "The user asked about a synthetic hedge.", "quotes": _cite(tags[0])}
            ],
            "status": {"value": "open", "quotes": _cite(tags[-1])},
            "intent": {"value": "fix", "text": "Fix the hedge.", "quotes": _cite(tags[0])},
            "open_questions": questions(tags),
        }

    return answer


def _offer_twice(tags: list[tuple[str, str, str]]) -> list[dict[str, Any]]:
    item = {"text": "Should the assistant draft the council letter?", "quotes": _cite(tags[1])}
    return [item, {**item, "text": "Should the assistant draft a letter to the council?"}]


def _digest(
    session: Session, native: str, answer: Callable[[ModelRequest], Any]
) -> ConversationDigest:
    stage = DigestStage(
        ModelStageRunner(session, FakeProvider(answer), EgressPolicy(text_llm=True))
    )
    outcome = stage.run(_load(session, native))
    assert outcome.state == "done" and outcome.digest is not None
    return outcome.digest


def test_a_one_part_chat_keeps_its_questions_as_written(session: Session) -> None:
    # Reconciling is only across parts (NOTE-032): one part saw the whole chat.
    digest = _digest(session, "accepted", _answer(_offer_twice))
    assert len(digest.open_questions) == 2 and digest.resolved_questions == ()


def test_an_offer_accepted_in_a_later_part_is_set_aside_with_the_reply(session: Session) -> None:
    chat = _load(session, "offered")
    messages = chat_messages(chat)
    offer = next(m for m in messages if "planting plan" in m.text)
    reply = next(m for m in messages if m.text.startswith("Yes, go ahead"))

    def listed(tags: list[tuple[str, str, str]]) -> list[dict[str, Any]]:
        if not any(t[0] == offer.native_id for t in tags):
            return []
        quoted = [{"message_id": offer.native_id, "text": "Want"}]
        return [{"text": "Should the assistant draft the planting plan?", "quotes": quoted}]

    runner = ModelStageRunner(session, FakeProvider(_answer(listed)), EgressPolicy(text_llm=True))
    budget = max(len(m.text) for m in messages) * 4
    parts = digest_parts(chat, budget)
    first = next(p for p in parts if offer.native_id in p)
    assert reply.native_id not in first  # the part that asked never saw the yes

    outcome = DigestStage(runner, max_characters=budget).run(chat)
    digest = outcome.digest
    assert digest is not None and digest.open_questions == ()
    [resolved] = digest.resolved_questions
    assert resolved.resolved_by.revision_id == reply.revision_id
    assert any(f.field == "resolved_questions" and f.index == 0 for f in digest.flags)


def _long_answer(broken_last: bool, closing_only: bool = False) -> Callable[[ModelRequest], Any]:
    def answer(request: ModelRequest) -> dict[str, Any]:
        tags = _TAG.findall(request.input_text)
        part = int(re.search(r"^Part (\d+) of (\d+)", request.input_text, re.M).group(1))  # type: ignore[union-attr]
        total = int(re.search(r"^Part \d+ of (\d+)", request.input_text, re.M).group(1))  # type: ignore[union-attr]
        cited = _cite(tags[-1])
        if (broken_last or closing_only) and part == total:
            cited = [{"message_id": tags[-1][0], "text": "words nobody wrote"}]
        summary = [{"text": f"Synthetic event number {part} happened.", "quotes": cited}]
        if closing_only and part == total:
            # The closing sentence fails its quote; an earlier one of this part holds.
            summary.insert(0, {"text": "Synthetic late event happened.", "quotes": _cite(tags[-2])})
        return {
            "summary": summary,
            "status": {"value": "settled", "quotes": _cite(tags[-1])},
            "intent": {"value": "plan", "text": "Plan the bed.", "quotes": _cite(tags[0])},
        }

    return answer


def _long_stage(session: Session, answer: Callable[[ModelRequest], Any]) -> DigestStage:
    budget = max(len(m.text) for m in chat_messages(_load(session, "long"))) * 4
    runner = ModelStageRunner(session, FakeProvider(answer), EgressPolicy(text_llm=True))
    return DigestStage(runner, max_characters=budget)


def test_a_long_chats_summary_includes_its_last_part(session: Session) -> None:
    stage = _long_stage(session, _long_answer(broken_last=False))
    chat = _load(session, "long")
    parts = digest_parts(chat, stage.max_characters)
    assert len(parts) > 4  # more parts than summary sentences

    outcome = stage.run(chat)
    assert outcome.digest is not None
    summary = outcome.digest.summary
    assert len(summary) == 4
    assert any(set(parts[-1]) & set(item.message_ids) for item in summary)
    assert summary[-1].text == f"Synthetic event number {len(parts)} happened."
    assert outcome.digest.ending_unsummarised is None


def test_a_last_part_with_no_surviving_sentence_is_said_in_the_note(session: Session) -> None:
    stage = _long_stage(session, _long_answer(broken_last=True))
    chat = _load(session, "long")
    parts = digest_parts(chat, stage.max_characters)

    outcome = stage.run(chat)
    digest = outcome.digest
    assert digest is not None and digest.ending_unsummarised == len(parts)
    text = render_note(rich_conversation_note(session, chat.conversation_id, digest=digest).model)
    assert f"How it ended: not summarised (see part {len(parts)})." in text


def test_a_failed_closing_sentence_gives_way_to_the_last_parts_other_one(
    session: Session,
) -> None:
    stage = _long_stage(session, _long_answer(broken_last=False, closing_only=True))
    outcome = stage.run(_load(session, "long"))
    digest = outcome.digest
    assert digest is not None and digest.ending_unsummarised is None
    assert digest.summary[-1].text == "Synthetic late event happened."


def test_a_single_part_chat_is_unchanged(session: Session) -> None:
    digest = _digest(session, "ignored", _answer(lambda tags: []))
    assert digest.ending_unsummarised is None and digest.resolved_questions == ()
    assert [f for f in digest.flags if "note-03" in f.reason] == []
