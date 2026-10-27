"""Slice I2: ``import_source`` and the guarantee that re-importing adds nothing.

This file owns the M1 promise "importing the same export again adds
nothing and costs nothing" (M1_CONSOLIDATION §4). It talks to the importer
only through ``import_source``.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from sqlalchemy import func, select, text

from knowledge_engine.domain.enums import ImportBatchStatus
from knowledge_engine.importer import ImportReport, import_source
from knowledge_engine.infrastructure.db import Base, create_sqlite_engine, database_path
from knowledge_engine.ingestion.inventory import tree_signature
from knowledge_engine.ingestion.source import UnsupportedFormatError
from knowledge_engine.settings import Settings, load_settings

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "chatgpt"
# Tables that record *attempts*, which are allowed to grow on every run.
LEDGER_TABLES = {"import_batches", "import_batch_files"}


def _settings(tmp_path: Path, name: str = "ws") -> Settings:
    return load_settings(workspace_root=tmp_path / name)


def _counts(settings: Settings) -> dict[str, int]:
    """Row count of every table the models define (new tables join automatically)."""
    engine = create_sqlite_engine(database_path(settings))
    try:
        with engine.connect() as conn:
            return {
                table.name: int(conn.scalar(select(func.count()).select_from(table)) or 0)
                for table in Base.metadata.sorted_tables
            }
    finally:
        engine.dispose()


def _root(case: str) -> Path:
    export = FIXTURES / case / "export"
    zips = list(export.glob("*.zip"))
    return zips[0] if zips else export


def test_identical_reimport_adds_nothing(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    root = _root("reexport_v1")
    raw_before = tree_signature(root)

    first = import_source(root, "fixture", settings=settings)
    after_first = _counts(settings)
    second = import_source(root, "fixture", settings=settings)
    after_second = _counts(settings)

    assert first.status is ImportBatchStatus.SUCCEEDED
    assert first.conversations == {"new": 4}
    assert first.messages == {"new": 12}
    assert len(first.changed_revisions) == 12

    assert second.status is ImportBatchStatus.SUCCEEDED
    assert second.conversations == {"unchanged": 4}
    assert second.messages == {"unchanged": 12}
    assert second.changed_revisions == ()
    assert second.model_calls_triggered == 0
    assert second.files == {"reused": 1}

    for table, count in after_second.items():
        if table == "import_batches":
            assert count == after_first[table] + 1
        elif table not in LEDGER_TABLES:
            assert count == after_first[table], table
    assert after_second["jobs"] == 0  # nothing downstream was queued

    for report in (first, second):
        assert report.raw_tree_hash_before == report.raw_tree_hash_after == raw_before
    assert tree_signature(root) == raw_before


@pytest.mark.parametrize("case", ["export_single", "export_sharded", "export_zip", "split_wrapper"])
def test_every_layout_imports_the_same_logical_records(tmp_path: Path, case: str) -> None:
    reference = _settings(tmp_path, "reference")
    import_source(_root("export_single"), "fixture", settings=reference)
    settings = _settings(tmp_path, case)

    report = import_source(_root(case), "fixture", settings=settings)

    assert report.conversations == {"new": 3}
    assert report.messages == {"new": 12}
    assert _ids(settings) == _ids(reference)


def _ids(settings: Settings) -> dict[str, set[tuple[str, ...]]]:
    """Logical identities by native keys and hashes.

    Stored IDs also include the workspace's own random ID, so two separate
    workspaces are compared by what the IDs are made from instead.
    """
    engine = create_sqlite_engine(database_path(settings))
    queries = {
        "conversations": "SELECT native_conversation_id FROM conversations",
        "nodes": (
            "SELECT c.native_conversation_id, n.native_node_id FROM message_nodes n "
            "JOIN conversations c USING (conversation_id)"
        ),
        "revisions": (
            "SELECT c.native_conversation_id, n.native_node_id, r.canonical_content_hash "
            "FROM message_revisions r JOIN message_nodes n USING (node_key) "
            "JOIN conversations c USING (conversation_id)"
        ),
        "edges": (
            "SELECT c.native_conversation_id, ch.native_node_id, pa.native_node_id "
            "FROM graph_edges e JOIN message_nodes ch ON ch.node_key = e.child_node_key "
            "JOIN message_nodes pa ON pa.node_key = e.parent_node_key "
            "JOIN conversations c ON c.conversation_id = e.conversation_id"
        ),
    }
    try:
        with engine.connect() as conn:
            return {k: {tuple(row) for row in conn.execute(text(q))} for k, q in queries.items()}
    finally:
        engine.dispose()


def test_split_warnings_reach_the_report(tmp_path: Path) -> None:
    report = import_source(_root("split_wrapper"), "fixture", settings=_settings(tmp_path))

    assert report.warnings["wrapper_message_count_mismatch"] == 1
    assert report.warnings["non_conversation_file_skipped"] == 1
    assert report.warnings["format_lacks_account_id"] == 1


def test_missing_native_id_is_not_guessed(tmp_path: Path) -> None:
    report = import_source(_root("id_collision"), "fixture", settings=_settings(tmp_path))

    assert report.status is ImportBatchStatus.PARTIAL
    assert report.warnings["missing_native_id"] == 1
    assert report.conversations["failed"] == 1


def test_account_namespace_keeps_accounts_apart(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    import_source(_root("export_single"), "account-a", settings=settings)
    second = import_source(_root("export_single"), "account-b", settings=settings)

    assert second.conversations == {"new": 3}
    assert _counts(settings)["conversations"] == 6


def test_crashed_import_is_abandoned_and_rerun_converges(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import knowledge_engine.importer.run as run_module
    from knowledge_engine.importer import delta

    settings = load_settings(
        workspace_root=tmp_path / "ws", limits={"max_conversations_per_batch": 2}
    )
    root = _root("reexport_v1")
    real = delta.apply_conversation
    calls: list[int] = []

    def crash_on_third(*args: object, **kwargs: object) -> object:
        calls.append(1)
        if len(calls) == 3:
            raise KeyboardInterrupt("simulated crash")
        return real(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(run_module, "apply_conversation", crash_on_third)
    with pytest.raises(KeyboardInterrupt):
        import_source(root, "fixture", settings=settings)
    monkeypatch.setattr(run_module, "apply_conversation", real)

    # The first group of 2 committed; the crashed group rolled back.
    assert _counts(settings)["conversations"] == 2
    rerun = import_source(root, "fixture", settings=settings)
    assert rerun.conversations == {"unchanged": 2, "new": 2}

    clean = _settings(tmp_path, "clean")
    import_source(root, "fixture", settings=clean)
    assert _ids(settings) == _ids(clean)

    engine = create_sqlite_engine(database_path(settings))
    with engine.connect() as conn:
        statuses = sorted(r[0] for r in conn.execute(text("SELECT status FROM import_batches")))
    engine.dispose()
    assert statuses == ["abandoned", "succeeded"]


def test_unknown_source_is_refused_before_writing(tmp_path: Path) -> None:
    (tmp_path / "raw").mkdir()
    (tmp_path / "raw" / "notes.txt").write_text("x")
    settings = _settings(tmp_path)

    with pytest.raises(UnsupportedFormatError):
        import_source(tmp_path / "raw", "fixture", settings=settings)
    assert not database_path(settings).exists()


def test_report_is_free_of_private_text(tmp_path: Path) -> None:
    copy = Path(shutil.copytree(_root("split_wrapper"), tmp_path / "private-titles"))
    report: ImportReport = import_source(copy, "fixture", settings=_settings(tmp_path))

    dumped = str(report.to_dict()) + str(report.warnings)
    assert "synthetic" not in dumped.lower()
    assert "private-titles" not in dumped
