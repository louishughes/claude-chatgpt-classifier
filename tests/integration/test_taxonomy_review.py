"""TAX-004: proposals change nothing until a different person approves them."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from knowledge_engine.infrastructure.db import create_sqlite_engine
from knowledge_engine.infrastructure.migrations import upgrade_to_head
from knowledge_engine.taxonomy.aliases import AliasResolver
from knowledge_engine.taxonomy.registry import (
    Dimension,
    TaxonomyRegistry,
    TaxonomyTermRow,
    TermStatus,
    UnknownTermError,
)
from knowledge_engine.taxonomy.review import (
    Operation,
    ReviewError,
    approve,
    proposals,
    propose,
    reject,
)

APPROVED = TermStatus.APPROVED


@pytest.fixture
def session(tmp_path: Path) -> Iterator[Session]:
    engine = create_sqlite_engine(tmp_path / "k.db")
    upgrade_to_head(engine)
    with Session(engine) as db:
        yield db
    engine.dispose()


def _add(session: Session, label: str, **extra: object) -> str:
    payload = {"dimension": "topic", "label": label, **extra}
    return propose(session, Operation.ADD, payload, proposer="model-run-1").proposal_id


def test_unapproved_proposal_cannot_appear_as_canonical_term(session: Session) -> None:
    registry = TaxonomyRegistry(session)
    proposal_id = _add(session, "Unreal Engine", aliases=["UE5"])
    before = registry.publish("tax-1", author="test")
    assert before.terms == ()
    assert session.query(TaxonomyTermRow).count() == 0  # not even a proposed row
    assert AliasResolver(before).resolve("UE5").target_id is None

    decided = approve(session, proposal_id, reviewer="reviewer-a", note="seen in 12 chats")
    after = registry.publish("tax-2", author="test")
    assert decided.result_id is not None
    assert after.term(decided.result_id).label == "Unreal Engine"
    assert AliasResolver(after).resolve("ue5").target_id == decided.result_id
    # The earlier version is frozen: it still doesn't have the term.
    with pytest.raises(UnknownTermError):
        registry.snapshot("tax-1").term(decided.result_id)


def test_proposer_cannot_review_and_decisions_are_final(session: Session) -> None:
    proposal_id = _add(session, "Unity")
    with pytest.raises(ReviewError, match="own proposal"):
        approve(session, proposal_id, reviewer="Model-Run-1")
    rejected = reject(session, proposal_id, reviewer="reviewer-a", note="too broad")
    assert (rejected.status, rejected.reviewer, rejected.decision_note) == (
        "rejected",
        "reviewer-a",
        "too broad",
    )
    assert rejected.decided_at is not None
    with pytest.raises(ReviewError, match="final"):
        approve(session, proposal_id, reviewer="reviewer-b")
    assert proposals(session) == []
    assert [p.proposal_id for p in proposals(session, status=None)] == [proposal_id]


def test_reject_needs_a_reason(session: Session) -> None:
    with pytest.raises(ReviewError):
        reject(session, _add(session, "Unity"), reviewer="reviewer-a", note=" ")


def test_rename_keeps_old_label_as_alias(session: Session) -> None:
    term = TaxonomyRegistry(session).add_term(Dimension.TOPIC, "Unreal", status=APPROVED)
    proposal = propose(
        session,
        Operation.RENAME,
        {"target_id": term.term_id, "label": "Unreal Engine"},
        proposer="model-run-1",
    )
    approve(session, proposal.proposal_id, reviewer="reviewer-a")
    snapshot = TaxonomyRegistry(session).publish("tax-1", author="test")
    resolver = AliasResolver(snapshot)
    assert snapshot.term(term.term_id).label == "Unreal Engine"
    assert resolver.resolve("Unreal").target_id == term.term_id
    assert resolver.resolve("Unreal Engine").target_id == term.term_id


def test_merge_moves_aliases_and_keeps_source_id(session: Session) -> None:
    registry = TaxonomyRegistry(session)
    keep = registry.add_term(Dimension.TOPIC, "Unreal Engine", status=APPROVED)
    dupe = registry.add_term(Dimension.TOPIC, "UE5", status=APPROVED)
    proposal = propose(
        session,
        Operation.MERGE,
        {"source_id": dupe.term_id, "target_id": keep.term_id},
        proposer="model-run-1",
        evidence={"segments": ["seg_a", "seg_b"]},
    )
    approve(session, proposal.proposal_id, reviewer="reviewer-a")
    snapshot = registry.publish("tax-1", author="test")
    assert snapshot.allowed_ids(Dimension.TOPIC) == (keep.term_id,)
    assert AliasResolver(snapshot).resolve("UE5").target_id == keep.term_id
    merged = session.get(TaxonomyTermRow, dupe.term_id)
    assert merged is not None
    assert (merged.status, merged.merged_into) == ("merged", keep.term_id)


def test_rules_are_checked_at_approval(session: Session) -> None:
    registry = TaxonomyRegistry(session)
    engine = registry.add_term(Dimension.TOPIC, "Game engines", status=APPROVED)
    unreal = registry.add_term(Dimension.TOPIC, "Unreal", parent_id=engine.term_id, status=APPROVED)
    domain = registry.add_term(Dimension.DOMAIN, "Games", status=APPROVED)
    session.commit()
    cases = [
        (Operation.ALIAS, {"target_id": engine.term_id, "alias": "UNREAL"}, "already names"),
        (Operation.MERGE, {"source_id": domain.term_id, "target_id": unreal.term_id}, "dimension"),
        (Operation.REPARENT, {"target_id": engine.term_id, "parent_id": unreal.term_id}, "two"),
        (Operation.RETIRE, {"target_id": engine.term_id}, "children"),
        (Operation.ALIAS, {"target_id": "term_missing", "alias": "x"}, "approved"),
    ]
    for operation, payload, message in cases:
        proposal = propose(session, operation, payload, proposer="model-run-1")
        with pytest.raises(ReviewError, match=message):
            approve(session, proposal.proposal_id, reviewer="reviewer-a")
        session.rollback()


def test_retired_term_leaves_the_next_snapshot(session: Session) -> None:
    registry = TaxonomyRegistry(session)
    term = registry.add_term(Dimension.TOPIC, "Flash", status=APPROVED)
    proposal = propose(session, Operation.RETIRE, {"target_id": term.term_id}, proposer="p")
    approve(session, proposal.proposal_id, reviewer="r")
    assert registry.publish("tax-1", author="test").terms == ()


def test_projects_go_through_the_same_review(session: Session) -> None:
    proposal = propose(
        session,
        Operation.ADD,
        {"kind": "project", "label": "Knowledge Engine", "aliases": ["KE", "ke"]},
        proposer="p",
    )
    project_id = approve(session, proposal.proposal_id, reviewer="r").result_id
    snapshot = TaxonomyRegistry(session).publish("tax-1", author="test")
    assert snapshot.project_ids() == (project_id,)
    assert AliasResolver(snapshot).resolve("KE", scope="project").target_id == project_id


def test_malformed_proposals_are_refused(session: Session) -> None:
    with pytest.raises(ReviewError, match="dimension"):
        propose(session, Operation.ADD, {"label": "x", "dimension": "colour"}, proposer="p")
    with pytest.raises(ReviewError, match="target_id"):
        propose(session, Operation.RETIRE, {}, proposer="p")
