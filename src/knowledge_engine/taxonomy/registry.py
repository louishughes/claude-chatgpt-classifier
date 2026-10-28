"""Taxonomy and project registry: tables and published snapshots (TAX-001, TAX-002).

The vocabulary that labels are allowed to use. OD-17 splits it into
separate **dimensions** (domain, purpose, topic, knowledge type, output);
projects get their own registry because they are names of real things, not
categories.

Rules this module enforces:

* **IDs never come from labels.** A term or project ID is random when the
  row is created and never changes, so renaming "Unreal" to "Unreal Engine"
  keeps every label that points at it.
* **Aliases are unique** within a dimension (or across projects) after
  normalising case, spacing and punctuation, so one spelling can't mean two
  things.
* **Only published snapshots are read by classification.** ``publish``
  copies the *approved* terms and aliases into an immutable version row
  with a SHA-256 of its contents. ``snapshot(version)`` reads that copy,
  never the live tables, so a run can't see a proposed term or a change
  made after it started (the vocabulary is frozen during a run).

Talking points:
    - "Labels point at IDs, and IDs never change. A rename is a new label on
      the same ID."
    - "A classifier reads a frozen, hashed snapshot. Proposed terms simply
      aren't in it."
"""

from __future__ import annotations

import hashlib
import json
import re
import secrets
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    select,
)
from sqlalchemy.orm import Mapped, Session, mapped_column

from knowledge_engine.infrastructure.db import Base

SNAPSHOT_FORMAT = "taxonomy-snapshot-v1"
_VERSION_RE = re.compile(r"^[a-z][a-z0-9.-]{0,39}$")


class Dimension(StrEnum):
    """The separate axes a segment is labelled on (OD-17)."""

    DOMAIN = "domain"
    PURPOSE = "purpose"
    TOPIC = "topic"
    KNOWLEDGE_TYPE = "knowledge_type"
    OUTPUT = "output"


class TermStatus(StrEnum):
    """Where a term stands. Only ``approved`` terms are ever published."""

    PROPOSED = "proposed"
    APPROVED = "approved"
    RETIRED = "retired"
    MERGED = "merged"  # see ``merged_into``


def _values(enum: type[StrEnum]) -> str:
    return ",".join(f"'{member.value}'" for member in enum)


def _utc_now() -> datetime:
    return datetime.now(UTC)


def new_id(prefix: str) -> str:
    """A fresh random ID, e.g. ``term_3f2a...``: never derived from a label."""
    return f"{prefix}_{secrets.token_hex(16)}"


def normalise_alias(text: str) -> str:
    """The comparison form of an alias: case-folded, accents and punctuation removed.

    ``"Unreal Engine 5"``, ``"unreal-engine 5"`` and ``"Unreal  Engine 5"``
    all become ``"unreal engine 5"``. TAX-003 builds matching on top of this.
    """
    decomposed = unicodedata.normalize("NFKD", text)
    plain = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    words = re.findall(r"[^\W_]+", plain.casefold())
    return " ".join(words)


class TaxonomyTermRow(Base):
    """One term in one dimension. Its ID survives renames and merges."""

    __tablename__ = "taxonomy_terms"
    __table_args__ = (
        CheckConstraint(f"dimension IN ({_values(Dimension)})", name="dimension_valid"),
        CheckConstraint(f"status IN ({_values(TermStatus)})", name="status_valid"),
        CheckConstraint(
            "(status = 'merged') = (merged_into IS NOT NULL)", name="merged_has_target"
        ),
    )

    term_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    dimension: Mapped[str] = mapped_column(String(20), index=True)
    label: Mapped[str] = mapped_column(String(200))
    definition: Mapped[str | None] = mapped_column(Text, default=None)
    # Two levels at most: a top-level term, or a child of one.
    parent_id: Mapped[str | None] = mapped_column(
        ForeignKey("taxonomy_terms.term_id"), default=None
    )
    status: Mapped[str] = mapped_column(String(12), default=TermStatus.PROPOSED.value)
    merged_into: Mapped[str | None] = mapped_column(
        ForeignKey("taxonomy_terms.term_id"), default=None
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)


class TaxonomyAliasRow(Base):
    """Another way of writing a term, unique within its dimension."""

    __tablename__ = "taxonomy_aliases"
    __table_args__ = (UniqueConstraint("dimension", "norm_form"),)

    alias_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    term_id: Mapped[str] = mapped_column(ForeignKey("taxonomy_terms.term_id"), index=True)
    dimension: Mapped[str] = mapped_column(String(20))
    alias: Mapped[str] = mapped_column(String(200))
    norm_form: Mapped[str] = mapped_column(String(200))


class TaxonomyVersionRow(Base):
    """One published, immutable snapshot of the approved vocabulary."""

    __tablename__ = "taxonomy_versions"

    version: Mapped[str] = mapped_column(String(40), primary_key=True)
    content_sha256: Mapped[str] = mapped_column(String(64))
    snapshot_json: Mapped[str] = mapped_column(Text)
    author: Mapped[str] = mapped_column(String(100))
    note: Mapped[str | None] = mapped_column(Text, default=None)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)


