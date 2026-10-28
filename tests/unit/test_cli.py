"""FND-008 acceptance: CLI help and invalid-invocation tests, plus output contracts."""

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from knowledge_engine.cli.main import ExitCode, main

SECRET = "sk-ant-SYNTHETIC-cli-test-key"


@pytest.fixture(autouse=True)
def _isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Run every test in an empty folder with no inherited KE_ settings.
    for name in list(os.environ):
        if name.startswith("KE_") or name == "ANTHROPIC_API_KEY":
            monkeypatch.delenv(name)
    monkeypatch.chdir(tmp_path)


def _json(capsys: pytest.CaptureFixture[str], argv: list[str]) -> tuple[int, dict[str, Any]]:
    code = main(argv)
    out = capsys.readouterr().out.strip().splitlines()
    assert len(out) == 1, "JSON mode prints exactly one line"
    payload: dict[str, Any] = json.loads(out[0])
    return code, payload


# ---------------------------------------------------------------- help and usage


def test_help_lists_commands(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["--help"])
    assert exit_info.value.code == 0
    out = capsys.readouterr().out
    for command in ("status", "db", "import"):
        assert command in out


def test_version_flag(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        main(["--version"])
    assert capsys.readouterr().out.startswith("ke ")


@pytest.mark.parametrize(
    "argv",
    [[], ["frobnicate"], ["db"], ["import"], ["import", "x", "--format", "pdf"], ["--nope"]],
)
def test_invalid_invocations_exit_with_usage(
    capsys: pytest.CaptureFixture[str], argv: list[str]
) -> None:
    assert main(argv) == ExitCode.USAGE
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "usage: ke" in captured.err


def test_usage_error_in_json_mode_is_one_json_object(capsys: pytest.CaptureFixture[str]) -> None:
    code, payload = _json(capsys, ["--json", "frobnicate"])
    assert code == ExitCode.USAGE
    assert payload["ok"] is False
    assert payload["error"] == {"code": "usage"}


# ---------------------------------------------------------------- status and db


def test_status_json_contract(capsys: pytest.CaptureFixture[str]) -> None:
    code, payload = _json(capsys, ["--json", "status"])
    assert code == ExitCode.OK
    assert set(payload) == {
        "schema_version",
        "command",
        "ok",
        "exit_code",
        "data",
        "message",
        "error",
    }
    assert payload["schema_version"] == 1
    assert payload["data"]["egress_enabled"] == []
    assert payload["data"]["database"]["exists"] is False


def test_status_does_not_create_the_workspace(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    main(["status"])
    capsys.readouterr()
    assert not (tmp_path / "workspace").exists()


def test_db_upgrade_then_status_is_up_to_date(capsys: pytest.CaptureFixture[str]) -> None:
    code, payload = _json(capsys, ["--json", "db", "upgrade"])
    assert code == ExitCode.OK and payload["data"]["changed"] is True
    code, payload = _json(capsys, ["--json", "db", "upgrade"])
    assert payload["data"]["changed"] is False  # idempotent
    _, status = _json(capsys, ["--json", "status"])
    assert status["data"]["database"]["revision"] == status["data"]["database"]["latest"]
    assert "ke db upgrade" not in status["message"]


def test_status_never_prints_raw_paths_or_secrets(
    capsys: pytest.CaptureFixture[str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", SECRET)
    raw = tmp_path / "private-raw-folder"
    config = tmp_path / "ke.toml"
    config.write_text(
        f'[[raw_roots]]\npath = "{raw.as_posix()}"\naccount_namespace = "fixture"\n',
        encoding="utf-8",
    )
    for mode in (["--json"], []):
        main([*mode, "--config", str(config), "status"])
        out = capsys.readouterr().out
        assert "private-raw-folder" not in out
        assert SECRET not in out
        assert "fixture" in out


# ---------------------------------------------------------------- errors


def test_import_reports_a_missing_source_plainly(
    capsys: pytest.CaptureFixture[str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Replaces the placeholder test now that `ke import` is wired (UI-002;
    # retired under the owner's delegated authority, OPEN_DECISIONS).
    monkeypatch.setenv("KE_WORKSPACE_ROOT", str(tmp_path / "ws"))
    code, payload = _json(capsys, ["--json", "import", str(tmp_path / "nowhere")])
    assert code == ExitCode.ERROR
    assert payload["error"] == {"code": "not_found"}
    assert str(tmp_path) not in payload["message"]  # never echoes the path


def test_invalid_config_exits_with_config_code(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    config = tmp_path / "ke.toml"
    config.write_text("[limits]\nmax_conversations_per_batch = 0\n", encoding="utf-8")
    code, payload = _json(capsys, ["--json", "--config", str(config), "status"])
    assert code == ExitCode.CONFIG
    assert "max_conversations_per_batch" in payload["message"]


def test_missing_config_file(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    code, payload = _json(capsys, ["--json", "--config", str(tmp_path / "absent.toml"), "status"])
    assert code == ExitCode.CONFIG
    assert "absent.toml" in payload["message"]


def test_secret_in_config_is_refused_without_echo(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    config = tmp_path / "ke.toml"
    config.write_text(f'anthropic_api_key = "{SECRET}"\n', encoding="utf-8")
    code, payload = _json(capsys, ["--json", "--config", str(config), "status"])
    assert code == ExitCode.CONFIG
    assert SECRET not in json.dumps(payload)


def test_exit_codes_are_stable() -> None:
    # Scripts depend on these numbers; changing one is a breaking change.
    assert {c.name: int(c) for c in ExitCode} == {
        "OK": 0,
        "ERROR": 1,
        "USAGE": 2,
        "CONFIG": 3,
        "NOT_IMPLEMENTED": 4,
        "BLOCKED": 5,
    }


def test_installed_ke_command_runs(tmp_path: Path) -> None:
    ke = Path(sys.executable).parent / ("ke.exe" if os.name == "nt" else "ke")
    result = subprocess.run(
        [str(ke), "--json", "status"], capture_output=True, text=True, cwd=tmp_path, check=False
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["command"] == "status"
