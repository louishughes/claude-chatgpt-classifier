"""Conversation relationships and their review history (REL-002).

``conversation_relationships`` holds one row per proposed link: who points
at whom (``from`` -> ``to``), what kind of link it is, how we know
(``evidence_class``) and where it stands in review. Its ID is built from
``(from, kind, to, detector)``, so running a detector again finds the same
row instead of adding a copy, and a link someone rejected stays rejected:
it is never re-proposed on the next import.

``relationship_reviews`` is the history. Every accept, reject or supersede
adds a row; nothing in it is ever updated or deleted (database triggers
refuse it). The ``review_state`` on the relationship is just the latest
entry, kept there so lists don't have to replay the history.

Direction is part of the identity and never changes in review: rejecting
"B forked from A" doesn't turn it into "A forked from B".

Talking points:
    - "A link between two chats is a proposal with evidence, a direction and
      a review trail. The machine proposes; only a person accepts."
    - "Rejections stick, because the rejection is the record a re-run checks."
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    select,
)
from sqlalchemy.orm import Mapped, Session, mapped_column

from knowledge_engine.domain.enums import ReviewState
from knowledge_engine.domain.ids import relationship_id

# Imported for its table: a relationship row's foreign key names import_batches,
# and a command that loads only this module (`ke related suggest`) would
# otherwise fail to build the table metadata (NoReferencedTableError).
from knowledge_engine.importer import ledger as _ledger  # noqa: F401
from knowledge_engine.infrastructure.db import Base


class RelationKind(StrEnum):
    """What one conversation is to another, read as "from <kind> to"."""

    CONTINUES = "continues"
    FORKED_FROM = "forked_from"
    QUOTES = "quotes"
    REFERENCES = "references"
    RELATED_TO = "related_to"
    SAME_PROJECT = "same_project"


class EvidenceClass(StrEnum):
    """How a relationship is known, strongest first."""

    NATIVE = "native"  # the export's own IDs or URLs say so
    STRUCTURAL = "structural"  # identical messages in the same order
    LEXICAL = "lexical"  # identical text
    SEMANTIC = "semantic"  # similar meaning (REL-003; never proves a fork)
    HUMAN = "human"  # a person said so


class ReviewAction(StrEnum):
    """What a reviewer did to a relationship."""

    ACCEPT = "accept"
    REJECT = "reject"
    SUPERSEDE = "supersede"


_RESULT = {
    ReviewAction.ACCEPT: ReviewState.ACCEPTED,
    ReviewAction.REJECT: ReviewState.REJECTED,
    ReviewAction.SUPERSEDE: ReviewState.SUPERSEDED,
}


def _values(enum: type[StrEnum]) -> str:
    return ",".join(f"'{member.value}'" for member in enum)


def _utc_now() -> datetime:
    return datetime.now(UTC)


class ConversationRelationshipRow(Base):
    """One proposed link from one conversation to another."""

    __tablename__ = "conversation_relationships"
    __table_args__ = (
        UniqueConstraint("from_conversation_id", "kind", "to_conversation_id", "detector"),
        CheckConstraint(f"kind IN ({_values(RelationKind)})", name="kind_valid"),
        CheckConstraint(f"evidence_class IN ({_values(EvidenceClass)})", name="evidence_valid"),
        CheckConstraint(f"review_state IN ({_values(ReviewState)})", name="review_state_valid"),
        CheckConstraint("from_conversation_id != to_conversation_id", name="not_self"),
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="confidence_range"),
    )

    relationship_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    from_conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.conversation_id"), index=True
    )
    kind: Mapped[str] = mapped_column(String(20))
    to_conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.conversation_id"), index=True
    )
    evidence_class: Mapped[str] = mapped_column(String(12))
    confidence: Mapped[float] = mapped_column(Float)
    review_state: Mapped[str] = mapped_column(String(12), default=ReviewState.CANDIDATE.value)
    # Detector name and version, e.g. "prefix-v1". Part of the identity, so
    # a new detector version proposes afresh instead of overwriting.
    detector: Mapped[str] = mapped_column(String(40))
    # IDs and counts only (revision IDs, node keys, link occurrence IDs):
    # the evidence points at the archive, it doesn't copy private text.
    evidence_json: Mapped[str] = mapped_column(Text)
    first_import_id: Mapped[str | None] = mapped_column(
        ForeignKey("import_batches.import_id"), default=None
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)


class RelationshipReviewRow(Base):
    """One review decision. Append-only: triggers refuse UPDATE and DELETE."""

    __tablename__ = "relationship_reviews"
    __table_args__ = (CheckConstraint(f"action IN ({_values(ReviewAction)})", name="action_valid"),)

    review_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    relationship_id: Mapped[str] = mapped_column(
        ForeignKey("conversation_relationships.relationship_id"), index=True
    )
    action: Mapped[str] = mapped_column(String(12))
    from_state: Mapped[str] = mapped_column(String(12))
    to_state: Mapped[str] = mapped_column(String(12))
    reviewer: Mapped[str] = mapped_column(String(100))
    note: Mapped[str | None] = mapped_column(Text, default=None)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)


# Created by migration 0013. Kept here so tests that build the schema
# without Alembic can install the same guard.
APPEND_ONLY_TRIGGERS = (
    "CREATE TRIGGER IF NOT EXISTS relationship_reviews_no_update "
    "BEFORE UPDATE ON relationship_reviews "
    "BEGIN SELECT RAISE(ABORT, 'relationship_reviews is append-only'); END",
    "CREATE TRIGGER IF NOT EXISTS relationship_reviews_no_delete "
    "BEFORE DELETE ON relationship_reviews "
    "BEGIN SELECT RAISE(ABORT, 'relationship_reviews is append-only'); END",
)


def propose(
    session: Session,
    *,
    from_conversation_id: str,
    kind: RelationKind,
    to_conversation_id: str,
    evidence_class: EvidenceClass,
    confidence: float,
    detector: str,
    evidence: Mapping[str, Any],
    import_id: str | None,
) -> bool:
    """Record a candidate relationship unless it is already known.

    An existing row (in any review state) is left exactly as it is, so a
    re-run can't undo a review or re-open a rejection.

    Args:
        session: A write session.
        from_conversation_id: The ``conv_`` ID the link starts from.
        kind: The kind of link.
        to_conversation_id: The ``conv_`` ID it points to.
        evidence_class: How it is known.
        confidence: 0..1, the detector's own measure (not a probability).
        detector: Detector name and version.
        evidence: IDs and counts backing it (no private text).
        import_id: The batch that proposed it, if any.

    Returns:
        True if a new candidate was added.
    """
    key = relationship_id(from_conversation_id, kind.value, to_conversation_id, detector)
    if session.get(ConversationRelationshipRow, key) is not None:
        return False
    session.add(
        ConversationRelationshipRow(
            relationship_id=key,
            from_conversation_id=from_conversation_id,
            kind=kind.value,
            to_conversation_id=to_conversation_id,
            evidence_class=evidence_class.value,
            confidence=confidence,
            review_state=ReviewState.CANDIDATE.value,
            detector=detector,
            evidence_json=json.dumps(evidence, sort_keys=True),
            first_import_id=import_id,
        )
    )
    session.flush()
    return True


def review(
    session: Session,
    relationship: str,
    action: ReviewAction,
    *,
    reviewer: str,
    note: str | None = None,
) -> RelationshipReviewRow:
    """Record a review decision and move the relationship to its new state.

    Args:
        session: A write session.
        relationship: The ``rel_`` ID.
        action: Accept, reject or supersede.
        reviewer: Who decided (a person's name, or ``"owner"``).
        note: Why, optionally.

    Returns:
        The new history row.

    Raises:
        KeyError: If there is no such relationship.
    """
    row = session.get(ConversationRelationshipRow, relationship)
    if row is None:
        raise KeyError("no such relationship")
    entry = RelationshipReviewRow(
        relationship_id=relationship,
        action=action.value,
        from_state=row.review_state,
        to_state=_RESULT[action].value,
        reviewer=reviewer,
        note=note,
    )
    session.add(entry)
    row.review_state = _RESULT[action].value
    session.flush()
    return entry


def history(session: Session, relationship: str) -> list[RelationshipReviewRow]:
    """Return a relationship's review history, oldest first."""
    return list(
        session.scalars(
            select(RelationshipReviewRow)
            .where(RelationshipReviewRow.relationship_id == relationship)
            .order_by(RelationshipReviewRow.review_id)
        )
    )


# The kinds a person may state by hand (REL-006). "quotes" and "references"
# are facts about the text that a detector can check; these three are
# judgements, which is exactly what a person adds.
HUMAN_KINDS = frozenset({RelationKind.CONTINUES, RelationKind.FORKED_FROM, RelationKind.RELATED_TO})
HUMAN_DETECTOR = "human-v1"


class RelationshipError(ValueError):
    """A hand-made link the store refuses."""


def add_human(
    session: Session,
    *,
    from_conversation_id: str,
    kind: RelationKind,
    to_conversation_id: str,
    reviewer: str,
    note: str | None = None,
    replaces: str | None = None,
) -> ConversationRelationshipRow:
    """Store a link a person stated, already accepted (REL-006). The caller commits.

    The link is evidence class ``human`` with confidence 1.0: no score made
    it, a person did. Its history starts with that person's ``accept``, so
    "who said B continues A, and when" is answered like any other review.

    Args:
        session: A write session.
        from_conversation_id: The chat the link starts from ("B" in "B continues A").
        kind: ``continues``, ``forked_from`` or ``related_to``.
        to_conversation_id: The chat it points to.
        reviewer: Who said so.
        note: Why, optionally.
        replaces: The ``rel_`` ID this link retypes, if any (kept in its evidence).

    Raises:
        KeyError: A chat doesn't exist.
        RelationshipError: Another kind, a chat linked to itself, no reviewer,
            or the same hand-made link is already stored (in any state: a
            rejected or replaced hand-made link is reviewed again, not re-added,
            so its history stays in one place).
    """
    from knowledge_engine.importer.records import ConversationRow

    if kind not in HUMAN_KINDS:
        raise RelationshipError("a hand-made link is continues, forked_from or related_to")
    if from_conversation_id == to_conversation_id:
        raise RelationshipError("a chat can't be linked to itself")
    if not reviewer.strip():
        raise RelationshipError("a hand-made link needs a named reviewer")
    for conversation_id in (from_conversation_id, to_conversation_id):
        if session.get(ConversationRow, conversation_id) is None:
            raise KeyError("no such conversation")
    key = relationship_id(from_conversation_id, kind.value, to_conversation_id, HUMAN_DETECTOR)
    if session.get(ConversationRelationshipRow, key) is not None:
        raise RelationshipError("that link is already recorded; review it instead")
    evidence: dict[str, Any] = {"stated_by": reviewer}
    if replaces is not None:
        evidence["replaces"] = replaces
    row = ConversationRelationshipRow(
        relationship_id=key,
        from_conversation_id=from_conversation_id,
        kind=kind.value,
        to_conversation_id=to_conversation_id,
        evidence_class=EvidenceClass.HUMAN.value,
        confidence=1.0,
        review_state=ReviewState.ACCEPTED.value,
        detector=HUMAN_DETECTOR,
        evidence_json=json.dumps(evidence, sort_keys=True),
        first_import_id=None,
    )
    session.add(row)
    session.add(
        RelationshipReviewRow(
            relationship_id=key,
            action=ReviewAction.ACCEPT.value,
            from_state=ReviewState.CANDIDATE.value,
            to_state=ReviewState.ACCEPTED.value,
            reviewer=reviewer,
            note=note,
        )
    )
    session.flush()
    return row


def retype(
    session: Session,
    relationship: str,
    kind: RelationKind,
    *,
    reverse: bool,
    reviewer: str,
    note: str | None = None,
) -> ConversationRelationshipRow:
    """Accept a link as another kind or the other way round (REL-006). The caller commits.

    The old row is never edited: its kind and direction are part of its ID.
    It is marked ``superseded`` (with this reviewer and note in its history)
    and a new hand-made link records what the person said instead, naming
    the old one in its evidence. Readers then show only the new link.

    Raises:
        KeyError: No such relationship.
        RelationshipError: See ``add_human``; also when nothing would change,
            or the old link is already rejected or superseded.
    """
    old = session.get(ConversationRelationshipRow, relationship)
    if old is None:
        raise KeyError("no such relationship")
    # A rejection sticks and a superseded link already has its replacement:
    # only an open or accepted link can be restated.
    if old.review_state not in (ReviewState.CANDIDATE.value, ReviewState.ACCEPTED.value):
        raise RelationshipError(f"the link is {old.review_state}; it can't be retyped")
    start, end = old.from_conversation_id, old.to_conversation_id
    if reverse:
        start, end = end, start
    if kind.value == old.kind and not reverse:
        raise RelationshipError("same kind and direction: accept it instead")
    new = add_human(
        session,
        from_conversation_id=start,
        kind=kind,
        to_conversation_id=end,
        reviewer=reviewer,
        note=note,
        replaces=relationship,
    )
    review(session, relationship, ReviewAction.SUPERSEDE, reviewer=reviewer, note=note)
    return new
