"""NOTE-034: the chat's status is decided once, from how the whole chat ends.

Synthetic chats mirroring the failure shapes the NOTE-013 pass 1 score
found (status right in 3 of 10 notes, wrong both ways):

* **finished but marked open:** a result and an offer end the chat, and
  the model lists an earlier question beside the offer. That earlier
  question used to switch off the offer's exemption, so the offer itself
  kept the chat open;
* **open but marked settled:** a long chat whose parts list more open
  questions than the digest keeps. The cut keeps the earliest, so the last
  part's question about the ending was lost and the chat stayed settled;
* **a long multi-part chat** whose last part reads "open" on its own but
  which ends with the user's thank-you.

The fake model's answer depends only on the messages it is shown, so a
long chat's parts each get their own answer, as with a real model.
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
from knowledge_engine.digest.ending import ENDING_VERSION, Ending, chat_ending
from knowledge_engine.digest.stage import DigestStage, chat_messages
from knowledge_engine.digest.status import STATUS_VERSION
from knowledge_engine.importer.records import ConversationRow
from knowledge_engine.importer.run import run_import
from knowledge_engine.infrastructure.db import create_sqlite_engine, database_path
from knowledge_engine.providers.base import FakeProvider, ModelRequest
from knowledge_engine.providers.ledger import ModelStageRunner
from knowledge_engine.rendering.transcript import load_conversation
from knowledge_engine.settings import EgressPolicy, Settings

_IDS = re.compile(r"^\[m:([^\]]+)\] (\w+):$", re.M)

SHED_OFFER = [
    ("user", "Which synthetic paint colour suits a garden shed?"),
    ("assistant", "Blue or green both suit a garden shed."),
    ("user", "Paint me a picture of the synthetic shed in blue."),
    (
        "assistant",
        "Here is the shed in blue, with a white door and a grey roof. "
        "Want me to make a green version too?",
    ),
]
# The user's last message asks for two things; the result covers only one.
TWO_ASKS = [
    ("user", "Draw the synthetic shed in blue and list the paint brands in stock."),
    (
        "assistant",
        "Here is the shed in blue, with a white door and a grey roof. "
        "Want me to make a green version too?",
    ),
]
_TOPICS = [
    "gutters", "fence posts", "patio slabs", "roof felt", "drain covers",
    "window frames", "garden gate", "shed floor", "porch light",
]  # fmt: skip
LONG_OPEN = [
    turn
    for topic in _TOPICS
    for turn in (
        ("user", f"What should I check first on the synthetic {topic} this spring?"),
        ("assistant", f"Look over the {topic} for damage, then clean them and note any repairs."),
    )
] + [
    ("user", "The roofer quoted 900 and the builder quoted 1200 for the synthetic repairs."),
    ("assistant", "Both quotes cover the gutters, the roof felt and the downpipes."),
]
LONG_THANKS = LONG_OPEN[:-2] + [("user", "Thanks, that's all I needed for the synthetic repairs.")]

CHATS = {
    "finished": SHED_OFFER,
    "finished_said_open": SHED_OFFER,
    "two_asks": TWO_ASKS,
    "long_open": LONG_OPEN,
    "long_thanks": LONG_THANKS,
}
TEXT = {f"{cid}-{i}": text for cid, turns in CHATS.items() for i, (_, text) in enumerate(turns)}


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


def _cite(message_id: str) -> list[dict[str, str]]:
    # Several words, so the quote is a real citation, not a lone word.
    return [{"message_id": message_id, "text": " ".join(TEXT[message_id].split()[:4])}]


Asker = Callable[[list[tuple[str, str]]], tuple[str, list[tuple[str, str]]]]


def _model(ask: Asker) -> Callable[[ModelRequest], dict[str, Any]]:
    """A fake model: ``ask`` maps the shown (id, role) pairs to a status and questions."""

    def answer(request: ModelRequest) -> dict[str, Any]:
        shown = _IDS.findall(request.input_text)
        status, questions = ask(shown)
        first = _cite(shown[0][0])
        return {
            "summary": [{"text": "Repairs were discussed.", "quotes": first}],
            "status": {"value": status, "quotes": _cite(shown[-1][0])},
            "intent": {"value": "plan", "text": "Plan the work.", "quotes": first},
            "open_questions": [{"text": t, "quotes": _cite(i)} for t, i in questions],
        }

    return answer


def _digest(
    session: Session, native: str, ask: Asker, max_characters: int | None = None
) -> tuple[ConversationDigest, int]:
    cid = session.scalar(
        select(ConversationRow.conversation_id).where(
            ConversationRow.native_conversation_id == native
        )
    )
    assert cid is not None
    chat = load_conversation(session, cid)
    fake = FakeProvider(_model(ask))
    runner = ModelStageRunner(session, fake, EgressPolicy(text_llm=True))
    stage = DigestStage(runner) if max_characters is None else DigestStage(runner, max_characters)
    outcome = stage.run(chat)
    assert outcome.digest is not None
    return outcome.digest, len(fake.submitted)


def _status_flags(digest: ConversationDigest) -> list[str]:
    return [f.reason for f in digest.flags if f.field == "status"]


def _budget(native: str, parts: int) -> int:
    turns = CHATS[native]
    return max(max(len(t) for _, t in turns) * 2, sum(len(t) for _, t in turns) // parts)


def test_the_rule_version_is_bumped() -> None:
    assert ENDING_VERSION == STATUS_VERSION == "note-034-v1"


@pytest.mark.parametrize(
    ("native", "said"), [("finished", "settled"), ("finished_said_open", "open")]
)
def test_a_finished_chat_with_an_earlier_question_is_settled(
    session: Session, native: str, said: str
) -> None:
    def ask(shown: list[tuple[str, str]]) -> tuple[str, list[tuple[str, str]]]:
        # An earlier question, and the closing offer listed as if unfinished.
        return said, [("Which colour suits a shed?", shown[0][0]),
                      ("A green version?", shown[-1][0])]  # fmt: skip

    digest, _ = _digest(session, native, ask)
    assert digest.status is ChatStatus.SETTLED
    if said == "settled":
        assert _status_flags(digest) == []
    else:
        [reason] = _status_flags(digest)
        assert reason == (
            f"changed from open to settled: the chat ends with assistant_offer ({STATUS_VERSION})"
        )
        assert digest.status_item is not None
        assert digest.status_item.message_ids == (f"{native}-3",)


def test_an_offer_with_a_question_in_the_last_exchange_stays_open_with_no_flag(
    session: Session,
) -> None:
    # The model already said open: the old two checks flagged open -> settled -> open.
    def ask(shown: list[tuple[str, str]]) -> tuple[str, list[tuple[str, str]]]:
        return "open", [("Which paint brands are in stock?", shown[0][0])]

    digest, _ = _digest(session, "two_asks", ask)
    assert digest.status is ChatStatus.OPEN
    assert _status_flags(digest) == []


def _per_message_questions(said: str) -> Asker:
    """Each part lists one open question per user message it saw, and says ``said``."""

    def ask(shown: list[tuple[str, str]]) -> tuple[str, list[tuple[str, str]]]:
        users = [i for i, role in shown if role == "user"]
        return said, [(f"Open point {i.rsplit('-', 1)[1]}?", i) for i in users]

    return ask


def test_a_long_chat_whose_last_question_was_cut_by_the_merge_is_open(session: Session) -> None:
    digest, parts = _digest(
        session, "long_open", _per_message_questions("settled"), _budget("long_open", 3)
    )
    assert parts >= 3
    last_user = f"long_open-{len(LONG_OPEN) - 2}"
    # The merge keeps the first 8 questions; the last part's is not among them.
    assert all(last_user not in q.message_ids for q in digest.open_questions)
    assert digest.status is ChatStatus.OPEN
    assert digest.status_item is not None and digest.status_item.message_ids == (last_user,)
    [reason] = _status_flags(digest)
    assert reason.startswith("changed from settled to open: an open question cites the last")


def test_a_long_chat_ending_in_thanks_is_settled_once(session: Session) -> None:
    digest, parts = _digest(
        session,
        "long_thanks",
        _per_message_questions("open"),
        _budget("long_thanks", 3),
    )
    assert parts >= 3
    thanks = f"long_thanks-{len(LONG_THANKS) - 1}"
    assert digest.status is ChatStatus.SETTLED
    assert digest.status_item is not None and digest.status_item.message_ids == (thanks,)
    [reason] = _status_flags(digest)  # one decision, one flag
    assert reason == (
        f"changed from open to settled: the chat ends with user_done ({STATUS_VERSION})"
    )


def test_the_endings_read_as_the_fixtures_intend(session: Session) -> None:
    expected = {
        "finished": Ending.ASSISTANT_OFFER,
        "two_asks": Ending.ASSISTANT_OFFER,
        "long_open": Ending.OTHER,
        "long_thanks": Ending.USER_DONE,
    }
    for native, ending in expected.items():
        cid = session.scalar(
            select(ConversationRow.conversation_id).where(
                ConversationRow.native_conversation_id == native
            )
        )
        assert cid is not None
        chat = load_conversation(session, cid)
        assert chat_ending(chat_messages(chat), chat).ending is ending, native
