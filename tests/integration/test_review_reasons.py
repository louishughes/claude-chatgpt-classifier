"""#255: the semantic smoke report says why answers went to review, by kind only."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from knowledge_engine.classification.store import review_reason_kind
from knowledge_engine.cli.main import main
from knowledge_engine.evaluation.semantic_smoke import (
    Faults,
    replay_review_reasons,
    run_semantic_smoke,
)
from knowledge_engine.evaluation.synthetic import write_generated
from knowledge_engine.importer import import_source
from knowledge_engine.infrastructure.db import create_sqlite_engine, database_path
from knowledge_engine.settings import Limits, Settings

KINDS = {
    "invalid_answer",
    "model_unsure",
    "evidence_outside_segment",
    "several_primaries",
    "listed_twice",
    "secondary_without_primary",
    "parts_disagree",
    "other",
}


@pytest.mark.parametrize(
    ("problem", "kind"),
    [
        ("answer failed validation twice", "invalid_answer"),
        ("flagged: the chat is about bread, no term fits", "model_unsure"),
        ("flagged: unsure", "model_unsure"),
        ("topic.term_x: evidence outside the segment: ['m9']", "evidence_outside_segment"),
        ("topic: 2 primaries", "several_primaries"),
        ("projects.proj_a: listed twice", "listed_twice"),
        ("intent: secondary without a primary", "secondary_without_primary"),
        ("the parts of this long segment got different primary labels", "parts_disagree"),
        ("something new", "other"),
    ],
)
def test_each_problem_has_a_kind(problem: str, kind: str) -> None:
    assert review_reason_kind(problem) == kind


def test_the_smoke_report_counts_review_reasons_without_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    source = write_generated(tmp_path / "src", 50, seed=11) / "export"
    settings = Settings(workspace_root=tmp_path / "ws")
    import_source(source, "smoke", settings=settings)
    engine = create_sqlite_engine(database_path(settings))
    with Session(engine) as session:
        report = run_semantic_smoke(
            session,
            limit=50,
            limits=Limits(max_model_calls_per_run=10_000, max_requests_per_batch=25),
            faults=Faults(invalid_every=7, silent_every=13),
        )
        session.commit()
        replayed = replay_review_reasons(session, limit=50)
        session.rollback()
    engine.dispose()

    classification = report["classification"]
    reasons = classification["review_reasons"]
    assert classification["review_required"] > 0
    assert set(reasons) <= KINDS
    # Every segment in review has at least one reason; one can have several kinds.
    assert sum(reasons.values()) >= classification["review_required"]
    # Replaying from the saved answers gives the same counts without a call.
    assert replayed["review_reasons"] == reasons
    assert replayed["review_required"] == classification["review_required"]
    # (A zero call budget means anything not saved would show as not_saved.)
    assert replayed["not_saved"] == classification["capped"] == 0
    assert "flagged" not in json.dumps(reasons)  # kinds only, never the model's words

    # The same counts from a saved workspace, without running anything.
    monkeypatch.setenv("KE_WORKSPACE_ROOT", str(settings.workspace_root))
    before = database_path(settings).read_bytes()
    assert main(["--json", "eval", "review-reasons", "--limit", "50"]) == 0
    assert json.loads(capsys.readouterr().out)["data"]["review_reasons"] == reasons
    assert database_path(settings).read_bytes() == before  # nothing written
