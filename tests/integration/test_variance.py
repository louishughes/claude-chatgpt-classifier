"""EVAL-008: shuffled orders and pinned repeats give the same answers, or say so."""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

from knowledge_engine.evaluation.semantic_smoke import LocalFakeProvider
from knowledge_engine.evaluation.variance import (
    SOURCES,
    RunView,
    differences,
    pinned_fake,
    run_variance,
)
from knowledge_engine.providers.base import ModelRequest

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
SOURCE_PATHS = [FIXTURES / s for s in SOURCES]


def test_three_orders_and_pinned_repeats_agree(tmp_path: Path) -> None:
    report = run_variance(SOURCE_PATHS, tmp_path)
    assert len({run.order for run in report.runs}) == 3  # three genuinely different orders
    assert report.items == [] and report.stable and not report.silent_drift
    assert report.repeat_identical and report.repeat_new_requests == 0
    statuses = [json.loads(v)["status"] for v in report.runs[0].records.values()]
    assert "superseded" in statuses  # the replacement is judged the same way every time
    assert len(report.runs[0].classification) >= 10


def drifting(snapshot: Any, items: Sequence[Any]) -> LocalFakeProvider:
    """Failing-case reproduction: a model that never labels the first segment it sees."""
    base = pinned_fake(snapshot, items)
    asked: list[str] = []

    def answer(request: ModelRequest) -> Any:
        asked.append(request.input_text)
        if request.input_text == asked[0]:
            return '{"needs_review": true}'
        return base.answer(request)

    return LocalFakeProvider(answer)


def test_order_dependent_answers_become_review_items(tmp_path: Path) -> None:
    report = run_variance(SOURCE_PATHS[:2], tmp_path, provider_factory=drifting)
    assert report.items and not report.stable and not report.silent_drift
    for item in report.items:
        assert item.kind == "classification" and len(item.values) == 3
        assert len(set(item.values)) > 1  # each run's answer, side by side


def test_differences_lists_missing_keys() -> None:
    a = RunView(1, ("x",), {"k": "1", "same": "s"}, {})
    b = RunView(2, ("x",), {"same": "s"}, {"r": "current"})
    found = {(i.kind, i.key): i.values for i in differences([a, b])}
    assert found == {
        ("classification", "k"): ("1", "(absent)"),
        ("record", "r"): ("(absent)", "current"),
    }


def test_cli_eval_variance(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from knowledge_engine.cli.main import main

    monkeypatch.setenv("KE_WORKSPACE_ROOT", str(tmp_path / "ws"))
    assert main(["--json", "eval", "variance", "--fixtures", str(FIXTURES)]) == 0
    data = json.loads(capsys.readouterr().out)["data"]
    assert data["stable"] and data["repeat_new_requests"] == 0 and data["orders_differ"]
