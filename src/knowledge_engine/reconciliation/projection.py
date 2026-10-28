"""What holds now, or held on a date, and why (REC-006).

The projector answers "what did I decide?" from the stored records and
the REC-004 timeline, without ever editing either. For each decision,
rejection, requirement and preference in scope it gives a **status** and
the **events that explain it**:

* ``current``: evidence-checked (``supported`` or ``confirmed``) and
  nothing replaces it;
* ``superseded``: a later record replaced it through a ``supersedes``
  event (REC-005 or a reviewer), and the event was not revoked;
* ``conflicted``: it is current, but an unresolved REC-003 conflict pairs
  it with another current record. Both stay visible; neither wins;
* ``pending``: proposed but not evidence-checked yet, or waiting for a
  reviewer. Never presented as a decision;
* ``unknown``: an ``as_of`` date was asked for and the record's own time
  is unknown, so it can't be placed before or after the date.

Proposals are reported separately as ``accepted``, ``rejected`` or
``open``, from the ``accepts`` and ``rejects`` events.

**Two clocks, so a past view is reproducible.**

* ``as_of`` (source time, seconds since 1970): only records whose source
  messages are at or before it, and only events that happened by then.
* ``known_at`` (record-keeping time): only records, events, revocations
  and conflict reviews that were stored by then.

Together they answer "what did the chats say by March, as we understood it
on 1 June?". Because every table read here is append-only or only ever
gains rows, the same two dates always give the same answer, however much
is added later.

Talking points:
    - "For every decision it says current, replaced, in conflict, pending or
      unknown, and lists the events behind that."
    - "Ask about a past date and you get exactly what we knew then; later
      additions don't change the old picture."
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

from sqlalchemy import select
from sqlalchemy.orm import Session

from knowledge_engine.extraction.records import KnowledgeRecord, RecordType, Trust
from knowledge_engine.extraction.store import KnowledgeRecordEventRow, KnowledgeRecordRow
from knowledge_engine.reconciliation.conflicts import (
    ConflictState,
    RecordConflictReviewRow,
    RecordConflictRow,
)
from knowledge_engine.reconciliation.relations import Placed, place
from knowledge_engine.reconciliation.timeline import OFFERS, DecisionEventRow, Transition

STATED = frozenset(
    {RecordType.DECISION, RecordType.REJECTION, RecordType.REQUIREMENT, RecordType.PREFERENCE}
)
TRUSTED = frozenset({Trust.SUPPORTED, Trust.CONFIRMED})


class Status(StrEnum):
    """Where a stated record stands in a projection."""

    CURRENT = "current"
    SUPERSEDED = "superseded"
    CONFLICTED = "conflicted"
    PENDING = "pending"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class Entry:
    """One record's standing.

    Attributes:
        record_id: The ``krec_`` ID.
        record_type: Its kind.
        status: Its standing (see the module text).
        because: Event and conflict IDs that explain it, oldest first.
        superseded_by: Records that replaced it.
        conflicts_with: Current records it is in unresolved conflict with.
    """

    record_id: str
    record_type: str
    status: Status
    because: tuple[str, ...]
    superseded_by: tuple[str, ...] = ()
    conflicts_with: tuple[str, ...] = ()


@dataclass(frozen=True)
class ProposalEntry:
    """A proposal's outcome: ``accepted``, ``rejected`` or ``open``."""

    record_id: str
    outcome: str
    because: tuple[str, ...]


@dataclass(frozen=True)
class Projection:
    """The state of things for one scope, at one pair of dates.

    Attributes:
        as_of: The source-time cut-off, if any.
        known_at: The record-keeping cut-off, if any.
        entries: Stated records, by record ID.
        proposals: Proposals and their outcomes, by record ID.
        unresolved_conflicts: Conflict IDs still open between current records.
    """

    as_of: float | None
    known_at: datetime | None
    entries: tuple[Entry, ...]
    proposals: tuple[ProposalEntry, ...]
    unresolved_conflicts: tuple[str, ...]

    def by_status(self, status: Status) -> list[str]:
        """Record IDs with this status."""
        return [e.record_id for e in self.entries if e.status is status]


def _aware(moment: datetime) -> datetime:
    # SQLite hands timezone-aware columns back naive; they were stored in UTC.
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def _known(moment: datetime, known_at: datetime | None) -> bool:
    return known_at is None or _aware(moment) <= _aware(known_at)


def _trust_at(session: Session, record_id: str, known_at: datetime | None) -> Trust | None:
    # The trust a record had at ``known_at``, from its append-only history.
    last = None
    for event in session.scalars(
        select(KnowledgeRecordEventRow)
        .where(KnowledgeRecordEventRow.record_id == record_id)
        .order_by(KnowledgeRecordEventRow.event_id)
    ):
        if _known(event.at, known_at):
            last = Trust(event.to_trust)
    return last


def _in_scope(item: Placed, project_id: str | None, conversation_id: str | None) -> bool:
    if project_id is not None and project_id not in item.record.project_ids:
        return False
    return conversation_id is None or item.conversation_id == conversation_id


