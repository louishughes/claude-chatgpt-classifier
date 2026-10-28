"""Which documents to rebuild when a record changes (DOC-001).

Every time a document is built and its content differs from the last
build, a **build** row is added (append-only), together with the exact
records and message revisions that build used (its **dependencies**). An
unchanged rebuild adds nothing, so building twice is free.

``affected_documents`` answers "this record changed: which documents must
be rebuilt?" with two lookups, and gives the reason for each:

* ``depends``: the document's latest build used the record. This catches a
  record that was edited, rejected or removed from the document;
* ``selects``: the selector (``subjects_of``) now puts the record in the
  document. This catches a brand-new record, or one that gained a project
  or topic, which no earlier build could have listed.

Nothing else is returned: a change to a record never triggers a rebuild of
a document that neither used it nor would show it. Message revisions are
tracked the same way (``depends`` only), for OPS-004's deletion closure.

Talking points:
    - "Each build remembers exactly which records it used, so a change maps
      to the exact documents that need rebuilding, and nothing more."
    - "A brand-new record is caught too, because the same rule that builds
      a document says which documents it belongs in."
"""

from __future__ import annotations

import hashlib
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, func, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from knowledge_engine.documents.model import (
    DocumentKind,
    KnowledgeDocument,
    chats_of,
    document_id,
    subjects_of,
)
from knowledge_engine.extraction.records import KnowledgeRecord
from knowledge_engine.extraction.store import KnowledgeRecordRow
from knowledge_engine.infrastructure.db import Base
from knowledge_engine.reconciliation.relations import place


def _utc_now() -> datetime:
    return datetime.now(UTC)


class DocumentBuildRow(Base):
    """One build of a document whose content changed. Append-only."""

    __tablename__ = "document_builds"
    __table_args__ = (
        CheckConstraint("kind IN ('conversation','project','topic')", name="kind_valid"),
    )

    build_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    document_id: Mapped[str] = mapped_column(String(40), index=True)
    # 1 for a document's first build, then 2, 3...: the latest is the highest.
    sequence: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(12))
    subject_id: Mapped[str] = mapped_column(String(200))
    content_hash: Mapped[str] = mapped_column(String(64))
    builder_version: Mapped[str] = mapped_column(String(40))
    record_count: Mapped[int] = mapped_column(Integer)
    built_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)


class DocumentDependencyRow(Base):
    """A record or message revision one build used. Append-only."""

    __tablename__ = "document_dependencies"
    __table_args__ = (CheckConstraint("dep_kind IN ('record','revision')", name="dep_kind_valid"),)

    build_id: Mapped[str] = mapped_column(ForeignKey("document_builds.build_id"), primary_key=True)
    dep_kind: Mapped[str] = mapped_column(String(10), primary_key=True)
    dep_id: Mapped[str] = mapped_column(String(40), primary_key=True, index=True)


# Created by migration 0026. Kept here so tests that build the schema
# without Alembic can install the same guard.
APPEND_ONLY_TRIGGERS = tuple(
    f"CREATE TRIGGER IF NOT EXISTS {table}_no_{action} BEFORE {action.upper()} ON {table} "
    f"BEGIN SELECT RAISE(ABORT, '{table} is append-only'); END"
    for table in ("document_builds", "document_dependencies")
    for action in ("update", "delete")
)


@dataclass(frozen=True)
class Registered:
    """What ``register`` did: the build ID, and whether it was new."""

    build_id: str
    changed: bool


def latest_builds(session: Session) -> dict[str, DocumentBuildRow]:
    """Document ID -> its latest build."""
    newest = (
        select(DocumentBuildRow.document_id, func.max(DocumentBuildRow.sequence).label("top"))
        .group_by(DocumentBuildRow.document_id)
        .subquery()
    )
    rows = session.scalars(
        select(DocumentBuildRow).join(
            newest,
            (newest.c.document_id == DocumentBuildRow.document_id)
            & (newest.c.top == DocumentBuildRow.sequence),
        )
    )
    return {row.document_id: row for row in rows}


def register(session: Session, document: KnowledgeDocument) -> Registered:
    """Record a build of ``document`` and its dependencies, unless nothing changed.

    The caller commits.
    """
    last = latest_builds(session).get(document.document_id)
    content = document.content_hash
    if last is not None and last.content_hash == content:
        return Registered(last.build_id, False)
    sequence = 1 if last is None else last.sequence + 1
    build_id = (
        "kdb_"
        + hashlib.sha256(f"{document.document_id}|{sequence}|{content}".encode()).hexdigest()[:32]
    )
    session.add(
        DocumentBuildRow(
            build_id=build_id,
            document_id=document.document_id,
            sequence=sequence,
            kind=document.kind.value,
            subject_id=document.subject_id,
            content_hash=content,
            builder_version=document.builder_version,
            record_count=len(document.record_ids),
        )
    )
    session.flush()  # the build row first: dependencies point at it
    session.add_all(
        [
            DocumentDependencyRow(build_id=build_id, dep_kind="record", dep_id=r)
            for r in document.record_ids
        ]
        + [
            DocumentDependencyRow(build_id=build_id, dep_kind="revision", dep_id=r)
            for r in document.revision_ids
        ]
    )
    session.flush()
    return Registered(build_id, True)


@dataclass(frozen=True)
class Affected:
    """A document to rebuild, and why.

    Attributes:
        document_id: The ``kdoc_`` ID.
        kind: Conversation, project or topic.
        subject_id: What it is about.
        reasons: ``depends:<id>`` (its latest build used it) and/or
            ``selects:<id>`` (it would show it now), sorted.
    """

    document_id: str
    kind: DocumentKind
    subject_id: str
    reasons: tuple[str, ...]


def affected_documents(session: Session, changed: Iterable[str]) -> list[Affected]:
    """The exact documents to rebuild after these records or revisions changed.

    Args:
        session: A read session.
        changed: ``krec_`` record IDs and/or ``rev_`` revision IDs.

    Returns:
        One entry per document, sorted by document ID.
    """
    wanted = sorted(set(changed))
    reasons: dict[str, set[str]] = defaultdict(set)
    subjects: dict[str, tuple[DocumentKind, str]] = {}
    latest = latest_builds(session)
    current = {b.build_id: b for b in latest.values()}
    if wanted:
        for build_id, dep_id in session.execute(
            select(DocumentDependencyRow.build_id, DocumentDependencyRow.dep_id).where(
                DocumentDependencyRow.dep_id.in_(wanted)
            )
        ):
            build = current.get(build_id)
            if build is None:
                continue  # an older build: what it used no longer matters
            reasons[build.document_id].add(f"depends:{dep_id}")
            subjects[build.document_id] = (DocumentKind(build.kind), build.subject_id)
    records = [
        KnowledgeRecord.model_validate_json(row.record_json)
        for row in session.scalars(
            select(KnowledgeRecordRow).where(KnowledgeRecordRow.record_id.in_(wanted))
        )
    ]
    placed = place(session, records)
    chats = chats_of(session, [r for p in placed for r in p.revisions])
    for item in placed:
        for kind, subject in subjects_of(item.record, item.revisions, chats):
            doc = document_id(kind, subject)
            reasons[doc].add(f"selects:{item.record.record_id}")
            subjects[doc] = (kind, subject)
    return [Affected(doc, *subjects[doc], tuple(sorted(reasons[doc]))) for doc in sorted(reasons)]
