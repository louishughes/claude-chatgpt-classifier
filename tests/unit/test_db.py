"""FND-003 acceptance: temporary SQLite round-trip and rollback."""

import threading
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import Column, ForeignKey, Integer, MetaData, String, Table, insert, select, text
from sqlalchemy.exc import IntegrityError, OperationalError

from knowledge_engine.infrastructure.db import (
    Base,
    SessionFactory,
    create_sqlite_engine,
    database_path,
)
from knowledge_engine.infrastructure.workspace import WorkspaceRepo, WorkspaceRow
from knowledge_engine.settings import load_settings


@pytest.fixture
def factory(tmp_path: Path) -> Iterator[SessionFactory]:
    engine = create_sqlite_engine(tmp_path / "ws" / "test.db")
    Base.metadata.create_all(engine)
    sessions = SessionFactory(engine)
    yield sessions
    sessions.dispose()


def test_pragmas_are_set_on_every_connection(factory: SessionFactory) -> None:
    # Two separate connections: pragmas are per connection, not per file.
    for _ in range(2):
        with factory.engine.connect() as connection:
            assert connection.execute(text("PRAGMA foreign_keys")).scalar_one() == 1
            assert connection.execute(text("PRAGMA journal_mode")).scalar_one() == "wal"
            assert connection.execute(text("PRAGMA busy_timeout")).scalar_one() == 5000


def test_round_trip_survives_a_new_engine(tmp_path: Path) -> None:
    db = tmp_path / "rt.db"
    first = SessionFactory(create_sqlite_engine(db))
    Base.metadata.create_all(first.engine)
    with first.transaction() as session:
        created = WorkspaceRepo(session).get_or_create("fixture")
        workspace_id = created.workspace_id
    first.dispose()

    second = SessionFactory(create_sqlite_engine(db))
    with second.transaction(write=False) as session:
        loaded = WorkspaceRepo(session).get(workspace_id)
        assert loaded is not None
        assert loaded.name == "fixture"
        assert loaded.created_at is not None
    second.dispose()


def test_exception_rolls_back_everything(factory: SessionFactory) -> None:
    with pytest.raises(RuntimeError, match="boom"):
        with factory.transaction() as session:
            WorkspaceRepo(session).get_or_create("a")
            WorkspaceRepo(session).get_or_create("b")
            raise RuntimeError("boom")
    with factory.transaction(write=False) as session:
        assert session.scalars(select(WorkspaceRow)).all() == []


def test_get_or_create_is_idempotent(factory: SessionFactory) -> None:
    with factory.transaction() as session:
        first = WorkspaceRepo(session).get_or_create("fixture").workspace_id
    with factory.transaction() as session:
        repo = WorkspaceRepo(session)
        assert repo.get_or_create(" fixture ").workspace_id == first
        assert len(session.scalars(select(WorkspaceRow)).all()) == 1


@pytest.mark.parametrize("name", ["", "   ", "x" * 101])
def test_invalid_workspace_name_is_rejected(factory: SessionFactory, name: str) -> None:
    with factory.transaction() as session, pytest.raises(ValueError):
        WorkspaceRepo(session).get_or_create(name)


def test_unique_name_is_enforced_by_the_database(factory: SessionFactory) -> None:
    with pytest.raises(IntegrityError):
        with factory.transaction() as session:
            session.add(WorkspaceRow(workspace_id="a" * 32, name="dup"))
            session.add(WorkspaceRow(workspace_id="b" * 32, name="dup"))
    with factory.transaction(write=False) as session:
        assert session.scalars(select(WorkspaceRow)).all() == []


def test_foreign_keys_are_enforced(factory: SessionFactory) -> None:
    # A test-only child table, so the check doesn't depend on future schema.
    metadata = MetaData()
    child = Table(
        "fk_probe",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("workspace_id", String(32), ForeignKey(WorkspaceRow.workspace_id), nullable=False),
    )
    metadata.create_all(factory.engine, tables=[child])
    with pytest.raises(IntegrityError, match="FOREIGN KEY"):
        with factory.transaction() as session:
            session.execute(insert(child).values(id=1, workspace_id="missing"))


