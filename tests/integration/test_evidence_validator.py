"""EXT-002: malformed references are rejected; ambiguous meanings are held for review."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from knowledge_engine.domain.enums import Role
from knowledge_engine.domain.models import EvidenceRef
from knowledge_engine.extraction.evidence import Verdict, _inside_quotation, check_record
from knowledge_engine.extraction.records import CandidateRecord
from knowledge_engine.graph.offsets import Span, cite, find_all
from knowledge_engine.importer import import_source
from knowledge_engine.importer.records import ConversationRow
from knowledge_engine.infrastructure.db import create_sqlite_engine, database_path
from knowledge_engine.rendering.transcript import StoredConversation, load_conversation
from knowledge_engine.settings import Settings

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "chatgpt"


@pytest.fixture(scope="module")
def world(tmp_path_factory: pytest.TempPathFactory) -> Iterator[tuple[Session, StoredConversation]]:
    settings = Settings(workspace_root=tmp_path_factory.mktemp("ext"))
    import_source(FIXTURES / "mixed_projects" / "export", "fixture", settings=settings)
    engine = create_sqlite_engine(database_path(settings))
    with Session(engine) as session:
        conversation_id = session.scalars(
            select(ConversationRow.conversation_id).where(
                ConversationRow.title == "Synthetic engine choice"
            )
        ).one()
        yield session, load_conversation(session, conversation_id)
    engine.dispose()


def _ref(conv: StoredConversation, native: str, quote: str) -> EvidenceRef:
    text = conv.messages[native].text
    [span] = find_all(text, quote)
    _, digest = cite(text, span)
    role = Role(conv.messages[native].role or "unknown")
    return EvidenceRef(
        revision_id=conv.revisions[native],
        start=span.start,
        end=span.end,
        quote_sha256=digest,
        actor=role,
    )


def _ids(conv: StoredConversation) -> dict[str, str]:
    # Node IDs from the generator: <conv>-u0, -a0, -u1, -a1.
    prefix = conv.native_conversation_id
    return {k: f"{prefix}-{k}" for k in ("u0", "a0", "u1", "a1")}


def _decision(evidence: list[EvidenceRef], **extra: Any) -> CandidateRecord:
    data: dict[str, Any] = {
        "record_type": "decision",
        "assertion": "Synthetic: use Godot",
        "actor": "user",
        "acceptance": "explicit",
        "scope_id": "seg_1",
        "evidence": evidence,
    }
    data.update(extra)
    return CandidateRecord.model_validate(data)


def test_explicit_user_decision_is_valid(world: tuple[Session, StoredConversation]) -> None:
    session, conv = world
    ids = _ids(conv)
    ref = _ref(conv, ids["u1"], "I've decided to go with Godot")
    check = check_record(session, _decision([ref]))
    assert (check.verdict, check.problems) == (Verdict.VALID, ())


def test_malformed_references_are_rejected(world: tuple[Session, StoredConversation]) -> None:
    session, conv = world
    good = _ref(conv, _ids(conv)["u1"], "I've decided to go with Godot")
    bad = {
        "revision_missing": good.model_copy(update={"revision_id": "rev_" + "0" * 32}),
        "span_out_of_range": good.model_copy(update={"start": 5000, "end": 5005}),
        "quote_mismatch": good.model_copy(update={"start": good.start + 1, "end": good.end + 1}),
        "actor_mismatch": good.model_copy(update={"actor": Role.ASSISTANT}),
    }
    for code, ref in bad.items():
        check = check_record(session, _decision([ref]))
        assert check.verdict is Verdict.INVALID
        assert [p.code for p in check.problems][0] == code
    duplicate = check_record(session, _decision([good, good]))
    assert duplicate.verdict is Verdict.INVALID
    assert "duplicate" in [p.code for p in duplicate.problems]


@pytest.mark.parametrize(
    ("message", "quote", "extra", "code"),
    [
        # The assistant's words alone can't make a user decision.
        ("a0", "Unity is common", {}, "assistant_words_only"),
        # A user question is not a decision.
        ("u0", "which game engine suits a small 2D game?", {}, "hedged_or_question"),
        # Inferred records always get a person.
        ("u1", "I've decided to go with Godot", {"origin": "inferred"}, "inferred"),
        ("u1", "I've decided to go with Godot", {"review_reason": "unsure"}, "extractor_flagged"),
    ],
)
def test_ambiguous_meanings_are_held_for_review(
    world: tuple[Session, StoredConversation],
    message: str,
    quote: str,
    extra: dict[str, Any],
    code: str,
) -> None:
    session, conv = world
    ref = _ref(conv, _ids(conv)[message], quote)
    check = check_record(session, _decision([ref], **extra))
    assert check.verdict is Verdict.REVIEW_REQUIRED
    assert code in [p.code for p in check.problems]


def test_quoted_words_are_not_the_speakers_own() -> None:
    text = 'Synthetic: my friend said "I will use Unity" but\n> Synthetic: I prefer Godot\nok'

    def ref(quote: str) -> EvidenceRef:
        [span] = find_all(text, quote)
        return EvidenceRef(
            revision_id="rev_" + "1" * 32,
            start=span.start,
            end=span.end,
            quote_sha256="0" * 64,
            actor=Role.USER,
        )

    assert _inside_quotation(text, ref("I will use Unity"))
    assert _inside_quotation(text, ref("I prefer Godot"))
    assert not _inside_quotation(text, ref("my friend said"))
    assert not _inside_quotation(text, ref("ok"))
    assert Span(0, 1).of(text) == "S"
