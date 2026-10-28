"""How decisions moved: proposed, accepted, rejected, revised, replaced (REC-004).

A decision has a history. The assistant proposes SQLite, the user accepts,
months later the user clarifies it ("SQLite, but in WAL mode") or replaces
it. This module keeps that history as **transition events** between
knowledge records, using the predicates of DATA_MODEL_AND_CONTRACTS §3:

=================  =============================================================
``proposes``       a proposal or recommendation is put forward (no target)
``accepts``        the user's decision takes up a proposal
``rejects``        the user's rejection turns one down
``clarifies``      later evidence narrows a decision; it does not replace it
``revises``        explicitly amends part of an earlier decision
``supersedes``     a later decision replaces an earlier one (REC-005 decides)
``contradicts``    two records conflict, and nothing says which holds
``related_to``     associated, not causal history
``revokes``        withdraws an earlier event (the event itself stays)
=================  =============================================================

The ``decision_events`` table is **append-only**: database triggers refuse
UPDATE and DELETE. Nothing is ever rewritten. A wrong event is withdrawn
by appending a ``revokes`` event that points at it, so the history shows
both what was believed and when it was corrected.

``build_events`` derives the events that need no judgement:

* ``proposes`` for every proposal or recommendation;
* ``accepts`` / ``rejects`` when a decision or rejection cites the very
  same proposal sentence (same message, same characters);
* ``contradicts`` for every unresolved REC-003 conflict.

``record_event`` is the checked entry point for everything else (a
reviewer's ``clarifies`` or ``revises``, REC-005's ``supersedes``). It
refuses predicates between the wrong record types, rejected records, and a
``supersedes`` that points forward in time.

Talking points:
    - "Every step of a decision is an event: who proposed it, who accepted
      it, what replaced it. Events are never edited or deleted."
    - "A mistake is fixed by adding a 'revokes' event, so the history shows
      the correction too."
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

from sqlalchemy import CheckConstraint, DateTime, Float, ForeignKey, String, Text, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from knowledge_engine.extraction.records import KnowledgeRecord, RecordType, Trust
from knowledge_engine.extraction.store import KnowledgeRecordRow
from knowledge_engine.infrastructure.db import Base
from knowledge_engine.reconciliation.conflicts import ConflictState, RecordConflictRow
from knowledge_engine.reconciliation.relations import Placed, place

DETECTOR_VERSION = "rec-004-v1"


class Transition(StrEnum):
    """The kinds of step in a decision's history (DATA_MODEL_AND_CONTRACTS §3)."""

    PROPOSES = "proposes"
    ACCEPTS = "accepts"
    REJECTS = "rejects"
    CLARIFIES = "clarifies"
    REVISES = "revises"
    SUPERSEDES = "supersedes"
    CONTRADICTS = "contradicts"
    RELATED_TO = "related_to"
    REVOKES = "revokes"


OFFERS = frozenset({RecordType.PROPOSAL, RecordType.RECOMMENDATION})
CHOICES = frozenset({RecordType.DECISION, RecordType.REQUIREMENT})


def _utc_now() -> datetime:
    return datetime.now(UTC)


_PREDICATES = ",".join(f"'{t.value}'" for t in Transition)


class DecisionEventRow(Base):
    """One step in a decision's history. Append-only."""

    __tablename__ = "decision_events"
    __table_args__ = (CheckConstraint(f"predicate IN ({_PREDICATES})", name="predicate_valid"),)

    event_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    predicate: Mapped[str] = mapped_column(String(12))
    from_record: Mapped[str | None] = mapped_column(
        ForeignKey("knowledge_records.record_id"), index=True, default=None
    )
    to_record: Mapped[str | None] = mapped_column(
        ForeignKey("knowledge_records.record_id"), index=True, default=None
    )
    revokes_event: Mapped[str | None] = mapped_column(
        ForeignKey("decision_events.event_id"), default=None
    )
    # When it happened in the chats (the source message time), if known.
    happened_at: Mapped[float | None] = mapped_column(Float, default=None)
    actor: Mapped[str] = mapped_column(String(100))
    evidence_json: Mapped[str] = mapped_column(Text, default="{}")
    note: Mapped[str | None] = mapped_column(Text, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)


# Created by migration 0025. Kept here so tests that build the schema
# without Alembic can install the same guard.
APPEND_ONLY_TRIGGERS = (
    "CREATE TRIGGER IF NOT EXISTS decision_events_no_update "
    "BEFORE UPDATE ON decision_events "
    "BEGIN SELECT RAISE(ABORT, 'decision_events is append-only'); END",
    "CREATE TRIGGER IF NOT EXISTS decision_events_no_delete "
    "BEFORE DELETE ON decision_events "
    "BEGIN SELECT RAISE(ABORT, 'decision_events is append-only'); END",
)


