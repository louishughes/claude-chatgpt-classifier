"""Scoring a workspace against an answer key on disk (the real EVAL-004 baseline path)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from knowledge_engine.evaluation.report_labels import AI_HEADING, OWNER_HEADING
from knowledge_engine.importer import import_source
from knowledge_engine.settings import Settings

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
GOLD = FIXTURES / "gold" / "synthetic-v1" / "gold.json"
CASES = ("actions_entities", "extraction_rules")


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Settings:
    settings = Settings(workspace_root=tmp_path / "ws")
    for case in CASES:
        import_source(FIXTURES / "chatgpt" / case / "export", "fixture", settings=settings)
    monkeypatch.setenv("KE_WORKSPACE_ROOT", str(settings.workspace_root))
    return settings


def test_gold_score_runs_rules_once_and_reports_numbers(
    workspace: Settings, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from knowledge_engine.cli.main import main

    review = tmp_path / "REVIEW.md"
    review.write_text("synthetic review record\n", encoding="utf-8")
    out = tmp_path / "report.md"
    args = ["--json", "gold", "score", "--gold", str(GOLD), "--reviewer", "ai_session"]
    assert main([*args, "--review", str(review), "--out", str(out)]) == 0
    data = json.loads(capsys.readouterr().out)["data"]
    assert data["gate_passed"] and data["unsupported_truth_decisions"] == 0
    assert data["rule_runs"] > 0 and data["produced"] > 0
    assert data["found_conversations"] < data["key_conversations"]  # only two cases imported
    text = out.read_text(encoding="utf-8")
    assert AI_HEADING in text and OWNER_HEADING not in text
    assert "Synthetic" not in text  # numbers and IDs only, never chat text
    # Scoring again repeats no extraction work and gives the same numbers.
    assert main(args) == 0
    again = json.loads(capsys.readouterr().out)["data"]
    assert again["rule_runs"] == 0
    assert (again["precision"], again["recall"]) == (data["precision"], data["recall"])


def test_gold_score_refuses_a_missing_key(
    workspace: Settings, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from knowledge_engine.cli.main import main

    missing = tmp_path / "nope.json"
    assert main(["--json", "gold", "score", "--gold", str(missing), "--reviewer", "none"]) == 2
    assert json.loads(capsys.readouterr().out)["error"]["code"] == "missing"
