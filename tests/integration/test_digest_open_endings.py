"""NOTE-023: an ending that leaves something open becomes an open question.

Four synthetic endings: an unanswered user question, an assistant-drafted
letter the user never said was sent, a promise to report back, and an
explicit "thanks, done". The fake model lists no open questions at all, so
each test shows what the ending check adds (or doesn't), with a flag for
the reviewer and a citation of the closing message.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from knowledge_engine.digest.contract import ChatStatus
from knowledge_engine.digest.ending import Ending, chat_ending, ending_questions
from knowledge_engine.digest.stage import DigestStage, chat_messages
from knowledge_engine.graph.offsets import quote_hash
from knowledge_engine.importer.records import ConversationRow
from knowledge_engine.importer.run import run_import
from knowledge_engine.infrastructure.db import create_sqlite_engine, database_path
from knowledge_engine.providers.base import FakeProvider, ModelRequest
from knowledge_engine.providers.ledger import ModelStageRunner
from knowledge_engine.rendering.transcript import load_conversation
from knowledge_engine.settings import EgressPolicy, Settings

_TAG = re.compile(r"^\[m:([^\]]+)\] (\w+):\n(.+)$", re.M)

CHATS = {
    "question": [
        ("user", "Which paint works on a synthetic garden fence?"),
        ("assistant", "Exterior acrylic suits most fences. Clean and dry the wood first."),
        ("user", "Thanks. And how many coats should I plan for on rough timber?"),
    ],
    "draft": [
        ("user", "Write my synthetic landlord a short letter about the boiler."),
        (
            "assistant",
            "Here is a draft:\n\nDear Ms Synthetic,\n\nThe boiler stopped working on Monday. "
            "Could someone look at it this week?\n\nKind regards,\nSam",
        ),
    ],
    "report": [
        ("user", "How do I test a synthetic smoke alarm?"),
        ("assistant", "Press and hold the test button until it sounds."),
        ("user", "OK, I'll try it tonight and let you know."),
    ],
    "thanks": [
        ("user", "Write a one-line synthetic toast for a retirement."),
        ("assistant", "To years of good work, and many more of good rest!"),
        ("user", "Thanks, that's done!"),
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
    return {
        "id": cid,
        "title": f"Synthetic {cid}",
        "create_time": 1704067200.0,
        "mapping": mapping,
        "current_node": parent,
    }


@pytest.fixture
def session(tmp_path: Path) -> Any:
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


def _no_questions(request: ModelRequest) -> dict[str, Any]:
    """A digest that lists no open questions (the re-score's failure)."""
    message_id, _, text = _TAG.findall(request.input_text)[0]
    cite = [{"message_id": message_id, "text": text.split()[0]}]
    return {
        "summary": [{"text": "Something was asked.", "quotes": cite}],
        "status": {"value": "settled", "quotes": cite},
        "intent": {"value": "learn", "text": "Find out.", "quotes": cite},
    }


def _digest(session: Session, native: str) -> Any:
    cid = session.scalar(
        select(ConversationRow.conversation_id).where(
            ConversationRow.native_conversation_id == native
        )
    )
    chat = load_conversation(session, cid)
    stage = DigestStage(
        ModelStageRunner(session, FakeProvider(_no_questions), EgressPolicy(text_llm=True))
    )
    outcome = stage.run(chat)
    assert outcome.digest is not None
    return chat, outcome.digest


@pytest.mark.parametrize(
    ("native", "ending", "words"),
    [
        ("question", Ending.USER_QUESTION, "how many coats should I plan for on rough timber?"),
        ("draft", Ending.UNSENT_DRAFT, "isn't confirmed as sent"),
        ("report", Ending.REPORT_BACK, "would report back"),
    ],
)
def test_an_open_ending_becomes_a_cited_open_question(
    session: Session, native: str, ending: Ending, words: str
) -> None:
    chat, digest = _digest(session, native)
    messages = chat_messages(chat)
    found = chat_ending(messages, chat)
    assert found.ending is ending
    [question] = digest.open_questions
    assert words in question.text
    # It cites the closing message, and its quote is really in that message.
    assert found.message is not None
    assert question.message_ids == (found.message.native_id,)
    [evidence] = question.evidence
    assert quote_hash(found.message.text[evidence.start : evidence.end]) == evidence.quote_sha256
    assert digest.status is ChatStatus.OPEN
    assert any(f.field == "open_questions" and ending.value in f.reason for f in digest.flags)


def test_thanks_done_leaves_nothing_open(session: Session) -> None:
    chat, digest = _digest(session, "thanks")
    assert chat_ending(chat_messages(chat), chat).ending is Ending.USER_DONE
    assert digest.open_questions == ()
    assert digest.status is ChatStatus.SETTLED


def test_a_question_the_model_already_listed_is_not_added_twice(session: Session) -> None:
    chat, digest = _digest(session, "question")
    messages = chat_messages(chat)
    # Run the check again on the digest that now cites the closing message.
    again = ending_questions(digest, messages, chat)
    assert again.open_questions == digest.open_questions
    assert len([f for f in again.flags if f.field == "open_questions"]) == 1