class TransitionError(ValueError):
    """An event the timeline refuses."""


def event_id(predicate: Transition, source: str | None, target: str | None, actor: str) -> str:
    """``kev_`` + hash of what, between which records, and who: one event per fact."""
    key = "\x00".join((predicate.value, source or "", target or "", actor))
    return "kev_" + hashlib.sha256(key.encode()).hexdigest()[:32]


def check(predicate: Transition, source: Placed, target: Placed | None) -> None:
    """Refuse an event that the record types or times don't allow.

    Raises:
        TransitionError: With the reason.
    """
    if Trust.REJECTED in (source.record.trust, target.record.trust if target else None):
        raise TransitionError("a rejected record takes part in no transition")
    kind = source.record.record_type
    if predicate is Transition.PROPOSES:
        if target is not None or kind not in OFFERS:
            raise TransitionError("only a proposal proposes, and it has no target")
        return
    if target is None:
        raise TransitionError(f"{predicate.value} needs a target record")
    if source.record.record_id == target.record.record_id:
        raise TransitionError("a record has no transition to itself")
    other = target.record.record_type
    if predicate is Transition.ACCEPTS and not (kind is RecordType.DECISION and other in OFFERS):
        raise TransitionError("accepts goes from a decision to a proposal")
    if predicate is Transition.REJECTS and not (kind is RecordType.REJECTION and other in OFFERS):
        raise TransitionError("rejects goes from a rejection to a proposal")
    if predicate in (Transition.CLARIFIES, Transition.REVISES, Transition.SUPERSEDES):
        if kind not in CHOICES or other not in CHOICES:
            raise TransitionError(f"{predicate.value} joins decisions or requirements")
        later, earlier = source.first_time, target.first_time
        if later is None or earlier is None or later <= earlier:
            # "A later date is not proof of replacement", but the reverse is
            # proof of none: nothing replaces what came after it.
            raise TransitionError(
                f"{predicate.value} must point from a later record to an earlier one"
            )
    if predicate is Transition.REVOKES:
        raise TransitionError("use revoke() to withdraw an event")


def record_event(
    session: Session,
    predicate: Transition,
    source: Placed,
    target: Placed | None,
    *,
    actor: str,
    evidence: dict[str, object] | None = None,
    note: str | None = None,
) -> tuple[DecisionEventRow, bool]:
    """Append one checked event, unless the same actor already recorded it.

    Args:
        session: The caller commits.
        predicate: What happened.
        source: The record it starts from.
        target: The record it points to (None only for ``proposes``).
        actor: A detector version or a named reviewer.
        evidence: IDs backing it; both records' source revisions are added.
        note: Why, for a reviewer's event.

    Returns:
        The event and whether it is new.

    Raises:
        TransitionError: See ``check``; also an unnamed actor.
    """
    if not actor.strip():
        raise TransitionError("an event needs an actor")
    check(predicate, source, target)
    key = event_id(
        predicate, source.record.record_id, target.record.record_id if target else None, actor
    )
    existing = session.get(DecisionEventRow, key)
    if existing is not None:
        return existing, False
    cited = {"from_revisions": list(source.revisions)}
    if target is not None:
        cited["to_revisions"] = list(target.revisions)
    row = DecisionEventRow(
        event_id=key,
        predicate=predicate.value,
        from_record=source.record.record_id,
        to_record=target.record.record_id if target else None,
        happened_at=source.first_time,
        actor=actor,
        evidence_json=json.dumps({**(evidence or {}), **cited}, sort_keys=True),
        note=note,
    )
    session.add(row)
    session.flush()
    return row, True


def revoke(session: Session, event: str, *, reviewer: str, note: str) -> DecisionEventRow:
    """Withdraw an event by appending a ``revokes`` event. The original stays.

    Raises:
        KeyError: No such event.
        TransitionError: No reviewer or reason, a revocation of a
            revocation, or an event already revoked.
    """
    target = session.get(DecisionEventRow, event)
    if target is None:
        raise KeyError("no such event")
    if not reviewer.strip() or not note.strip():
        raise TransitionError("a revocation needs a named reviewer and a reason")
    if target.predicate == Transition.REVOKES:
        raise TransitionError("record a new event instead of revoking a revocation")
    if event in revoked(session):
        raise TransitionError("the event is already revoked")
    row = DecisionEventRow(
        event_id=event_id(Transition.REVOKES, event, None, reviewer),
        predicate=Transition.REVOKES.value,
        revokes_event=event,
        happened_at=None,
        actor=reviewer,
        note=note,
    )
    session.add(row)
    session.flush()
    return row


