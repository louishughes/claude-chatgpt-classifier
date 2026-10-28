"""RET-008: the pinned retrieval benchmark is reproducible and above its floors."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from knowledge_engine.evaluation.retrieval_bench import (
    QUERIES,
    THRESHOLDS,
    check,
    run_benchmark,
    to_markdown,
)

COMMITTED = Path(__file__).resolve().parents[2] / "docs" / "evaluation" / "RET-008_BENCHMARK.md"


def test_benchmark_is_reproducible_and_above_its_floors(tmp_path: Path) -> None:
    first = run_benchmark(tmp_path / "one")
    second = run_benchmark(tmp_path / "two")
    assert first == second  # wall time is left out of the comparison
    assert check(first) == []
    assert first.model_requests == 0
    # The committed report is exactly what a fresh run produces.
    assert to_markdown(first) == COMMITTED.read_text(encoding="utf-8")
    # The trade-off the benchmark exists to show: words find codes, not rewording.
    lexical, hybrid = first.scores["lexical"], first.scores["hybrid"]
    assert lexical.recall5_by_kind["paraphrase"] == 0.0
    assert hybrid.exact_term_hit == 1.0
    assert hybrid.recall[5] >= first.scores["semantic"].recall[5]


def test_a_drop_below_a_floor_is_reported(tmp_path: Path) -> None:
    report = run_benchmark(tmp_path)
    hybrid = report.scores["hybrid"]
    worse = type(hybrid)(**{**hybrid.__dict__, "mrr": 0.1})
    failed = type(report)(**{**report.__dict__, "scores": {**report.scores, "hybrid": worse}})
    assert check(failed) == [f"hybrid.mrr: 0.1 < {THRESHOLDS['hybrid']['mrr']}"]
    assert "FAIL" in to_markdown(failed)
    assert len({q.query_id for q in QUERIES}) == len(QUERIES)


def test_cli_eval_retrieval(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from knowledge_engine.cli.main import main

    monkeypatch.setenv("KE_WORKSPACE_ROOT", str(tmp_path / "ws"))
    out = tmp_path / "report.md"
    assert main(["--json", "eval", "retrieval", "--out", str(out)]) == 0
    data = json.loads(capsys.readouterr().out)["data"]
    assert data["failures"] == [] and data["model_requests"] == 0
    assert out.read_text(encoding="utf-8") == COMMITTED.read_text(encoding="utf-8")
