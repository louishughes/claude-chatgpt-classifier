"""EVAL-007: one pass over every check, labelled, with a finite stop."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from knowledge_engine.evaluation.gate import (
    CHECKS,
    Check,
    GateInputs,
    Outcome,
    Status,
    run_gate,
    to_dict,
    to_markdown,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def _check(check_id: str, run: object) -> Check:
    return Check(check_id, "T-1", "threshold", "synthetic", "cmd", run)  # type: ignore[arg-type]


def test_each_check_runs_once_and_a_crash_does_not_stop_the_rest(tmp_path: Path) -> None:
    calls: list[str] = []

    def ok(_: GateInputs) -> Outcome:
        calls.append("ok")
        return Outcome(Status.PASS, "fine")

    def boom(_: GateInputs) -> Outcome:
        calls.append("boom")
        raise RuntimeError("disk on fire")

    def low(_: GateInputs) -> Outcome:
        calls.append("low")
        return Outcome(Status.FAIL, "recall 0.5")

    report = run_gate(
        GateInputs(FIXTURES, tmp_path), [_check("a", boom), _check("b", ok), _check("c", low)]
    )
    assert calls == ["boom", "ok", "low"]  # one pass, in order, never retried
    statuses = [r.outcome.status for r in report.results]
    assert statuses == [Status.FAIL, Status.PASS, Status.FAIL]
    assert report.results[0].outcome.notes == ("RuntimeError: disk on fire",)
    assert report.overall is Status.FAIL and not report.passed
    text = to_markdown(report, commit="abc123")
    tickets = text.split("## Tickets to file (FAIL)", 1)[1].split("##", 1)[0]
    assert "`a` (T-1): RuntimeError: disk on fire" in tickets and "`c`" in tickets


def test_overall_is_the_worst_label_and_only_fail_fails(tmp_path: Path) -> None:
    def label(status: Status) -> Check:
        return _check(status.value, lambda _: Outcome(status, "x"))

    report = run_gate(GateInputs(FIXTURES, tmp_path), [label(Status.PASS), label(Status.REVIEW)])
    assert report.overall is Status.REVIEW and report.passed
    report = run_gate(GateInputs(FIXTURES, tmp_path), [label(Status.REVIEW), label(Status.BLOCKED)])
    assert report.overall is Status.BLOCKED and report.passed
    assert run_gate(GateInputs(FIXTURES, tmp_path), []).overall is Status.PASS


def test_the_real_gate_on_this_repository(tmp_path: Path) -> None:
    report = run_gate(GateInputs(FIXTURES, tmp_path))
    found = {r.check.check_id: r.outcome.status for r in report.results}
    assert set(found) == {c.check_id for c in CHECKS}
    assert report.passed, to_markdown(report)
    # What can't be measured here says so instead of passing.
    assert found["quality.real_golden_set"] is Status.BLOCKED
    assert found["provider.real_smoke"] is Status.BLOCKED
    # Two true replacements wait for a person rather than being guessed.
    assert found["temporal.supersession"] is Status.REVIEW
    for row in to_dict(report)["checks"]:
        assert row["data"] in {"synthetic", "real"} and row["threshold"]


def test_cli_eval_gate(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from knowledge_engine.cli.main import main

    monkeypatch.setenv("KE_WORKSPACE_ROOT", str(tmp_path / "ws"))
    out = tmp_path / "gate.md"
    assert main(["--json", "eval", "gate", "--out", str(out), "--commit", "abc"]) == 0
    data = json.loads(capsys.readouterr().out)["data"]
    assert data["passed"] and data["counts"]["FAIL"] == 0
    assert "commit `abc`" in out.read_text(encoding="utf-8")
    assert main(["--json", "eval", "gate", "--fixtures", str(tmp_path / "none")]) == 2
