"""Taxonomy, review and knowledge endpoints (API-003).

The same review rules as the command line, over HTTP. Nothing here decides
anything on its own: it lists what is waiting, shows the evidence, and
passes a person's decision to the existing workflow, which refuses what it
always refuses:

* **Taxonomy proposals** (TAX-004). Anyone can propose; the reviewer must
  not be the proposer; a proposal is decided once; renaming or merging a
  project needs a note. Approving changes the live vocabulary only; the
  next ``publish`` makes it visible to classifiers.
* **Knowledge records** (EXT-007). Only ``supported`` and ``confirmed``
  records are knowledge. A reviewer can support, confirm or reject a record
  that has been through the evidence gate, and the record rules still
  apply: an assistant's suggestion can't become the user's decision without
  the user's acceptance. Every change is logged with who, when and why.

Refusals come back as ``reviewer_not_allowed`` (403: no reviewer, the
built-in validator's name, or the proposer reviewing their own proposal)
or ``invalid_transition`` (409: anything the workflow doesn't allow). The
reviewer is a name the caller gives. Once accounts exist (PROD-002) that
name must be the caller's own account, or the request is refused
(``identity_mismatch``).

Talking points:
    - "The API can't do anything the review rules forbid: no self-approval,
      no deciding twice, and a suggestion never becomes my decision."
    - "Knowledge lists only show checked records; everything else waits in
      the review queue with its evidence."
"""

from __future__ import annotations

import json
from dataclasses import asdict
from enum import StrEnum
from typing import Annotated, Any

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.orm import Session

from knowledge_engine.api.access import AccessDep
from knowledge_engine.api.deps import ApiError, SessionsDep
from knowledge_engine.extraction.records import (
    KnowledgeRecord,
    RecordType,
    Trust,
    TrustTransitionError,
)
from knowledge_engine.extraction.store import (
    VALIDATOR,
    Decision,
    GateError,
    current_truth,
    decide,
    history,
    load,
    review_queue,
)
from knowledge_engine.taxonomy.governance import governance_report
from knowledge_engine.taxonomy.registry import (
    ProjectRow,
    TaxonomyProposalRow,
    TaxonomyRegistry,
    TaxonomyTermRow,
)
from knowledge_engine.taxonomy.review import (
    Operation,
    ReviewError,
    approve,
    proposals,
    propose,
    reject,
)

router = APIRouter()

# Which trust a record must have for each decision. ``decide`` itself
# quietly returns a record unchanged when a decision doesn't apply (support
# on a supported record); over the API that is refused instead, so a caller
# never mistakes "nothing happened" for "done".
_DECIDABLE = {
    Decision.SUPPORT: {Trust.REVIEW_REQUIRED},
    Decision.CONFIRM: {Trust.REVIEW_REQUIRED, Trust.SUPPORTED},
    Decision.REJECT: {Trust.REVIEW_REQUIRED, Trust.SUPPORTED},
}

Name = Annotated[str, Field(min_length=1, max_length=100)]
Note = Annotated[str | None, Field(default=None, max_length=2000)]


class ProposalStatus(StrEnum):
    """Which proposals to list."""

    OPEN = "open"
    APPROVED = "approved"
    REJECTED = "rejected"
    ALL = "all"


class ProposalRequest(BaseModel):
    """``POST /taxonomy/proposals``: a suggested vocabulary change.

    ``payload`` holds the operation's fields, as for ``ke taxonomy propose``:
    ``add`` takes ``label`` and ``dimension`` (or ``kind: "project"``), with
    optional ``aliases``, ``parent_id`` and ``definition``; the others name
    their target by ID.
    """

    operation: Operation
    payload: dict[str, Any]
    proposer: Name
    evidence: dict[str, Any] = Field(default_factory=dict)


class ProposalDecision(BaseModel):
    """``POST /taxonomy/proposals/{id}/review``: approve or reject."""

    decision: str = Field(pattern="^(approve|reject)$")
    reviewer: Name
    note: Note = None
    label: str | None = Field(default=None, max_length=200)


