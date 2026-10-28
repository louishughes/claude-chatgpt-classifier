"""OPS-009: `ke inspect --redact` prints ID prefixes; peak memory is never a bare null."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from knowledge_engine.cli.main import main
from knowledge_engine.evaluation import smoke
from knowledge_engine.importer import import_source
from knowledge_engine.settings import Settings

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "chatgpt"
NATIVE = "c0000002-0000-4000-8000-000000000002"


def test_inspect_redact_prints_only_a_prefix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    settings = Settings(workspace_root=tmp_path / "ws")
    import_source(FIXTURES / "branches_regen" / "export", "fixture", settings=settings)
    monkeypatch.setenv("KE_WORKSPACE_ROOT", str(settings.workspace_root))
    capsys.readouterr()

    assert main(["--json", "inspect", NATIVE]) == 0
    full = json.loads(capsys.readouterr().out)["data"]
    assert full["native_conversation_id"] == NATIVE  # local debugging: complete

    assert main(["--json", "inspect", NATIVE, "--redact"]) == 0
    redacted = json.loads(capsys.readouterr().out)["data"]
    assert redacted["native_conversation_id"] == NATIVE[:8]
    assert NATIVE not in json.dumps(redacted)
    assert {k: v for k, v in redacted.items() if k != "native_conversation_id"} == {
        k: v for k, v in full.items() if k != "native_conversation_id"
    }


def test_peak_memory_is_a_number_or_says_why() -> None:
    peak = smoke._peak_memory_mb()
    if sys.platform == "win32" or sys.platform.startswith(("linux", "darwin")):
        assert isinstance(peak, float) and peak > 0
    else:
        assert peak == smoke.UNAVAILABLE


def test_peak_memory_without_the_windows_api_says_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import ctypes

    monkeypatch.delattr(ctypes, "WinDLL", raising=False)
    assert smoke._windows_peak_mb() == smoke.UNAVAILABLE
