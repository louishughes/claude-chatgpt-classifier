"""NOTE-003: the digest stage asks once per chat, caches, repairs once, respects egress."""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from knowledge_engine.digest.stage import DigestStage, chat_messages
from knowledge_engine.importer import import_source
from knowledge_engine.importer.records import ConversationRow
from knowledge_engine.infrastructure.db import create_sqlite_engine, database_path
from knowledge_engine.providers.base import FakeProvider, ModelRequest
from knowledge_engine.providers.ledger import ModelRequestRow, ModelStageRunner
from knowledge_engine.rendering.transcript import StoredConversation, load_conversation
from knowledge_engine.settings import EgressDisabledError, EgressPolicy, Settings

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "chatgpt"
BRANCHED = FIXTURES / "branches_edit"
LONG = FIXTURES / "late_rejection"
_TAG = re.compile(r"^\[m:([^\]]+)\] (\w+):\n(.+)$", re.M)


def _load(tmp_path: Path, case: Path) -> Iterator[tuple[Session, StoredConversation]]:
    settings = Settings(workspace_root=tmp_path / "ws")
    import_source(case / "export", "fixture", settings=settings)
    engine = create_sqlite_engine(database_path(settings))
    with Session(engine) as session:
        [conversation_id] = session.scalars(select(ConversationRow.conversation_id)).all()
        yield session, load_conversation(session, conversation_id)
    engine.dispose()


@pytest.fixture
def branched(tmp_path: Path) -> Iterator[tuple[Session, StoredConversation]]:
    yield from _load(tmp_path, BRANCHED)


def _good(request: ModelRequest) -> dict[str, Any]:
    """A valid digest citing the first word of the last message in the request."""
    message_id, _, text = _TAG.findall(request.input_text)[-1]
    cite = [{"message_id": f"[m:{message_id}]", "text": text.split()[0]}]
    return {
        "summary": [{"text": "Something was discussed.", "quotes": cite}],
        "status": {"value": "open", "quotes": cite},
        "intent": {"value": "learn", "text": "Find out.", "quotes": cite},
        "topics": [{"text": "a topic", "quotes": cite}],
    }


def _rows(session: Session) -> int:
    return session.scalar(select(func.count()).select_from(ModelRequestRow)) or 0


def test_one_request_per_chat_shows_the_active_path_and_the_forks(
    branched: tuple[Session, StoredConversation],
) -> None:
    session, chat = branched
    provider = FakeProvider(_good)
    outcome = DigestStage(ModelStageRunner(session, provider, EgressPolicy(text_llm=True))).run(
        chat
    )

    assert outcome.state == "done" and outcome.digest is not None
    [request] = provider.submitted
    shown = {m for m, _, _ in _TAG.findall(request.input_text)}
    assert shown == {m.native_id for m in chat_messages(chat)}
    assert "edit-u0b" in shown and not any(n.endswith("-u0") for n in shown)  # active edit only
    assert "edit fork, 1 other version(s) not shown" in request.input_text
    assert outcome.digest.summary[0].message_ids  # resolved to real evidence


def test_a_rerun_is_answered_from_the_cache_with_zero_requests(
    branched: tuple[Session, StoredConversation],
) -> None:
    session, chat = branched
    DigestStage(ModelStageRunner(session, FakeProvider(_good), EgressPolicy(text_llm=True))).run(
        chat
    )
    again = FakeProvider(_good)
    outcome = DigestStage(ModelStageRunner(session, again, EgressPolicy(text_llm=True))).run(chat)

    assert outcome.state == "done"
    assert again.submitted == []


def test_an_invalid_answer_gets_one_repair_then_review(
    branched: tuple[Session, StoredConversation],
) -> None:
    session, chat = branched

    def repaired(request: ModelRequest) -> dict[str, Any] | str:
        return _good(request) if request.attempt == 2 else '{"summary": "not a list"}'

    provider = FakeProvider(repaired)
    stage = DigestStage(ModelStageRunner(session, provider, EgressPolicy(text_llm=True)))
    # The repair is a new ask: like any batch answer it arrives on a later
    # collect, so the first run waits and the next one finishes.
    assert stage.run(chat).state == "pending"
    assert stage.run(chat).state == "done"
    assert [r.attempt for r in provider.submitted] == [1, 2]


def test_two_invalid_answers_go_to_review(branched: tuple[Session, StoredConversation]) -> None:
    session, chat = branched
    provider = FakeProvider(lambda request: {"summary": [], "invented": True})
    stage = DigestStage(ModelStageRunner(session, provider, EgressPolicy(text_llm=True)))
    assert stage.run(chat).state == "pending"  # waiting for the repair
    outcome = stage.run(chat)

    assert outcome.state == "review_required" and outcome.digest is None
    assert len(provider.submitted) == 2  # the ask and its one repair, nothing more


def test_egress_off_sends_and_writes_nothing(branched: tuple[Session, StoredConversation]) -> None:
    session, chat = branched
    provider = FakeProvider(_good)
    stage = DigestStage(ModelStageRunner(session, provider, EgressPolicy()))
    with pytest.raises(EgressDisabledError):
        stage.run(chat)
    assert provider.submitted == []
    assert _rows(session) == 0


def test_no_supported_summary_means_review_not_a_note(
    branched: tuple[Session, StoredConversation],
) -> None:
    session, chat = branched

    def invented(request: ModelRequest) -> dict[str, Any]:
        answer = _good(request)
        answer["summary"][0]["quotes"] = [
            {**answer["summary"][0]["quotes"][0], "text": "words nobody wrote"}
        ]
        return answer

    stage = DigestStage(
        ModelStageRunner(session, FakeProvider(invented), EgressPolicy(text_llm=True))
    )
    outcome = stage.run(chat)
    assert outcome.state == "review_required"
    assert outcome.digest is not None and outcome.digest.flags[0].field == "summary"


def test_a_long_chat_is_split_never_clipped_and_merged(tmp_path: Path) -> None:
    for session, chat in _load(tmp_path, LONG):
        messages = chat_messages(chat)
        budget = max(len(m.text) for m in messages) * 2
        provider = FakeProvider(_good)
        stage = DigestStage(
            ModelStageRunner(session, provider, EgressPolicy(text_llm=True)), max_characters=budget
        )
        outcome = stage.run(chat)

        assert len(provider.submitted) > 1 and outcome.state == "done"
        sent = [m for r in provider.submitted for m, _, _ in _TAG.findall(r.input_text)]
        assert set(sent) == {m.native_id for m in messages}  # every message, none cut
        for request in provider.submitted:
            assert re.search(r"^Part \d+ of \d+ of a longer chat\.", request.input_text)
        assert outcome.digest is not None
        # Every part is represented, and the sentence they share is said once
        # (NOTE-030: identical lines join, keeping each part's citation).
        [line] = outcome.digest.summary
        assert len(line.message_ids) == min(4, len(provider.submitted))
        # One topic text, cited in every part, is kept once.
        assert len(outcome.digest.topics) == 1
        json.dumps(outcome.digest.model_dump(mode="json"))  # storable as-is
