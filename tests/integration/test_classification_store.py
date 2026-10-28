"""CLS-004 / CLS-005: stored classifications, reviewer choices that survive re-runs,
and order-independence."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import replace
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from knowledge_engine.classification.classifier import (
    DONE,
    PENDING,
    REVIEW_REQUIRED,
    SegmentClassification,
    SegmentClassifier,
)
from knowledge_engine.classification.drift import order_experiment
from knowledge_engine.classification.store import (
    FIELDS,
    ClassificationLabelRow,
    ClassificationRow,
    ReviewInputError,
    effective_labels,
    record_review,
    review_queue,
    save,
)
from knowledge_engine.importer import import_source
from knowledge_engine.importer.records import ConversationRow
from knowledge_engine.infrastructure.db import create_sqlite_engine, database_path
from knowledge_engine.rendering.transcript import StoredConversation, load_conversation
from knowledge_engine.segmentation.segmenter import Segment, segment_conversation
from knowledge_engine.settings import Settings
from knowledge_engine.taxonomy.registry import SnapshotProject, SnapshotTerm, TaxonomySnapshot

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "chatgpt"


def _term(term_id: str, label: str, *aliases: str) -> SnapshotTerm:
    return SnapshotTerm(term_id, "topic", label, None, None, aliases)


SNAPSHOT = TaxonomySnapshot(
    "tax-7",
    "e" * 64,
    terms=(
        _term("term_gardening", "Gardening", "seedlings", "raised bed"),
        _term("term_godot", "Godot"),
        _term("term_unity", "Unity"),
        _term("term_webdesign", "Web design", "menu page"),
    ),
    projects=(
        SnapshotProject("proj_bakery", "Bakery site", ()),
        SnapshotProject("proj_garden", "Garden plan", ()),
    ),
)
Pairs = list[tuple[StoredConversation, Segment]]


@pytest.fixture
def world(tmp_path: Path) -> Iterator[tuple[Session, Pairs]]:
    settings = Settings(workspace_root=tmp_path / "ws")
    import_source(FIXTURES / "mixed_projects" / "export", "fixture", settings=settings)
    engine = create_sqlite_engine(database_path(settings))
    with Session(engine) as session:
        ids = session.scalars(
            select(ConversationRow.conversation_id).order_by(ConversationRow.native_conversation_id)
        ).all()
        pairs: Pairs = []
        for conversation_id in ids:
            conv = load_conversation(session, conversation_id)
            pairs += [(conv, seg) for seg in segment_conversation(conv)]
        yield session, pairs
    engine.dispose()


def _count(session: Session, table: type) -> int:
    return session.scalar(select(func.count()).select_from(table)) or 0


def test_human_reviewed_choice_persists_through_repeated_processing(
    world: tuple[Session, Pairs],
) -> None:
    session, pairs = world
    garden_chat = pairs[0]
    segment_id = garden_chat[1].segment_id
    save(session, SegmentClassifier(SNAPSHOT).classify(pairs))
    machine = effective_labels(session, segment_id, SNAPSHOT)["projects"]
    assert (machine.primary, machine.source) == ("proj_garden", "machine")

    # The reviewer says the segment is really about the bakery site.
    record_review(
        session, SNAPSHOT, segment_id, "projects", primary="proj_bakery", reviewer="reviewer-a"
    )
    rows = _count(session, ClassificationRow)

    # Same run again: nothing new is stored, the choice stands.
    save(session, SegmentClassifier(SNAPSHOT).classify(pairs))
    assert _count(session, ClassificationRow) == rows
    # A different run (new settings, new stage keys): new machine rows, choice still stands.
    save(session, SegmentClassifier(SNAPSHOT, min_score=0.5).classify(pairs))
    assert _count(session, ClassificationRow) == rows + len(pairs)
    chosen = effective_labels(session, segment_id, SNAPSHOT)["projects"]
    assert (chosen.primary, chosen.secondary, chosen.source) == ("proj_bakery", (), "review")
    # Fields nobody reviewed still follow the machine.
    assert effective_labels(session, segment_id, SNAPSHOT)["topic"].source == "machine"

    # A later version without the reviewed project: flagged, not dropped or kept silently.
    newer = replace(SNAPSHOT, version="tax-8", projects=SNAPSHOT.projects[1:])
    assert effective_labels(session, segment_id, newer)["projects"].source == "stale_review"


def test_stored_rows_keep_versions_labels_and_evidence(world: tuple[Session, Pairs]) -> None:
    session, pairs = world
    [row, _] = save(session, SegmentClassifier(SNAPSHOT).classify(pairs))
    assert (row.taxonomy_version, row.method, row.state) == ("tax-7", "keyword", DONE)
    labels = session.scalars(
        select(ClassificationLabelRow).where(
            ClassificationLabelRow.classification_id == row.classification_id
        )
    ).all()
    assert {(lbl.field, lbl.target_id, lbl.rank) for lbl in labels} >= {
        ("projects", "proj_garden", "primary"),
        ("projects", "proj_bakery", "secondary"),
    }
    assert all(0 <= lbl.confidence <= 1 and lbl.evidence_json != "[]" for lbl in labels)


def test_pending_row_is_completed_once(world: tuple[Session, Pairs]) -> None:
    session, pairs = world
    [done] = SegmentClassifier(SNAPSHOT).classify(pairs[:1])
    waiting = replace(done, state=PENDING, answer=None)
    [row] = save(session, [waiting])
    assert row.state == PENDING and _count(session, ClassificationLabelRow) == 0
    [row] = save(session, [done])
    assert row.state == DONE and _count(session, ClassificationLabelRow) > 0
    labels = _count(session, ClassificationLabelRow)
    save(session, [done])
    assert _count(session, ClassificationLabelRow) == labels  # never added twice


def test_review_queue_until_every_flagged_field_is_decided(world: tuple[Session, Pairs]) -> None:
    session, pairs = world
    # Everything a near tie: every answer is flagged for review.
    save(session, SegmentClassifier(SNAPSHOT, tie_margin=100.0).classify(pairs))
    queue = review_queue(session, "tax-7")
    assert [r.segment_id for r in queue] == sorted(seg.segment_id for _, seg in pairs)
    assert all(r.state == REVIEW_REQUIRED for r in queue)
    first = queue[0].segment_id
    for field in FIELDS:  # a general flag needs every field decided
        primary = {"projects": "proj_garden", "topic": "term_gardening"}.get(field)
        record_review(session, SNAPSHOT, first, field, primary=primary, reviewer="reviewer-a")
    assert [r.segment_id for r in review_queue(session, "tax-7")] == [queue[1].segment_id]


def test_review_input_is_checked_against_the_version(world: tuple[Session, Pairs]) -> None:
    session, pairs = world
    segment_id = pairs[0][1].segment_id
    with pytest.raises(ReviewInputError, match="not approved"):
        record_review(session, SNAPSHOT, segment_id, "topic", primary="term_pizza", reviewer="r")
    with pytest.raises(ReviewInputError, match="not approved"):
        record_review(session, SNAPSHOT, segment_id, "topic", primary="proj_garden", reviewer="r")
    with pytest.raises(ReviewInputError, match="need a primary"):
        record_review(
            session,
            SNAPSHOT,
            segment_id,
            "topic",
            primary=None,
            secondary=["term_godot"],
            reviewer="r",
        )
    with pytest.raises(ReviewInputError, match="unknown field"):
        record_review(session, SNAPSHOT, segment_id, "mood", primary=None, reviewer="r")
    # "Nothing fits" is a valid decision.
    none = record_review(session, SNAPSHOT, segment_id, "topic", primary=None, reviewer="r")
    assert none.sequence == 1
    assert effective_labels(session, segment_id, SNAPSHOT)["topic"].primary is None


def test_three_order_golden_experiment_yields_same_ids(world: tuple[Session, Pairs]) -> None:
    _, pairs = world
    report = order_experiment(SegmentClassifier(SNAPSHOT), pairs)
    assert report.orders == ("given", "reversed", "shuffled")
    assert (report.segments, report.stable, report.unstable) == (len(pairs), len(pairs), [])
    assert report.passed


class _OrderDependent:
    """A stand-in for a classifier with hidden state: whatever comes first wins."""

    def __init__(self) -> None:
        self.inner = SegmentClassifier(SNAPSHOT)

    def classify(
        self, items: Sequence[tuple[StoredConversation, Segment]]
    ) -> list[SegmentClassification]:
        results = self.inner.classify(items)
        return [replace(results[0], state=REVIEW_REQUIRED), *results[1:]]


def test_order_dependent_classifier_is_flagged_for_review(world: tuple[Session, Pairs]) -> None:
    _, pairs = world
    report = order_experiment(_OrderDependent(), pairs)
    assert report.stable < report.segments
    assert report.unstable and all(item.review_required for item in report.unstable)
    assert set(report.unstable[0].by_order) == {"given", "reversed", "shuffled"}
    assert report.passed  # differences became review items, none were hidden
