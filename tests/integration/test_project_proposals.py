"""TAX-005: project names become proposals; the same name never merges by itself."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from knowledge_engine.infrastructure.db import create_sqlite_engine
from knowledge_engine.infrastructure.migrations import upgrade_to_head
from knowledge_engine.taxonomy.aliases import AliasResolver, MatchStatus
from knowledge_engine.taxonomy.projects import propose_project
from knowledge_engine.taxonomy.registry import ProjectRow, TaxonomyRegistry, TermStatus
from knowledge_engine.taxonomy.review import Operation, ReviewError, approve, propose, reject


@pytest.fixture
def session(tmp_path: Path) -> Iterator[Session]:
    engine = create_sqlite_engine(tmp_path / "k.db")
    upgrade_to_head(engine)
    with Session(engine) as db:
        yield db
    engine.dispose()


def _atlas(session: Session) -> str:
    return (
        TaxonomyRegistry(session)
        .add_project("Atlas", aliases=["Atlas garden app"], status=TermStatus.APPROVED)
        .project_id
    )


def test_same_name_different_project_is_not_merged(session: Session) -> None:
    garden = _atlas(session)
    proposal = propose_project(
        session, "atlas", proposer="discovery", evidence={"conversations": ["conv_maps"]}
    )
    # A question for review, not an attachment to the existing project.
    assert proposal.status == "open"
    assert '"same_name_as": ["' + garden + '"]' in proposal.evidence_json
    assert session.query(ProjectRow).count() == 1
    session.commit()
    # Approving it as-is would make "atlas" mean two things: refused.
    with pytest.raises(ReviewError, match="already names"):
        approve(session, proposal.proposal_id, reviewer="reviewer-a")
    session.rollback()
    # The reviewer decides it's a different project and names it apart.
    maps = approve(
        session, proposal.proposal_id, reviewer="reviewer-a", label="Atlas map script"
    ).result_id
    assert maps is not None and maps != garden
    snapshot = TaxonomyRegistry(session).publish("tax-1", author="test")
    resolver = AliasResolver(snapshot)
    assert resolver.resolve("Atlas", scope="project").target_id == garden
    assert resolver.resolve("Atlas map script", scope="project").target_id == maps
    assert snapshot.project_ids() == tuple(sorted((garden, maps)))


def test_reviewer_can_reject_a_same_name_candidate(session: Session) -> None:
    _atlas(session)
    proposal = propose_project(session, "Atlas", proposer="discovery", evidence={})
    reject(session, proposal.proposal_id, reviewer="reviewer-a", note="same project")
    assert session.query(ProjectRow).count() == 1


def test_the_same_candidate_again_reuses_the_open_proposal(session: Session) -> None:
    evidence = {"conversations": ["conv_1", "conv_2"]}
    first = propose_project(session, "Knowledge Engine", proposer="d", evidence=evidence)
    again = propose_project(session, "Knowledge Engine", proposer="d", evidence=evidence)
    other = propose_project(session, "Knowledge Engine", proposer="d", evidence={"x": 1})
    assert first.proposal_id == again.proposal_id != other.proposal_id
    with pytest.raises(ReviewError):
        propose_project(session, "!!", proposer="d", evidence={})


def test_project_rename_and_merge_need_a_note(session: Session) -> None:
    registry = TaxonomyRegistry(session)
    keep = registry.add_project("Knowledge Engine", status=TermStatus.APPROVED)
    dupe = registry.add_project("KE app", status=TermStatus.APPROVED)
    rename = propose(
        session,
        Operation.RENAME,
        {"target_id": keep.project_id, "label": "Knowledge Engine 2"},
        proposer="p",
    )
    with pytest.raises(ReviewError, match="high-impact"):
        approve(session, rename.proposal_id, reviewer="r")
    approve(session, rename.proposal_id, reviewer="r", note="renamed by the owner")
    merge = propose(
        session,
        Operation.MERGE,
        {"source_id": dupe.project_id, "target_id": keep.project_id},
        proposer="p",
    )
    with pytest.raises(ReviewError, match="high-impact"):
        approve(session, merge.proposal_id, reviewer="r", note="  ")
    approve(session, merge.proposal_id, reviewer="r", note="same repo")
    snapshot = registry.publish("tax-1", author="test")
    resolver = AliasResolver(snapshot)
    # The project ID survives; the old names still resolve to it.
    for name in ("Knowledge Engine", "Knowledge Engine 2", "KE app"):
        assert resolver.resolve(name, scope="project").target_id == keep.project_id
    assert resolver.resolve("KE", scope="project").status is MatchStatus.UNMATCHED


def test_label_override_is_for_adds_only(session: Session) -> None:
    project = _atlas(session)
    proposal = propose(session, Operation.RETIRE, {"target_id": project}, proposer="p")
    with pytest.raises(ReviewError, match="replacement label"):
        approve(session, proposal.proposal_id, reviewer="r", label="x")
