"""SQLite connection setup and the transaction scope every write goes through.

The engine keeps everything in one local SQLite file inside the workspace.
This module makes sure every connection runs with the same safety settings:
foreign keys enforced (SQLite leaves them off unless asked), write-ahead
logging (WAL, which lets readers keep reading while one writer writes) and a
busy timeout (wait for a lock instead of failing at once). It also fixes a
known quirk of Python's ``sqlite3`` driver that otherwise breaks savepoints,
and offers ``SessionFactory.transaction()``: a block that either commits
everything or rolls everything back. Later tickets (imports, checkpoints)
depend on that all-or-nothing behaviour.

Talking points:
    - "SQLite doesn't enforce foreign keys by default. I switch them on for
      every connection and test that it's on."
    - "Every write runs inside one transaction scope: commit on success,
      roll back on any error, nothing half-written."
    - "Imports take the write lock up front (BEGIN IMMEDIATE), so two
      importers can't deadlock each other halfway through."
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, MetaData, create_engine, event, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from knowledge_engine.settings import Settings

DATABASE_FILENAME = "knowledge.db"

# Fixed names for constraints and indexes. Alembic (FND-004) can only alter
# or drop a constraint later if it has a predictable name.
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

# Execution option that chooses how a transaction starts. "DEFERRED" (the
# SQLite default) takes the write lock only at the first write; "IMMEDIATE"
# takes it at BEGIN, which avoids two writers each holding a read lock and
# waiting for the other.
_BEGIN_MODE_OPTION = "ke_begin_mode"
_BEGIN_MODES = frozenset({"DEFERRED", "IMMEDIATE"})


class Base(DeclarativeBase):
    """Parent class for every table definition in the engine."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class DatabaseConfigError(RuntimeError):
    """Raised when the database cannot run with the required safety settings."""


def create_sqlite_engine(db_path: Path, *, busy_timeout_ms: int = 5000) -> Engine:
    """Create a SQLAlchemy engine for a SQLite file with the engine's pragmas.

    The file and its parent folder are created if missing.

    Args:
        db_path: Where the database file lives (normally inside the workspace).
        busy_timeout_ms: How long a connection waits for a lock before giving
            up with "database is locked".

    Returns:
        A configured engine. Every pooled connection gets the same pragmas.

    Raises:
        DatabaseConfigError: If SQLite refuses WAL mode or foreign keys, for
            example on some network drives.
        ValueError: If ``busy_timeout_ms`` is negative.
    """
    if busy_timeout_ms < 0:
        raise ValueError("busy_timeout_ms must be zero or positive")
    db_path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite+pysqlite:///{db_path.as_posix()}")

    @event.listens_for(engine, "connect")
    def _on_connect(dbapi_connection: Any, _record: Any) -> None:
        # Python's sqlite3 driver starts and ends transactions on its own
        # schedule, which breaks savepoints. Turning that off and issuing
        # BEGIN ourselves (below) is the fix SQLAlchemy's docs recommend.
        dbapi_connection.isolation_level = None
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys = ON")
            cursor.execute(f"PRAGMA busy_timeout = {int(busy_timeout_ms)}")
            mode = cursor.execute("PRAGMA journal_mode = WAL").fetchone()[0]
            # NORMAL is safe with WAL: a power cut may lose the last commit
            # but never corrupts the file.
            cursor.execute("PRAGMA synchronous = NORMAL")
        finally:
            cursor.close()
        if str(mode).lower() != "wal":
            raise DatabaseConfigError(
                f"SQLite refused WAL mode (got {mode!r}); keep the workspace on a local disk"
            )

    @event.listens_for(engine, "begin")
    def _on_begin(connection: Any) -> None:
        mode = connection.get_execution_options().get(_BEGIN_MODE_OPTION, "DEFERRED")
        if mode not in _BEGIN_MODES:
            raise ValueError(f"unknown begin mode {mode!r}")
        connection.exec_driver_sql(f"BEGIN {mode}")

    _check_pragmas(engine)
    return engine


def _check_pragmas(engine: Engine) -> None:
    """Open one connection and confirm the safety pragmas actually took effect."""
    with engine.connect() as connection:
        foreign_keys = connection.execute(text("PRAGMA foreign_keys")).scalar_one()
        if foreign_keys != 1:
            raise DatabaseConfigError("SQLite foreign key enforcement could not be enabled")


def database_path(settings: Settings) -> Path:
    """Return where the database lives for the given settings.

    Args:
        settings: The loaded settings.

    Returns:
        ``<workspace_root>/knowledge.db``.
    """
    return settings.workspace_root / DATABASE_FILENAME


class SessionFactory:
    """Hands out database sessions and the all-or-nothing transaction scope.

    A *session* is SQLAlchemy's unit of work: it tracks the rows you add or
    change and writes them when the transaction commits.
    """

    def __init__(self, engine: Engine) -> None:
        """Wrap an engine created by ``create_sqlite_engine``.

        Args:
            engine: The configured engine.
        """
        self._engine = engine
        self._sessions = sessionmaker(bind=engine, expire_on_commit=False)
        self._write_sessions = sessionmaker(
            bind=engine.execution_options(**{_BEGIN_MODE_OPTION: "IMMEDIATE"}),
            expire_on_commit=False,
        )

    @classmethod
    def from_settings(cls, settings: Settings) -> SessionFactory:
        """Build a factory for the database in the settings' workspace.

        Args:
            settings: The loaded settings.

        Returns:
            A ready factory.
        """
        return cls(create_sqlite_engine(database_path(settings)))

    @property
    def engine(self) -> Engine:
        """The underlying engine (for migrations and diagnostics)."""
        return self._engine

    @contextmanager
    def transaction(self, *, write: bool = True) -> Iterator[Session]:
        """Run a block of database work as one transaction.

        Commits if the block finishes, rolls back if it raises, and always
        closes the session. Example::

            with factory.transaction() as session:
                session.add(row)

        Args:
            write: True (default) takes the write lock at the start, so the
                block can't fail halfway because another writer got in
                first. Use False for read-only work so it never waits for a
                writer.

        Yields:
            A session bound to the open transaction.

        Raises:
            Exception: Whatever the block raised, after rolling back.
        """
        maker = self._write_sessions if write else self._sessions
        session = maker()
        try:
            with session.begin():
                yield session
        finally:
            session.close()

    def dispose(self) -> None:
        """Close all pooled connections (call before deleting the file)."""
        self._engine.dispose()
