"""OPS-005: CI is one local command, and it never sees a model credential."""

from __future__ import annotations

from pathlib import Path

from knowledge_engine.devtools.ci import CHECKS, NIGHTLY, clean_environment, main

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"


def test_credentials_are_stripped_and_the_rest_kept() -> None:
    env = clean_environment(
        {
            "ANTHROPIC_API_KEY": "x",
            "SOME_VENDOR_API_KEY": "x",
            "GITHUB_AUTH_TOKEN": "x",
            "MY_SECRET": "x",
            "PATH": "/bin",
        }
    )
    assert env == {"PATH": "/bin", "KE_CI": "1"}


def test_the_workflow_only_runs_the_local_command_and_uses_no_secrets() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "secrets." not in text
    runs = [line.strip() for line in text.splitlines() if line.strip().startswith("- run:")]
    assert runs == [
        '- run: python -m pip install -e ".[dev]"',
        "- run: python -m knowledge_engine.devtools.ci",
        '- run: python -m pip install -e ".[dev]"',
        "- run: python -m knowledge_engine.devtools.ci --nightly",
    ]


def test_the_steps_cover_lint_types_guard_tests_and_the_bounded_nightly(capsys) -> None:  # type: ignore[no-untyped-def]
    assert [s.name for s in CHECKS] == ["lint", "format", "types", "guard", "tests"]
    assert [s.name for s in NIGHTLY] == ["gate", "variance", "e2e"]
    assert main(["--list"]) == 0 and main(["--nightly", "--list"]) == 0
    printed = capsys.readouterr().out
    assert "pytest" in printed and "eval gate" in printed
