"""Database schema migrations, managed by Alembic.

A *migration* is a small, numbered script that changes the database schema
(add a table, add a column) and can undo that change. Running them in order
turns an empty file, or an older database, into the current schema. The
scripts live inside the package so an installed copy can upgrade its own
database without extra files. Tables are never created any other way in
real use; ``Base.metadata.create_all`` is for throwaway test databases only.

Talking points:
    - "My schema has version control too: every change is a numbered,
      reversible migration, tested by upgrading twice and downgrading."
    - "A test compares the migrated database with the Python table
      definitions, so the two can't drift apart."
"""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Engine

_MIGRATIONS_DIR = Path(__file__).parent


def alembic_config(engine: Engine | None = None) -> Config:
    """Build an Alembic configuration, optionally bound to ``engine``.

    No ``alembic.ini`` file is needed: the settings are set in code, and the
    engine is handed to ``env.py`` directly so migrations use the same
    safety pragmas as the rest of the app.

    Args:
        engine: An engine from ``create_sqlite_engine``. Leave out to only
            read the migration scripts.

    Returns:
        The Alembic config.
    """
    config = Config()
    config.set_main_option("script_location", str(_MIGRATIONS_DIR))
    if engine is not None:
        config.attributes["engine"] = engine
    return config


def upgrade_to_head(engine: Engine) -> None:
    """Apply every migration that hasn't run yet. Safe to call repeatedly.

    Args:
        engine: The database to upgrade.
    """
    command.upgrade(alembic_config(engine), "head")


def downgrade_to(engine: Engine, revision: str) -> None:
    """Undo migrations back to ``revision`` (``"base"`` means an empty schema).

    Args:
        engine: The database to downgrade.
        revision: Target revision ID, or ``"base"``.
    """
    command.downgrade(alembic_config(engine), revision)


def current_revision(engine: Engine) -> str | None:
    """Return the migration revision the database is at, or None if unversioned.

    Args:
        engine: The database to inspect.

    Returns:
        The revision ID, or None.
    """
    with engine.connect() as connection:
        return MigrationContext.configure(connection).get_current_revision()


def head_revision() -> str:
    """Return the newest migration revision shipped with this code.

    Returns:
        The head revision ID.

    Raises:
        RuntimeError: If the scripts have more than one head (a branching
            mistake that must be fixed before release).
    """
    script = ScriptDirectory.from_config(alembic_config())
    heads = script.get_heads()
    if len(heads) != 1:
        raise RuntimeError(f"expected one migration head, found {heads}")
    return heads[0]