def project(
    session: Session,
    *,
    as_of: float | None = None,
    known_at: datetime | None = None,
    project_id: str | None = None,
    conversation_id: str | None = None,
) -> Projection:
    """Project the state of stated records and proposals. Reads only.

    Args:
        session: A read session.
        as_of: Source-time cut-off (seconds since 1970), or None for now.
        known_at: Record-keeping cut-off, or None for everything stored.
        project_id: Only records naming this project.
        conversation_id: Only records whose sources are in this chat.

    Returns:
        The projection, entries sorted by record ID.
    """
    rows = [
        r
        for r in session.scalars(select(KnowledgeRecordRow).order_by(KnowledgeRecordRow.record_id))
        if _known(r.created_at, known_at)
    ]
    placed = {
        p.record.record_id: p
        for p in place(session, [KnowledgeRecord.model_validate_json(r.record_json) for r in rows])
        if _in_scope(p, project_id, conversation_id)
    }
    trust = {
        record_id: _trust_at(session, record_id, known_at)
        if known_at
        else placed[record_id].record.trust
        for record_id in placed
    }

    def visible(item: Placed) -> bool | None:
        # True: in the window; False: after it; None: can't tell.
        if as_of is None:
            return True
        if item.first_time is None:
            return None
        return item.first_time <= as_of

    events = [
        e
        for e in session.scalars(select(DecisionEventRow).order_by(DecisionEventRow.event_id))
        if _known(e.created_at, known_at)
    ]
    withdrawn = {e.revokes_event for e in events if e.revokes_event}
    live = [
        e
        for e in events
        if e.event_id not in withdrawn
        and e.predicate != Transition.REVOKES
        and (as_of is None or (e.happened_at is not None and e.happened_at <= as_of))
    ]
    live.sort(key=lambda e: (e.happened_at or 0.0, e.event_id))

    replaced_by: dict[str, list[tuple[str, str]]] = defaultdict(list)
    answers: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for event in live:
        if event.from_record not in placed or event.to_record not in placed:
            continue
        assert event.from_record is not None and event.to_record is not None
        if visible(placed[event.from_record]) is not True:
            continue
        if event.predicate == Transition.SUPERSEDES:
            replaced_by[event.to_record].append((event.from_record, event.event_id))
        elif event.predicate in (Transition.ACCEPTS, Transition.REJECTS):
            answers[event.to_record].append((event.predicate, event.event_id))

    entries: dict[str, Entry] = {}
    for record_id, item in placed.items():
        if item.record.record_type not in STATED:
            continue
        seen = visible(item)
        if seen is False:
            continue
        kind = item.record.record_type.value
        if seen is None:
            entries[record_id] = Entry(record_id, kind, Status.UNKNOWN, ())
        elif trust[record_id] not in TRUSTED:
            entries[record_id] = Entry(record_id, kind, Status.PENDING, ())
        elif record_id in replaced_by:
            later = replaced_by[record_id]
            entries[record_id] = Entry(
                record_id,
                kind,
                Status.SUPERSEDED,
                tuple(event for _, event in later),
                superseded_by=tuple(sorted({r for r, _ in later})),
            )
        else:
            entries[record_id] = Entry(record_id, kind, Status.CURRENT, ())

    open_conflicts = []
    for conflict in session.scalars(
        select(RecordConflictRow).order_by(RecordConflictRow.conflict_id)
    ):
        if not _known(conflict.created_at, known_at):
            continue
        if _conflict_state(session, conflict, known_at) is not ConflictState.UNRESOLVED:
            continue
        a, b = entries.get(conflict.record_a), entries.get(conflict.record_b)
        if a is None or b is None:
            continue
        if {a.status, b.status} - {Status.CURRENT, Status.CONFLICTED}:
            continue  # one side is replaced, pending or unplaced: nothing to weigh now
        open_conflicts.append(conflict.conflict_id)
        for one, other in ((a, b), (b, a)):
            entries[one.record_id] = Entry(
                one.record_id,
                one.record_type,
                Status.CONFLICTED,
                (*entries[one.record_id].because, conflict.conflict_id),
                conflicts_with=tuple(
                    sorted({*entries[one.record_id].conflicts_with, other.record_id})
                ),
            )

    proposals = []
    for record_id, item in placed.items():
        if item.record.record_type not in OFFERS or visible(item) is not True:
            continue
        said = answers.get(record_id, [])
        # The latest answer counts; the earlier ones stay in ``because``.
        outcome = (
            "open"
            if not said
            else ("accepted" if said[-1][0] == Transition.ACCEPTS else "rejected")
        )
        proposals.append(ProposalEntry(record_id, outcome, tuple(e for _, e in said)))

    return Projection(
        as_of,
        known_at,
        tuple(entries[k] for k in sorted(entries)),
        tuple(proposals),
        tuple(open_conflicts),
    )


def _conflict_state(
    session: Session, conflict: RecordConflictRow, known_at: datetime | None
) -> ConflictState:
    if known_at is None:
        return ConflictState(conflict.state)
    state = ConflictState.UNRESOLVED
    for review in session.scalars(
        select(RecordConflictReviewRow)
        .where(RecordConflictReviewRow.conflict_id == conflict.conflict_id)
        .order_by(RecordConflictReviewRow.review_id)
    ):
        if _known(review.at, known_at):
            state = ConflictState(review.to_state)
    return state
