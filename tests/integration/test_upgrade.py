"""OPS-007: upgrades back up first; imports never migrate an old database.

The "old version" here is the same database migrated one step back, which
is exactly what the previous release left on disk.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest
from alembic.script import ScriptDirectory

from knowledge_engine.cli.main import main
from knowledge_engine.evaluation.synthetic import write_generated
from knowledge_engine.infrastructure.backup import restore_backup, verify_backup
from knowledge_engine.infrastructure.db import create_sqlite_engine, database_path
from knowledge_engine.infrastructure.migrations import (
    alembic_config,
    current_revision,
    downgrade_to,
    head_revision,
)
from knowledge_engine.settings import Settings


def _ke(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, dict[str, Any]]:
    code = main(["--json", *argv])
    return code, json.loads(capsys.readouterr().out)


def _previous() -> str:
    script = ScriptDirectory.from_config(alembic_config())
    down = script.get_revision(head_revision()).down_revision
    assert isinstance(down, str)
    return down


@pytest.fixture
def old_workspace(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> tuple[Settings, Path]:
    source = write_generated(tmp_path / "src", 4, seed=3) / "export"
    monkeypatch.setenv("KE_WORKSPACE_ROOT", str(tmp_path / "ws"))
    assert _ke(capsys, "import", str(source))[0] == 0
    settings = Settings(workspace_root=tmp_path / "ws")
    engine = create_sqlite_engine(database_path(settings))
    downgrade_to(engine, _previous())  # what the last release left behind
    engine.dispose()
    return settings, source


def test_an_import_refuses_an_old_database(old_workspace, capsys) -> None:  # type: ignore[no-untyped-def]
    _, source = old_workspace
    code, out = _ke(capsys, "import", str(source))
    assert code == 1 and out["error"]["code"] == "schema_mismatch"
    assert "ke db upgrade" in out["message"]


def test_upgrade_backs_up_first_and_the_backup_restores(old_workspace, capsys, tmp_path) -> None:  # type: ignore[no-untyped-def]
    settings, source = old_workspace
    code, out = _ke(capsys, "db", "upgrade")
    assert code == 0, out
    data = out["data"]
    assert data["changed"] and data["before"] == _previous() and data["after"] == head_revision()
    folder = tmp_path / "ws-backups" / data["backup"]  # next to the workspace, not in it
    assert verify_backup(folder).ok
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["schema_revision"] == _previous()  # the state before the upgrade
    # Rolling back = restoring that folder; it comes back at the old revision.
    assert restore_backup(folder, tmp_path / "rolled-back").ok
    engine = create_sqlite_engine(tmp_path / "rolled-back" / "knowledge.db")
    assert current_revision(engine) == _previous()
    engine.dispose()
    # And after the upgrade, imports work again.
    assert _ke(capsys, "import", str(source))[0] == 0
    code, out = _ke(capsys, "db", "upgrade")
    assert out["data"]["changed"] is False and out["data"]["backup"] is None


def test_no_backup_only_when_asked(old_workspace, capsys, tmp_path) -> None:  # type: ignore[no-untyped-def]
    code, out = _ke(capsys, "db", "upgrade", "--no-backup")
    assert code == 0 and out["data"]["changed"] and out["data"]["backup"] is None
    assert not (tmp_path / "ws-backups").exists()


def test_a_database_from_a_newer_version_is_refused(old_workspace, capsys) -> None:  # type: ignore[no-untyped-def]
    settings, source = old_workspace
    with sqlite3.connect(database_path(settings)) as db:
        db.execute("UPDATE alembic_version SET version_num = '9999_from_the_future'")
    code, out = _ke(capsys, "db", "upgrade")
    assert code == 1 and out["error"]["code"] == "upgrade_refused"
    assert "newer version" in out["message"]
    assert _ke(capsys, "import", str(source))[1]["error"]["code"] == "schema_mismatch"
