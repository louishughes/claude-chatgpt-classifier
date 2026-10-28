"""Records that cannot both hold: conflicts, found and left unresolved (REC-003).

A conflict is two records by the same person, about the same thing, in an
overlapping scope, that pull in different directions:

* ``accepted_and_rejected``: a decision and a rejection of the same thing;
* ``polarity``: a preference *for* and a preference *against* it;
* ``negation``: the same statement with and without "not";
* ``numbers``: the same statement with different numbers (port 8080
  versus 8081, "under ten minutes" versus "under 20").

"About the same thing" uses REC-001's content words: they must share at
least ``THRESHOLD`` of them. Only decisions, rejections, requirements and
preferences are compared, and records of a reported speaker (someone the
user quoted) are compared only with the same reported speaker.

**Scope.** Two records conflict only if their scopes overlap:

* both name projects and share one; records for different projects never
  conflict, however alike they read;
* neither names a project and both come from the same chat;
* or both are the user's own preferences, which apply everywhere.

**No winner by date.** A later record is not assumed to replace an earlier
one: the conflict is stored ``unresolved`` with both records' source
revisions, and the order is recorded only as context. Deciding which holds
(supersession) is REC-004/REC-005's job, with evidence. A reviewer can mark
a conflict ``dismissed`` (not really a conflict) or ``resolved`` with a
note; every review is kept in an append-only log.

Talking points:
    - "Two of my statements conflict only if they're about the same thing,
      in the same project or chat, and point opposite ways."
    - "The newer one doesn't win automatically. The conflict stays open
      until there's evidence or a reviewer says how it ends."
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, Text, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from knowledge_engine.domain.enums import Role
from knowledge_engine.extraction.records import KnowledgeRecord, RecordType, Trust
from knowledge_engine.extraction.store import KnowledgeRecordRow
from knowledge_engine.infrastructure.db import Base
from knowledge_engine.reconciliation.equivalence import THRESHOLD, content_words, differences
from knowledge_engine.reconciliation.relations import Placed, place

DETECTOR_VERSION = "rec-003-v1"
COMPARED = frozenset(
    {RecordType.DECISION, RecordType.REJECTION, RecordType.REQUIREMENT, RecordType.PREFERENCE}
)


class ConflictKind(StrEnum):
    """How two records pull apart."""

    ACCEPTED_AND_REJECTED = "accepted_and_rejected"
    POLARITY = "polarity"
    NEGATION = "negation"
    NUMBERS = "numbers"


class ConflictState(StrEnum):
    """Where a conflict stands. New conflicts are always unresolved."""

    UNRESOLVED = "unresolved"
    DISMISSED = "dismissed"
    RESOLVED = "resolved"


def _utc_now() -> datetime:
    return datetime.now(UTC)


class RecordConflictRow(Base):
    """Two records that cannot both hold, as far as the detector can tell."""

    __tablename__ = "record_conflicts"
    __table_args__ = (
        CheckConstraint("state IN ('unresolved','dismissed','resolved')", name="state_valid"),
        CheckConstraint("record_a < record_b", name="pair_ordered"),
    )

    conflict_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    record_a: Mapped[str] = mapped_column(ForeignKey("knowledge_records.record_id"), index=True)
    record_b: Mapped[str] = mapped_column(ForeignKey("knowledge_records.record_id"), index=True)
    kinds_json: Mapped[str] = mapped_column(Text)
    scope_json: Mapped[str] = mapped_column(Text)
    evidence_json: Mapped[str] = mapped_column(Text)
    detector: Mapped[str] = mapped_column(String(40))
    state: Mapped[str] = mapped_column(String(10), default=ConflictState.UNRESOLVED.value)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)


class RecordConflictReviewRow(Base):
    """One review decision on a conflict. Append-only."""

    __tablename__ = "record_conflict_reviews"

    review_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conflict_id: Mapped[str] = mapped_column(ForeignKey("record_conflicts.conflict_id"), index=True)
    from_state: Mapped[str] = mapped_column(String(10))
    to_state: Mapped[str] = mapped_column(String(10))
    reviewer: Mapped[str] = mapped_column(String(100))
    note: Mapped[str] = mapped_column(Text)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)


# Created by migration 0024. Kept here so tests that build the schema
# without Alembic can install the same guard.
APPEND_ONLY_TRIGGERS = (
    "CREATE TRIGGER IF NOT EXISTS record_conflict_reviews_no_update "
    "BEFORE UPDATE ON record_conflict_reviews "
    "BEGIN SELECT RAISE(ABORT, 'record_conflict_reviews is append-only'); END",
    "CREATE TRIGGER IF NOT EXISTS record_conflict_reviews_no_delete "
    "BEFORE DELETE ON record_conflict_reviews "
    "BEGIN SELECT RAISE(ABORT, 'record_conflict_reviews is append-only'); END",
)


class ConflictError(ValueError):
    """A review the store refuses."""


@dataclass(frozen=True)
class Conflict:
    """A detected conflict, before it is stored.

    Attributes:
        record_a: The smaller record ID.
        record_b: The larger record ID.
        kinds: How they pull apart.
        scope: Why their scopes overlap (``project``, ``conversation`` or
            ``personal_preference``) and the shared IDs.
        evidence: Both records' source revisions and their order (context
            only: the order never decides the conflict).
    """

    record_a: str
    record_b: str
    kinds: tuple[ConflictKind, ...]
    scope: dict[str, object]
    evidence: dict[str, object]

    @property
    def conflict_id(self) -> str:
        """``kcf_`` + hash of the two record IDs."""
        key = f"{self.record_a}\x00{self.record_b}"
        return "kcf_" + hashlib.sha256(key.encode()).hexdigest()[:32]


def overlap(a: Placed, b: Placed) -> dict[str, object] | None:
    """Why the two records' scopes overlap, or None if they don't."""
    projects_a, projects_b = set(a.record.project_ids), set(b.record.project_ids)
    if projects_a or projects_b:
        shared = sorted(projects_a & projects_b)
        return {"by": "project", "project_ids": shared} if shared else None
    if a.conversation_id is not None and a.conversation_id == b.conversation_id:
        return {"by": "conversation", "conversation_id": a.conversation_id}
    preferences = {a.record.record_type, b.record.record_type} == {RecordType.PREFERENCE}
    if preferences and a.record.actor is Role.USER and b.record.actor is Role.USER:
        return {"by": "personal_preference"}
    return None


def _kinds(a: KnowledgeRecord, b: KnowledgeRecord) -> tuple[ConflictKind, ...]:
    kinds = []
    types = {a.record_type, b.record_type}
    if types == {RecordType.DECISION, RecordType.REJECTION}:
        kinds.append(ConflictKind.ACCEPTED_AND_REJECTED)
    elif len(types) > 1:
        return ()  # e.g. a preference and a requirement: different things
    if a.polarity is not None and b.polarity is not None and a.polarity is not b.polarity:
        kinds.append(ConflictKind.POLARITY)
    found = differences(a, b)
    if "negation" in found:
        kinds.append(ConflictKind.NEGATION)
    if "numbers" in found:
        kinds.append(ConflictKind.NUMBERS)
    return tuple(kinds)


def _order(a: Placed, b: Placed) -> str:
    if a.first_time is None or b.first_time is None or a.first_time == b.first_time:
        return "unknown"
    return "a_first" if a.first_time < b.first_time else "b_first"


def compare(a: Placed, b: Placed, threshold: float = THRESHOLD) -> Conflict | None:
    """Return the conflict between two placed records, or None."""
    ra, rb = a.record, b.record
    if ra.record_id == rb.record_id or Trust.REJECTED in (ra.trust, rb.trust):
        return None
    if ra.record_type not in COMPARED or rb.record_type not in COMPARED:
        return None
    if ra.actor is not rb.actor or ra.attributed_to != rb.attributed_to:
        return None
    scope = overlap(a, b)
    if scope is None:
        return None
    words_a, words_b = content_words(ra.assertion), content_words(rb.assertion)
    if not words_a or not words_b:
        return None
    if len(words_a & words_b) / len(words_a | words_b) < threshold:
        return None
    kinds = _kinds(ra, rb)
    if not kinds:
        return None
    first, second = sorted((a, b), key=lambda p: p.record.record_id)
    return Conflict(
        first.record.record_id,
        second.record.record_id,
        kinds,
        scope,
        {
            "a_revisions": list(first.revisions),
            "b_revisions": list(second.revisions),
            "order": _order(first, second),
        },
    )


def find_conflicts(items: Sequence[Placed], threshold: float = THRESHOLD) -> list[Conflict]:
    """Every conflict among the placed records, sorted by conflict ID.

    Only records sharing a content word are compared, so the work grows
    with plausible pairs, not with every pair.
    """
    usable = [i for i in items if i.record.record_type in COMPARED and i.revisions]
    by_word: dict[str, list[int]] = defaultdict(list)
    for index, item in enumerate(usable):
        for word in content_words(item.record.assertion):
            by_word[word].append(index)
    pairs = {(i, j) for indexes in by_word.values() for i in indexes for j in indexes if i < j}
    found: dict[str, Conflict] = {}
    for i, j in sorted(pairs):
        conflict = compare(usable[i], usable[j], threshold)
        if conflict is not None:
            found[conflict.conflict_id] = conflict
    return [found[key] for key in sorted(found)]


@dataclass(frozen=True)
class ConflictReport:
    """What one detection run did.

    Attributes:
        added: Conflict IDs newly recorded.
        known: Conflicts already stored (left exactly as they were).
    """

    added: tuple[str, ...]
    known: tuple[str, ...]


def detect_conflicts(session: Session) -> ConflictReport:
    """Record every new conflict as ``unresolved``. The caller commits."""
    rows = session.scalars(select(KnowledgeRecordRow).order_by(KnowledgeRecordRow.record_id))
    records = [KnowledgeRecord.model_validate_json(row.record_json) for row in rows]
    added, known = [], []
    for conflict in find_conflicts(place(session, records)):
        if session.get(RecordConflictRow, conflict.conflict_id) is not None:
            known.append(conflict.conflict_id)
            continue
        session.add(
            RecordConflictRow(
                conflict_id=conflict.conflict_id,
                record_a=conflict.record_a,
                record_b=conflict.record_b,
                kinds_json=json.dumps([k.value for k in conflict.kinds]),
                scope_json=json.dumps(conflict.scope, sort_keys=True),
                evidence_json=json.dumps(conflict.evidence, sort_keys=True),
                detector=DETECTOR_VERSION,
            )
        )
        added.append(conflict.conflict_id)
    session.flush()
    return ConflictReport(tuple(added), tuple(known))


def review_conflict(
    session: Session, conflict: str, decision: ConflictState, *, reviewer: str, note: str
) -> RecordConflictReviewRow:
    """Dismiss, resolve or re-open a conflict, always with a reason. The caller commits.

    Raises:
        KeyError: No such conflict.
        ConflictError: No reviewer, no reason, or no change.
    """
    row = session.get(RecordConflictRow, conflict)
    if row is None:
        raise KeyError("no such conflict")
    if not reviewer.strip():
        raise ConflictError("a decision needs a named reviewer")
    if not note.strip():
        raise ConflictError("say why")
    if row.state == decision.value:
        raise ConflictError(f"the conflict is already {decision.value}")
    entry = RecordConflictReviewRow(
        conflict_id=conflict,
        from_state=row.state,
        to_state=decision.value,
        reviewer=reviewer,
        note=note,
    )
    session.add(entry)
    row.state = decision.value
    session.flush()
    return entry


def conflicts(
    session: Session, states: Iterable[ConflictState] = (ConflictState.UNRESOLVED,)
) -> list[RecordConflictRow]:
    """Stored conflicts in the given states (unresolved by default)."""
    return list(
        session.scalars(
            select(RecordConflictRow)
            .where(RecordConflictRow.state.in_([s.value for s in states]))
            .order_by(RecordConflictRow.conflict_id)
        )
    )
