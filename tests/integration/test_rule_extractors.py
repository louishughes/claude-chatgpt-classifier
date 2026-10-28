"""EXT-003 / EXT-004: decisions, rejections, preferences and requirements by rule."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from knowledge_engine.domain.enums import Role
from knowledge_engine.extraction.decisions import extract_decisions
from knowledge_engine.extraction.evidence import Verdict, check_record
from knowledge_engine.extraction.preferences import extract_preferences
from knowledge_engine.extraction.records import CandidateRecord
from knowledge_engine.extraction.text import ExtractionMessage, segment_extraction_messages
from knowledge_engine.importer import import_source
from knowledge_engine.importer.records import ConversationRow
from knowledge_engine.infrastructure.db import create_sqlite_engine, database_path
from knowledge_engine.rendering.transcript import StoredConversation, load_conversation
from knowledge_engine.segmentation.segmenter import segment_conversation
from knowledge_engine.settings import Settings

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "chatgpt"
EXPECTED: dict[str, Any] = json.loads(
    (FIXTURES / "extraction_rules" / "manifest.json").read_text(encoding="utf-8")
)["expected"]

Chats = dict[str, tuple[StoredConversation, list[tuple[str, list[ExtractionMessage]]]]]


@pytest.fixture(scope="module")
def world(tmp_path_factory: pytest.TempPathFactory) -> Iterator[tuple[Session, Chats]]:
    settings = Settings(workspace_root=tmp_path_factory.mktemp("ext3"))
    import_source(FIXTURES / "extraction_rules" / "export", "fixture", settings=settings)
    engine = create_sqlite_engine(database_path(settings))
    with Session(engine) as session:
        chats: Chats = {}
        for conversation_id in session.scalars(select(ConversationRow.conversation_id)):
            conv = load_conversation(session, conversation_id)
            chats[conv.native_conversation_id] = (
                conv,
                [
                    (seg.segment_id, segment_extraction_messages(conv, seg))
                    for seg in segment_conversation(conv)
                ],
            )
        yield session, chats
    engine.dispose()


def _native(conv: StoredConversation, record: CandidateRecord) -> str:
    by_revision = {rev: native for native, rev in conv.revisions.items()}
    return by_revision[record.evidence[0].revision_id]


def _all(chats: Chats, native: str, extractor: Any) -> list[CandidateRecord]:
    _, segments = chats[native]
    return [r for seg_id, msgs in segments for r in extractor(msgs, segment_id=seg_id)]


def test_suggestion_plus_curious_user_is_not_accepted_and_explicit_yes_is(
    world: tuple[Session, Chats],
) -> None:
    session, chats = world
    for native, want in EXPECTED["decisions"].items():
        conv, _ = chats[native]
        records = _all(chats, native, extract_decisions)
        got = [[r.record_type.value, r.acceptance.value, _native(conv, r)] for r in records]
        assert got == want
    # The curious chat: one assistant proposal, no user decision at all.
    [curious] = [n for n, w in EXPECTED["decisions"].items() if len(w) == 1]
    assert all(r.actor is Role.ASSISTANT for r in _all(chats, curious, extract_decisions))
    # The explicit yes passes the evidence check and cites the proposal it accepts.
    [shed] = [n for n, w in EXPECTED["decisions"].items() if len(w) > 1]
    yes = _all(chats, shed, extract_decisions)[1]
    assert [e.actor for e in yes.evidence] == [Role.USER, Role.ASSISTANT]
    assert check_record(session, yes).verdict is Verdict.VALID


def test_every_extracted_record_has_sound_evidence(world: tuple[Session, Chats]) -> None:
    session, chats = world
    for native in chats:
        for extractor in (extract_decisions, extract_preferences):
            for record in _all(chats, native, extractor):
                assert check_record(session, record).verdict is not Verdict.INVALID


def test_quoted_preference_and_soft_hard_constraints_are_separate(
    world: tuple[Session, Chats],
) -> None:
    session, chats = world
    for native, want in EXPECTED["preferences"].items():
        conv, _ = chats[native]
        records = _all(chats, native, extract_preferences)
        got = [
            [
                r.record_type.value,
                r.strength.value if r.strength else None,
                r.polarity.value if r.polarity else None,
                r.attributed_to,
                _native(conv, r),
            ]
            for r in records
        ]
        assert got == want
        for record in records:
            check = check_record(session, record)
            if record.attributed_to:  # someone else's view: never trusted as the user's
                assert check.verdict is Verdict.REVIEW_REQUIRED
                assert "someone_elses_view" in [p.code for p in check.problems]
            else:
                assert check.verdict is Verdict.VALID


def _message(role: Role, text: str, n: int) -> ExtractionMessage:
    return ExtractionMessage(f"m{n}", f"rev_{n:032x}", role, text)


@pytest.mark.parametrize(
    ("reply", "want"),
    [
        ("Maybe, what would that cost? Synthetic.", []),
        ("Sounds good, but is it fast? Synthetic.", [("decision", "acceptance mixed")]),
        ("Synthetic: I haven't decided to use it.", []),
        ("Synthetic: I've ruled out the second one.", [("rejection", None)]),
    ],
)
def test_reply_edge_cases(reply: str, want: list[tuple[str, str | None]]) -> None:
    messages = [
        _message(Role.ASSISTANT, "Synthetic: I suggest the first one.", 1),
        _message(Role.USER, reply, 2),
    ]
    records = [r for r in extract_decisions(messages, segment_id="seg_x") if r.actor is Role.USER]
    got = [(r.record_type.value, (r.review_reason or "")[:16] or None) for r in records]
    assert got == want


def test_several_proposals_make_the_antecedent_unclear() -> None:
    messages = [
        _message(Role.ASSISTANT, "Synthetic: I suggest pine. You could also use oak.", 1),
        _message(Role.USER, "Yes, let's do that. Synthetic.", 2),
    ]
    decision = extract_decisions(messages, segment_id="seg_x")[-1]
    assert decision.review_reason is not None and "several proposals" in decision.review_reason
    assert len(decision.evidence) == 3  # the yes, and both proposals it might mean
