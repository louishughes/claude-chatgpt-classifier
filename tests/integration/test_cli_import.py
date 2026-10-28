"""UI-002: `ke import` runs the real importer and prints its report."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from knowledge_engine.cli.main import ExitCode, main

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


@pytest.fixture
def export(tmp_path: Path) -> Path:
    source = next(p for p in sorted(FIXTURES.rglob("conversations.json")))
    root = tmp_path / "export"
    shutil.copytree(source.parent, root)
    return root


def _run(capsys: pytest.CaptureFixture[str], argv: list[str]) -> tuple[int, dict[str, object]]:
    code = main(argv)
    return code, json.loads(capsys.readouterr().out)


def test_import_then_repeat_is_unchanged(
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    export: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("KE_WORKSPACE_ROOT", str(tmp_path / "ws"))
    code, first = _run(capsys, ["--json", "import", str(export)])
    assert code == ExitCode.OK
    data = first["data"]
    assert isinstance(data, dict)
    assert data["status"] == "succeeded"
    assert data["conversations"].get("new", 0) >= 1
    assert data["raw_tree_unchanged"] is True

    code, second = _run(capsys, ["--json", "import", str(export)])
    assert code == ExitCode.OK
    again = second["data"]
    assert isinstance(again, dict)
    assert set(again["conversations"]) <= {"unchanged"}

    code, report = _run(capsys, ["--json", "imports", "report", "latest"])
    assert code == ExitCode.OK
    assert report["data"]["import_id"] == again["import_id"]  # type: ignore[index]


def test_unsupported_source_is_a_plain_error(
    capsys: pytest.CaptureFixture[str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("KE_WORKSPACE_ROOT", str(tmp_path / "ws"))
    junk = tmp_path / "junk"
    junk.mkdir()
    (junk / "notes.txt").write_text("hello", encoding="utf-8")
    code, payload = _run(capsys, ["--json", "import", str(junk)])
    assert code == ExitCode.ERROR
    assert payload["error"] == {"code": "unsupported_format"}
    assert str(junk) not in json.dumps(payload)
