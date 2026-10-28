"""NOTE-005: the model-backed knowledge extractor keeps attribution honest."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from knowledge_engine.domain.enums import Role
from knowledge_engine.extraction.model_knowledge import (
    PROMPT_VERSION,
    check_candidates,
    is_preamble,
    knowledge_extractor,
)
from knowledge_engine.extraction.records import Acceptance, CandidateRecord, RecordType
from knowledge_engine.extraction.runner import run
from knowledge_engine.extraction.store import KnowledgeRecordRow, load
from knowledge_engine.extraction.text import ExtractionMessage, quote, segment_extraction_messages
from knowledge_engine.graph.offsets import find_quote
from knowledge_engine.importer import import_source
from knowledge_engine.importer.records import ConversationRow
from knowledge_engine.infrastructure.db import create_sqlite_engine, database_path
from knowledge_engine.providers.base import FakeProvider, ModelRequest
from knowledge_engine.providers.ledger import ModelStageRunner
from knowledge_engine.rendering.transcript import load_conversation
from knowledge_engine.segmentation.segmenter import segment_conversation
from knowledge_engine.settings import EgressPolicy, Settings

CASE = Path(__file__).resolve().parents[1] / "fixtures" / "chatgpt" / "late_rejection"

PREAMBLE = "You are a senior travel planner. " + "Always answer in short bullet points. " * 6
USER = ExtractionMessage("u1", f"rev_{1:032x}", Role.USER, PREAMBLE)
ASK = ExtractionMessage("u2", f"rev_{2:032x}", Role.USER, "Where should we go in May?")
OPTIONS = ExtractionMessage(
    "a1", f"rev_{3:032x}", Role.ASSISTANT, "Try Lisbon. Or Porto. Or the Algarve coast."
)
CHOSEN = ExtractionMessage("u3", f"rev_{4:032x}", Role.USER, "Yes, Lisbon it is.")
CHAT = [USER, ASK, OPTIONS, CHOSEN]


def _cite(message: ExtractionMessage, words: str) -> Any:
    return quote(message, find_quote(message.text, words)[0])


def _record(kind: RecordType, actor: Role, *cites: Any, **extra: Any) -> CandidateRecord:
    return CandidateRecord(
        record_type=kind,
        assertion=extra.pop("assertion", f"{kind} by {actor}"),
        actor=actor,
        scope_id="seg_x",
        evidence=cites,
        **extra,
    )


def test_a_setup_prompt_is_recognised_but_a_short_reply_is_not() -> None:
    assert is_preamble(USER)
    assert not is_preamble(ExtractionMessage("u9", f"rev_{9:032x}", Role.USER, "You are right."))
    assert not is_preamble(OPTIONS)  # the assistant's own words never count


def test_an_assistant_suggestion_never_becomes_a_user_decision() -> None:
    claimed = _record(
        RecordType.DECISION,
        Role.USER,
        _cite(OPTIONS, "Try Lisbon."),
        acceptance=Acceptance.EXPLICIT,
    )
    [kept] = check_candidates([claimed], CHAT)

    assert kept.record_type is RecordType.PROPOSAL and kept.actor is Role.ASSISTANT
    assert kept.acceptance is Acceptance.ABSENT
    assert kept.review_reason and "only the assistant" in kept.review_reason


def test_a_real_user_decision_is_kept_as_it_is() -> None:
    decided = _record(
        RecordType.DECISION,
        Role.USER,
        _cite(CHOSEN, "Yes, Lisbon it is."),
        _cite(OPTIONS, "Try Lisbon."),
        acceptance=Acceptance.EXPLICIT,
    )
    assert check_candidates([decided], CHAT) == [decided]


def test_a_pasted_preamble_gives_no_decision() -> None:
    setup = _record(
        RecordType.REQUIREMENT,
        Role.USER,
        _cite(USER, "Always answer in short bullet points."),
        acceptance=Acceptance.EXPLICIT,
    )
    question = _record(
        RecordType.QUESTION,
        Role.USER,
        _cite(ASK, "Where should we go in May?"),
        acceptance=Acceptance.NOT_APPLICABLE,
    )
    assert check_candidates([setup, question], CHAT) == [question]


def test_one_list_of_options_is_one_proposal() -> None:
    options = [
        _record(RecordType.PROPOSAL, Role.ASSISTANT, _cite(OPTIONS, w), assertion=w)
        for w in ("Try Lisbon.", "Or Porto.", "Or the Algarve coast.")
    ]
    [merged] = check_candidates(options, CHAT)

    assert merged.assertion == "Options suggested: Try Lisbon.; Or Porto.; Or the Algarve coast."
    assert len(merged.evidence) == 3


# ---- through the stage runner and the EXT-002 gate, on an imported chat ----


@pytest.fixture
def world(tmp_path: Path) -> Iterator[tuple[Session, str, list[ExtractionMessage]]]:
    settings = Settings(workspace_root=tmp_path / "ws")
    import_source(CASE / "export", "fixture", settings=settings)
    engine = create_sqlite_engine(database_path(settings))
    with Session(engine) as session:
        [conversation_id] = session.scalars(select(ConversationRow.conversation_id)).all()
        chat = load_conversation(session, conversation_id)
        segment = segment_conversation(chat)[-1]
        yield session, segment.segment_id, segment_extraction_messages(chat, segment)
    engine.dispose()


def test_model_records_pass_the_evidence_gate(
    world: tuple[Session, str, list[ExtractionMessage]],
) -> None:
    session, segment_id, messages = world
    # The last user message and the assistant message just before it share a
    # request even when a long segment is split into parts.
    at = max(i for i, m in enumerate(messages) if m.role is Role.USER)
    user = messages[at]
    helper = next(m for m in reversed(messages[:at]) if m.role is Role.ASSISTANT)
    user_words = " ".join(user.text.split()[:2])
    helper_words = " ".join(helper.text.split()[:3])

    def answer(request: ModelRequest) -> dict[str, Any]:
        if f"[m:{user.native_id}]" not in request.input_text:
            return {"records": []}
        return {
            "records": [
                {
                    "record_type": "decision",
                    "assertion": "Synthetic: the assistant's idea, mislabelled",
                    "actor": "user",
                    "acceptance": "explicit",
                    "quotes": [{"message_id": helper.native_id, "text": helper_words}],
                },
                {
                    "record_type": "question",
                    "assertion": "Synthetic: what the user asked",
                    "actor": "user",
                    "acceptance": "not_applicable",
                    "quotes": [{"message_id": user.native_id, "text": user_words}],
                },
            ]
        }

    runner = ModelStageRunner(session, FakeProvider(answer), EgressPolicy(text_llm=True))
    report = run(session, [(segment_id, messages)], [knowledge_extractor(runner)])
    assert report.done and not report.failed

    stored = [load(session, rid) for rid in session.scalars(select(KnowledgeRecordRow.record_id))]
    model_made = [
        r for r in stored if r.provenance and r.provenance.prompt_version == PROMPT_VERSION
    ]
    kinds = {(r.record_type, r.actor) for r in model_made}
    assert (RecordType.DECISION, Role.USER) not in kinds
    assert (RecordType.PROPOSAL, Role.ASSISTANT) in kinds
    # The EXT-002 gate checked every quote against the archive.
    assert all(r.evidence_checked_by for r in model_made if r.trust.value != "review_required")
