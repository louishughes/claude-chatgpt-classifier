"""Typed links between knowledge records, each citing its sources (REC-002).

REC-001 asks "do these two records say the same thing?". This asks "how are
these two different records connected?". Only four kinds of link exist,
and each only between the record types it makes sense for:

=================  ==========================================  =============
Predicate          From -> to                                  Direction
=================  ==========================================  =============
``creates``        action / decision / proposal /              request ->
                   recommendation -> artefact                  what it made
``references``     any record but a reference -> a reference   mention ->
                   (a named game, book, tool...)               the thing
``elaborates``     a record -> an earlier record of the same   later detail
                   kind, person, direction and projects        -> the claim
``same_project``   a record -> a record in another chat that   later ->
                   shares a project *and* a topic              earlier
=================  ==========================================  =============

``allowed`` enforces that table: anything else is refused before it is
stored. Conversation-level links (continues, forked_from...) are not here;
they are REL-002's.

How each is detected, deterministically, from stored records only:

* **creates**: an artefact in a segment is linked to the latest request
  (action, decision, proposal, recommendation) in the same segment that
  came at or before it. One creator per artefact, so two requests and two
  images don't produce four links.
* **references**: a record in the same chat whose assertion contains the
  referenced thing's name as whole words.
* **elaborates**: a later record in the same chat that repeats most of an
  earlier record's content words and adds more. Pairs REC-001 would call
  the same claim are left to REC-001.
* **same_project**: records in different chats that share an approved
  project ID and a taxonomy term. Sharing a project alone is not enough:
  every record of a big project would link to every other.

Every link stores the source message revisions of both records (its
citation) and is a ``candidate`` until a named reviewer accepts or rejects
it. Reviews are append-only; a re-run never changes a reviewed link. The
records themselves are never edited.

Talking points:
    - "Only four typed links, each only between record kinds where it makes
      sense, and the code refuses anything else."
    - "Every link points at the messages behind both records, and it's a
      candidate until a reviewer says yes."
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, Text, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from knowledge_engine.extraction.records import KnowledgeRecord, RecordType, Trust
from knowledge_engine.extraction.store import KnowledgeRecordRow
from knowledge_engine.importer.media import AssetOccurrenceRow
from knowledge_engine.importer.records import MessageNodeRow, MessageRevisionRow
from knowledge_engine.infrastructure.db import Base
from knowledge_engine.reconciliation.equivalence import compare, content_words

DETECTOR_VERSION = "rec-002-v1"
ELABORATION_COVERAGE = 0.6


class Predicate(StrEnum):
    """The only kinds of record-to-record link."""

    CREATES = "creates"
    REFERENCES = "references"
    ELABORATES = "elaborates"
    SAME_PROJECT = "same_project"


class LinkState(StrEnum):
    """Where a link stands."""

    CANDIDATE = "candidate"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


REQUESTS = frozenset(
    {RecordType.ACTION, RecordType.DECISION, RecordType.PROPOSAL, RecordType.RECOMMENDATION}
)


def _utc_now() -> datetime:
    return datetime.now(UTC)


class RecordLinkRow(Base):
    """A typed link between two knowledge records."""

    __tablename__ = "record_links"
    __table_args__ = (
        CheckConstraint(
            "predicate IN ('creates','references','elaborates','same_project')",
            name="predicate_valid",
        ),
        CheckConstraint("state IN ('candidate','accepted','rejected')", name="state_valid"),
        CheckConstraint("from_record <> to_record", name="not_self"),
    )

    link_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    from_record: Mapped[str] = mapped_column(ForeignKey("knowledge_records.record_id"), index=True)
    predicate: Mapped[str] = mapped_column(String(14))
    to_record: Mapped[str] = mapped_column(ForeignKey("knowledge_records.record_id"), index=True)
    detector: Mapped[str] = mapped_column(String(40))
    evidence_json: Mapped[str] = mapped_column(Text)
    state: Mapped[str] = mapped_column(String(10), default=LinkState.CANDIDATE.value)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)


class RecordLinkReviewRow(Base):
    """One review decision on a link. Append-only."""

    __tablename__ = "record_link_reviews"

    review_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    link_id: Mapped[str] = mapped_column(ForeignKey("record_links.link_id"), index=True)
    from_state: Mapped[str] = mapped_column(String(10))
    to_state: Mapped[str] = mapped_column(String(10))
    reviewer: Mapped[str] = mapped_column(String(100))
    note: Mapped[str | None] = mapped_column(Text, default=None)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)


# Created by migration 0023. Kept here so tests that build the schema
# without Alembic can install the same guard.
APPEND_ONLY_TRIGGERS = (
    "CREATE TRIGGER IF NOT EXISTS record_link_reviews_no_update "
    "BEFORE UPDATE ON record_link_reviews "
    "BEGIN SELECT RAISE(ABORT, 'record_link_reviews is append-only'); END",
    "CREATE TRIGGER IF NOT EXISTS record_link_reviews_no_delete "
    "BEFORE DELETE ON record_link_reviews "
    "BEGIN SELECT RAISE(ABORT, 'record_link_reviews is append-only'); END",
)


class LinkError(ValueError):
    """A link or review the store refuses."""


@dataclass(frozen=True)
class Placed:
    """A record with where and when its sources are.

    Attributes:
        record: The stored record.
        conversation_id: The chat its sources are in (None if they span chats
            or none were found).
        revisions: The message revisions it cites (quotes and images).
        first_time: The earliest source message time, if known.
    """

    record: KnowledgeRecord
    conversation_id: str | None
    revisions: tuple[str, ...]
    first_time: float | None


@dataclass(frozen=True)
class LinkCandidate:
    """A proposed link, before it is stored.

    Attributes:
        from_record: Where the link starts.
        predicate: What kind of link.
        to_record: Where it points.
        evidence: IDs backing it (no text): both records' source revisions
            and what the detector matched on.
    """

    from_record: str
    predicate: Predicate
    to_record: str
    evidence: dict[str, object]

    @property
    def link_id(self) -> str:
        """``krl_`` + hash of the ends, the predicate and the detector."""
        key = "\x00".join(
            (self.from_record, self.predicate.value, self.to_record, DETECTOR_VERSION)
        )
        return "krl_" + hashlib.sha256(key.encode()).hexdigest()[:32]


def allowed(predicate: Predicate, source: KnowledgeRecord, target: KnowledgeRecord) -> bool:
    """Whether this predicate may join these two record types (the table above)."""
    if source.record_id == target.record_id:
        return False
    if predicate is Predicate.CREATES:
        return source.record_type in REQUESTS and target.record_type is RecordType.ARTEFACT
    if predicate is Predicate.REFERENCES:
        return (
            source.record_type is not RecordType.REFERENCE
            and target.record_type is RecordType.REFERENCE
        )
    if predicate is Predicate.ELABORATES:
        return (
            source.record_type is target.record_type
            and source.actor is target.actor
            and source.polarity is target.polarity
            and set(source.project_ids) == set(target.project_ids)
        )
    return bool(set(source.project_ids) & set(target.project_ids))


def place(session: Session, records: Sequence[KnowledgeRecord]) -> list[Placed]:
    """Find each record's source revisions, chat and earliest time."""
    occurrence_ids = [o for r in records for o in r.asset_occurrences]
    via_occurrence = {
        occurrence: revision
        for occurrence, revision in session.execute(
            select(AssetOccurrenceRow.occurrence_id, AssetOccurrenceRow.revision_id).where(
                AssetOccurrenceRow.occurrence_id.in_(occurrence_ids)
            )
        )
    }
    cited = {
        r.record_id: sorted(
            {e.revision_id for e in r.evidence}
            | {via_occurrence[o] for o in r.asset_occurrences if o in via_occurrence}
        )
        for r in records
    }
    wanted = sorted({rev for revs in cited.values() for rev in revs})
    where: dict[str, tuple[str, float | None]] = {}
    for start in range(0, len(wanted), 500):  # stay under SQLite's variable limit
        for revision, conversation, created in session.execute(
            select(
                MessageRevisionRow.revision_id,
                MessageNodeRow.conversation_id,
                MessageRevisionRow.create_time,
            )
            .join(MessageNodeRow, MessageNodeRow.node_key == MessageRevisionRow.node_key)
            .where(MessageRevisionRow.revision_id.in_(wanted[start : start + 500]))
        ):
            where[revision] = (conversation, created)
    placed = []
    for record in records:
        found = [where[rev] for rev in cited[record.record_id] if rev in where]
        chats = {chat for chat, _ in found}
        times = [t for _, t in found if t is not None]
        placed.append(
            Placed(
                record,
                next(iter(chats)) if len(chats) == 1 else None,
                tuple(cited[record.record_id]),
                min(times) if times else None,
            )
        )
    return placed


