"""SQLite and PostgreSQL differences, in one place (PROD-001).

The engine is SQLite-first: one file per workspace, no server. PROD-001
proves the same schema and the same importer run on PostgreSQL too, for a
future hosted version. Almost everything is already portable through
SQLAlchemy; this module holds the few things that aren't.

* **Append-only triggers.** Audit tables (reviews, decision events, the
  purge log...) refuse updates and deletes with a trigger. The table
  modules write them in SQLite's syntax, which the SQLite migrations run
  unchanged. For PostgreSQL, ``trigger_ddl`` rewrites each one into a
  PostgreSQL trigger that calls one shared function raising the same
  message.

Talking points:
    - "The audit tables refuse edits on both databases; on PostgreSQL the
      same rule is written in PostgreSQL's own trigger syntax."
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from sqlalchemy import Engine, create_engine

# The one shape the table modules use. Anything else is refused loudly
# rather than silently skipped: an audit table must never lose its guard.
_SQLITE_TRIGGER = re.compile(
    r"^CREATE TRIGGER IF NOT EXISTS (?P<name>\w+) BEFORE (?P<event>UPDATE|DELETE) "
    r"ON (?P<table>\w+) BEGIN SELECT RAISE\(ABORT, '(?P<message>[^']*)'\); END$"
)
REFUSE_FUNCTION = (
    "CREATE OR REPLACE FUNCTION ke_refuse_change() RETURNS trigger LANGUAGE plpgsql AS "
    "$$ BEGIN RAISE EXCEPTION '%', TG_ARGV[0]; END $$"
)


def trigger_ddl(statements: Iterable[str], dialect: str) -> list[str]:
    """The trigger statements to run on ``dialect`` (``sqlite`` or ``postgresql``).

    Raises:
        ValueError: An unknown dialect, or a trigger this can't translate.
    """
    statements = list(statements)
    if dialect == "sqlite":
        return statements
    if dialect != "postgresql":
        raise ValueError(f"no trigger translation for {dialect!r}")
    translated = [REFUSE_FUNCTION]
    for statement in statements:
        match = _SQLITE_TRIGGER.match(statement)
        if match is None:
            raise ValueError(f"can't translate trigger: {statement[:60]}")
        translated.append(
            f"CREATE TRIGGER {match['name']} BEFORE {match['event']} ON {match['table']} "
            f"FOR EACH ROW EXECUTE FUNCTION ke_refuse_change('{match['message']}')"
        )
    return translated


def run_triggers(statements: Iterable[str]) -> None:
    """Create append-only triggers from inside a migration, on either database."""
    from alembic import op

    for statement in trigger_ddl(statements, op.get_bind().dialect.name):
        op.execute(statement)


def create_postgres_engine(url: str) -> Engine:
    """An engine for a PostgreSQL URL (``postgresql+psycopg://...``).

    Raises:
        ValueError: The URL isn't PostgreSQL.
    """
    if not url.startswith("postgresql+psycopg://"):
        raise ValueError("expected a postgresql+psycopg:// URL")
    return create_engine(url, pool_pre_ping=True)