class TaxonomyProposalRow(Base):
    """A suggested change to the vocabulary, waiting for review (workflow: TAX-004)."""

    __tablename__ = "taxonomy_proposals"
    __table_args__ = (
        CheckConstraint(
            "operation IN ('add','rename','alias','merge','retire','reparent')",
            name="operation_valid",
        ),
        CheckConstraint("status IN ('open','approved','rejected')", name="status_valid"),
    )

    proposal_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    operation: Mapped[str] = mapped_column(String(12))
    payload_json: Mapped[str] = mapped_column(Text)
    # IDs and counts that support it (segments, quotes): never free text.
    evidence_json: Mapped[str] = mapped_column(Text, default="{}")
    proposer: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(10), default="open")
    reviewer: Mapped[str | None] = mapped_column(String(100), default=None)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)


class ProjectRow(Base):
    """A real project the chats talk about. Its ID survives renames and merges."""

    __tablename__ = "projects"
    __table_args__ = (
        CheckConstraint(f"status IN ({_values(TermStatus)})", name="status_valid"),
        CheckConstraint(
            "(status = 'merged') = (merged_into IS NOT NULL)", name="merged_has_target"
        ),
    )

    project_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text, default=None)
    status: Mapped[str] = mapped_column(String(12), default=TermStatus.PROPOSED.value)
    merged_into: Mapped[str | None] = mapped_column(ForeignKey("projects.project_id"), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)


class ProjectAliasRow(Base):
    """Another name for a project, unique across all projects."""

    __tablename__ = "project_aliases"
    __table_args__ = (UniqueConstraint("norm_form"),)

    alias_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.project_id"), index=True)
    alias: Mapped[str] = mapped_column(String(200))
    norm_form: Mapped[str] = mapped_column(String(200))


class UnknownTermError(KeyError):
    """A term ID that isn't approved in the snapshot being used."""


@dataclass(frozen=True)
class SnapshotTerm:
    """One approved term as published."""

    term_id: str
    dimension: str
    label: str
    definition: str | None
    parent_id: str | None
    aliases: tuple[str, ...]


@dataclass(frozen=True)
class SnapshotProject:
    """One approved project as published."""

    project_id: str
    name: str
    aliases: tuple[str, ...]


@dataclass(frozen=True)
class TaxonomySnapshot:
    """An immutable published vocabulary: approved terms and projects only.

    Attributes:
        version: e.g. ``tax-1``.
        content_sha256: Fingerprint of exactly what was published.
        terms: Approved terms, sorted by dimension then ID.
        projects: Approved projects, sorted by ID.
    """

    version: str
    content_sha256: str
    terms: tuple[SnapshotTerm, ...]
    projects: tuple[SnapshotProject, ...]

    def term(self, term_id: str) -> SnapshotTerm:
        """Return an approved term, or raise ``UnknownTermError``.

        A proposed, retired or merged term is not in a snapshot, so asking
        for one fails: classification can't use it by accident.
        """
        for term in self.terms:
            if term.term_id == term_id:
                return term
        raise UnknownTermError(term_id)

    def dimension(self, dimension: Dimension) -> tuple[SnapshotTerm, ...]:
        """Approved terms of one dimension."""
        return tuple(t for t in self.terms if t.dimension == dimension.value)

    def allowed_ids(self, dimension: Dimension) -> tuple[str, ...]:
        """The IDs a model may answer with for one dimension (the schema enum)."""
        return tuple(t.term_id for t in self.dimension(dimension))

    def project_ids(self) -> tuple[str, ...]:
        """The IDs a model may answer with for the project field."""
        return tuple(p.project_id for p in self.projects)

    def validate(self, dimension: Dimension, term_ids: Iterable[str]) -> None:
        """Raise ``UnknownTermError`` unless every ID is approved in ``dimension``."""
        allowed = set(self.allowed_ids(dimension))
        for term_id in term_ids:
            if term_id not in allowed:
                raise UnknownTermError(term_id)


