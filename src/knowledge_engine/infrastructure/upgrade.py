"""Upgrading the database safely: back up first, then migrate (OPS-007).

A new version of the engine can bring new migrations. Running them changes
the database in place, and an older version can't read the result. So:

* ``ke db upgrade`` takes a full OPS-003 backup **before** it migrates,
  into a folder next to the workspace (``<workspace>-backups``) unless told
  otherwise. If a migration fails, the message names the backup to restore.
* An import never migrates an existing database on its own any more. If
  the database is behind the code, the import stops and says to run
  ``ke db upgrade``. A brand-new workspace is still created straight away:
  there is nothing to lose.
* A database **newer** than the code (an older version installed over a
  newer one) is refused: the way back is to restore the backup taken
  before the upgrade (see ``docs/runbooks/UPGRADE_AND_ROLLBACK.md``).

Talking points:
    - "Every schema upgrade starts with a verified backup, so a bad release
      costs me a restore, not my data."
    - "Imports won't quietly migrate my database: upgrading is one explicit
      command that backs up first."
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from alembic.script import ScriptDirectory
from sqlalchemy import Engine

from knowledge_engine.infrastructure.db import create_sqlite_engine, database_path
from knowledge_engine.infrastructure.migrations import (
    alembic_config,
    current_revision,
    head_revision,
    upgrade_to_head,
)
from knowledge_engine.settings import Settings


class SchemaMismatchError(RuntimeError):
    """The database's schema doesn't match this version of the code."""


def default_backup_root(settings: Settings) -> Path:
    """Where pre-upgrade backups go by default: a sibling of the workspace."""
    root = settings.workspace_root.resolve()
    return root.parent / f"{root.name}-backups"


def schema_status(engine: Engine) -> str:
    """``empty``, ``current``, ``behind`` or ``ahead`` (unknown to this code)."""
    revision = current_revision(engine)
    if revision is None:
        return "empty"
    if revision == head_revision():
        return "current"
    known = {s.revision for s in ScriptDirectory.from_config(alembic_config()).walk_revisions()}
    return "behind" if revision in known else "ahead"


def require_current(engine: Engine) -> None:
    """Refuse to work on a database from another version (an empty one is fine).

    Raises:
        SchemaMismatchError: The schema is behind or ahead of the code.
    """
    status = schema_status(engine)
    if status == "behind":
        raise SchemaMismatchError(
            "the database is older than this version: run `ke db upgrade` (it backs up first)"
        )
    if status == "ahead":
        raise SchemaMismatchError(
            "the database was upgraded by a newer version: install that version again, "
            "or restore the backup taken before the upgrade"
        )


def safe_upgrade(settings: Settings, backup_root: Path | None) -> dict[str, Any]:
    """Bring the database to this version's schema, backing up first.

    Args:
        settings: The workspace.
        backup_root: Where the pre-upgrade backup goes; None skips it (the
            caller asked for that explicitly).

    Returns:
        ``before``, ``after``, ``changed`` and ``backup`` (the new backup
        folder's name, or None when nothing needed migrating or no backup
        was asked for).

    Raises:
        SchemaMismatchError: The database is newer than the code, or a
            migration failed (the message names the backup to restore).
    """
    from knowledge_engine.infrastructure.backup import create_backup

    engine = create_sqlite_engine(database_path(settings))
    try:
        status = schema_status(engine)
        before = current_revision(engine)
        if status == "ahead":
            require_current(engine)
        backup = None
        if status == "behind" and backup_root is not None:
            engine.dispose()  # the backup opens the database itself
            backup = create_backup(settings, backup_root)["folder"]
        try:
            upgrade_to_head(engine)
        except Exception as error:
            where = f" Restore the backup {backup} with `ke backup restore`." if backup else ""
            raise SchemaMismatchError(f"the upgrade failed: {error}.{where}") from error
        after = current_revision(engine)
    finally:
        engine.dispose()
    return {
        "before": before or "none",
        "after": after or "none",
        "changed": before != after,
        "backup": backup,
    }