def test_savepoint_rolls_back_only_the_inner_block(factory: SessionFactory) -> None:
    # Savepoints only work because the driver's own transaction handling is
    # switched off in create_sqlite_engine.
    with factory.transaction() as session:
        repo = WorkspaceRepo(session)
        repo.get_or_create("outer")
        try:
            with session.begin_nested():
                repo.get_or_create("inner")
                raise RuntimeError("undo inner only")
        except RuntimeError:
            pass
    with factory.transaction(write=False) as session:
        names = {row.name for row in session.scalars(select(WorkspaceRow))}
    assert names == {"outer"}


def test_second_writer_waits_then_fails_cleanly(tmp_path: Path) -> None:
    db = tmp_path / "lock.db"
    holder = SessionFactory(create_sqlite_engine(db))
    Base.metadata.create_all(holder.engine)
    waiter = SessionFactory(create_sqlite_engine(db, busy_timeout_ms=100))

    lock_taken = threading.Event()
    release = threading.Event()

    def hold_write_lock() -> None:
        with holder.transaction() as session:
            WorkspaceRepo(session).get_or_create("holder")
            lock_taken.set()
            release.wait(timeout=5)

    thread = threading.Thread(target=hold_write_lock)
    thread.start()
    try:
        assert lock_taken.wait(timeout=5)
        with pytest.raises(OperationalError, match="locked"):
            with waiter.transaction() as session:
                WorkspaceRepo(session).get_or_create("waiter")
        # A reader is not blocked by the writer (WAL).
        with waiter.transaction(write=False) as session:
            assert session.scalars(select(WorkspaceRow)).all() == []
    finally:
        release.set()
        thread.join(timeout=5)
    with waiter.transaction(write=False) as session:
        assert [row.name for row in session.scalars(select(WorkspaceRow))] == ["holder"]
    holder.dispose()
    waiter.dispose()


def test_database_lives_in_the_workspace(tmp_path: Path) -> None:
    settings = load_settings(workspace_root=tmp_path / "ws")
    assert database_path(settings) == tmp_path / "ws" / "knowledge.db"
    factory = SessionFactory.from_settings(settings)
    assert (tmp_path / "ws" / "knowledge.db").exists()
    factory.dispose()


def test_negative_busy_timeout_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        create_sqlite_engine(tmp_path / "x.db", busy_timeout_ms=-1)


def test_constraint_names_follow_the_convention() -> None:
    table = Base.metadata.tables["workspaces"]
    assert table.primary_key.name == "pk_workspaces"
    names = {str(c.name) for c in table.constraints}
    assert {name for name in names if name.startswith("uq_")} == {"uq_workspaces_name"}


def test_write_transaction_takes_the_lock_before_its_first_write(tmp_path: Path) -> None:
    # BEGIN IMMEDIATE: merely opening a write transaction blocks other writers,
    # so an import can never be overtaken halfway through. A read-only
    # transaction must not take the lock.
    db = tmp_path / "immediate.db"
    holder = SessionFactory(create_sqlite_engine(db))
    Base.metadata.create_all(holder.engine)
    waiter = SessionFactory(create_sqlite_engine(db, busy_timeout_ms=100))

    for write, expect_locked in ((True, True), (False, False)):
        with holder.transaction(write=write) as held:
            held.execute(text("SELECT 1"))  # starts the transaction, writes nothing
            if expect_locked:
                with pytest.raises(OperationalError, match="locked"):
                    with waiter.transaction() as session:
                        WorkspaceRepo(session).get_or_create("waiter")
            else:
                with waiter.transaction() as session:
                    WorkspaceRepo(session).get_or_create("waiter")
    holder.dispose()
    waiter.dispose()
