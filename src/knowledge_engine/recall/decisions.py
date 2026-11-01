"""How a project's decisions moved, and where they still disagree (RCL-004).

``recall decisions history NAME`` groups a project's decisions by subject
and prints each subject's steps oldest first: suggested, accepted,
rejected, clarified, revised, replaced, contradicted. ``recall decisions
conflicts NAME`` lists the pairs that still disagree. Both only *read*:

* the steps are the REC-004 **timeline** (``decision_events``), the
  append-only history of what happened between records;
* each record's standing is the REC-006 **projection**, through the same
  document builder ``recall projects show`` uses (DOC-001);
* the conflicts are the REC-003 **conflict register**.

So this module never decides that one thing replaced another. A step says
"replaced" only because a ``supersedes`` event was recorded, and REC-005
records one only for an explicit switch ("change of plan, X instead of
Y"). A later date on its own never does: two decisions about different
things simply stay side by side. A contradiction stays "unresolved" until
a person settles it; it is never shown as a replacement.

**What "a subject" is.** Records joined by any event (a suggestion and the
decision that accepted it, a decision and what replaced it) form one
subject. A decision with no events is a subject of its own.

**Status words** (approved in the RCL plan):

==============  ==================================================
``proposed``    an assistant suggestion that was answered
``explored``    an assistant suggestion nobody answered
``confirmed``   your decision or requirement, holding now
``preferred``   your preference, holding now
``rejected``    something you turned down, holding now
``superseded``  replaced by a later decision (an explicit switch)
``conflicted``  in an unresolved conflict
``pending``     waiting for a check (REC-006 ``pending``)
``date unknown``  no source date, so its order can't be told
==============  ==================================================

**Withdrawn steps stay.** An event revoked by a reviewer is still shown,
marked revoked, with who withdrew it and why: the history shows both what
was believed and when it was corrected.

Talking points:
    - "recall never decides a replacement itself: it shows the ones the
      engine recorded for an explicit switch, so 'later' never means 'replaced'."
    - "Each decision's history reads oldest first: who suggested it, who
      accepted it, what replaced it, with the quote for every step."
    - "A withdrawn step is still on screen, marked, so a correction is
      visible rather than silently erasing what was believed."
"""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from knowledge_engine.documents.model import (
    DocItem,
    DocumentKind,
    KnowledgeDocument,
    build_document,
    chats_of,
)
from knowledge_engine.extraction.records import KnowledgeRecord
from knowledge_engine.extraction.store import KnowledgeRecordRow
from knowledge_engine.recall.projects import MAX_QUOTES, Quote, check_quote
from knowledge_engine.reconciliation.conflicts import ConflictState, RecordConflictRow
from knowledge_engine.reconciliation.timeline import DecisionEventRow, Transition, timeline
from knowledge_engine.taxonomy.registry import ProjectRow

DECISIONS_VERSION = "rcl-004-v1"

# How each REC-004 predicate reads as a step. ``revokes`` is not a step of
# its own: it marks the step it withdraws.
STEP_LABELS = {
    Transition.PROPOSES.value: "suggested",
    Transition.ACCEPTS.value: "accepted",
    Transition.REJECTS.value: "rejected",
    Transition.CLARIFIES.value: "clarified",
    Transition.REVISES.value: "revised",
    Transition.SUPERSEDES.value: "replaced",
    Transition.CONTRADICTS.value: "contradicted",
    Transition.RELATED_TO.value: "related",
}
# The document sections whose records take part in a decision's history.
_SECTIONS = ("current", "conflicted", "pending", "unknown", "superseded", "proposals")


def status_word(record_type: str, status: str) -> str:
    """The approved status word for a record's REC-006 status or proposal outcome.

    Args:
        record_type: decision, requirement, preference, rejection, proposal...
        status: Its REC-006 status, or a proposal's outcome (accepted,
            rejected, open).

    Returns:
        One of the words in the module docstring's table.
    """
    if record_type in ("proposal", "recommendation"):
        return "explored" if status == "open" else "proposed"
    if status == "current":
        return {"preference": "preferred", "rejection": "rejected"}.get(record_type, "confirmed")
    return {"unknown": "date unknown"}.get(status, status)


@dataclass(frozen=True)
class DecisionRecord:
    """One record in a subject, with its standing and quotes."""

    record_id: str
    record_type: str
    status: str
    assertion: str
    first_time: float | None
    quotes: tuple[Quote, ...]


@dataclass(frozen=True)
class Step:
    """One event in a subject's history.

    Attributes:
        event_id: The ``kev_`` event.
        label: suggested, accepted, rejected, clarified, revised, replaced,
            contradicted or related.
        happened_at: Source message time, if known.
        from_record: The record that took the step (the decision that
            accepted, the one that replaced...).
        to_record: The record it acts on, if any.
        actor: The detector version or reviewer that recorded it.
        revoked_by: Who withdrew it, if it was revoked.
        revoked_note: Their reason.
    """

    event_id: str
    label: str
    happened_at: float | None
    from_record: str | None
    to_record: str | None
    actor: str
    revoked_by: str | None = None
    revoked_note: str | None = None


@dataclass(frozen=True)
class Subject:
    """Records joined by events, and those events oldest first."""

    records: tuple[DecisionRecord, ...]
    steps: tuple[Step, ...]


@dataclass(frozen=True)
class ConflictView:
    """One stored conflict between two of the project's records."""

    conflict_id: str
    state: str
    kinds: tuple[str, ...]
    records: tuple[DecisionRecord, DecisionRecord]


