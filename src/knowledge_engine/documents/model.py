"""What a knowledge document says, as data, before any Markdown (DOC-001).

Three kinds of document are built from the stored knowledge records:

* a **conversation** document: every record whose evidence is in that chat;
* a **project** document: every record that names that project;
* a **topic** document: every record tagged with that taxonomy term.

A record can be in several documents at once (its chat, its project, its
topic). Which documents a record belongs to is decided by ``subjects_of``,
the same selector the builder uses, so "where does this record show up?"
always has one answer.

``build_document`` turns one subject into a ``KnowledgeDocument``: plain
data with sections in a fixed order, each item carrying its record ID, its
REC-006 status (current, in conflict, pending, date unknown, replaced), the
events behind that status, and the message revisions it cites. Records a
reviewer rejected are left out: they aren't knowledge. Rendering this into
Markdown is DOC-003..005's job; keeping the content as data means the same
inputs always give the same document, and its ``content_hash`` shows
whether anything actually changed.

Talking points:
    - "A document is a list of record IDs with their standing, decided
      from the database, before a single line of Markdown is written."
    - "One selector decides which documents a record belongs to, so
      finding the documents to rebuild is a lookup, not a guess."
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass
from enum import StrEnum

from sqlalchemy import select
from sqlalchemy.orm import Session

from knowledge_engine.extraction.records import KnowledgeRecord, Trust
from knowledge_engine.extraction.store import KnowledgeRecordRow
from knowledge_engine.importer.records import MessageNodeRow, MessageRevisionRow
from knowledge_engine.reconciliation.projection import STATED, Projection, project
from knowledge_engine.reconciliation.relations import Placed, place
from knowledge_engine.reconciliation.timeline import OFFERS

BUILDER_VERSION = "doc-001-v1"


class DocumentKind(StrEnum):
    """What a document is about."""

    CONVERSATION = "conversation"
    PROJECT = "project"
    TOPIC = "topic"


def document_id(kind: DocumentKind, subject_id: str) -> str:
    """``kdoc_`` + hash of the kind and subject: one document per subject, forever."""
    digest = hashlib.sha256(f"{kind.value}\x00{subject_id}".encode())
    return "kdoc_" + digest.hexdigest()[:32]


@dataclass(frozen=True)
class DocItem:
    """One record as a document shows it.

    Attributes:
        record_id: The ``krec_`` ID.
        record_type: Its kind.
        status: REC-006 standing for decisions, requirements, preferences and
            rejections; ``accepted``/``rejected``/``open`` for proposals;
            the record's trust for everything else.
        assertion: What it says (imported text: escape when rendering).
        actor: Who it is attributed to.
        revisions: The message revisions it cites.
        because: Events and conflicts behind the status.
        superseded_by: Records that replaced it.
        conflicts_with: Records it is in open conflict with.
    """

    record_id: str
    record_type: str
    status: str
    assertion: str
    actor: str
    revisions: tuple[str, ...]
    because: tuple[str, ...] = ()
    superseded_by: tuple[str, ...] = ()
    conflicts_with: tuple[str, ...] = ()


@dataclass(frozen=True)
class DocSection:
    """A titled group of items (titles are the engine's own words)."""

    key: str
    title: str
    items: tuple[DocItem, ...]


@dataclass(frozen=True)
class KnowledgeDocument:
    """One document's content, as data.

    Attributes:
        document_id: ``kdoc_`` ID (from kind and subject).
        kind: Conversation, project or topic.
        subject_id: The ``conv_`` ID, project ID or term ID.
        sections: Non-empty sections, in the fixed order.
        record_ids: Every record shown, sorted.
        revision_ids: Every message revision cited, sorted.
        as_of: The source-time cut-off it was built for, if any.
        builder_version: This module's version.
    """

    document_id: str
    kind: DocumentKind
    subject_id: str
    sections: tuple[DocSection, ...]
    record_ids: tuple[str, ...]
    revision_ids: tuple[str, ...]
    as_of: float | None = None
    builder_version: str = BUILDER_VERSION

    @property
    def content_hash(self) -> str:
        """SHA-256 of the whole content: equal hashes mean nothing changed."""
        body = json.dumps(asdict(self), sort_keys=True, default=str)
        return hashlib.sha256(body.encode()).hexdigest()


# Sections in the order a reader needs them: what holds now first.
_SECTIONS = (
    ("current", "Current"),
    ("conflicted", "In conflict"),
    ("pending", "Waiting for a check"),
    ("unknown", "Date unknown"),
    ("superseded", "Replaced"),
    ("proposals", "Suggestions and their outcome"),
    ("other", "Other knowledge"),
)


def chats_of(session: Session, revision_ids: Iterable[str]) -> dict[str, str]:
    """Revision ID -> its ``conv_`` ID."""
    wanted = sorted(set(revision_ids))
    found: dict[str, str] = {}
    for start in range(0, len(wanted), 500):  # stay under SQLite's variable limit
        found |= {
            revision: conversation
            for revision, conversation in session.execute(
                select(MessageRevisionRow.revision_id, MessageNodeRow.conversation_id)
                .join(MessageNodeRow, MessageNodeRow.node_key == MessageRevisionRow.node_key)
                .where(MessageRevisionRow.revision_id.in_(wanted[start : start + 500]))
            )
        }
    return found


def subjects_of(
    record: KnowledgeRecord, revisions: Sequence[str], chats: dict[str, str]
) -> set[tuple[DocumentKind, str]]:
    """Every (kind, subject) whose document shows this record."""
    found = {(DocumentKind.CONVERSATION, chats[r]) for r in revisions if r in chats}
    found |= {(DocumentKind.PROJECT, p) for p in record.project_ids}
    found |= {(DocumentKind.TOPIC, t) for t in record.term_ids}
    return found


def _all_placed(session: Session) -> tuple[list[Placed], dict[str, str]]:
    rows = session.scalars(select(KnowledgeRecordRow).order_by(KnowledgeRecordRow.record_id))
    placed = place(session, [KnowledgeRecord.model_validate_json(r.record_json) for r in rows])
    return placed, chats_of(session, [rev for p in placed for rev in p.revisions])


def _item(item: Placed, status: str, **why: tuple[str, ...]) -> DocItem:
    record = item.record
    return DocItem(
        record.record_id,
        record.record_type.value,
        status,
        record.assertion,
        record.actor.value,
        tuple(item.revisions),
        **why,
    )


@dataclass(frozen=True)
class Snapshot:
    """Everything the builder reads, gathered once so many documents can share it."""

    placed: tuple[Placed, ...]
    chats: dict[str, str]
    state: Projection
    as_of: float | None


def snapshot(session: Session, *, as_of: float | None = None) -> Snapshot:
    """Read the records, their chats and the REC-006 projection once."""
    placed, chats = _all_placed(session)
    return Snapshot(tuple(placed), chats, project(session, as_of=as_of), as_of)


def build_document(
    session: Session,
    kind: DocumentKind,
    subject_id: str,
    *,
    as_of: float | None = None,
    seen: Snapshot | None = None,
) -> KnowledgeDocument:
    """Build one document's content from the stored records. Reads only.

    Args:
        session: A read session.
        kind: Conversation, project or topic.
        subject_id: The ``conv_`` ID, project ID or term ID.
        as_of: Source-time cut-off for statuses (REC-006), or None for now.
        seen: A ``snapshot`` to reuse (its ``as_of`` wins), when building many.
    """
    seen = seen or snapshot(session, as_of=as_of)
    members = {
        p.record.record_id: p
        for p in seen.placed
        if p.record.trust is not Trust.REJECTED
        and (kind, subject_id) in subjects_of(p.record, p.revisions, seen.chats)
    }
    standing = {e.record_id: e for e in seen.state.entries}
    outcomes = {p.record_id: p for p in seen.state.proposals}
    grouped: dict[str, list[DocItem]] = {key: [] for key, _ in _SECTIONS}
    for record_id in sorted(members):
        item = members[record_id]
        record = item.record
        if record.record_type in STATED:
            entry = standing.get(record_id)
            if entry is None:
                continue  # after the as_of date: not in this version of the document
            grouped[entry.status.value].append(
                _item(
                    item,
                    entry.status.value,
                    because=entry.because,
                    superseded_by=entry.superseded_by,
                    conflicts_with=entry.conflicts_with,
                )
            )
        elif record.record_type in OFFERS:
            outcome = outcomes.get(record_id)
            if outcome is not None:
                grouped["proposals"].append(_item(item, outcome.outcome, because=outcome.because))
        else:
            grouped["other"].append(_item(item, record.trust.value))
    sections = tuple(
        DocSection(key, title, tuple(grouped[key])) for key, title in _SECTIONS if grouped[key]
    )
    items = [i for s in sections for i in s.items]
    return KnowledgeDocument(
        document_id(kind, subject_id),
        kind,
        subject_id,
        sections,
        tuple(sorted(i.record_id for i in items)),
        tuple(sorted({r for i in items for r in i.revisions})),
        seen.as_of,
    )


def build_all(session: Session, *, as_of: float | None = None) -> list[KnowledgeDocument]:
    """Every document that has at least one record, sorted by kind and subject."""
    seen = snapshot(session, as_of=as_of)
    subjects: set[tuple[DocumentKind, str]] = set()
    for item in seen.placed:
        if item.record.trust is not Trust.REJECTED:
            subjects |= subjects_of(item.record, item.revisions, seen.chats)
    return [build_document(session, k, s, seen=seen) for k, s in sorted(subjects)]
