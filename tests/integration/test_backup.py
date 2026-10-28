"""OPS-003: a backup restores to the same hashes and row counts, or says it doesn't."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from knowledge_engine.importer import import_source
from knowledge_engine.infrastructure.backup import (
    BackupError,
    create_backup,
    restore_backup,
    verify_backup,
)
from knowledge_engine.settings import Settings

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "e2e" / "export.zip"


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    settings = Settings(workspace_root=tmp_path / "ws")
    import_source(FIXTURE, "backup", settings=settings)
    return settings


def test_backup_verify_restore_round_trip(settings: Settings, tmp_path: Path) -> None:
    manifest = create_backup(settings, tmp_path / "backups")
    folder = tmp_path / "backups" / manifest["folder"]
    assert manifest["tables"]["conversations"] == 5
    assert any(name.startswith("archive/") for name in manifest["files"])
    assert verify_backup(folder).ok
    restored = restore_backup(folder, tmp_path / "restored")
    assert restored.ok and restored.rows == sum(manifest["tables"].values())
    # The restored workspace works: importing the same export again changes nothing.
    again = Settings(workspace_root=tmp_path / "restored")
    report = import_source(FIXTURE, "backup", settings=again)
    assert report.conversations.get("new", 0) == 0 and report.files.get("new", 0) == 0
    with sqlite3.connect(tmp_path / "restored" / "knowledge.db") as connection:
        assert connection.execute("SELECT COUNT(*) FROM conversations").fetchone()[0] == 5
    # A second backup is a new folder; nothing is overwritten.
    second = create_backup(settings, tmp_path / "backups")
    assert second["folder"] != manifest["folder"]
    assert len(list((tmp_path / "backups").iterdir())) == 2


def test_tampering_is_found_and_blocks_restore(settings: Settings, tmp_path: Path) -> None:
    folder = tmp_path / "backups" / create_backup(settings, tmp_path / "backups")["folder"]
    blob = next(p for p in (folder / "archive").rglob("*") if p.is_file())
    # Archive copies are read-only (as in the store); the tamperer undoes that first.
    blob.chmod(0o644)
    blob.write_bytes(blob.read_bytes() + b"x")
    with sqlite3.connect(folder / "knowledge.db") as connection:
        connection.execute("DELETE FROM link_occurrences")
    check = verify_backup(folder)
    assert not check.ok
    assert blob.relative_to(folder).as_posix() in check.changed
    assert "knowledge.db" in check.changed
    assert any(m.startswith("link_occurrences: 0 != ") for m in check.count_mismatches)
    with pytest.raises(BackupError, match="does not verify"):
        restore_backup(folder, tmp_path / "restored")
    assert not (tmp_path / "restored").exists()


def test_refusals(settings: Settings, tmp_path: Path) -> None:
    with pytest.raises(BackupError, match="outside the workspace"):
        create_backup(settings, settings.workspace_root / "backups")
    with pytest.raises(BackupError, match="nothing imported"):
        create_backup(Settings(workspace_root=tmp_path / "empty"), tmp_path / "b")
    folder = tmp_path / "backups" / create_backup(settings, tmp_path / "backups")["folder"]
    occupied = tmp_path / "occupied"
    occupied.mkdir()
    (occupied / "keep.txt").write_text("mine", encoding="utf-8")
    with pytest.raises(BackupError, match="empty folder"):
        restore_backup(folder, occupied)
    assert (occupied / "keep.txt").read_text(encoding="utf-8") == "mine"
    with pytest.raises(BackupError, match="not a backup"):
        verify_backup(tmp_path)


def test_cli_backup(
    settings: Settings,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from knowledge_engine.cli.main import main

    monkeypatch.setenv("KE_WORKSPACE_ROOT", str(settings.workspace_root))
    assert main(["--json", "backup", "create", "--to", str(tmp_path / "b")]) == 0
    folder = tmp_path / "b" / json.loads(capsys.readouterr().out)["data"]["folder"]
    assert main(["--json", "backup", "verify", str(folder)]) == 0
    assert json.loads(capsys.readouterr().out)["data"]["ok"]
    assert main(["--json", "backup", "restore", str(folder), "--to", str(tmp_path / "r")]) == 0
    assert json.loads(capsys.readouterr().out)["data"]["integrity"] == "ok"
    assert main(["--json", "backup", "restore", str(folder), "--to", str(tmp_path / "r")]) == 1
    assert json.loads(capsys.readouterr().out)["error"]["code"] == "refused"