def _evidence(a: Placed, b: Placed, **matched: object) -> dict[str, object]:
    return {
        "from_revisions": list(a.revisions),
        "to_revisions": list(b.revisions),
        **matched,
    }


def _later(a: Placed, b: Placed) -> bool:
    # Strictly later by message time; equal times fall back to record ID so
    # the direction is still deterministic.
    if a.first_time is None or b.first_time is None:
        return False
    return (a.first_time, a.record.record_id) > (b.first_time, b.record.record_id)


def _creates(items: Sequence[Placed]) -> Iterable[LinkCandidate]:
    by_segment: dict[str, list[tuple[float, Placed]]] = defaultdict(list)
    for item in items:
        if item.record.scope_id and item.first_time is not None:
            by_segment[item.record.scope_id].append((item.first_time, item))
    for members in by_segment.values():
        requests = [(t, m) for t, m in members if m.record.record_type in REQUESTS]
        for when, artefact in members:
            if artefact.record.record_type is not RecordType.ARTEFACT:
                continue
            before = [(t, r) for t, r in requests if t <= when]
            if not before:
                continue
            latest = max(t for t, _ in before)
            for request in sorted(
                (r for t, r in before if t == latest), key=lambda r: r.record.record_id
            ):
                yield LinkCandidate(
                    request.record.record_id,
                    Predicate.CREATES,
                    artefact.record.record_id,
                    _evidence(request, artefact, segment_id=request.record.scope_id),
                )


