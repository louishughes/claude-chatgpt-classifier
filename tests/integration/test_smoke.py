"""Slice E: the batch smoke test (EVAL-010).

Acceptance (EVAL-010): 50- and 100-conversation batches import, re-import
with zero new logical records and render; a recorded report lists timings
and warnings; raw tree hash unchanged. The real-data half runs on the
owner's machine (REV-009); these tests cover the synthetic batches.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from knowledge_engine.cli.main import main
from knowledge_engine.evaluation.smoke import run_smoke
from knowledge_engine.evaluation.synthetic import generate_conversations, write_generated
from knowledge_engine.settings import load_settings

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "chatgpt"


@pytest.mark.parametrize("count", [50, 100])
def test_synthetic_batches_pass_the_smoke_test(tmp_path: Path, count: int) -> None:
    root = write_generated(tmp_path / "batch", count, seed=7) / "export"

    report = run_smoke(root, load_settings(workspace_root=tmp_path / "ws"))

    assert report["passed"], report["checks"]
    assert report["conversations"] == count
    assert report["reimport"]["added_records"] == {}
    assert report["render"] == {"notes": count, "broken_embeds": 0}
    assert set(report["timings_s"]) == {"import", "reimport", "render"}
    assert "warnings" in report["first_import"]
    # The report is numbers and codes: no titles or message text.
    conversations, _ = generate_conversations(count, seed=7)
    text = json.dumps(report)
    assert conversations[0]["title"] not in text
    assert "Synthetic question" not in text


def test_limit_imports_a_prefix_and_marks_nothing_missing(tmp_path: Path) -> None:
    report = run_smoke(
        FIXTURES / "export_single" / "export",
        load_settings(workspace_root=tmp_path / "ws"),
        limit=2,
    )

    assert report["passed"], report["checks"]
    assert report["conversations"] == 2
    assert "not_seen" not in report["first_import"]["conversations"]


def _cli(capsys: pytest.CaptureFixture[str], *args: str) -> tuple[int, dict[str, Any]]:
    capsys.readouterr()
    code = main(["--json", "eval", "smoke", *args])
    return code, json.loads(capsys.readouterr().out)


def test_cli_records_a_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("KE_WORKSPACE_ROOT", str(tmp_path / "ws"))

    code, payload = _cli(capsys, "--synthetic", "5", "--seed", "3")
    bad_code, bad = _cli(capsys)

    assert code == 0 and payload["data"]["checks"]["reimport_adds_nothing"] is True
    recorded = tmp_path / "ws" / "smoke" / payload["data"]["report"]
    assert json.loads(recorded.read_text(encoding="utf-8"))["passed"] is True
    assert (bad_code, bad["error"]) == (2, {"code": "usage"})
