"""NOTE-019: the digest's status is checked against how the chat ends.

Three endings from the first real score: an assistant offer after a
delivered result (settled), a user question nobody answered (open), and an
explicit "thanks, done" (settled). The fake model always gets it wrong, so
each test shows the rule correcting it, with a flag for the reviewer.
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

OFFER = [
    ("user", "Draw a lighthouse at dusk for the cover of my synthetic zine."),
    (
        "assistant",
        "Here is the lighthouse at dusk, with warm light on the water. "
        "Want me to make a version in portrait format?",
    ),
]
QUESTION = [
    ("user", "Which paint works on a synthetic garden fence?"),
    ("assistant", "Exterior acrylic suits most fences. Clean and dry the wood first."),
    ("user", "And how many coats should I plan for on rough timber?"),
]
THANKS = [
    ("user", "How do I reset the synthetic router to factory settings?"),
    ("assistant", "Hold the reset button for ten seconds until the lights blink."),
    ("user", "Thanks, that's done!"),
    ("assistant", "You're welcome. Let me know if anything else comes up."),
]
PLAIN = [
    ("user", "Explain what a synthetic compost heap needs."),
    ("assistant", "Greens, browns, air and water, turned now and then."),
]


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
    chats = [
        _chat("offer", OFFER),
        _chat("question", QUESTION),
        _chat("thanks", THANKS),
        _chat("plain", PLAIN),
    ]
    (export / "conversations.json").write_text(json.dumps(chats), encoding="utf-8")
    settings = Settings(workspace_root=tmp_path / "ws")
    run_import(export, "acct", format_id=None, settings=settings)
    engine = create_sqlite_engine(database_path(settings))
    with Session(engine) as s:
        yield s
    engine.dispose()


def _wrong(request: ModelRequest) -> dict[str, Any]:
    """A digest whose status is the opposite of the right one."""
    message_id, _, text = _TAG.findall(request.input_text)[-1]
    cite = [{"message_id": f"[m:{message_id}]", "text": text.split()[0]}]
    wrong = "settled" if "coats" in request.input_text else "open"
    return {
        "summary": [{"text": "Something was discussed.", "quotes": cite}],
        "status": {"value": wrong, "quotes": cite},
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
        ModelStageRunner(session, FakeProvider(_wrong), EgressPolicy(text_llm=True))
    )
    outcome = stage.run(chat)
    assert outcome.digest is not None
    return chat, outcome.digest


@pytest.mark.parametrize(
    ("native", "ending", "status"),
    [
        ("offer", Ending.ASSISTANT_OFFER, ChatStatus.SETTLED),
        ("question", Ending.USER_QUESTION, ChatStatus.OPEN),
        ("thanks", Ending.USER_DONE, ChatStatus.SETTLED),
    ],
)
def test_the_ending_decides_the_status_and_flags_the_change(
    session: Session, native: str, ending: Ending, status: ChatStatus
) -> None:
    chat, digest = _digest(session, native)
    found = chat_ending(chat_messages(chat), chat)
    assert found.ending is ending
    assert digest.status is status
    # The new status cites the message that decided it.
    assert digest.status_item is not None
    assert digest.status_item.message_ids == (found.message.native_id,)  # type: ignore[union-attr]
    [flag] = [f for f in digest.flags if f.field == "status"]
    assert f"to {status.value}" in flag.reason and ending.value in flag.reason


def test_no_rule_leaves_the_models_reading_alone(session: Session) -> None:
    chat, digest = _digest(session, "plain")
    assert chat_ending(chat_messages(chat), chat).ending is Ending.OTHER
    assert digest.status is ChatStatus.OPEN  # what the model said
    assert not [f for f in digest.flags if f.field == "status"]


def test_an_offer_with_nothing_delivered_is_not_settled(session: Session) -> None:
    # A bare "Want me to start?" may be a clarifying question: no rule applies.
    chat, _ = _digest(session, "offer")
    messages = chat_messages(chat)
    bare = messages[-1].__class__(
        messages[-1].native_id, messages[-1].revision_id, messages[-1].role, "Want me to start?"
    )
    assert chat_ending([messages[0], bare], chat).ending is Ending.OTHER
