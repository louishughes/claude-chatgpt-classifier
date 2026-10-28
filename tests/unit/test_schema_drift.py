"""OPS-005: the migrations build exactly the schema the code defines (every table module)."""

from __future__ import annotations

from pathlib import Path

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext

from knowledge_engine.infrastructure.db import create_sqlite_engine
from knowledge_engine.infrastructure.migrations import upgrade_to_head
from knowledge_engine.infrastructure.migrations.tables import TABLE_MODULES, all_tables


def test_every_table_module_matches_the_migrations(tmp_path: Path) -> None:
    metadata = all_tables()
    engine = create_sqlite_engine(tmp_path / "drift.db")
    try:
        upgrade_to_head(engine)
        with engine.connect() as connection:
            context = MigrationContext.configure(connection, opts={"compare_type": True})
            assert compare_metadata(context, metadata) == []
    finally:
        engine.dispose()


def test_every_module_that_defines_a_table_is_listed() -> None:
    root = Path(__file__).resolve().parents[2] / "src"
    defining = {
        ".".join(path.relative_to(root).with_suffix("").parts)
        for path in (root / "knowledge_engine").rglob("*.py")
        if "migrations" not in path.parts and "__tablename__" in path.read_text(encoding="utf-8")
    }
    assert defining == set(TABLE_MODULES)
