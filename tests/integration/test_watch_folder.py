"""INT-003: watched folders import each export once, after it settles.

The acceptance check: repeated events import once, and notes about
unrelated chats stay byte-identical. A fake clock drives the debounce, so
nothing here sleeps.
"""

from __future__ import annotations

import json
import os
import shutil
import zipfile
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from knowledge_engine.cli.main import ExitCode, main
from knowledge_engine.documents.vault import sync_vault
from knowledge_engine.importer import import_source
from knowledge_engine.importer.failures import describe_failure
from knowledge_engine.importer.records import MessageRevisionRow
from knowledge_engine.importer.report import ImportReport
from knowledge_engine.importer.watch import FolderWatcher, WatchError, state_path
from knowledge_engine.infrastructure.db import create_sqlite_engine, database_path
from knowledge_engine.ingestion.inventory import tree_signature
from knowledge_engine.settings import Settings

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "chatgpt"


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


class Counting:
    """The real importer, counting its calls."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.calls = 0

    def __call__(self, source: Path) -> ImportReport:
        self.calls += 1
        return import_source(source, "watch", settings=self.settings, full_export=False)


def _describe(error: BaseException) -> str | None:
    failure = describe_failure(error) if isinstance(error, Exception) else None
    return failure.code if failure else None


@pytest.fixture
def env(tmp_path: Path) -> dict[str, object]:
    settings = Settings(workspace_root=tmp_path / "ws")
    inbox = tmp_path / "downloads"
    inbox.mkdir()
    clock = Clock()
    importer = Counting(settings)
    watcher = FolderWatcher(
        settings, inbox, importer, settle_s=2.0, clock=clock, describe=_describe
    )
    return {
        "settings": settings,
        "inbox": inbox,
        "clock": clock,
        "importer": importer,
        "w": watcher,
    }


def _drop(name: str, inbox: Path, as_name: str) -> Path:
    return Path(shutil.copytree(FIXTURES / name / "export", inbox / as_name))


def _revisions(settings: Settings) -> int:
    engine = create_sqlite_engine(database_path(settings))
    with Session(engine) as session:
        count = session.scalar(select(func.count()).select_from(MessageRevisionRow)) or 0
    engine.dispose()
    return count


def _later(env: dict[str, object], seconds: float = 3.0) -> None:
    clock = env["clock"]
    assert isinstance(clock, Clock)
    clock.now += seconds


def test_repeated_events_import_once(env: dict[str, object]) -> None:
    w, inbox, importer, settings = env["w"], env["inbox"], env["importer"], env["settings"]
    assert isinstance(w, FolderWatcher) and isinstance(inbox, Path)
    assert isinstance(importer, Counting) and isinstance(settings, Settings)
    source = _drop("reexport_v1", inbox, "export-a")

    assert w.tick().waiting == 1  # first sight: wait for it to settle
    _later(env)
    first = w.tick()
    assert len(first.imported) == 1 and first.changed_revisions > 0
    stored = _revisions(settings)

    for _ in range(3):  # the same folder seen again and again
        _later(env)
        assert w.tick().unchanged == 1
    os.utime(source / "conversations.json")  # touched: new metadata, same bytes
    before = tree_signature(source)
    _later(env)
    assert w.tick().waiting == 1
    _later(env)
    assert w.tick().same_contents == 1
    shutil.copytree(source, inbox / "export-a-copy")  # the same export saved twice
    _later(env)
    w.tick()
    _later(env)
    assert w.tick().same_contents == 1

    assert importer.calls == 1 and _revisions(settings) == stored
    assert tree_signature(source) == before  # the source is only read

    # A new watcher (say, after a restart) remembers what was imported.
    again = FolderWatcher(settings, inbox, importer, settle_s=0, clock=env["clock"])  # type: ignore[arg-type]
    assert again.tick().unchanged == 2 and importer.calls == 1
    state = json.loads(state_path(settings, inbox).read_text("utf-8"))
    assert "conversations" not in json.dumps(state)  # fingerprints and IDs, no chat text


def test_a_changed_export_imports_again(env: dict[str, object]) -> None:
    w, inbox, importer = env["w"], env["inbox"], env["importer"]
    assert isinstance(w, FolderWatcher) and isinstance(inbox, Path)
    assert isinstance(importer, Counting)
    target = _drop("reexport_v1", inbox, "export")
    w.tick()
    _later(env)
    assert len(w.tick().imported) == 1
    shutil.rmtree(target)  # the next full export replaces it under the same name
    _drop("reexport_v2", inbox, "export")
    w.tick()
    _later(env)
    tick = w.tick()
    assert len(tick.imported) == 1 and tick.changed_revisions > 0
    assert importer.calls == 2


def test_an_export_still_being_copied_waits(env: dict[str, object]) -> None:
    w, inbox, importer = env["w"], env["inbox"], env["importer"]
    assert isinstance(w, FolderWatcher) and isinstance(inbox, Path)
    assert isinstance(importer, Counting)
    growing = inbox / "export.zip"
    data = (FIXTURES / "export_zip" / "export" / "export.zip").read_bytes()
    for size in (10, len(data) // 2, len(data)):
        growing.write_bytes(data[:size])
        _later(env)
        assert w.tick().waiting == 1  # it changed since the last look
    assert importer.calls == 0
    _later(env)
    assert len(w.tick().imported) == 1


def test_a_broken_export_fails_once_and_is_not_retried(env: dict[str, object]) -> None:
    w, inbox, importer = env["w"], env["inbox"], env["importer"]
    assert isinstance(w, FolderWatcher) and isinstance(inbox, Path)
    assert isinstance(importer, Counting)
    (inbox / "broken.zip").write_bytes(b"not a zip at all")
    (inbox / "notes.txt").write_text("ignored", encoding="utf-8")
    (inbox / "export.zip.crdownload").write_bytes(b"partial")
    w.tick()
    _later(env)
    tick = w.tick()
    assert tick.failed and not tick.imported
    for _ in range(3):
        _later(env)
        assert w.tick().unchanged == 1
    assert importer.calls == 1


def test_unrelated_notes_stay_byte_identical(env: dict[str, object], tmp_path: Path) -> None:
    settings, inbox, clock = env["settings"], env["inbox"], env["clock"]
    assert isinstance(settings, Settings) and isinstance(inbox, Path) and isinstance(clock, Clock)
    vault = tmp_path / "vault"

    def sync() -> dict[str, int]:
        engine = create_sqlite_engine(database_path(settings))
        with Session(engine) as session:
            counts = sync_vault(session, vault, settings.workspace_root / "archive").counts()
        engine.dispose()
        return counts

    w = FolderWatcher(
        settings, inbox, Counting(settings), settle_s=2.0, clock=clock, stages={"vault": sync}
    )
    _drop("export_single", inbox, "first")
    w.tick()
    _later(env)
    assert w.tick().stages["vault"]["created"] > 0
    notes = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in vault.rglob("*.md")}

    _drop("similar_unrelated", inbox, "second")
    w.tick()
    _later(env)
    tick = w.tick()
    assert tick.stages["vault"]["created"] > 0
    for path, (body, mtime) in notes.items():
        assert path.read_bytes() == body and path.stat().st_mtime_ns == mtime

    _later(env)
    assert w.tick().stages == {}  # nothing changed: no stage runs


def test_the_workspace_itself_cannot_be_watched(tmp_path: Path) -> None:
    settings = Settings(workspace_root=tmp_path / "ws")
    (tmp_path / "ws" / "inbox").mkdir(parents=True)
    for folder in (tmp_path / "ws", tmp_path / "ws" / "inbox", tmp_path):
        with pytest.raises(WatchError):
            FolderWatcher(settings, folder, Counting(settings))
    with pytest.raises(WatchError):
        FolderWatcher(settings, tmp_path / "missing", Counting(settings))


def test_the_cli_watches_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("KE_WORKSPACE_ROOT", str(tmp_path / "ws"))
    inbox = tmp_path / "downloads"
    inbox.mkdir()
    with zipfile.ZipFile(FIXTURES / "export_zip" / "export" / "export.zip") as archive:
        archive.testzip()
    shutil.copy(FIXTURES / "export_zip" / "export" / "export.zip", inbox / "export.zip")
    args = ["--json", "watch", str(inbox), "--once", "--settle", "0", "--partial"]
    assert main(args) == ExitCode.OK
    data = json.loads(capsys.readouterr().out)["data"]
    assert data["imported"] == 1 and data["failed"] == {}
    assert main(args) == ExitCode.OK
    data = json.loads(capsys.readouterr().out)["data"]
    assert (data["imported"], data["unchanged"]) == (0, 1)
    assert main(["--json", "watch", str(tmp_path / "ws")]) == ExitCode.USAGE
    assert json.loads(capsys.readouterr().out)["error"]["code"] == "bad_folder"