class _Records:
    """The project's document, its records and their quotes, loaded once."""

    def __init__(self, session: Session, project: ProjectRow) -> None:
        self.session = session
        self.document: KnowledgeDocument = build_document(
            session, DocumentKind.PROJECT, project.project_id
        )
        self.items: dict[str, DocItem] = {
            i.record_id: i for s in self.document.sections if s.key in _SECTIONS for i in s.items
        }
        self.stored = {
            row.record_id: KnowledgeRecord.model_validate_json(row.record_json)
            for row in session.scalars(
                select(KnowledgeRecordRow).where(KnowledgeRecordRow.record_id.in_(self.items))
            )
        }
        self.chat_of = chats_of(session, self.document.revision_ids)
        self._views: dict[str, DecisionRecord] = {}

    def view(self, record_id: str) -> DecisionRecord:
        if record_id not in self._views:
            item = self.items[record_id]
            refs = self.stored[record_id].evidence if record_id in self.stored else ()
            quotes = tuple(check_quote(self.session, r, self.chat_of) for r in refs[:MAX_QUOTES])
            times = [q.created for q in quotes if q.created is not None]
            self._views[record_id] = DecisionRecord(
                record_id,
                item.record_type,
                status_word(item.record_type, item.status),
                item.assertion,
                min(times) if times else None,
                quotes,
            )
        return self._views[record_id]


def decision_history(session: Session, project: ProjectRow) -> list[Subject]:
    """A project's decisions grouped by subject, each subject's steps oldest first.

    Args:
        session: A read session.
        project: An approved project (``recall.projects.find_project``).

    Returns:
        The subjects, the one whose history starts earliest first.
    """
    loaded = _Records(session, project)
    ids = set(loaded.items)
    entries = [e for e in timeline(session, ids) if e.predicate != Transition.REVOKES.value]
    revocations = _revocations(session, [e.event_id for e in entries if e.revoked])

    # Union-find: records joined by an event inside the project are one subject.
    parent = {record_id: record_id for record_id in ids}

    def root(record_id: str) -> str:
        while parent[record_id] != record_id:
            parent[record_id] = parent[parent[record_id]]
            record_id = parent[record_id]
        return record_id

    for entry in entries:
        ends = [r for r in (entry.from_record, entry.to_record) if r in ids]
        if len(ends) == 2:
            a, b = root(ends[0]), root(ends[1])
            if a != b:
                parent[max(a, b)] = min(a, b)

    members: dict[str, list[str]] = defaultdict(list)
    for record_id in sorted(ids):
        members[root(record_id)].append(record_id)
    steps_of: dict[str, list[Step]] = defaultdict(list)
    for entry in entries:  # already oldest first (REC-004 ``timeline``)
        anchor = next((r for r in (entry.from_record, entry.to_record) if r in ids), None)
        if anchor is None:
            continue
        who, why = revocations.get(entry.event_id, (None, None))
        steps_of[root(anchor)].append(
            Step(
                entry.event_id,
                STEP_LABELS.get(entry.predicate, entry.predicate),
                entry.happened_at,
                entry.from_record,
                entry.to_record,
                entry.actor,
                who,
                why,
            )
        )
    subjects = []
    for key, record_ids in members.items():
        records = sorted(
            (loaded.view(r) for r in record_ids),
            key=lambda r: (r.first_time is None, r.first_time or 0.0, r.record_id),
        )
        subjects.append(Subject(tuple(records), tuple(steps_of[key])))
    subjects.sort(key=_subject_order)
    return subjects


def _subject_order(subject: Subject) -> tuple[bool, float, str]:
    times = [s.happened_at for s in subject.steps if s.happened_at is not None]
    times += [r.first_time for r in subject.records if r.first_time is not None]
    return (not times, min(times) if times else 0.0, subject.records[0].record_id)


def _revocations(session: Session, event_ids: Iterable[str]) -> dict[str, tuple[str, str | None]]:
    """Revoked event ID -> (who revoked it, why)."""
    wanted = list(event_ids)
    if not wanted:
        return {}
    return {
        row.revokes_event: (row.actor, row.note)
        for row in session.scalars(
            select(DecisionEventRow).where(DecisionEventRow.revokes_event.in_(wanted))
        )
        if row.revokes_event is not None
    }


def decision_conflicts(
    session: Session, project: ProjectRow, *, include_settled: bool = False
) -> list[ConflictView]:
    """Stored conflicts between two of the project's records.

    Args:
        session: A read session.
        project: An approved project.
        include_settled: Also show conflicts a person dismissed or resolved.

    Returns:
        The conflicts, oldest first by the earlier record's date.
    """
    loaded = _Records(session, project)
    states = [ConflictState.UNRESOLVED.value]
    if include_settled:
        states += [ConflictState.DISMISSED.value, ConflictState.RESOLVED.value]
    rows = session.scalars(
        select(RecordConflictRow)
        .where(RecordConflictRow.state.in_(states))
        .where(
            or_(
                RecordConflictRow.record_a.in_(loaded.items),
                RecordConflictRow.record_b.in_(loaded.items),
            )
        )
        .order_by(RecordConflictRow.conflict_id)
    ).all()
    found = []
    for row in rows:
        # Both sides must be in this project: a conflict with a record filed
        # elsewhere shows on that project's screen instead.
        if row.record_a not in loaded.items or row.record_b not in loaded.items:
            continue
        kinds = json.loads(row.kinds_json)
        found.append(
            ConflictView(
                row.conflict_id,
                row.state,
                tuple(str(k) for k in kinds) if isinstance(kinds, list) else (),
                (loaded.view(row.record_a), loaded.view(row.record_b)),
            )
        )
    found.sort(
        key=lambda c: (
            min((r.first_time or float("inf")) for r in c.records),
            c.conflict_id,
        )
    )
    return found