def _name_pattern(name: str) -> re.Pattern[str]:
    return re.compile(r"(?<!\w)" + re.escape(name) + r"(?!\w)", re.IGNORECASE)


def _references(items: Sequence[Placed]) -> Iterable[LinkCandidate]:
    by_chat: dict[str, list[Placed]] = defaultdict(list)
    for item in items:
        if item.conversation_id is not None:
            by_chat[item.conversation_id].append(item)
    for members in by_chat.values():
        things = [
            m for m in members if m.record.record_type is RecordType.REFERENCE and m.record.entity
        ]
        for thing in things:
            assert thing.record.entity is not None
            pattern = _name_pattern(thing.record.entity.name)
            for other in members:
                if other.record.record_type is RecordType.REFERENCE:
                    continue
                if pattern.search(other.record.assertion):
                    yield LinkCandidate(
                        other.record.record_id,
                        Predicate.REFERENCES,
                        thing.record.record_id,
                        _evidence(other, thing, entity_type=thing.record.entity.entity_type.value),
                    )


def _elaborates(items: Sequence[Placed]) -> Iterable[LinkCandidate]:
    by_chat: dict[str, list[Placed]] = defaultdict(list)
    for item in items:
        if item.conversation_id is not None and item.first_time is not None:
            by_chat[item.conversation_id].append(item)
    for members in by_chat.values():
        for later in members:
            later_words = content_words(later.record.assertion)
            for earlier in members:
                if not _later(later, earlier) or not allowed(
                    Predicate.ELABORATES, later.record, earlier.record
                ):
                    continue
                earlier_words = content_words(earlier.record.assertion)
                if not earlier_words or len(later_words) <= len(earlier_words):
                    continue
                coverage = len(earlier_words & later_words) / len(earlier_words)
                if coverage < ELABORATION_COVERAGE or compare(later.record, earlier.record):
                    continue
                yield LinkCandidate(
                    later.record.record_id,
                    Predicate.ELABORATES,
                    earlier.record.record_id,
                    _evidence(later, earlier, coverage=round(coverage, 4)),
                )


def _same_project(items: Sequence[Placed]) -> Iterable[LinkCandidate]:
    by_project: dict[str, list[Placed]] = defaultdict(list)
    for item in items:
        if item.conversation_id is not None and item.first_time is not None:
            for project in item.record.project_ids:
                by_project[project].append(item)
    seen: set[tuple[str, str]] = set()
    for members in by_project.values():
        for later in members:
            for earlier in members:
                if later.conversation_id == earlier.conversation_id or not _later(later, earlier):
                    continue
                terms = sorted(set(later.record.term_ids) & set(earlier.record.term_ids))
                key = (later.record.record_id, earlier.record.record_id)
                if not terms or key in seen:
                    continue
                seen.add(key)
                projects = sorted(set(later.record.project_ids) & set(earlier.record.project_ids))
                yield LinkCandidate(
                    later.record.record_id,
                    Predicate.SAME_PROJECT,
                    earlier.record.record_id,
                    _evidence(later, earlier, project_ids=projects, term_ids=terms),
                )


