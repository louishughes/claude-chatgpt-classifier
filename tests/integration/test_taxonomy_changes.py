"""TAX-007: a version diff invalidates only the outputs that cite a changed ID."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from knowledge_engine.infrastructure.db import create_sqlite_engine
from knowledge_engine.infrastructure.migrations import upgrade_to_head
from knowledge_engine.taxonomy.changes import (
    StageInvalidationRow,
    TaxonomyChangeRow,
    diff_snapshots,
    invalidate,
    invalidated,
    record_diff,
)
from knowledge_engine.taxonomy.registry import Dimension, TaxonomyRegistry, TermStatus
from knowledge_engine.taxonomy.review import Operation, approve, propose

APPROVED = TermStatus.APPROVED


@pytest.fixture
def session(tmp_path: Path) -> Iterator[Session]:
    engine = create_sqlite_engine(tmp_path / "k.db")
    upgrade_to_head(engine)
    with Session(engine) as db:
        yield db
    engine.dispose()


def test_unrelated_project_classifications_untouched_by_alias_update(session: Session) -> None:
    registry = TaxonomyRegistry(session)
    garden = registry.add_project("Garden app", status=APPROVED).project_id
    engine_project = registry.add_project("Knowledge Engine", status=APPROVED).project_id
    topic = registry.add_term(Dimension.TOPIC, "Python", status=APPROVED).term_id
    old = registry.publish("tax-1", author="test")
    alias = propose(session, Operation.ALIAS, {"target_id": garden, "alias": "GA"}, proposer="p")
    approve(session, alias.proposal_id, reviewer="r")
    new = registry.publish("tax-2", author="test")

    diff = diff_snapshots(old, new)
    assert diff.changed == {garden: ("aliases",)}
    assert (diff.added, diff.removed) == (frozenset(), frozenset())
    outputs = {
        "stg_garden_chat": [garden, topic],
        "stg_engine_chat": [engine_project, topic],
        "stg_topic_only": [topic],
    }
    assert invalidate(session, diff, outputs) == ["stg_garden_chat"]
    assert invalidated(session, "stg_garden_chat")
    assert not invalidated(session, "stg_engine_chat")
    assert not invalidated(session, "stg_topic_only")
    # Running it again doesn't add a second row.
    invalidate(session, diff, outputs)
    assert session.query(StageInvalidationRow).count() == 1


def test_merge_retire_and_rename_are_all_seen(session: Session) -> None:
    registry = TaxonomyRegistry(session)
    keep = registry.add_term(Dimension.TOPIC, "Unreal Engine", status=APPROVED).term_id
    dupe = registry.add_term(Dimension.TOPIC, "UE5", status=APPROVED).term_id
    old_term = registry.add_term(Dimension.TOPIC, "Flash", status=APPROVED).term_id
    other = registry.add_term(Dimension.TOPIC, "Godot", status=APPROVED).term_id
    old = registry.publish("tax-1", author="test")
    for operation, payload in [
        (Operation.MERGE, {"source_id": dupe, "target_id": keep}),
        (Operation.RETIRE, {"target_id": old_term}),
    ]:
        approve(
            session, propose(session, operation, payload, proposer="p").proposal_id, reviewer="r"
        )
    added = propose(session, Operation.ADD, {"dimension": "topic", "label": "Unity"}, proposer="p")
    new_id = approve(session, added.proposal_id, reviewer="r").result_id
    new = registry.publish("tax-2", author="test")

    diff = diff_snapshots(old, new)
    assert diff.removed == {dupe, old_term}
    assert diff.added == {new_id}
    assert diff.changed == {keep: ("aliases",)}
    assert other not in diff.touched
    row = record_diff(session, diff)
    assert record_diff(session, diff) is row
    assert session.query(TaxonomyChangeRow).count() == 1


def test_identical_versions_have_an_empty_diff(session: Session) -> None:
    registry = TaxonomyRegistry(session)
    registry.add_term(Dimension.TOPIC, "Python", status=APPROVED)
    diff = diff_snapshots(
        registry.publish("tax-1", author="t"), registry.publish("tax-2", author="t")
    )
    assert diff.empty
    assert invalidate(session, diff, {"stg_x": ["anything"]}) == []
