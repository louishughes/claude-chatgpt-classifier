"""NOTE-028 and NOTE-029: the status follows the digest's own open questions, and
the summary says each sentence once.

The fourth note score found chats marked settled whose open questions said
otherwise, and summaries that repeated a sentence. Every chat is synthetic;
the fake model marks each one settled with one open question, citing the
message each test chooses.
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

from knowledge_engine.digest.contract import ChatStatus, ConversationDigest
from knowledge_engine.digest.ending import Ending, chat_ending
from knowledge_engine.digest.stage import DigestStage, chat_messages
from knowledge_engine.importer.records import ConversationRow
from knowledge_engine.importer.run import run_import
from knowledge_engine.infrastructure.db import create_sqlite_engine, database_path
from knowledge_engine.providers.base import FakeProvider, ModelRequest
from knowledge_engine.providers.ledger import ModelStageRunner
from knowledge_engine.rendering.transcript import load_conversation
from knowledge_engine.settings import EgressPolicy, Settings

_TAG = re.compile(r"^\[m:([^\]]+)\] (\w+):\n(.+)$", re.M)
SHED = [
    ("user", "Which synthetic paint colour suits a shed?"),
    ("assistant", "Blue or green both suit a shed."),
    ("user", "Let's go with blue for the synthetic shed."),
    ("assistant", "Blue is a good choice for the shed."),
]
CHATS = {
    "late": SHED,
    "early": SHED,
    "offer": [
        ("user", "Write a synthetic haiku about rain."),
        (
            "assistant",
            "Rain taps on the roof,\nsoft drums for a sleepy town,\npuddles keep the beat.\n\n"
            "Want me to write another one?",
        ),
    ],
    "thanks": [
        ("user", "Write a one-line synthetic toast."),
        ("assistant", "To good work and good rest!"),
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


def _cid(session: Session, native: str) -> str:
    cid = session.scalar(
        select(ConversationRow.conversation_id).where(
            ConversationRow.native_conversation_id == native
        )
    )
    assert cid is not None
    return cid


def _settled_with_a_question(at: int, summary: list[str]) -> Callable[[ModelRequest], Any]:
    def answer(request: ModelRequest) -> dict[str, Any]:
        tags = _TAG.findall(request.input_text)
        first = [{"message_id": tags[0][0], "text": tags[0][2].split()[0]}]
        asked = [{"message_id": tags[at][0], "text": tags[at][2].split()[0]}]
        return {
            "summary": [{"text": text, "quotes": first} for text in summary],
            "status": {"value": "settled", "quotes": first},
            "intent": {"value": "learn", "text": "Find out.", "quotes": first},
            "open_questions": [{"text": "Which shade?", "quotes": asked}],
        }

    return answer


def _digest(
    session: Session, native: str, at: int, summary: list[str] | None = None
) -> ConversationDigest:
    cid = _cid(session, native)
    chat = load_conversation(session, cid)
    fake = FakeProvider(_settled_with_a_question(at, summary or ["Something was asked."]))
    outcome = DigestStage(ModelStageRunner(session, fake, EgressPolicy(text_llm=True))).run(chat)
    assert outcome.digest is not None
    return outcome.digest


def test_a_question_left_in_the_last_exchange_keeps_the_chat_open(session: Session) -> None:
    digest = _digest(session, "late", at=-2)  # cites the user's last message
    assert digest.status is ChatStatus.OPEN
    assert digest.status_item is not None and digest.status_item.message_ids == ("late-2",)
    assert any(
        f.field == "status" and f.reason.startswith("changed from settled to open")
        for f in digest.flags
    )


def test_a_question_from_earlier_in_the_chat_leaves_the_model_reading(session: Session) -> None:
    digest = _digest(session, "early", at=0)  # the chat went on after it
    assert digest.status is ChatStatus.SETTLED
    assert not any(f.field == "status" for f in digest.flags)


@pytest.mark.parametrize(
    ("native", "ending"), [("offer", Ending.ASSISTANT_OFFER), ("thanks", Ending.USER_DONE)]
)
def test_an_offer_or_a_thank_you_stays_settled(
    session: Session, native: str, ending: Ending
) -> None:
    digest = _digest(session, native, at=-1)  # cites the closing message
    cid = _cid(session, native)
    chat = load_conversation(session, cid)
    assert chat_ending(chat_messages(chat), chat).ending is ending
    assert digest.status is ChatStatus.SETTLED


def test_a_repeated_sentence_is_said_once(session: Session) -> None:
    summary = [
        "They picked blue. They picked blue.",
        "They picked  blue. Then they painted the shed.",
        "Then they painted the shed",
    ]
    digest = _digest(session, "early", at=0, summary=summary)
    assert [item.text for item in digest.summary] == [
        "They picked blue.",
        "Then they painted the shed.",
    ]  # the third said nothing new: it joined the second (NOTE-030)