class RecordDecision(BaseModel):
    """``POST /knowledge/{id}/review``: support, confirm or reject."""

    decision: Decision
    reviewer: Name
    note: Note = None


def _proposal(row: TaxonomyProposalRow) -> dict[str, Any]:
    return {
        "proposal_id": row.proposal_id,
        "operation": row.operation,
        "payload": json.loads(row.payload_json),
        "evidence": json.loads(row.evidence_json or "{}"),
        "proposer": row.proposer,
        "status": row.status,
        "reviewer": row.reviewer,
        "decision_note": row.decision_note,
        "result_id": row.result_id,
        "created_at": row.created_at,
        "decided_at": row.decided_at,
    }


def _record(record: KnowledgeRecord) -> dict[str, Any]:
    data: dict[str, Any] = record.model_dump(mode="json")
    return data


# ------------------------------------------------------------------ taxonomy


@router.get("/taxonomy", tags=["taxonomy"])
def get_taxonomy(sessions: SessionsDep) -> dict[str, Any]:
    """The live vocabulary (every status) and the published versions."""
    with sessions.transaction(write=False) as session:
        terms = session.query(TaxonomyTermRow).order_by(TaxonomyTermRow.term_id).all()
        projects = session.query(ProjectRow).order_by(ProjectRow.project_id).all()
        versions = TaxonomyRegistry(session).versions()
        return {
            "versions": versions,
            "terms": [
                {
                    "term_id": t.term_id,
                    "dimension": t.dimension,
                    "label": t.label,
                    "definition": t.definition,
                    "parent_id": t.parent_id,
                    "status": t.status,
                    "merged_into": t.merged_into,
                }
                for t in terms
            ],
            "projects": [
                {
                    "project_id": p.project_id,
                    "name": p.name,
                    "status": p.status,
                    "merged_into": p.merged_into,
                }
                for p in projects
            ],
        }


@router.get("/taxonomy/versions/{version}", tags=["taxonomy"])
def get_taxonomy_version(version: str, sessions: SessionsDep) -> dict[str, Any]:
    """One published, frozen snapshot: what classifiers of that version saw."""
    with sessions.transaction(write=False) as session:
        try:
            snapshot = TaxonomyRegistry(session).snapshot(version)
        except KeyError as error:
            raise ApiError(404, "not_found", "no such taxonomy version") from error
    data: dict[str, Any] = asdict(snapshot)
    return data


@router.get("/taxonomy/governance", tags=["taxonomy"])
def get_governance(sessions: SessionsDep) -> dict[str, Any]:
    """Vocabulary health: duplicates, parent and merge problems, waiting proposals."""
    with sessions.transaction(write=False) as session:
        report: dict[str, Any] = asdict(governance_report(session))
    return report


@router.get("/taxonomy/proposals", tags=["taxonomy"])
def get_proposals(
    sessions: SessionsDep, status: ProposalStatus = ProposalStatus.OPEN
) -> dict[str, Any]:
    """Proposals in one status, oldest first."""
    wanted = None if status is ProposalStatus.ALL else status.value
    with sessions.transaction(write=False) as session:
        return {"items": [_proposal(row) for row in proposals(session, wanted)]}


@router.post("/taxonomy/proposals", status_code=201, tags=["taxonomy"])
def post_proposal(
    body: ProposalRequest, sessions: SessionsDep, access: AccessDep
) -> dict[str, Any]:
    """Record a proposal. Nothing in the vocabulary changes until it is approved."""
    access.require_identity(body.proposer)
    with sessions.transaction() as session:
        try:
            row = propose(
                session,
                body.operation,
                body.payload,
                proposer=body.proposer,
                evidence=body.evidence,
            )
        except ReviewError as error:
            raise ApiError(400, "invalid_proposal", str(error)) from error
        return _proposal(row)