def revoked(session: Session) -> set[str]:
    """IDs of the events that a ``revokes`` event withdrew."""
    return set(
        session.scalars(
            select(DecisionEventRow.revokes_event).where(
                DecisionEventRow.revokes_event.is_not(None)
            )
        )
    )


def _same_quote(a: KnowledgeRecord, b: KnowledgeRecord) -> bool:
    spans = {(e.revision_id, e.start, e.end) for e in a.evidence}
    return any((e.revision_id, e.start, e.end) in spans for e in b.evidence)


@dataclass(frozen=True)
class BuildReport:
    """What one ``build_events`` run added, per predicate."""

    added: dict[str, int]
    known: int


def build_events(session: Session) -> BuildReport:
    """Derive the events that need no judgement (see the module text). The caller commits."""
    rows = session.scalars(select(KnowledgeRecordRow).order_by(KnowledgeRecordRow.record_id))
    placed = {
        p.record.record_id: p
        for p in place(session, [KnowledgeRecord.model_validate_json(r.record_json) for r in rows])
        if p.record.trust is not Trust.REJECTED
    }
    added: dict[str, int] = {}
    known = 0

    def emit(predicate: Transition, source: Placed, target: Placed | None, **extra: object) -> None:
        nonlocal known
        _, new = record_event(
            session, predicate, source, target, actor=DETECTOR_VERSION, evidence=dict(extra)
        )
        if new:
            added[predicate.value] = added.get(predicate.value, 0) + 1
        else:
            known += 1

    offers = [p for p in placed.values() if p.record.record_type in OFFERS]
    for offer in offers:
        emit(Transition.PROPOSES, offer, None)
    for item in placed.values():
        answer = {
            RecordType.DECISION: Transition.ACCEPTS,
            RecordType.REJECTION: Transition.REJECTS,
        }.get(item.record.record_type)
        if answer is None:
            continue
        for offer in offers:
            if _same_quote(item.record, offer.record):
                emit(answer, item, offer, basis="cites_the_proposal")
    for conflict in session.scalars(
        select(RecordConflictRow).where(RecordConflictRow.state == ConflictState.UNRESOLVED.value)
    ):
        a, b = placed.get(conflict.record_a), placed.get(conflict.record_b)
        if a is None or b is None:
            continue
        later, earlier = (a, b) if (a.first_time or 0) >= (b.first_time or 0) else (b, a)
        emit(Transition.CONTRADICTS, later, earlier, conflict_id=conflict.conflict_id)
    return BuildReport(dict(sorted(added.items())), known)


@dataclass(frozen=True)
class TimelineEntry:
    """One event as a timeline shows it.

    Attributes:
        event_id: The ``kev_`` ID.
        predicate: What happened.
        from_record: Where it starts (None for a revocation).
        to_record: Where it points, if anywhere.
        happened_at: Source message time, if known.
        actor: Detector version or reviewer.
        revoked: True if a later ``revokes`` event withdrew it.
        revokes_event: For a revocation, the event it withdraws.
    """

    event_id: str
    predicate: str
    from_record: str | None
    to_record: str | None
    happened_at: float | None
    actor: str
    revoked: bool
    revokes_event: str | None


def timeline(session: Session, record_ids: Iterable[str] | None = None) -> list[TimelineEntry]:
    """Events touching these records (all if None), oldest first.

    Order: source time (unknown last), then when the event was recorded.
    Revoked events are included and marked; revocations of shown events too.
    """
    rows: Sequence[DecisionEventRow] = session.scalars(select(DecisionEventRow)).all()
    if record_ids is not None:
        wanted = set(record_ids)
        shown = {r.event_id for r in rows if {r.from_record, r.to_record} & wanted}
        rows = [r for r in rows if r.event_id in shown or r.revokes_event in shown]
    withdrawn = {r.revokes_event for r in rows if r.revokes_event}
    ordered = sorted(
        rows,
        key=lambda r: (
            r.happened_at is None,
            r.happened_at or 0.0,
            r.created_at,
            r.event_id,
        ),
    )
    return [
        TimelineEntry(
            r.event_id,
            r.predicate,
            r.from_record,
            r.to_record,
            r.happened_at,
            r.actor,
            r.event_id in withdrawn,
            r.revokes_event,
        )
        for r in ordered
    ]