def find_links(items: Sequence[Placed]) -> list[LinkCandidate]:
    """Every link the four detectors propose, sorted by link ID.

    Rejected records take part in nothing, and a record with no source
    revisions found is skipped: a link must be able to cite its sources.
    """
    usable = [i for i in items if i.record.trust is not Trust.REJECTED and i.revisions]
    by_id = {i.record.record_id: i.record for i in usable}
    found: dict[str, LinkCandidate] = {}
    for detector in (_creates, _references, _elaborates, _same_project):
        for candidate in detector(usable):
            if allowed(
                candidate.predicate, by_id[candidate.from_record], by_id[candidate.to_record]
            ):
                found[candidate.link_id] = candidate
    return [found[key] for key in sorted(found)]


@dataclass(frozen=True)
class LinkReport:
    """What one detection run did.

    Attributes:
        added: Link IDs newly proposed.
        known: Links already stored (left exactly as they were).
        by_predicate: New links per predicate.
    """

    added: tuple[str, ...]
    known: tuple[str, ...]
    by_predicate: dict[str, int]


def store_link(session: Session, candidate: LinkCandidate) -> bool:
    """Store one candidate link unless it is already known. The caller commits.

    Raises:
        LinkError: An unknown record, a predicate not allowed between these
            record types, or evidence that cites no source on either end.
    """
    ends = []
    for record_id in (candidate.from_record, candidate.to_record):
        row = session.get(KnowledgeRecordRow, record_id)
        if row is None:
            raise LinkError("no such record")
        ends.append(KnowledgeRecord.model_validate_json(row.record_json))
    if not allowed(candidate.predicate, ends[0], ends[1]):
        raise LinkError(f"{candidate.predicate.value} is not allowed between these records")
    if not candidate.evidence.get("from_revisions") or not candidate.evidence.get("to_revisions"):
        raise LinkError("a link must cite the sources of both records")
    if session.get(RecordLinkRow, candidate.link_id) is not None:
        return False
    session.add(
        RecordLinkRow(
            link_id=candidate.link_id,
            from_record=candidate.from_record,
            predicate=candidate.predicate.value,
            to_record=candidate.to_record,
            detector=DETECTOR_VERSION,
            evidence_json=json.dumps(candidate.evidence, sort_keys=True),
        )
    )
    session.flush()
    return True


def propose_links(session: Session) -> LinkReport:
    """Detect and store new candidate links over every stored record. The caller commits."""
    rows = session.scalars(select(KnowledgeRecordRow).order_by(KnowledgeRecordRow.record_id))
    records = [KnowledgeRecord.model_validate_json(row.record_json) for row in rows]
    added, known = [], []
    counts: dict[str, int] = defaultdict(int)
    for candidate in find_links(place(session, records)):
        if store_link(session, candidate):
            added.append(candidate.link_id)
            counts[candidate.predicate.value] += 1
        else:
            known.append(candidate.link_id)
    return LinkReport(tuple(added), tuple(known), dict(sorted(counts.items())))


def review_link(
    session: Session, link: str, decision: LinkState, *, reviewer: str, note: str | None = None
) -> RecordLinkReviewRow:
    """Accept or reject a link (or change an earlier decision). The caller commits.

    Raises:
        KeyError: No such link.
        LinkError: No reviewer, ``candidate`` as a decision, or no change.
    """
    row = session.get(RecordLinkRow, link)
    if row is None:
        raise KeyError("no such link")
    if not reviewer.strip():
        raise LinkError("a decision needs a named reviewer")
    if decision is LinkState.CANDIDATE:
        raise LinkError("a decision is accepted or rejected")
    if row.state == decision.value:
        raise LinkError(f"the link is already {decision.value}")
    entry = RecordLinkReviewRow(
        link_id=link, from_state=row.state, to_state=decision.value, reviewer=reviewer, note=note
    )
    session.add(entry)
    row.state = decision.value
    session.flush()
    return entry


def links_of(
    session: Session, record_id: str, states: Iterable[LinkState] = tuple(LinkState)
) -> list[RecordLinkRow]:
    """Links to or from a record, in the given states."""
    wanted = [s.value for s in states]
    return list(
        session.scalars(
            select(RecordLinkRow)
            .where(
                (RecordLinkRow.from_record == record_id) | (RecordLinkRow.to_record == record_id),
                RecordLinkRow.state.in_(wanted),
            )
            .order_by(RecordLinkRow.predicate, RecordLinkRow.link_id)
        )
    )
