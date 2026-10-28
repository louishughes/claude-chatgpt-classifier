"""Proposing and reviewing vocabulary changes (TAX-004).

Nobody edits the approved vocabulary directly. A change starts as a
**proposal** (a row in ``taxonomy_proposals``) and only touches the term or
project tables when a reviewer approves it. Until then a proposed term
simply does not exist as a term, so it can't be published, and a
classifier can't use it.

Six operations:

* ``add``: a new term (in a dimension) or a new project, with aliases.
* ``rename``: a new label; the old one stays as an alias, so text that used
  the old name still matches.
* ``alias``: one more spelling.
* ``merge``: two terms (or projects) are the same thing. The source keeps
  its ID but becomes ``merged`` and points at the target; its aliases move
  to the target. Labels that already point at the source can be followed.
* ``retire``: no longer used for new labels; nothing is deleted.
* ``reparent``: move a term under another (two levels at most) or to the top.

Rules: the reviewer must not be the proposer (ADR-0009 §5); only an open
proposal can be decided, once; the proposal row keeps who decided, when,
why and what it created. That row *is* the audit trail. A decision changes
the live tables only; the next ``publish`` makes it visible to classifiers.

Talking points:
    - "A proposed term isn't a term yet. It becomes one only when someone
      other than the proposer approves it, and then only in the next
      published version."
    - "Nothing is deleted: merged and retired terms keep their IDs, so old
      labels still resolve."
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from knowledge_engine.taxonomy.registry import (
    Dimension,
    ProjectAliasRow,
    ProjectRow,
    TaxonomyAliasRow,
    TaxonomyProposalRow,
    TaxonomyRegistry,
    TaxonomyTermRow,
    TermStatus,
    new_id,
    normalise_alias,
)

OPEN = "open"
APPROVED = "approved"
REJECTED = "rejected"


class Operation(StrEnum):
    """What a proposal asks for."""

    ADD = "add"
    RENAME = "rename"
    ALIAS = "alias"
    MERGE = "merge"
    RETIRE = "retire"
    REPARENT = "reparent"


class ReviewError(ValueError):
    """A proposal that can't be made or decided as asked."""


# The fields each operation's payload must carry.
_REQUIRED: dict[Operation, tuple[str, ...]] = {
    Operation.ADD: ("label",),
    Operation.RENAME: ("target_id", "label"),
    Operation.ALIAS: ("target_id", "alias"),
    Operation.MERGE: ("source_id", "target_id"),
    Operation.RETIRE: ("target_id",),
    Operation.REPARENT: ("target_id",),
}


def propose(
    session: Session,
    operation: Operation,
    payload: Mapping[str, Any],
    *,
    proposer: str,
    evidence: Mapping[str, Any] | None = None,
) -> TaxonomyProposalRow:
    """Record a proposed change. Nothing in the vocabulary changes yet.

    Args:
        session: The caller commits.
        operation: What to do.
        payload: The operation's fields. ``add`` takes ``label`` plus either
            ``dimension`` (a term; optional ``parent_id``, ``definition``)
            or ``kind: "project"``; both take optional ``aliases``.
        proposer: Who (or which run) proposed it.
        evidence: Supporting IDs and counts, e.g. segment IDs.

    Returns:
        The open proposal.

    Raises:
        ReviewError: If a required field is missing or the dimension is unknown.
    """
    missing = [name for name in _REQUIRED[operation] if not payload.get(name)]
    if missing:
        raise ReviewError(f"{operation.value} needs: {', '.join(missing)}")
    if operation is Operation.ADD and payload.get("kind") != "project":
        try:
            Dimension(payload.get("dimension", ""))
        except ValueError:
            raise ReviewError("add needs a dimension, or kind 'project'") from None
    row = TaxonomyProposalRow(
        proposal_id=new_id("prop"),
        operation=operation.value,
        payload_json=json.dumps(dict(payload), sort_keys=True),
        evidence_json=json.dumps(dict(evidence or {}), sort_keys=True),
        proposer=proposer,
        status=OPEN,
    )
    session.add(row)
    session.flush()
    return row


def approve(
    session: Session,
    proposal_id: str,
    *,
    reviewer: str,
    note: str | None = None,
    label: str | None = None,
) -> TaxonomyProposalRow:
    """Apply an open proposal to the live vocabulary and record the decision.

    Args:
        session: The caller commits (or rolls back if this raises).
        proposal_id: The ``prop_`` ID.
        reviewer: Who approved; must not be the proposer.
        note: Why. Required for high-impact changes: renaming or merging a
            project (TAX-005), because every label on it moves too.
        label: For an ``add`` only: the label the reviewer chose instead of
            the proposed one, e.g. to tell apart two projects that share a
            name. Recorded in the decision note.

    Returns:
        The decided proposal; ``result_id`` holds the ID an ``add`` created.

    Raises:
        ReviewError: If it isn't open, the reviewer proposed it, or the
            change would break a rule (unknown target, alias collision,
            a third level, merging across dimensions...).
    """
    row = _open(session, proposal_id, reviewer)
    payload = json.loads(row.payload_json)
    operation = Operation(row.operation)
    if _high_impact(session, operation, payload) and not (note or "").strip():
        raise ReviewError("renaming or merging a project is high-impact: give a note")
    if label is not None:
        if operation is not Operation.ADD or not label.strip():
            raise ReviewError("a replacement label applies to a new term or project only")
        note = f"[label set by reviewer: {label.strip()}] {note or ''}".strip()
        payload["label"] = label.strip()
    result = _APPLY[operation](TaxonomyRegistry(session), payload)
    _decide(row, APPROVED, reviewer, note)
    row.result_id = result
    session.flush()
    return row


