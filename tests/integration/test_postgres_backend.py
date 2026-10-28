"""PROD-001: the same import fixtures give the same archive on SQLite and PostgreSQL.

Each fixture is imported twice, into a SQLite workspace and into a fresh
PostgreSQL database, and the results are compared: the import reports,
every table's row count, the stored messages, and word-search results.
IDs that include the random workspace ID differ by design, so the
comparison uses the export's own IDs and content hashes.

The PostgreSQL server is a private one started in a temporary folder; the
tests skip where PostgreSQL isn't installed or the run is as root.
"""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from sqlalchemy import Engine, func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from knowledge_engine.devtools.postgres import PostgresUnavailable, new_database, temporary_server
from knowledge_engine.importer.records import ConversationRow, MessageNodeRow, MessageRevisionRow
from knowledge_engine.importer.run import run_import
from knowledge_engine.infrastructure.db import create_sqlite_engine, database_path
from knowledge_engine.infrastructure.dialects import create_postgres_engine, trigger_ddl
from knowledge_engine.infrastructure.migrations import (
    current_revision,
    head_revision,
    upgrade_to_head,
)
from knowledge_engine.infrastructure.migrations.tables import all_tables
from knowledge_engine.infrastructure.workspace import WorkspaceRow
from knowledge_engine.retrieval.lexical import LexicalIndex, SearchMode, search_index_path
from knowledge_engine.settings import Settings

CHATGPT = Path(__file__).resolve().parents[1] / "fixtures" / "chatgpt"
CASES = [
    "export_single",
    "export_zip",
    "export_sharded",
    "split_wrapper",
    "branches_edit",
    "branches_regen",
    "repeated_image",
    "asset_problems",
    "id_collision",
    "copied_prefix",
    "no_children",
    "metadata_drift",
]
# Keys of the report that name this run rather than describe the archive.
_RUN_KEYS = {"import_id", "started_at", "finished_at"}


@pytest.fixture(scope="module")
def server() -> Iterator[str]:
    try:
        with temporary_server() as url:
            yield url
    except PostgresUnavailable as reason:
        pytest.skip(str(reason))


def _source(case: str, tmp_path: Path) -> Path:
    export = CHATGPT / case / "export"
    zips = list(export.glob("*.zip"))
    target = tmp_path / f"in-{case}"
    if zips:
        target.mkdir()
        shutil.copy2(zips[0], target / zips[0].name)
        return target / zips[0].name
    shutil.copytree(export, target)
    return target


def _import(
    sources: list[Path], workspace: Path, url: str | None
) -> tuple[list[dict[str, Any]], Engine]:
    settings = Settings(workspace_root=workspace)
    reports = []
    for source in sources:
        report = run_import(source, "acct", format_id=None, settings=settings, database_url=url)
        reports.append({k: v for k, v in report.to_dict().items() if k not in _RUN_KEYS})
    engine = create_postgres_engine(url) if url else create_sqlite_engine(database_path(settings))
    return reports, engine


def _archive(engine: Engine, workspace: Path) -> dict[str, Any]:
    """What was stored, in terms that don't depend on the backend."""
    with Session(engine) as session:
        counts = {
            table.name: session.scalar(select(func.count()).select_from(table))
            for table in all_tables().sorted_tables
        }
        conversations = sorted(
            session.execute(
                select(
                    ConversationRow.native_conversation_id,
                    ConversationRow.presence,
                    ConversationRow.title,
                )
            ).tuples()
        )
        messages = sorted(
            session.execute(
                select(
                    MessageNodeRow.native_node_id,
                    MessageRevisionRow.canonical_content_hash,
                    MessageRevisionRow.role,
                ).join(MessageRevisionRow, MessageRevisionRow.node_key == MessageNodeRow.node_key)
            ).tuples()
        )
        workspace_id = session.scalars(select(WorkspaceRow.workspace_id)).one()
    with LexicalIndex(search_index_path(Settings(workspace_root=workspace))) as index:
        found = {
            word: sorted(
                hit.native_node_id
                for hit in index.search(word, workspace_id=workspace_id, mode=SearchMode.TOKENS)
            )
            for word in ("synthetic", "image", "the")
        }
    return {"counts": counts, "conversations": conversations, "messages": messages, "search": found}


@pytest.mark.parametrize("case", CASES)
def test_the_same_fixture_gives_the_same_archive(case: str, server: str, tmp_path: Path) -> None:
    source = _source(case, tmp_path)
    lite_reports, lite = _import([source, source], tmp_path / "lite", None)
    pg_reports, pg = _import([source, source], tmp_path / "pg", new_database(server))
    try:
        assert pg_reports == lite_reports
        assert _archive(pg, tmp_path / "pg") == _archive(lite, tmp_path / "lite")
    finally:
        lite.dispose()
        pg.dispose()


def test_a_re_export_updates_the_same_way(server: str, tmp_path: Path) -> None:
    sources = [_source("reexport_v1", tmp_path), _source("reexport_v2", tmp_path)]
    lite_reports, lite = _import(sources, tmp_path / "lite", None)
    pg_reports, pg = _import(sources, tmp_path / "pg", new_database(server))
    try:
        assert pg_reports == lite_reports
        assert pg_reports[1]["conversations"] != pg_reports[0]["conversations"]
        assert _archive(pg, tmp_path / "pg") == _archive(lite, tmp_path / "lite")
    finally:
        lite.dispose()
        pg.dispose()


def test_migrations_match_the_tables_and_downgrade(server: str) -> None:
    engine = create_postgres_engine(new_database(server))
    try:
        upgrade_to_head(engine)
        assert current_revision(engine) == head_revision()
        with engine.connect() as connection:
            drift = compare_metadata(MigrationContext.configure(connection), all_tables())
        assert drift == []
        from knowledge_engine.infrastructure.migrations import downgrade_to

        downgrade_to(engine, "base")
        assert current_revision(engine) is None
        upgrade_to_head(engine)
        assert current_revision(engine) == head_revision()
    finally:
        engine.dispose()


def test_audit_tables_refuse_changes_on_postgres(server: str) -> None:
    engine = create_postgres_engine(new_database(server))
    try:
        upgrade_to_head(engine)
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO purge_events (purge_id, actor, reason, plan_sha256, status, "
                    "counts_json, verification_json, created_at) VALUES ('p1', 'a', 'r', "
                    "'0', 'done', '{}', '{}', now())"
                )
            )
        with pytest.raises(DBAPIError, match="purge_events is an audit log"):
            with engine.begin() as connection:
                connection.execute(text("DELETE FROM purge_events"))
    finally:
        engine.dispose()


def test_trigger_translation_refuses_unknown_shapes() -> None:
    sqlite = ["CREATE TRIGGER IF NOT EXISTS t BEFORE UPDATE ON x BEGIN SELECT 1; END"]
    assert trigger_ddl(sqlite, "sqlite") == sqlite
    with pytest.raises(ValueError, match="can't translate"):
        trigger_ddl(sqlite, "postgresql")
    with pytest.raises(ValueError, match="no trigger translation"):
        trigger_ddl([], "mysql")
