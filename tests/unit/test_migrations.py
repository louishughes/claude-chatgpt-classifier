"""FND-004 acceptance: upgrade an empty database twice and verify the schema."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import Engine, inspect

from knowledge_engine.infrastructure import jobs, migrations, workspace  # noqa: F401  (registers tables)
from knowledge_engine.infrastructure.db import Base, SessionFactory, create_sqlite_engine
from knowledge_engine.infrastructure.migrations import (
    current_revision,
    downgrade_to,
    head_revision,
    upgrade_to_head,
)
from knowledge_engine.infrastructure.workspace import WorkspaceRepo


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[Engine]:
    db_engine = create_sqlite_engine(tmp_path / "migrate.db")
    yield db_engine
    db_engine.dispose()


def _tables(engine: Engine) -> set[str]:
    return set(inspect(engine).get_table_names()) - {"alembic_version"}


def test_there_is_exactly_one_head_and_it_is_the_newest_file() -> None:
    # head_revision() itself raises if the scripts branch into two heads.
    versions = Path(migrations.__file__).parent / "versions"
    newest = max(p.stem for p in versions.glob("[0-9][0-9][0-9][0-9]_*.py"))
    assert head_revision() == newest


def test_upgrade_empty_database_twice(engine: Engine) -> None:
    assert current_revision(engine) is None
    upgrade_to_head(engine)
    assert current_revision(engine) == head_revision()
    first = _tables(engine)
    upgrade_to_head(engine)  # second run must be a no-op, not an error
    assert current_revision(engine) == head_revision()
    assert _tables(engine) == first == set(Base.metadata.tables)


def test_migrated_schema_matches_table_definitions(engine: Engine) -> None:
    # If someone changes a table class without writing a migration, this fails.
    upgrade_to_head(engine)
    with engine.connect() as connection:
        diff = compare_metadata(MigrationContext.configure(connection), Base.metadata)
    assert diff == []


def test_constraints_and_names_exist_after_upgrade(engine: Engine) -> None:
    upgrade_to_head(engine)
    inspector = inspect(engine)
    assert inspector.get_pk_constraint("workspaces")["constrained_columns"] == ["workspace_id"]
    uniques = inspector.get_unique_constraints("workspaces")
    assert [(u["name"], u["column_names"]) for u in uniques] == [("uq_workspaces_name", ["name"])]


def test_downgrade_to_base_and_upgrade_again(engine: Engine) -> None:
    upgrade_to_head(engine)
    downgrade_to(engine, "base")
    assert _tables(engine) == set()
    assert current_revision(engine) is None
    upgrade_to_head(engine)
    assert _tables(engine) == set(Base.metadata.tables)


def test_migrated_database_works_with_the_repository(engine: Engine) -> None:
    upgrade_to_head(engine)
    factory = SessionFactory(engine)
    with factory.transaction() as session:
        workspace_id = WorkspaceRepo(session).get_or_create("fixture").workspace_id
    with factory.transaction(write=False) as session:
        row = WorkspaceRepo(session).get(workspace_id)
        assert row is not None and row.name == "fixture"


def test_upgrade_keeps_existing_rows(engine: Engine) -> None:
    upgrade_to_head(engine)
    factory = SessionFactory(engine)
    with factory.transaction() as session:
        WorkspaceRepo(session).get_or_create("kept")
    upgrade_to_head(engine)
    with factory.transaction(write=False) as session:
        assert WorkspaceRepo(session).get_by_name("kept") is not None