def reject(session: Session, proposal_id: str, *, reviewer: str, note: str) -> TaxonomyProposalRow:
    """Close an open proposal without changing anything. A reason is required."""
    if not note.strip():
        raise ReviewError("say why it was rejected")
    row = _open(session, proposal_id, reviewer)
    _decide(row, REJECTED, reviewer, note)
    session.flush()
    return row


def proposals(session: Session, status: str | None = OPEN) -> list[TaxonomyProposalRow]:
    """Proposals in one status (all if None), oldest first."""
    query = select(TaxonomyProposalRow).order_by(
        TaxonomyProposalRow.created_at, TaxonomyProposalRow.proposal_id
    )
    if status is not None:
        query = query.where(TaxonomyProposalRow.status == status)
    return list(session.scalars(query))


def _high_impact(session: Session, operation: Operation, payload: Mapping[str, Any]) -> bool:
    if operation not in (Operation.RENAME, Operation.MERGE):
        return False
    ids = (payload.get("target_id"), payload.get("source_id"))
    return any(i is not None and session.get(ProjectRow, i) is not None for i in ids)


def _open(session: Session, proposal_id: str, reviewer: str) -> TaxonomyProposalRow:
    row = session.get(TaxonomyProposalRow, proposal_id)
    if row is None:
        raise ReviewError("no such proposal")
    if row.status != OPEN:
        raise ReviewError(f"already {row.status}; a decision is final")
    if reviewer.strip().casefold() == row.proposer.strip().casefold():
        raise ReviewError("the proposer can't review their own proposal")
    return row


def _decide(row: TaxonomyProposalRow, status: str, reviewer: str, note: str | None) -> None:
    row.status = status
    row.reviewer = reviewer
    row.decision_note = note
    row.decided_at = datetime.now(UTC)


def _apply_add(registry: TaxonomyRegistry, payload: dict[str, Any]) -> str:
    aliases = _distinct(payload["label"], payload.get("aliases", []))
    if payload.get("kind") == "project":
        for alias in (payload["label"], *aliases):
            _free_project_alias(registry.session, alias)
        project = registry.add_project(
            payload["label"], aliases=aliases, status=TermStatus.APPROVED
        )
        return project.project_id
    dimension = Dimension(payload["dimension"])
    parent_id = payload.get("parent_id")
    if parent_id is not None:
        _approved_term(registry.session, parent_id)
    for alias in (payload["label"], *aliases):
        _free_term_alias(registry.session, dimension.value, alias)
    term = registry.add_term(
        dimension,
        payload["label"],
        definition=payload.get("definition"),
        parent_id=parent_id,
        status=TermStatus.APPROVED,
    )
    for alias in aliases:
        registry.add_alias(term, alias)
    return term.term_id


def _distinct(label: str, aliases: Iterable[str]) -> list[str]:
    # Drop aliases that normalise to the label or to each other: they'd
    # collide with themselves on the unique alias index.
    seen = {normalise_alias(label)}
    kept = []
    for alias in aliases:
        norm = normalise_alias(alias)
        if norm not in seen:
            seen.add(norm)
            kept.append(alias)
    return kept


def _apply_rename(registry: TaxonomyRegistry, payload: dict[str, Any]) -> str:
    label = payload["label"].strip()
    target = _target(registry.session, payload["target_id"])
    if isinstance(target, TaxonomyTermRow):
        if not _term_alias_owned(registry.session, target, label):
            _free_term_alias(registry.session, target.dimension, label)
            registry.add_alias(target, label)
        target.label = label  # the old label is already an alias, so it still matches
        return target.term_id
    if not _project_alias_owned(registry.session, target, label):
        _free_project_alias(registry.session, label)
        _add_project_alias(registry.session, target, label)
    target.name = label
    return target.project_id


def _apply_alias(registry: TaxonomyRegistry, payload: dict[str, Any]) -> str:
    target = _target(registry.session, payload["target_id"])
    if isinstance(target, TaxonomyTermRow):
        _free_term_alias(registry.session, target.dimension, payload["alias"])
        registry.add_alias(target, payload["alias"])
        return target.term_id
    _free_project_alias(registry.session, payload["alias"])
    _add_project_alias(registry.session, target, payload["alias"])
    return target.project_id


