"""IMP-008 and OPS-010: how long each import stage took, and estimated tokens per stage.

Both are counts only: no message text is shown or stored. Synthetic data.
"""

from __future__ import annotations

import hashlib
import io
import json
import shutil
from collections.abc import Iterable
from pathlib import Path
from typing import Any, Literal

import pytest
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from knowledge_engine.cli.main import main
from knowledge_engine.importer.ledger import ImportBatchRow
from knowledge_engine.importer.report import TIMING_STAGES
from knowledge_engine.importer.run import run_import
from knowledge_engine.infrastructure.db import create_sqlite_engine, database_path
from knowledge_engine.orchestration.limits import estimate_tokens
from knowledge_engine.orchestration.stage_keys import stage_key
from knowledge_engine.providers.base import FakeProvider, ModelRequest
from knowledge_engine.providers.ledger import ModelStageRunner, token_estimates
from knowledge_engine.settings import EgressPolicy, Settings
from knowledge_engine.ui.app import make_app

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def _export(tmp_path: Path) -> Path:
    export = tmp_path / "export"
    shutil.copytree(FIXTURES / "chatgpt" / "export_single" / "export", export)
    return export


def _page(settings: Settings, path: str) -> str:
    captured: dict[str, Any] = {}

    def start_response(status: str, headers: list[tuple[str, str]]) -> None:
        captured["status"] = status

    environ = {
        "REQUEST_METHOD": "GET",
        "PATH_INFO": path,
        "QUERY_STRING": "",
        "HTTP_HOST": "127.0.0.1:8765",
        "CONTENT_LENGTH": "0",
        "wsgi.input": io.BytesIO(b""),
    }
    body: Iterable[bytes] = make_app(settings)(environ, start_response)
    assert captured["status"].startswith("200")
    return b"".join(body).decode("utf-8")


def test_the_import_report_says_how_long_each_stage_took(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    settings = Settings(workspace_root=tmp_path / "ws")
    report = run_import(_export(tmp_path), "acct", format_id=None, settings=settings)

    assert "timings" not in report.to_dict()  # what idempotency checks compare stays stable
    timings = report.to_stored()["timings"]
    assert list(timings) == list(TIMING_STAGES)
    assert all(isinstance(v, float) and v >= 0 for v in timings.values())
    parts = sum(v for k, v in timings.items() if k != "total")
    assert timings["total"] >= parts - 0.001

    monkeypatch.setenv("KE_WORKSPACE_ROOT", str(settings.workspace_root))
    assert main(["--json", "imports", "report", "latest"]) == 0
    data = json.loads(capsys.readouterr().out)["data"]
    assert data["timings"] == timings  # stored with the report, read back as written
    assert main(["imports", "report", "latest"]) == 0
    assert "How long it took: archive" in capsys.readouterr().out

    page = _page(settings, f"/imports/{report.import_id}")
    assert "<h2>How long it took</h2>" in page and "identity revisions" in page


def test_a_report_stored_before_timings_still_shows(tmp_path: Path) -> None:
    settings = Settings(workspace_root=tmp_path / "ws")
    report = run_import(_export(tmp_path), "acct", format_id=None, settings=settings)
    engine = create_sqlite_engine(database_path(settings))
    with Session(engine) as session:
        row = session.get(ImportBatchRow, report.import_id)
        assert row is not None
        counts = json.loads(row.counts_json or "{}")
        del counts["timings"]  # as an older version stored it
        row.counts_json = json.dumps(counts)
        session.commit()
    engine.dispose()
    page = _page(settings, f"/imports/{report.import_id}")
    assert "How long it took" not in page and "Import report" in page


class Label(BaseModel):
    model_config = ConfigDict(extra="forbid")

    domain: Literal["work", "home"]


def _request(stage: str, text: str) -> ModelRequest:
    key = stage_key(stage, hashlib.sha256(text.encode()).hexdigest(), {"code": "1"})
    return ModelRequest(key, stage, "Label it.", text, Label, "p1", "s1")


def test_tokens_are_estimated_per_stage_and_cached_answers_counted_apart(tmp_path: Path) -> None:
    assert estimate_tokens("") == 0
    assert estimate_tokens("abcd") == 1 and estimate_tokens("abcde") == 2  # rounded up
    settings = Settings(workspace_root=tmp_path / "ws")
    run_import(_export(tmp_path), "acct", format_id=None, settings=settings)
    engine = create_sqlite_engine(database_path(settings))
    with Session(engine) as session:
        answered = FakeProvider(lambda r: {"domain": "work"})
        silent = FakeProvider(lambda r: None)
        on = EgressPolicy(text_llm=True)
        digest = [_request("digest.conversation.v1", "Synthetic " + "x" * 30)]
        classify = [_request("classify.segment.v1", f"Synthetic {n}") for n in range(3)]
        runner = ModelStageRunner(session, answered, on)
        runner.submit(digest)
        runner.collect(digest)
        ModelStageRunner(session, silent, on).submit(classify)  # sent, never answered
        session.commit()
        totals = token_estimates(session)
        again = token_estimates(session)
    engine.dispose()

    assert totals == again  # deterministic
    assert totals["digest"] == {
        "requests": 1,
        "cached": 1,
        "input_tokens": -(-digest[0].characters // 4),  # characters / 4, rounded up
        "output_tokens": estimate_tokens(Label(domain="work").model_dump_json()),
    }
    assert totals["classify"]["requests"] == 3 and totals["classify"]["cached"] == 0
    assert totals["classify"]["input_tokens"] == sum(-(-r.characters // 4) for r in classify)
    assert totals["extract"] == dict.fromkeys(totals["extract"], 0)
