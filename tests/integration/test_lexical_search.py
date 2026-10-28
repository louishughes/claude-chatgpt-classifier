"""RET-001: the search_terms fixture's queries find exactly the expected messages."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from knowledge_engine.cli.main import main
from knowledge_engine.importer import import_source
from knowledge_engine.importer.records import ConversationRow
from knowledge_engine.infrastructure.db import create_sqlite_engine, database_path
from knowledge_engine.retrieval.lexical import (
    LexicalIndex,
    SearchMode,
    search_index_path,
    sync_index,
)
from knowledge_engine.settings import Settings

CASE = Path(__file__).resolve().parents[1] / "fixtures" / "chatgpt" / "search_terms"
QUERIES: list[list[Any]] = json.loads((CASE / "manifest.json").read_text(encoding="utf-8"))[
    "expected"
]["queries"]


@pytest.fixture(scope="module")
def imported(tmp_path_factory: pytest.TempPathFactory) -> Iterator[tuple[Settings, str]]:
    settings = Settings(workspace_root=tmp_path_factory.mktemp("ws"))
    report = import_source(CASE / "export", "fixture", settings=settings)
    assert report.search_indexed > 0
    engine = create_sqlite_engine(database_path(settings))
    try:
        with Session(engine) as session:
            workspace = session.scalars(select(ConversationRow.workspace_id)).first()
            assert workspace is not None
            yield settings, workspace
    finally:
        engine.dispose()


@pytest.mark.parametrize(("query", "mode", "expected"), QUERIES)
def test_fixture_queries(
    imported: tuple[Settings, str], query: str, mode: str, expected: list[str]
) -> None:
    settings, workspace = imported
    with LexicalIndex(search_index_path(settings)) as index:
        hits = index.search(query, workspace_id=workspace, mode=SearchMode(mode), limit=50)
    assert sorted(hit.native_node_id for hit in hits) == expected


def test_hits_point_back_to_their_revision_and_mark_the_match(
    imported: tuple[Settings, str],
) -> None:
    settings, workspace = imported
    with LexicalIndex(search_index_path(settings)) as index:
        [hit] = index.search("KubeCtl", workspace_id=workspace, mode=SearchMode.EXACT)
        assert hit.revision_id.startswith("rev_") and hit.node_key.startswith("node_")
        assert "[KubeCtl]" in hit.snippet
        # Scope: another workspace sees nothing, and so does another chat.
        assert index.search("kubectl", workspace_id="ws_other") == []
        assert index.search("kubectl", workspace_id=workspace, conversation_id=hit.conversation_id)


def test_index_is_a_rebuildable_cache(imported: tuple[Settings, str], tmp_path: Path) -> None:
    settings, workspace = imported
    copy = Settings(workspace_root=tmp_path)
    engine = create_sqlite_engine(database_path(settings))
    try:
        with Session(engine) as session:
            with LexicalIndex(search_index_path(copy)) as fresh:
                first = sync_index(session, fresh)
                assert first > 0
                assert sync_index(session, fresh) == 0  # up to date: nothing re-added
                assert fresh.search("SYN-CODE-4471", workspace_id=workspace)
            # A file from another index version is dropped and rebuilt, not half-used.
            with sqlite3.connect(search_index_path(copy)) as raw:
                raw.execute("UPDATE meta SET value = 'old' WHERE key = 'version'")
            with LexicalIndex(search_index_path(copy)) as rebuilt:
                assert rebuilt.indexed() == set()
                assert sync_index(session, rebuilt) == first
    finally:
        engine.dispose()


def test_identical_reimport_indexes_nothing(imported: tuple[Settings, str]) -> None:
    settings, _ = imported
    again = import_source(CASE / "export", "fixture", settings=settings)
    assert again.search_indexed == 0


def test_cli_search(
    imported: tuple[Settings, str],
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings, _ = imported
    monkeypatch.setenv("KE_WORKSPACE_ROOT", str(settings.workspace_root))
    assert main(["--json", "search", "synthetic blue widget", "--mode", "phrase"]) == 0
    data = json.loads(capsys.readouterr().out)["data"]
    assert [h["native_node_id"] for h in data["hits"]] == [
        "c0000009-0000-4000-8000-000000000001-a1"
    ]
    assert main(["--json", "search", "synthetic", "--limit", "3"]) == 0
    assert len(json.loads(capsys.readouterr().out)["data"]["hits"]) == 3