def _apply_merge(registry: TaxonomyRegistry, payload: dict[str, Any]) -> str:
    session = registry.session
    source = _target(session, payload["source_id"])
    target = _target(session, payload["target_id"])
    if source is target:
        raise ReviewError("can't merge something into itself")
    if isinstance(source, TaxonomyTermRow) and isinstance(target, TaxonomyTermRow):
        if source.dimension != target.dimension:
            raise ReviewError("terms can only merge within one dimension")
        if _children(session, source.term_id):
            raise ReviewError("reparent or merge the source's children first")
        session.execute(
            update(TaxonomyAliasRow)
            .where(TaxonomyAliasRow.term_id == source.term_id)
            .values(term_id=target.term_id)
        )
        source.status = TermStatus.MERGED.value
        source.merged_into = target.term_id
        return target.term_id
    if isinstance(source, ProjectRow) and isinstance(target, ProjectRow):
        session.execute(
            update(ProjectAliasRow)
            .where(ProjectAliasRow.project_id == source.project_id)
            .values(project_id=target.project_id)
        )
        source.status = TermStatus.MERGED.value
        source.merged_into = target.project_id
        return target.project_id
    raise ReviewError("a term can't merge with a project")


def _apply_retire(registry: TaxonomyRegistry, payload: dict[str, Any]) -> str:
    target = _target(registry.session, payload["target_id"])
    if isinstance(target, TaxonomyTermRow):
        if _children(registry.session, target.term_id):
            raise ReviewError("reparent or retire its children first")
        target.status = TermStatus.RETIRED.value
        return target.term_id
    target.status = TermStatus.RETIRED.value
    return target.project_id


def _apply_reparent(registry: TaxonomyRegistry, payload: dict[str, Any]) -> str:
    target = _target(registry.session, payload["target_id"])
    if not isinstance(target, TaxonomyTermRow):
        raise ReviewError("only terms have parents")
    parent_id = payload.get("parent_id")
    if parent_id is not None:
        parent = _approved_term(registry.session, parent_id)
        if parent.term_id == target.term_id or parent.dimension != target.dimension:
            raise ReviewError("the parent must be another term in the same dimension")
        if parent.parent_id is not None or _children(registry.session, target.term_id):
            raise ReviewError("the taxonomy has two levels at most")
    target.parent_id = parent_id
    return target.term_id


_APPLY = {
    Operation.ADD: _apply_add,
    Operation.RENAME: _apply_rename,
    Operation.ALIAS: _apply_alias,
    Operation.MERGE: _apply_merge,
    Operation.RETIRE: _apply_retire,
    Operation.REPARENT: _apply_reparent,
}


def _target(session: Session, target_id: str) -> TaxonomyTermRow | ProjectRow:
    # Only approved things can be changed: a proposal can't edit another
    # proposal's term, or bring back a merged or retired one.
    found: TaxonomyTermRow | ProjectRow | None = session.get(TaxonomyTermRow, target_id)
    if found is None:
        found = session.get(ProjectRow, target_id)
    if found is None or found.status != TermStatus.APPROVED.value:
        raise ReviewError("the target must be an approved term or project")
    return found


def _approved_term(session: Session, term_id: str) -> TaxonomyTermRow:
    term = _target(session, term_id)
    if not isinstance(term, TaxonomyTermRow):
        raise ReviewError("expected a term, got a project")
    return term


def _children(session: Session, term_id: str) -> list[str]:
    return list(
        session.scalars(
            select(TaxonomyTermRow.term_id).where(
                TaxonomyTermRow.parent_id == term_id,
                TaxonomyTermRow.status == TermStatus.APPROVED.value,
            )
        )
    )


def _free_term_alias(session: Session, dimension: str, alias: str) -> None:
    norm = normalise_alias(alias)
    if not norm:
        raise ReviewError("an alias needs at least one letter or digit")
    taken = session.scalar(
        select(TaxonomyAliasRow.term_id).where(
            TaxonomyAliasRow.dimension == dimension, TaxonomyAliasRow.norm_form == norm
        )
    )
    if taken is not None:
        raise ReviewError(f"'{alias}' already names a term in {dimension}")


def _free_project_alias(session: Session, alias: str) -> None:
    norm = normalise_alias(alias)
    if not norm:
        raise ReviewError("an alias needs at least one letter or digit")
    if session.scalar(select(ProjectAliasRow.project_id).where(ProjectAliasRow.norm_form == norm)):
        raise ReviewError(f"'{alias}' already names a project")


def _term_alias_owned(session: Session, term: TaxonomyTermRow, alias: str) -> bool:
    owner = session.scalar(
        select(TaxonomyAliasRow.term_id).where(
            TaxonomyAliasRow.dimension == term.dimension,
            TaxonomyAliasRow.norm_form == normalise_alias(alias),
        )
    )
    return owner == term.term_id


def _project_alias_owned(session: Session, project: ProjectRow, alias: str) -> bool:
    owner = session.scalar(
        select(ProjectAliasRow.project_id).where(
            ProjectAliasRow.norm_form == normalise_alias(alias)
        )
    )
    return owner == project.project_id


def _add_project_alias(session: Session, project: ProjectRow, alias: str) -> None:
    session.add(
        ProjectAliasRow(
            project_id=project.project_id, alias=alias.strip(), norm_form=normalise_alias(alias)
        )
    )
    session.flush()
