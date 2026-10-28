"""TAX-008: the governance report surfaces duplicates, parent loops and review activity."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from knowledge_engine.infrastructure.db import create_sqlite_engine, database_path
from knowledge_engine.infrastructure.migrations import upgrade_to_head
from knowledge_engine.settings import Settings
from knowledge_engine.taxonomy.governance import governance_report
from knowledge_engine.taxonomy.registry import (
    Dimension,
    TaxonomyProposalRow,
    TaxonomyRegistry,
    TaxonomyTermRow,
    TermStatus,
)
from knowledge_engine.taxonomy.review import Operation, approve, propose, reject

APPROVED = TermStatus.APPROVED


@pytest.fixture
def session(tmp_path: Path) -> Iterator[Session]:
    engine = create_sqlite_engine(tmp_path / "k.db")
    upgrade_to_head(engine)
    with Session(engine) as db:
        yield db
    engine.dispose()


def _audit_fixture(session: Session) -> None:
    """A vocabulary with planted problems. Rows the API would refuse are written directly,
    the way an old version or a hand edit might have left them."""
    registry = TaxonomyRegistry(session)
    registry.add_term(Dimension.TOPIC, "Game Engines", status=APPROVED, term_id="term_a")
    registry.add_term(Dimension.TOPIC, "Gameengine", status=APPROVED, term_id="term_b")
    # Same label, no alias row: an exact duplicate the alias table never saw.
    session.add(
        TaxonomyTermRow(
            term_id="term_c", dimension="topic", label="Game Engines", status="approved"
        )
    )
    # A parent loop: x -> y -> x.
    session.add_all(
        [
            TaxonomyTermRow(term_id="term_x", dimension="domain", label="Synthetic X"),
            TaxonomyTermRow(term_id="term_y", dimension="domain", label="Synthetic Y"),
        ]
    )
    session.flush()
    session.get(TaxonomyTermRow, "term_x").parent_id = "term_y"  # type: ignore[union-attr]
    session.get(TaxonomyTermRow, "term_y").parent_id = "term_x"  # type: ignore[union-attr]
    # An approved child of a retired parent.
    registry.add_term(
        Dimension.PURPOSE, "Synthetic old", status=TermStatus.RETIRED, term_id="term_r"
    )
    registry.add_term(
        Dimension.PURPOSE, "Synthetic kid", status=APPROVED, term_id="term_k", parent_id="term_r"
    )
    # A topic and a project spelled the same.
    registry.add_project("Gameengine", status=APPROVED, project_id="proj_g")
    session.flush()


def test_duplicate_and_parent_cycle_fixture_surfaces_issues(session: Session) -> None:
    _audit_fixture(session)
    report = governance_report(session)
    found = {(issue.kind, issue.ids) for issue in report.issues}
    assert ("duplicate", ("term_a", "term_c")) in found
    assert ("near_duplicate", ("term_a", "term_b", "term_c")) in found
    assert ("parent_cycle", ("term_x", "term_y")) in found
    assert ("orphan", ("term_k", "term_r")) in found
    assert ("cross_scope", ("proj_g", "term_b")) in found
    assert report.kinds()["parent_cycle"] == 1  # one loop, reported once
    assert report.terms == {"approved": 4, "proposed": 2, "retired": 1}


def test_report_only_reads(session: Session) -> None:
    _audit_fixture(session)
    session.commit()
    before = {row.term_id: (row.status, row.parent_id) for row in session.query(TaxonomyTermRow)}
    governance_report(session)
    assert not session.dirty and not session.new
    after = {row.term_id: (row.status, row.parent_id) for row in session.query(TaxonomyTermRow)}
    assert before == after


def test_clean_vocabulary_has_no_issues(session: Session) -> None:
    registry = TaxonomyRegistry(session)
    parent = registry.add_term(Dimension.TOPIC, "Baking", status=APPROVED)
    registry.add_term(Dimension.TOPIC, "Sourdough", status=APPROVED, parent_id=parent.term_id)
    registry.add_project("Synthetic garden", status=APPROVED)
    assert governance_report(session).issues == []


def test_review_activity_and_self_review_flag(session: Session) -> None:
    first = propose(
        session, Operation.ADD, {"dimension": "topic", "label": "Beekeeping"}, proposer="discovery"
    )
    second = propose(
        session, Operation.ADD, {"dimension": "topic", "label": "Knitting"}, proposer="discovery"
    )
    propose(
        session, Operation.ADD, {"dimension": "topic", "label": "Pottery"}, proposer="discovery"
    )
    approve(session, first.proposal_id, reviewer="reviewer-a")
    reject(session, second.proposal_id, reviewer="reviewer-a", note="out of scope")
    # An old row decided by its own proposer (the API now refuses this).
    session.add(
        TaxonomyProposalRow(
            proposal_id="prop_old",
            operation="add",
            payload_json=json.dumps({"dimension": "topic", "label": "Synthetic"}),
            proposer="someone",
            status="approved",
            reviewer="Someone",
        )
    )
    session.flush()
    report = governance_report(session)
    assert report.open_proposals == {"add": 1}
    assert len(report.oldest_open) == 1
    assert report.reviewers["reviewer-a"] == {"approved": 1, "rejected": 1}
    assert ("self_review", ("prop_old",)) in {(i.kind, i.ids) for i in report.issues}


def test_cli_taxonomy_report(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from knowledge_engine.cli.main import main

    settings = Settings(workspace_root=tmp_path / "ws")
    monkeypatch.setenv("KE_WORKSPACE_ROOT", str(settings.workspace_root))
    assert main(["--json", "taxonomy", "report"]) != 0  # no database yet
    capsys.readouterr()
    db = database_path(settings)
    db.parent.mkdir(parents=True, exist_ok=True)
    engine = create_sqlite_engine(db)
    upgrade_to_head(engine)
    with Session(engine) as db_session:
        _audit_fixture(db_session)
        db_session.commit()
    engine.dispose()
    assert main(["--json", "taxonomy", "report"]) == 0
    data = json.loads(capsys.readouterr().out)["data"]
    assert {issue["kind"] for issue in data["issues"]} >= {"duplicate", "parent_cycle", "orphan"}
