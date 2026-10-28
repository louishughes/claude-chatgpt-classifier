"""What changed between two taxonomy versions, and which outputs that touches (TAX-007).

When a new taxonomy version is published, some saved classifications may
no longer be right: a term was merged away, renamed, given a new alias or
retired. Re-running everything would be slow and, with a paid model,
expensive. So we work out exactly which IDs changed and invalidate only the
outputs that **cite** one of them.

* ``diff_snapshots(old, new)`` compares two published versions, term by
  term and project by project: added, removed (merged, retired), changed
  (label, aliases, definition, parent).
* ``record_diff`` stores that list of changed IDs, once per version pair.
* ``invalidate(diff, outputs)`` takes saved outputs with the IDs each one
  cites and marks only the affected ones, in an append-only table. A
  classification of project B is untouched when project A gets an alias.
* ``invalidated(stage_key)`` tells a stage whether a cached output may
  still be reused.

Nothing is deleted: an invalidated output stays as history, the stage just
won't reuse it.

Talking points:
    - "A new version doesn't mean redo everything: only outputs that cite a
      changed ID are marked stale."
    - "Stale is a flag in a separate table; the old answer stays for the
      record."
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import DateTime, Integer, String, Text, UniqueConstraint, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from knowledge_engine.infrastructure.db import Base
from knowledge_engine.taxonomy.registry import TaxonomySnapshot


def _utc_now() -> datetime:
    return datetime.now(UTC)


class TaxonomyChangeRow(Base):
    """The IDs that changed between two published versions."""

    __tablename__ = "taxonomy_changes"

    from_version: Mapped[str] = mapped_column(String(40), primary_key=True)
    to_version: Mapped[str] = mapped_column(String(40), primary_key=True)
    added_json: Mapped[str] = mapped_column(Text)
    removed_json: Mapped[str] = mapped_column(Text)
    changed_json: Mapped[str] = mapped_column(Text)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)


class StageInvalidationRow(Base):
    """A saved output that cites a changed ID and must not be reused."""

    __tablename__ = "stage_invalidations"
    __table_args__ = (UniqueConstraint("stage_key", "to_version"),)

    invalidation_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    stage_key: Mapped[str] = mapped_column(String(70), index=True)
    from_version: Mapped[str] = mapped_column(String(40))
    to_version: Mapped[str] = mapped_column(String(40))
    cited_ids_json: Mapped[str] = mapped_column(Text)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)


@dataclass(frozen=True)
class TaxonomyDiff:
    """The IDs that differ between two versions.

    Attributes:
        from_version: The older version.
        to_version: The newer version.
        added: IDs only in the newer version.
        removed: IDs only in the older one (merged, retired).
        changed: IDs in both whose label, aliases, definition or parent
            differ, mapped to the names of the fields that changed.
    """

    from_version: str
    to_version: str
    added: frozenset[str]
    removed: frozenset[str]
    changed: Mapping[str, tuple[str, ...]]

    @property
    def touched(self) -> frozenset[str]:
        """Every ID an existing output could be affected by (removed or changed)."""
        return self.removed | frozenset(self.changed)

    @property
    def empty(self) -> bool:
        """True when the two versions have the same content."""
        return not (self.added or self.removed or self.changed)


def _entries(snapshot: TaxonomySnapshot) -> dict[str, dict[str, Any]]:
    found: dict[str, dict[str, Any]] = {}
    for term in snapshot.terms:
        found[term.term_id] = {
            "label": term.label,
            "aliases": sorted(term.aliases),
            "definition": term.definition,
            "parent_id": term.parent_id,
        }
    for project in snapshot.projects:
        found[project.project_id] = {"label": project.name, "aliases": sorted(project.aliases)}
    return found


def diff_snapshots(old: TaxonomySnapshot, new: TaxonomySnapshot) -> TaxonomyDiff:
    """Compare two published versions ID by ID."""
    before, after = _entries(old), _entries(new)
    changed = {}
    for item_id in before.keys() & after.keys():
        fields = tuple(
            sorted(k for k in after[item_id] if before[item_id].get(k) != after[item_id][k])
        )
        if fields:
            changed[item_id] = fields
    return TaxonomyDiff(
        old.version,
        new.version,
        frozenset(after.keys() - before.keys()),
        frozenset(before.keys() - after.keys()),
        dict(sorted(changed.items())),
    )


def record_diff(session: Session, diff: TaxonomyDiff) -> TaxonomyChangeRow:
    """Store a diff once; recording the same version pair again returns the stored row."""
    row = session.get(TaxonomyChangeRow, (diff.from_version, diff.to_version))
    if row is not None:
        return row
    row = TaxonomyChangeRow(
        from_version=diff.from_version,
        to_version=diff.to_version,
        added_json=json.dumps(sorted(diff.added)),
        removed_json=json.dumps(sorted(diff.removed)),
        changed_json=json.dumps({k: list(v) for k, v in diff.changed.items()}),
    )
    session.add(row)
    session.flush()
    return row


def invalidate(
    session: Session, diff: TaxonomyDiff, outputs: Mapping[str, Iterable[str]]
) -> list[str]:
    """Mark the outputs that cite a removed or changed ID.

    Args:
        session: The caller commits.
        diff: From ``diff_snapshots``.
        outputs: Stage key -> the term and project IDs that output cites.

    Returns:
        The stage keys marked, sorted. Outputs citing only unchanged IDs
        are not touched.
    """
    marked = []
    for stage_key, cited in sorted(outputs.items()):
        hits = sorted(set(cited) & diff.touched)
        if not hits:
            continue
        exists = session.scalar(
            select(StageInvalidationRow.invalidation_id).where(
                StageInvalidationRow.stage_key == stage_key,
                StageInvalidationRow.to_version == diff.to_version,
            )
        )
        if exists is None:
            session.add(
                StageInvalidationRow(
                    stage_key=stage_key,
                    from_version=diff.from_version,
                    to_version=diff.to_version,
                    cited_ids_json=json.dumps(hits),
                )
            )
        marked.append(stage_key)
    session.flush()
    return marked


def invalidated(session: Session, stage_key: str) -> bool:
    """True if a taxonomy change made this saved output stale."""
    return (
        session.scalar(
            select(StageInvalidationRow.invalidation_id).where(
                StageInvalidationRow.stage_key == stage_key
            )
        )
        is not None
    )
