"""TEST_EVERYTHING.bat's report: every CI step, a clean environment, safe HTML."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path

import pytest

from knowledge_engine.devtools import test_report
from knowledge_engine.devtools.ci import CHECKS, NIGHTLY, Step
from knowledge_engine.devtools.test_report import AREAS, render_html, run_steps

ROOT = Path(__file__).resolve().parents[2]


class FakeRunner:
    """Writes a log and returns a chosen exit code instead of starting a process."""

    def __init__(self, failing: set[str], output: str = "line\n") -> None:
        self.failing = failing
        self.output = output
        self.envs: list[dict[str, str]] = []
        self.commands: list[tuple[str, ...]] = []

    def __call__(self, command: Sequence[str], env: Mapping[str, str], log_file: Path) -> int:
        self.envs.append(dict(env))
        self.commands.append(tuple(command))
        log_file.write_text(self.output, encoding="utf-8")
        return 1 if log_file.stem in self.failing else 0


def test_every_ci_step_has_plain_words() -> None:
    # A step added to CI without words here would show only its bare name.
    for step in (*CHECKS, *NIGHTLY):
        assert step.name in AREAS
        area = AREAS[step.name]
        assert area.title and area.proves and area.if_red


def test_every_step_runs_after_a_failure_with_no_credentials(tmp_path: Path) -> None:
    runner = FakeRunner(failing={"lint"})
    results = run_steps(
        [("everyday", CHECKS), ("nightly", NIGHTLY)],
        {"ANTHROPIC_API_KEY": "sk-x", "PATH": "/bin"},
        tmp_path,
        runner,
    )
    assert [r.name for r in results] == [s.name for s in (*CHECKS, *NIGHTLY)]
    assert runner.commands == [s.command for s in (*CHECKS, *NIGHTLY)]
    assert [r.passed for r in results] == [r.name != "lint" for r in results]
    assert all("ANTHROPIC_API_KEY" not in env and env["KE_CI"] == "1" for env in runner.envs)
    assert all(r.log_file.exists() for r in results)


def test_the_report_escapes_log_text_and_says_what_to_do(tmp_path: Path) -> None:
    runner = FakeRunner(failing={"tests"}, output="FAILED <script>alert(1)</script>\n")
    results = run_steps([("everyday", CHECKS)], {}, tmp_path, runner)
    page = render_html(results, datetime(2026, 10, 30, tzinfo=UTC))
    assert "<script>" not in page
    assert "&lt;script&gt;" in page
    assert "1 of 5 areas need attention" in page
    assert AREAS["tests"].if_red in page
    # Green lines carry no advice and no log tail.
    assert AREAS["lint"].if_red not in page
    assert page.count("<details>") == 1


def test_an_all_green_run_says_so(tmp_path: Path) -> None:
    results = run_steps([("everyday", CHECKS)], {}, tmp_path, FakeRunner(failing=set()))
    page = render_html(results, datetime(2026, 10, 30, tzinfo=UTC))
    assert "Everything passed" in page
    assert "<details>" not in page


def test_an_unknown_step_still_shows_up(tmp_path: Path) -> None:
    extra = Step("brand-new", ("python", "-c", "pass"))
    results = run_steps([("everyday", [extra])], {}, tmp_path, FakeRunner(failing={"brand-new"}))
    assert "brand-new" in render_html(results, datetime(2026, 10, 30, tzinfo=UTC))


def test_main_writes_the_report_and_fails_when_a_step_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = FakeRunner(failing={"types"})
    monkeypatch.setattr(test_report, "run_to_log", runner)
    code = test_report.main(["--quick", "--no-browser", "--out", str(tmp_path)])
    assert code == 1
    assert (tmp_path / "report.html").exists()
    # --quick leaves the nightly steps out.
    assert len(runner.commands) == len(CHECKS)


def test_the_batch_files_exist_and_call_the_report() -> None:
    text = (ROOT / "TEST_EVERYTHING.bat").read_text(encoding="utf-8")
    assert "knowledge_engine.devtools.test_report" in text
    assert '-e ".[dev]"' in text
    demo = (ROOT / "OPEN_DEMO_DASHBOARD.bat").read_text(encoding="utf-8")
    assert "KE_WORKSPACE_ROOT=%~dp0workspace\\demo" in demo
    assert (ROOT / "tests" / "fixtures" / "e2e" / "export.zip").exists()


def test_checks_run_in_utf8_mode(tmp_path: Path) -> None:
    runner = FakeRunner(failing=set())
    run_steps([("everyday", CHECKS)], {}, tmp_path, runner)
    assert all(env["PYTHONUTF8"] == "1" for env in runner.envs)


@pytest.mark.parametrize(
    ("seconds", "words"), [(5.2, "5s"), (59.6, "1m 0s"), (119.7, "2m 0s"), (754, "12m 34s")]
)
def test_durations_never_show_60_seconds(seconds: float, words: str) -> None:
    assert test_report._duration(seconds) == words


def test_access_tokens_are_stripped_too() -> None:
    # KE_YOUTUBE_ACCESS_TOKEN matched none of the older hints (OPS-011 review).
    from knowledge_engine.devtools.ci import clean_environment

    assert "KE_YOUTUBE_ACCESS_TOKEN" not in clean_environment({"KE_YOUTUBE_ACCESS_TOKEN": "x"})
