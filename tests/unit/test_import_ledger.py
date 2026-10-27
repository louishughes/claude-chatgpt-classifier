"""IMP-001 (slice I1): import batches and source snapshots."""

from __future__ import annotations

import json
import stat
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import func, select

from knowledge_engine.domain.enums import ImportBatchStatus, InvalidTransitionError
from knowledge_engine.domain.ids import snapshot_id
from knowledge_engine.importer.archive import BlobCorruptError, BlobStore
from knowledge_engine.importer.ledger import (
    ImportBatchFileRow,
    ImportBatchRow,
    ImportLedger,
    SourceSnapshotRow,
    root_fingerprint,
    stored_blob,
)
from knowledge_engine.infrastructure.db import SessionFactory, create_sqlite_engine
from knowledge_engine.infrastructure.migrations import upgrade_to_head
from knowledge_engine.infrastructure.workspace import WorkspaceRepo

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "chatgpt" / "export_sharded" / "export"
VERSIONS = {"code": "0.0.1", "parser": "chatgpt-export-v1"}


@pytest.fixture
def factory(tmp_path: Path) -> Iterator[SessionFactory]:
    engine = create_sqlite_engine(tmp_path / "ws" / "knowledge.db")
    upgrade_to_head(engine)
    sessions = SessionFactory(engine)
    yield sessions
    sessions.dispose()


@pytest.fixture
def archive(tmp_path: Path) -> BlobStore:
    return BlobStore(tmp_path / "ws" / "archive")


def _import_once(factory: SessionFactory, archive: BlobStore, root: Path) -> str:
    """Record every JSON file under root as one succeeded batch."""
    with factory.transaction() as session:
        workspace = WorkspaceRepo(session).get_or_create("default")
        ledger = ImportLedger(session, archive)
        batch = ledger.start(
            workspace_id=workspace.workspace_id,
            account_namespace="fixture",
            root=root,
            format_id="chatgpt-export-v1",
            versions=VERSIONS,
            tree_hash="0" * 64,
        )
        for path in sorted(root.glob("*.json")):
            ledger.record_file(batch, path.name, path=path)
        ledger.finish(
            batch, ImportBatchStatus.SUCCEEDED, counts={"files": 2}, warnings={}, tree_hash="0" * 64
        )
        return batch.import_id


def _count(factory: SessionFactory, table: type) -> int:
    with factory.transaction(write=False) as session:
        return int(session.scalar(select(func.count()).select_from(table)) or 0)


def test_same_input_twice_gives_two_batches_and_one_snapshot_per_file(
    factory: SessionFactory, archive: BlobStore
) -> None:
    first = _import_once(factory, archive, FIXTURE)
    second = _import_once(factory, archive, FIXTURE)

    assert first != second
    assert _count(factory, ImportBatchRow) == 2
    assert _count(factory, SourceSnapshotRow) == 2  # two shard files
    assert _count(factory, ImportBatchFileRow) == 4
    blobs = [p for p in archive.root.rglob("*") if p.is_file()]
    assert len(blobs) == 2


def test_snapshot_ids_come_from_content(factory: SessionFactory, archive: BlobStore) -> None:
    _import_once(factory, archive, FIXTURE)
    with factory.transaction(write=False) as session:
        rows = session.scalars(select(SourceSnapshotRow)).all()
        for row in rows:
            assert row.snapshot_id == snapshot_id(row.sha256)
            assert row.storage_mode == "copy"
            assert archive.read_bytes(stored_blob(row))


def test_corrupted_archive_copy_is_rejected(factory: SessionFactory, archive: BlobStore) -> None:
    _import_once(factory, archive, FIXTURE)
    with factory.transaction(write=False) as session:
        row = session.scalars(select(SourceSnapshotRow)).first()
        assert row is not None
        stored = Path(row.storage_ref)
    stored.chmod(stat.S_IREAD | stat.S_IWRITE)
    stored.write_bytes(b"tampered")

    with pytest.raises(BlobCorruptError):
        _import_once(factory, archive, FIXTURE)
    # The failed attempt rolled back: no third batch row, evidence untouched.
    assert _count(factory, ImportBatchRow) == 1
    assert stored.read_bytes() == b"tampered"


def test_interrupted_batch_is_abandoned_never_succeeded(
    factory: SessionFactory, archive: BlobStore
) -> None:
    with factory.transaction() as session:
        workspace = WorkspaceRepo(session).get_or_create("default")
        crashed = ImportLedger(session, archive).start(
            workspace_id=workspace.workspace_id,
            account_namespace="fixture",
            root=FIXTURE,
            format_id="chatgpt-export-v1",
            versions=VERSIONS,
            tree_hash="0" * 64,
        )
        crashed_id = crashed.import_id
    # The process "died" here: the batch was committed as running.

    _import_once(factory, archive, FIXTURE)

    with factory.transaction(write=False) as session:
        old = session.get(ImportBatchRow, crashed_id)
        assert old is not None
        assert old.status == ImportBatchStatus.ABANDONED.value
        assert old.finished_at is not None
        latest = ImportLedger(session, archive).latest()
        assert latest is not None and latest.status == ImportBatchStatus.SUCCEEDED.value


def test_finished_batch_cannot_change(factory: SessionFactory, archive: BlobStore) -> None:
    import_id = _import_once(factory, archive, FIXTURE)
    with factory.transaction() as session:
        batch = session.get(ImportBatchRow, import_id)
        assert batch is not None
        ledger = ImportLedger(session, archive)
        with pytest.raises(InvalidTransitionError):
            ledger.finish(batch, ImportBatchStatus.FAILED, counts={}, warnings={}, tree_hash="")


def test_batch_row_stores_fingerprints_not_paths(
    factory: SessionFactory, archive: BlobStore
) -> None:
    import_id = _import_once(factory, archive, FIXTURE)
    with factory.transaction(write=False) as session:
        batch = session.get(ImportBatchRow, import_id)
        assert batch is not None
        assert batch.root_fingerprint == root_fingerprint(FIXTURE)
        row_text = json.dumps([batch.root_fingerprint, batch.versions_json, batch.counts_json])
        assert str(FIXTURE) not in row_text
        assert json.loads(batch.versions_json) == VERSIONS


def test_bytes_and_reference_modes(
    factory: SessionFactory, archive: BlobStore, tmp_path: Path
) -> None:
    media = tmp_path / "raw" / "images" / "pic.png"
    media.parent.mkdir(parents=True)
    media.write_bytes(b"\x89PNG\r\n\x1a\nfake")
    with factory.transaction() as session:
        workspace = WorkspaceRepo(session).get_or_create("default")
        ledger = ImportLedger(session, archive)
        batch = ledger.start(
            workspace_id=workspace.workspace_id,
            account_namespace="fixture",
            root=tmp_path / "raw",
            format_id="chatgpt-export-v1",
            versions=VERSIONS,
            tree_hash="0" * 64,
        )
        member, created = ledger.record_file(batch, "conversations.json", data=b"[]")
        again, created_again = ledger.record_file(batch, "copy/conversations.json", data=b"[]")
        ref, _ = ledger.record_file(batch, "images/pic.png", path=media, mode="reference")
        assert created and not created_again and again.snapshot_id == member.snapshot_id
        assert ref.storage_mode == "reference" and Path(ref.storage_ref) == media
        with pytest.raises(ValueError):
            ledger.record_file(batch, "x", data=b"1", path=media)
        with pytest.raises(ValueError):
            ledger.record_file(batch, "x", data=b"1", mode="reference")
