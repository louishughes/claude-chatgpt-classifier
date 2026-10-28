"""TAX-006: discovery only ever files proposals; nothing is approved without review."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from knowledge_engine.infrastructure.db import create_sqlite_engine
from knowledge_engine.infrastructure.migrations import upgrade_to_head
from knowledge_engine.segmentation.inventory import SegmentText
from knowledge_engine.taxonomy.discovery import (
    BackendUnavailable,
    BertopicBackend,
    TfidfBackend,
    discover,
)
from knowledge_engine.taxonomy.registry import (
    Dimension,
    TaxonomyRegistry,
    TaxonomyTermRow,
    TermStatus,
)
from knowledge_engine.taxonomy.review import approve, proposals

TEXTS = [
    "Synthetic: the sourdough starter needs flour and warm water.",
    "Synthetic: my sourdough loaf came out flat, the starter was weak.",
    "Synthetic: sourdough hydration and starter feeding times.",
    "Synthetic: the beehive frames need checking for the queen.",
    "Synthetic: moving a beehive in winter and keeping the queen warm.",
    "Synthetic: a lone note about kayaks.",
]


@pytest.fixture
def session(tmp_path: Path) -> Iterator[Session]:
    engine = create_sqlite_engine(tmp_path / "k.db")
    upgrade_to_head(engine)
    with Session(engine) as db:
        yield db
    engine.dispose()


def _items() -> list[SegmentText]:
    return [SegmentText(f"seg_{i}", f"conv_{i}", "active", 2, t) for i, t in enumerate(TEXTS)]


def test_tfidf_backend_is_deterministic() -> None:
    first = TfidfBackend().cluster(_items())
    assert first == TfidfBackend().cluster(_items())
    groups = {c.label_words[0]: c.members for c in first}
    assert groups["sourdough"] == (0, 1, 2)
    assert groups["beehive"] == (3, 4)


def test_discovery_never_writes_approved_terms_without_review(session: Session) -> None:
    report = discover(session, _items())
    assert len(report.proposed) == 2
    assert report.too_small == 1  # the lone kayak segment
    assert session.query(TaxonomyTermRow).count() == 0
    registry = TaxonomyRegistry(session)
    assert registry.publish("tax-1", author="test").terms == ()
    waiting = proposals(session)
    assert {json.loads(p.payload_json)["label"] for p in waiting} == {"Sourdough", "Beehive"}
    evidence = json.loads(waiting[0].evidence_json)
    assert evidence["backend"] == "tfidf" and evidence["size"] >= 2
    assert all(p.proposer == "discovery" for p in waiting)
    # Only after a different reviewer approves does a term exist.
    approve(session, report.proposed[0], reviewer="reviewer-a")
    assert len(registry.publish("tax-2", author="test").terms) == 1


def test_rerun_does_not_repeat_and_known_terms_are_skipped(session: Session) -> None:
    TaxonomyRegistry(session).add_term(Dimension.TOPIC, "Beehive", status=TermStatus.APPROVED)
    first = discover(session, _items())
    again = discover(session, _items())
    assert (first.known, len(first.proposed)) == (["Beehive"], 1)
    assert (again.proposed, again.waiting) == ([], ["Sourdough"])


def test_optional_backend_reports_when_missing() -> None:
    try:
        BertopicBackend()
    except BackendUnavailable as error:
        assert "bertopic" in str(error)
