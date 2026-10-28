"""Project candidates: names found in chats become proposals, never projects (TAX-005).

A project name spotted in conversations (by a person, discovery or later a
model) goes through ``propose_project``. It never creates or extends a
project by itself:

* A **new name** becomes an ``add`` proposal with its evidence.
* A name that **already belongs to an approved project** still becomes an
  ``add`` proposal, marked ``same_name_as`` that project. Two different
  things are often called the same ("Atlas" the garden app and "Atlas" the
  map script), so a matching name is a question for a reviewer, not a
  merge. The reviewer either rejects it (same project) or approves it under
  a distinguishing label (``approve(..., label="Atlas map script")``).
* The **same candidate again** (same name, same evidence) returns the open
  proposal already waiting, so re-running discovery doesn't pile up copies.

Project IDs are random and permanent (TAX-001), and renaming or merging a
project needs a reviewer's note (``review.approve``), because every label
pointing at it moves with it.

Talking points:
    - "Matching names are a question, not an answer: same name, different
      project is common, so nothing merges automatically."
    - "A project's ID never changes; its names are just aliases."
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from knowledge_engine.taxonomy.registry import (
    ProjectAliasRow,
    ProjectRow,
    TaxonomyProposalRow,
    TermStatus,
    normalise_alias,
)
from knowledge_engine.taxonomy.review import OPEN, Operation, ReviewError, propose


def same_name_projects(session: Session, name: str) -> list[str]:
    """Approved project IDs that already use this name (after normalising)."""
    norm = normalise_alias(name)
    return list(
        session.scalars(
            select(ProjectAliasRow.project_id)
            .join(ProjectRow, ProjectRow.project_id == ProjectAliasRow.project_id)
            .where(
                ProjectAliasRow.norm_form == norm,
                ProjectRow.status == TermStatus.APPROVED.value,
            )
            .order_by(ProjectAliasRow.project_id)
        )
    )


def propose_project(
    session: Session,
    name: str,
    *,
    proposer: str,
    evidence: Mapping[str, Any],
    aliases: Iterable[str] = (),
) -> TaxonomyProposalRow:
    """Turn a project name seen in the chats into a reviewable proposal.

    Args:
        session: The caller commits.
        name: The name as written.
        proposer: Who or what found it.
        evidence: IDs supporting it, e.g. ``{"conversations": [...]}``.
        aliases: Other spellings seen.

    Returns:
        The open ``add`` proposal (an existing one if this exact candidate
        is already waiting).

    Raises:
        ReviewError: If the name has no letters or digits.
    """
    if not normalise_alias(name):
        raise ReviewError("a project name needs at least one letter or digit")
    facts = dict(evidence)
    clash = same_name_projects(session, name)
    if clash:
        facts["same_name_as"] = clash
    payload = {"kind": "project", "label": name.strip(), "aliases": sorted(set(aliases))}
    waiting = _waiting(session, payload, facts)
    if waiting is not None:
        return waiting
    return propose(session, Operation.ADD, payload, proposer=proposer, evidence=facts)


def _waiting(
    session: Session, payload: Mapping[str, Any], evidence: Mapping[str, Any]
) -> TaxonomyProposalRow | None:
    wanted = (json.dumps(dict(payload), sort_keys=True), json.dumps(dict(evidence), sort_keys=True))
    for row in session.scalars(
        select(TaxonomyProposalRow).where(
            TaxonomyProposalRow.status == OPEN,
            TaxonomyProposalRow.operation == Operation.ADD.value,
        )
    ):
        if (row.payload_json, row.evidence_json) == wanted:
            return row
    return None