@router.post("/taxonomy/proposals/{proposal_id}/review", tags=["taxonomy"])
def review_proposal(
    proposal_id: str, body: ProposalDecision, sessions: SessionsDep, access: AccessDep
) -> dict[str, Any]:
    """Approve or reject an open proposal; a refused decision changes nothing."""
    access.require_identity(body.reviewer)
    with sessions.transaction() as session:
        row = session.get(TaxonomyProposalRow, proposal_id)
        if row is None:
            raise ApiError(404, "not_found", "no such proposal")
        if body.reviewer.strip().casefold() == row.proposer.strip().casefold():
            raise ApiError(
                403, "reviewer_not_allowed", "the proposer can't review their own proposal"
            )
        try:
            if body.decision == "approve":
                row = approve(
                    session, proposal_id, reviewer=body.reviewer, note=body.note, label=body.label
                )
            else:
                row = reject(session, proposal_id, reviewer=body.reviewer, note=body.note or "")
        except ReviewError as error:
            # The transaction rolls back: a half-applied change can't stay.
            raise ApiError(409, "invalid_transition", str(error)) from error
        return _proposal(row)


# ----------------------------------------------------------------- knowledge


@router.get("/knowledge", tags=["knowledge"])
def get_knowledge(
    sessions: SessionsDep,
    scope_id: Annotated[str | None, Query(max_length=100)] = None,
    record_type: Annotated[list[RecordType] | None, Query(alias="type")] = None,
) -> dict[str, Any]:
    """Current knowledge: ``supported`` and ``confirmed`` records only."""
    with sessions.transaction(write=False) as session:
        records = current_truth(session, scope_id=scope_id, types=record_type or ())
    return {"items": [_record(r) for r in records]}


@router.get("/review", tags=["knowledge"])
def get_review(sessions: SessionsDep) -> dict[str, Any]:
    """Everything waiting for a person: records to review and open proposals."""
    with sessions.transaction(write=False) as session:
        return {
            "records": [_record(r) for r in review_queue(session)],
            "proposals": [_proposal(row) for row in proposals(session)],
        }


@router.get("/knowledge/{record_id}", tags=["knowledge"])
def get_record(record_id: str, sessions: SessionsDep) -> dict[str, Any]:
    """One record (any trust) with its evidence anchors and its full trust history."""
    with sessions.transaction(write=False) as session:
        record = _load(session, record_id)
        events = [
            {
                "from": e.from_trust,
                "to": e.to_trust,
                "actor": e.actor,
                "note": e.note,
                "problems": json.loads(e.problems_json or "[]"),
                "at": e.at,
            }
            for e in history(session, record_id)
        ]
    return {"record": _record(record), "history": events}


@router.post("/knowledge/{record_id}/review", tags=["knowledge"])
def review_record(
    record_id: str, body: RecordDecision, sessions: SessionsDep, access: AccessDep
) -> dict[str, Any]:
    """Support, confirm or reject a gated record; a refused decision changes nothing."""
    access.require_identity(body.reviewer)
    if body.reviewer.strip() == VALIDATOR:
        raise ApiError(403, "reviewer_not_allowed", "a decision needs a named reviewer")
    with sessions.transaction() as session:
        current = _load(session, record_id)
        if current.trust is Trust.CANDIDATE:
            raise ApiError(409, "invalid_transition", "run the evidence gate first")
        if current.trust not in _DECIDABLE[body.decision]:
            raise ApiError(
                409,
                "invalid_transition",
                f"a {current.trust.value} record can't take '{body.decision.value}'",
            )
        try:
            record = decide(
                session, record_id, body.decision, reviewer=body.reviewer, note=body.note
            )
        except (GateError, TrustTransitionError) as error:
            raise ApiError(409, "invalid_transition", str(error)) from error
        except ValidationError as error:
            # Only the rule's own words: the error's input could be quoted text.
            rules = "; ".join(sorted({e["msg"] for e in error.errors()}))
            raise ApiError(409, "invalid_transition", rules) from error
        return _record(record)


def _load(session: Session, record_id: str) -> KnowledgeRecord:
    try:
        return load(session, record_id)
    except GateError as error:
        raise ApiError(404, "not_found", "no such record") from error
