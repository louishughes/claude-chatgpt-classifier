"""The import ledger (IMP-001): every import attempt, and every file it read.

Each run of ``ke import`` becomes one *import batch* row: when it started
and finished, which adapter and code versions ran, the raw folder's
fingerprint before and after, the counts and warnings, and how it ended
(``succeeded``, ``partial``, ``failed`` or ``abandoned``). A batch row is
never deleted or reused, so the history of imports is complete.

Each input file becomes a *source snapshot*, identified by the SHA-256 of
its bytes. If the same bytes arrive again (in the next export, or the same
export imported twice), the existing snapshot is reused after checking that
its stored copy is still intact; a damaged copy stops the import. The link
"this batch read this file at this path" is recorded separately, so two
batches of identical files give two batch rows but one snapshot.

A batch that was still ``running`` when the process died is marked
``abandoned`` by the next import. It is never shown as succeeded.

Talking points:
    - "Every import is a row in a ledger that's never rewritten, so I can
      always say what was imported, when, and with which code."
    - "Identical files are stored once, however many exports they appear in,
      and their stored copy is re-checked every time."
    - "A crashed import is marked abandoned, never mistaken for a success."
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    String,
    Text,
    select,
)
from sqlalchemy.orm import Mapped, Session, mapped_column

from knowledge_engine.domain.enums import ImportBatchStatus, check_transition
from knowledge_engine.domain.ids import snapshot_id
from knowledge_engine.importer.archive import BlobStore, StorageMode, StoredBlob
from knowledge_engine.infrastructure.db import Base


def _utc_now() -> datetime:
    return datetime.now(UTC)


class ImportBatchRow(Base):
    """One import attempt (``import_batches``).

    Attributes:
        import_id: Random permanent ID.
        workspace_id: The workspace imported into.
        account_namespace: The account label of the raw root (OD-03).
        root_fingerprint: SHA-256 of the root's resolved path. The path
            itself is private and is not stored here.
        format_id: The adapter used, e.g. ``chatgpt-split-v1``.
        versions_json: Code and parser versions, as JSON.
        status: An ``ImportBatchStatus`` value.
        tree_hash_before: Raw tree signature before reading.
        tree_hash_after: Raw tree signature after reading (must match).
        counts_json: The report's counts, as JSON.
        warnings_json: Warning codes and counts, as JSON. No private text.
    """

    __tablename__ = "import_batches"
    __table_args__ = (
        CheckConstraint(
            "status IN ('running','succeeded','partial','failed','abandoned')",
            name="status_valid",
        ),
    )

    import_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.workspace_id"))
    account_namespace: Mapped[str] = mapped_column(String(63))
    root_fingerprint: Mapped[str] = mapped_column(String(64))
    format_id: Mapped[str] = mapped_column(String(40))
    versions_json: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    tree_hash_before: Mapped[str] = mapped_column(String(64))
    tree_hash_after: Mapped[str | None] = mapped_column(String(64), default=None)
    counts_json: Mapped[str | None] = mapped_column(Text, default=None)
    warnings_json: Mapped[str | None] = mapped_column(Text, default=None)


class SourceSnapshotRow(Base):
    """One distinct input file, by content (``source_snapshots``).

    Attributes:
        snapshot_id: ``snap_`` ID derived from the SHA-256.
        sha256: The bytes' SHA-256; unique.
        size: Size in bytes.
        storage_mode: ``copy`` (in the archive) or ``reference`` (in place).
        storage_ref: Where the bytes are. Private: never shown in reports.
        first_import_id: The batch that first saw these bytes.
    """

    __tablename__ = "source_snapshots"
    __table_args__ = (
        CheckConstraint("storage_mode IN ('copy','reference')", name="storage_mode_valid"),
    )

    snapshot_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    sha256: Mapped[str] = mapped_column(String(64), unique=True)
    size: Mapped[int] = mapped_column(BigInteger)
    storage_mode: Mapped[str] = mapped_column(String(10))
    storage_ref: Mapped[str] = mapped_column(Text)
    first_import_id: Mapped[str] = mapped_column(ForeignKey("import_batches.import_id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)


class ImportBatchFileRow(Base):
    """Which file, at which relative path, a batch read (``import_batch_files``)."""

    __tablename__ = "import_batch_files"

    import_id: Mapped[str] = mapped_column(ForeignKey("import_batches.import_id"), primary_key=True)
    # Relative to the raw root. Private (file names can be chat titles):
    # stored in the private workspace database, never printed.
    relative_path: Mapped[str] = mapped_column(Text, primary_key=True)
    snapshot_id: Mapped[str] = mapped_column(ForeignKey("source_snapshots.snapshot_id"))


def root_fingerprint(root: Path) -> str:
    """Return a stable, non-reversible fingerprint of a raw root's location.

    Args:
        root: The raw folder or ZIP.

    Returns:
        SHA-256 hex of the resolved path.
    """
    return hashlib.sha256(str(root.resolve()).encode("utf-8")).hexdigest()


class ImportLedger:
    """Records batches and snapshots inside the caller's transaction."""

    def __init__(self, session: Session, archive: BlobStore) -> None:
        """Bind the ledger to a session and an archive store.

        Args:
            session: A write session from ``SessionFactory.transaction()``.
            archive: Where snapshot bytes are kept.
        """
        self._session = session
        self._archive = archive

    def start(
        self,
        *,
        workspace_id: str,
        account_namespace: str,
        root: Path,
        format_id: str,
        versions: dict[str, str],
        tree_hash: str,
    ) -> ImportBatchRow:
        """Open a new batch, first marking any stale ``running`` ones abandoned.

        Call while holding the write lock (a write transaction), so no other
        import can be running at the same time.

        Args:
            workspace_id: Target workspace.
            account_namespace: Raw root's account label.
            root: The raw root (only its fingerprint is stored).
            format_id: The adapter's format ID.
            versions: Code and parser versions.
            tree_hash: Raw tree signature before reading.

        Returns:
            The new batch, status ``running``.
        """
        self.abandon_stale()
        batch = ImportBatchRow(
            import_id=uuid.uuid4().hex,
            workspace_id=workspace_id,
            account_namespace=account_namespace,
            root_fingerprint=root_fingerprint(root),
            format_id=format_id,
            versions_json=json.dumps(versions, sort_keys=True),
            status=ImportBatchStatus.RUNNING.value,
            tree_hash_before=tree_hash,
        )
        self._session.add(batch)
        self._session.flush()
        return batch

    def abandon_stale(self) -> int:
        """Mark batches left ``running`` by a crash as ``abandoned``.

        Returns:
            How many batches were marked.
        """
        stale = self._session.scalars(
            select(ImportBatchRow).where(ImportBatchRow.status == ImportBatchStatus.RUNNING.value)
        ).all()
        for batch in stale:
            self._move(batch, ImportBatchStatus.ABANDONED)
            batch.finished_at = _utc_now()
        self._session.flush()
        return len(stale)

    def record_file(
        self,
        batch: ImportBatchRow,
        relative_path: str,
        *,
        data: bytes | None = None,
        path: Path | None = None,
        mode: StorageMode = "copy",
    ) -> tuple[SourceSnapshotRow, bool]:
        """Archive one input file and link it to the batch.

        Exactly one of ``data`` (e.g. a ZIP member) or ``path`` is given.

        Args:
            batch: The running batch.
            relative_path: The file's path relative to the raw root.
            data: The file's bytes.
            path: The file on disk.
            mode: ``copy`` into the archive, or ``reference`` in place
                (``path`` only).

        Returns:
            The snapshot and whether it was new.

        Raises:
            ValueError: For a bad combination of arguments.
            BlobCorruptError: If identical bytes were stored before and the
                stored copy is now damaged. Nothing is overwritten.
        """
        if (data is None) == (path is None):
            raise ValueError("give exactly one of data or path")
        if mode == "reference" and path is None:
            raise ValueError("reference mode needs a path")
        if data is not None:
            blob = self._archive.put_bytes(data)
        elif mode == "reference":
            assert path is not None
            blob = self._archive.put_reference(path)
        else:
            assert path is not None
            blob = self._archive.put_file(path)

        snapshot = self._session.get(SourceSnapshotRow, snapshot_id(blob.sha256))
        created = snapshot is None
        if snapshot is None:
            snapshot = SourceSnapshotRow(
                snapshot_id=snapshot_id(blob.sha256),
                sha256=blob.sha256,
                size=blob.size,
                storage_mode=blob.mode,
                storage_ref=str(blob.location),
                first_import_id=batch.import_id,
            )
            self._session.add(snapshot)
        else:
            # Reused: check the copy the ledger points at, not just the new one.
            self._archive.verify(stored_blob(snapshot))
        link = self._session.get(ImportBatchFileRow, (batch.import_id, relative_path))
        if link is None:
            self._session.add(
                ImportBatchFileRow(
                    import_id=batch.import_id,
                    relative_path=relative_path,
                    snapshot_id=snapshot.snapshot_id,
                )
            )
        self._session.flush()
        return snapshot, created

    def finish(
        self,
        batch: ImportBatchRow,
        status: ImportBatchStatus,
        *,
        counts: dict[str, Any],
        warnings: dict[str, int],
        tree_hash: str,
    ) -> None:
        """Close a batch with its final status, counts and warnings.

        Args:
            batch: The running batch.
            status: ``succeeded``, ``partial`` or ``failed``.
            counts: Report counts (JSON-serialisable, no private text).
            warnings: Warning code -> count.
            tree_hash: Raw tree signature after reading.

        Raises:
            InvalidTransitionError: If the batch isn't running.
        """
        self._move(batch, status)
        batch.finished_at = _utc_now()
        batch.counts_json = json.dumps(counts, sort_keys=True)
        batch.warnings_json = json.dumps(warnings, sort_keys=True)
        batch.tree_hash_after = tree_hash
        self._session.flush()

    def latest(self) -> ImportBatchRow | None:
        """Return the most recently started batch, or None."""
        return self._session.scalars(
            select(ImportBatchRow).order_by(ImportBatchRow.started_at.desc()).limit(1)
        ).first()

    def _move(self, batch: ImportBatchRow, new: ImportBatchStatus) -> None:
        check_transition(ImportBatchStatus(batch.status), new)
        batch.status = new.value


def stored_blob(snapshot: SourceSnapshotRow) -> StoredBlob:
    """Rebuild the archive handle for a snapshot row.

    Args:
        snapshot: A snapshot row.

    Returns:
        The ``StoredBlob`` that ``BlobStore.verify`` and ``read_bytes`` take.
    """
    mode: StorageMode = "reference" if snapshot.storage_mode == "reference" else "copy"
    return StoredBlob(snapshot.sha256, snapshot.size, mode, Path(snapshot.storage_ref))
