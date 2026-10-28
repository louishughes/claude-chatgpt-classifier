"""Local backups that prove they can be restored (OPS-003).

A backup is a folder holding:

* ``knowledge.db``: a consistent copy of the database, taken with SQLite's
  own online-backup API (safe even while the database is open);
* ``archive/``: the original export files and images, stored by their
  SHA-256 (already content-addressed, so each is checked against its name);
* ``manifest.json``: every file's SHA-256 and size, the schema revision,
  and the number of rows in every table.

The search indexes in ``index/`` are left out on purpose: they are built
from the database and can be rebuilt (``ke index``), so backing them up
would only double the size.

Three operations, each refusing to overwrite anything:

* **create** writes a new folder (built under a temporary name and renamed
  at the end, so a half-written backup never looks finished), while
  holding the import lock so no import is half-way through;
* **verify** re-hashes every file, runs SQLite's integrity check and
  recounts every table against the manifest;
* **restore** copies a verified backup into an empty folder, then checks
  the restored copy the same way. A restore that doesn't match is
  reported, never quietly accepted.

Talking points:
    - "A backup carries a list of every file's fingerprint and every
      table's row count, so I can prove a restore got everything back."
    - "It never overwrites anything: backups go to a new folder, and a
      restore only goes into an empty one."
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from knowledge_engine.infrastructure.db import DATABASE_FILENAME
from knowledge_engine.settings import Settings

BACKUP_VERSION = "ops-003-v1"
MANIFEST = "manifest.json"
ARCHIVE = "archive"


class BackupError(ValueError):
    """A backup or restore was refused (the reason is in the message)."""


@dataclass
class Check:
    """What a verification found (empty lists: everything matches)."""

    files: int = 0
    rows: int = 0
    missing: list[str] = field(default_factory=list)
    changed: list[str] = field(default_factory=list)
    extra: list[str] = field(default_factory=list)
    count_mismatches: list[str] = field(default_factory=list)  # "table: 3 != 4"
    integrity: str = "unknown"

    @property
    def ok(self) -> bool:
        """Every file and every count matches, and SQLite says the database is sound."""
        return (
            not (self.missing or self.changed or self.extra or self.count_mismatches)
            and self.integrity == "ok"
        )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _counts(database: Path) -> tuple[dict[str, int], str | None, str]:
    """(rows per table, schema revision, integrity check) of a database, read only."""
    connection = sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True)
    try:
        tables = [
            name
            for (name,) in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' "
                "AND name NOT LIKE 'sqlite_%' ORDER BY name"
            )
        ]
        counts = {
            name: int(connection.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0])
            for name in tables
        }
        revision = None
        if "alembic_version" in tables:
            row = connection.execute("SELECT version_num FROM alembic_version").fetchone()
            revision = str(row[0]) if row else None
        integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
    finally:
        connection.close()
    return counts, revision, integrity


def _files(root: Path) -> dict[str, Path]:
    """The files a backup holds: the database and the archive, by relative path."""
    found = {DATABASE_FILENAME: root / DATABASE_FILENAME}
    archive = root / ARCHIVE
    if archive.is_dir():
        for path in sorted(archive.rglob("*")):
            if path.is_file():
                found[path.relative_to(root).as_posix()] = path
    return found


def create_backup(settings: Settings, destination: Path) -> dict[str, Any]:
    """Back the workspace up into a new folder inside ``destination``.

    Returns:
        The manifest (also written as ``manifest.json``).

    Raises:
        BackupError: No database, the destination is inside the workspace,
            or an archive file no longer matches its own name.
    """
    from knowledge_engine.importer.lock import import_lock

    root = settings.workspace_root.resolve()
    database = root / DATABASE_FILENAME
    if not database.is_file():
        raise BackupError("no database to back up (nothing imported yet)")
    destination = destination.resolve()
    if destination == root or root in destination.parents:
        raise BackupError("a backup must be stored outside the workspace")
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    final = destination / f"ke-backup-{stamp}"
    partial = destination / f".partial-{stamp}"
    partial.mkdir(parents=True)
    try:
        with import_lock(root, timeout_s=settings.limits.import_lock_timeout_s):
            source = sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True)
            target = sqlite3.connect(partial / DATABASE_FILENAME)
            try:
                source.backup(target)  # a consistent copy, even if the database is open
                # The copy inherits WAL mode, which keeps later writes in a side
                # file; one self-contained file is what a backup should be.
                target.execute("PRAGMA journal_mode=DELETE")
            finally:
                target.close()
                source.close()
            for relative, path in _files(root).items():
                if relative == DATABASE_FILENAME:
                    continue
                digest = _sha256(path)
                if digest != path.name.split(".")[0]:
                    raise BackupError(f"archive file does not match its name: {relative}")
                copy = partial / relative
                copy.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, copy)
        counts, revision, integrity = _counts(partial / DATABASE_FILENAME)
        if integrity != "ok":
            raise BackupError(f"database copy failed SQLite's integrity check: {integrity}")
        manifest = {
            "version": BACKUP_VERSION,
            "created_at": datetime.now(UTC).isoformat(),
            "schema_revision": revision,
            "tables": counts,
            "files": {
                relative: {"sha256": _sha256(path), "size": path.stat().st_size}
                for relative, path in _files(partial).items()
            },
            "left_out": ["index/ (rebuilt from the database with `ke index`)"],
        }
        (partial / MANIFEST).write_text(json.dumps(manifest, indent=1), encoding="utf-8")
        partial.rename(final)
    except BaseException:
        shutil.rmtree(partial, ignore_errors=True)
        raise
    return {**manifest, "folder": final.name}


def _manifest(folder: Path) -> dict[str, Any]:
    path = folder / MANIFEST
    if not path.is_file():
        raise BackupError("not a backup folder (no manifest.json)")
    manifest: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("version") != BACKUP_VERSION:
        raise BackupError(f"unknown backup version: {manifest.get('version')}")
    return manifest


def check_against(root: Path, manifest: dict[str, Any]) -> Check:
    """Compare a folder (a backup or a restored workspace) with a manifest. Reads only."""
    check = Check()
    expected: dict[str, dict[str, Any]] = manifest["files"]
    present = _files(root)
    for relative, meta in sorted(expected.items()):
        path = present.get(relative)
        if path is None or not path.is_file():
            check.missing.append(relative)
            continue
        check.files += 1
        if _sha256(path) != meta["sha256"] and relative != DATABASE_FILENAME:
            check.changed.append(relative)
    check.extra = sorted(set(present) - set(expected))
    if (root / DATABASE_FILENAME).is_file():
        counts, _, check.integrity = _counts(root / DATABASE_FILENAME)
        for table, rows in sorted(manifest["tables"].items()):
            got = counts.get(table)
            check.rows += got or 0
            if got != rows:
                check.count_mismatches.append(f"{table}: {got} != {rows}")
        for table in sorted(set(counts) - set(manifest["tables"])):
            check.count_mismatches.append(f"{table}: {counts[table]} != (absent)")
    return check


def verify_backup(folder: Path) -> Check:
    """Re-hash every file, integrity-check the database and recount every table."""
    manifest = _manifest(folder)
    check = check_against(folder, manifest)
    # Inside the backup the database file itself must be byte-identical too.
    database = folder / DATABASE_FILENAME
    meta = manifest["files"].get(DATABASE_FILENAME)
    if database.is_file() and meta and _sha256(database) != meta["sha256"]:
        check.changed.append(DATABASE_FILENAME)
    return check


def restore_backup(folder: Path, target: Path) -> Check:
    """Restore a verified backup into an empty (or new) folder, then check the result.

    The restored database is compared by integrity check and row counts
    (SQLite may rewrite pages when it is opened, so its bytes are not
    compared); every archive file by its hash.

    Raises:
        BackupError: The backup fails verification, or ``target`` is not empty.
    """
    manifest = _manifest(folder)
    before = verify_backup(folder)
    if not before.ok:
        raise BackupError("the backup does not verify; nothing was restored")
    if target.exists() and any(target.iterdir()):
        raise BackupError("restore needs an empty folder; nothing was overwritten")
    target.mkdir(parents=True, exist_ok=True)
    for relative in manifest["files"]:
        copy = target / relative
        copy.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(folder / relative, copy)
    return check_against(target, manifest)


def check_to_dict(check: Check) -> dict[str, Any]:
    """JSON-ready (paths are content hashes and table names only)."""
    return {
        "ok": check.ok,
        "files": check.files,
        "rows": check.rows,
        "integrity": check.integrity,
        "missing": check.missing,
        "changed": check.changed,
        "extra": check.extra,
        "count_mismatches": check.count_mismatches,
    }
