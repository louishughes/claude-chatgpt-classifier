"""TAX-001/002: stable IDs, unique aliases, immutable approved-only snapshots."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from knowledge_engine.infrastructure.db import create_sqlite_engine
from knowledge_engine.infrastructure.migrations import upgrade_to_head
from knowledge_engine.taxonomy.registry import (
    Dimension,
    TaxonomyRegistry,
    TaxonomyTermRow,
    TaxonomyVersionRow,
    TermStatus,
    UnknownTermError,
    normalise_alias,
)

APPROVED = TermStatus.APPROVED


@pytest.fixture
def session(tmp_path: Path) -> Iterator[Session]:
    engine = create_sqlite_engine(tmp_path / "k.db")
    upgrade_to_head(engine)
    with Session(engine) as db:
        yield db
    engine.dispose()


def test_alias_normal_form() -> None:
    assert normalise_alias("Unreal  Engine-5") == "unreal engine 5"
    assert normalise_alias("Café_Ops!") == "cafe ops"
    assert normalise_alias("UE5") == "ue5"


def test_aliases_are_unique_per_dimension(session: Session) -> None:
    registry = TaxonomyRegistry(session)
    games = registry.add_term(Dimension.DOMAIN, "Game development", status=APPROVED)
    registry.add_alias(games, "gamedev")
    # The same spelling in another dimension is fine...
    registry.add_term(Dimension.TOPIC, "Gamedev", status=APPROVED)
    session.commit()
    # ...but not twice in one dimension, however it's written.
    with pytest.raises(IntegrityError):
        registry.add_alias(registry.add_term(Dimension.DOMAIN, "Games"), "GAME-development")
    session.rollback()


def test_project_aliases_are_unique(session: Session) -> None:
    registry = TaxonomyRegistry(session)
    registry.add_project("Knowledge Engine", aliases=["KE"], status=APPROVED)
    session.commit()
    with pytest.raises(IntegrityError):
        registry.add_project("ke")
    session.rollback()


def test_two_levels_at_most(session: Session) -> None:
    registry = TaxonomyRegistry(session)
    top = registry.add_term(Dimension.DOMAIN, "Software", status=APPROVED)
    child = registry.add_term(Dimension.DOMAIN, "Python", parent_id=top.term_id, status=APPROVED)
    with pytest.raises(ValueError, match="two levels"):
        registry.add_term(Dimension.DOMAIN, "Packaging", parent_id=child.term_id)
    with pytest.raises(ValueError, match="same dimension"):
        registry.add_term(Dimension.TOPIC, "Wheels", parent_id=top.term_id)


def test_ids_do_not_depend_on_labels(session: Session) -> None:
    registry = TaxonomyRegistry(session)
    a = registry.add_term(Dimension.TOPIC, "Unreal", status=APPROVED)
    term_id = a.term_id
    a.label = "Unreal Engine"  # a rename keeps the ID
    session.flush()
    assert session.get(TaxonomyTermRow, term_id) is a
    assert term_id.startswith("term_") and "unreal" not in term_id


def test_snapshot_holds_approved_terms_only_and_never_changes(session: Session) -> None:
    registry = TaxonomyRegistry(session)
    work = registry.add_term(Dimension.DOMAIN, "Work", status=APPROVED)
    proposed = registry.add_term(Dimension.DOMAIN, "Hobbies")  # proposed
    retired = registry.add_term(Dimension.DOMAIN, "Old", status=TermStatus.RETIRED)
    registry.add_project("Knowledge Engine", aliases=["KE"], status=APPROVED)
    registry.add_project("Maybe project")
    snapshot = registry.publish("tax-1", author="test")
    session.commit()

    assert snapshot.allowed_ids(Dimension.DOMAIN) == (work.term_id,)
    assert [p.name for p in snapshot.projects] == ["Knowledge Engine"]
    assert snapshot.projects[0].aliases == ("KE", "Knowledge Engine")
    for hidden in (proposed.term_id, retired.term_id):
        with pytest.raises(UnknownTermError):
            snapshot.term(hidden)
    with pytest.raises(UnknownTermError):
        snapshot.validate(Dimension.DOMAIN, [work.term_id, proposed.term_id])
    snapshot.validate(Dimension.DOMAIN, [work.term_id])

    # Approving later changes the live table, not the published version.
    proposed.status = APPROVED.value
    session.flush()
    again = registry.snapshot("tax-1")
    assert again == snapshot
    assert registry.publish("tax-2", author="test").allowed_ids(Dimension.DOMAIN) == tuple(
        sorted((work.term_id, proposed.term_id))
    )
    assert registry.versions() == ["tax-1", "tax-2"]

    with pytest.raises(ValueError, match="immutable"):
        registry.publish("tax-1", author="test")
    with pytest.raises(ValueError, match="look like"):
        registry.publish("Tax One", author="test")
    with pytest.raises(KeyError):
        registry.snapshot("tax-9")


def test_tampered_snapshot_is_refused(session: Session) -> None:
    registry = TaxonomyRegistry(session)
    registry.add_term(Dimension.DOMAIN, "Work", status=APPROVED)
    registry.publish("tax-1", author="test")
    row = session.get(TaxonomyVersionRow, "tax-1")
    assert row is not None
    row.snapshot_json = row.snapshot_json.replace("Work", "Play")
    session.flush()
    with pytest.raises(ValueError, match="fingerprint"):
        registry.snapshot("tax-1")


def test_merged_terms_need_a_target(session: Session) -> None:
    registry = TaxonomyRegistry(session)
    term = registry.add_term(Dimension.TOPIC, "UE")
    term.status = TermStatus.MERGED.value
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()