class TaxonomyRegistry:
    """Reads and writes the vocabulary tables in one session."""

    def __init__(self, session: Session) -> None:
        """Wrap a session; the caller commits."""
        self.session = session

    def add_term(
        self,
        dimension: Dimension,
        label: str,
        *,
        definition: str | None = None,
        parent_id: str | None = None,
        status: TermStatus = TermStatus.PROPOSED,
        term_id: str | None = None,
    ) -> TaxonomyTermRow:
        """Create a term (proposed unless stated). Approval workflow: TAX-004.

        Raises:
            ValueError: If the parent is missing, in another dimension, or
                itself a child (two levels at most).
        """
        if parent_id is not None:
            parent = self.session.get(TaxonomyTermRow, parent_id)
            if parent is None or parent.dimension != dimension.value:
                raise ValueError("parent must be a term in the same dimension")
            if parent.parent_id is not None:
                raise ValueError("the taxonomy has two levels at most")
        row = TaxonomyTermRow(
            term_id=term_id or new_id("term"),
            dimension=dimension.value,
            label=label.strip(),
            definition=definition,
            parent_id=parent_id,
            status=status.value,
        )
        self.session.add(row)
        self.session.flush()  # the alias row refers to it
        self.add_alias(row, label)
        return row

    def add_alias(self, term: TaxonomyTermRow, alias: str) -> TaxonomyAliasRow:
        """Add a spelling. Fails at flush if the dimension already has it."""
        norm = normalise_alias(alias)
        if not norm:
            raise ValueError("an alias needs at least one letter or digit")
        row = TaxonomyAliasRow(
            term_id=term.term_id, dimension=term.dimension, alias=alias.strip(), norm_form=norm
        )
        self.session.add(row)
        self.session.flush()
        return row

    def add_project(
        self,
        name: str,
        *,
        aliases: Iterable[str] = (),
        status: TermStatus = TermStatus.PROPOSED,
        project_id: str | None = None,
    ) -> ProjectRow:
        """Create a project and its aliases (the name is an alias too)."""
        row = ProjectRow(project_id=project_id or new_id("proj"), name=name.strip(), status=status)
        self.session.add(row)
        self.session.flush()
        for alias in (name, *aliases):
            self.session.add(
                ProjectAliasRow(
                    project_id=row.project_id, alias=alias.strip(), norm_form=normalise_alias(alias)
                )
            )
        self.session.flush()
        return row

    def publish(self, version: str, *, author: str, note: str | None = None) -> TaxonomySnapshot:
        """Freeze the approved vocabulary as a new, immutable version.

        Args:
            version: A new version name, e.g. ``tax-2``.
            author: Who published it.
            note: Why, optionally.

        Returns:
            The snapshot, exactly as stored.

        Raises:
            ValueError: If the name is malformed or already used.
        """
        if not _VERSION_RE.fullmatch(version):
            raise ValueError("version must look like 'tax-1'")
        if self.session.get(TaxonomyVersionRow, version) is not None:
            raise ValueError("that version is already published; versions are immutable")
        content = self._approved_content()
        encoded = json.dumps(content, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
        self.session.add(
            TaxonomyVersionRow(
                version=version,
                content_sha256=digest,
                snapshot_json=encoded,
                author=author,
                note=note,
            )
        )
        self.session.flush()
        return self.snapshot(version)

    def snapshot(self, version: str) -> TaxonomySnapshot:
        """Return a published version, read from its frozen copy only.

        Raises:
            KeyError: If no such version was published.
        """
        row = self.session.get(TaxonomyVersionRow, version)
        if row is None:
            raise KeyError("no such taxonomy version")
        content = json.loads(row.snapshot_json)
        encoded = json.dumps(content, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        if hashlib.sha256(encoded.encode("utf-8")).hexdigest() != row.content_sha256:
            raise ValueError("taxonomy snapshot does not match its fingerprint")
        return TaxonomySnapshot(
            version=row.version,
            content_sha256=row.content_sha256,
            terms=tuple(SnapshotTerm(**t) for t in _tupled(content["terms"])),
            projects=tuple(SnapshotProject(**p) for p in _tupled(content["projects"])),
        )

    def versions(self) -> list[str]:
        """Published version names, oldest first."""
        return list(
            self.session.scalars(
                select(TaxonomyVersionRow.version).order_by(TaxonomyVersionRow.published_at)
            )
        )

    def _approved_content(self) -> dict[str, Any]:
        approved = TermStatus.APPROVED.value
        aliases: dict[str, list[str]] = {}
        for alias in self.session.scalars(select(TaxonomyAliasRow)):
            aliases.setdefault(alias.term_id, []).append(alias.alias)
        terms = [
            {
                "term_id": t.term_id,
                "dimension": t.dimension,
                "label": t.label,
                "definition": t.definition,
                "parent_id": t.parent_id,
                "aliases": sorted(aliases.get(t.term_id, [])),
            }
            for t in self.session.scalars(
                select(TaxonomyTermRow)
                .where(TaxonomyTermRow.status == approved)
                .order_by(TaxonomyTermRow.dimension, TaxonomyTermRow.term_id)
            )
        ]
        project_aliases: dict[str, list[str]] = {}
        for name in self.session.scalars(select(ProjectAliasRow)):
            project_aliases.setdefault(name.project_id, []).append(name.alias)
        projects = [
            {
                "project_id": p.project_id,
                "name": p.name,
                "aliases": sorted(project_aliases.get(p.project_id, [])),
            }
            for p in self.session.scalars(
                select(ProjectRow)
                .where(ProjectRow.status == approved)
                .order_by(ProjectRow.project_id)
            )
        ]
        return {"format": SNAPSHOT_FORMAT, "terms": terms, "projects": projects}


def _tupled(items: list[dict[str, Any]]) -> Iterable[dict[str, Any]]:
    for item in items:
        yield {k: tuple(v) if isinstance(v, list) else v for k, v in item.items()}
