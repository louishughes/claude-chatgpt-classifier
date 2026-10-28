"""UI-006: the read-only evaluation dashboard agrees with the EVAL-004 scorer."""

from __future__ import annotations

import io
import json
import re
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from knowledge_engine.evaluation.extraction_eval import ExtractionReport
from knowledge_engine.evaluation.report_labels import AI_HEADING, OWNER_HEADING, ReviewerKind
from knowledge_engine.evaluation.workspace_score import score_extraction
from knowledge_engine.extraction.store import KnowledgeRecordRow
from knowledge_engine.importer import import_source
from knowledge_engine.infrastructure.db import create_sqlite_engine, database_path
from knowledge_engine.settings import Settings
from knowledge_engine.ui.app import make_app
from knowledge_engine.ui.evaluation import KeySource

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
GOLD = FIXTURES / "gold" / "synthetic-v1" / "gold.json"
CASES = ("actions_entities", "extraction_rules")


def _call(
    settings: Settings, target: str, key: KeySource | None = None, method: str = "GET"
) -> tuple[str, str]:
    captured: dict[str, Any] = {}

    def start_response(status: str, headers: list[tuple[str, str]]) -> None:
        captured["status"] = status

    path, _, query = target.partition("?")
    environ: dict[str, Any] = {
        "REQUEST_METHOD": method,
        "PATH_INFO": path,
        "QUERY_STRING": query,
        "HTTP_HOST": "127.0.0.1:8765",
        "CONTENT_LENGTH": "0",
        "wsgi.input": io.BytesIO(b""),
    }
    body: Iterable[bytes] = make_app(settings, key)(environ, start_response)
    return captured["status"], b"".join(body).decode("utf-8")


@pytest.fixture(scope="module")
def scored(tmp_path_factory: pytest.TempPathFactory) -> tuple[Settings, ExtractionReport, Path]:
    root = tmp_path_factory.mktemp("ui6")
    settings = Settings(workspace_root=root / "ws")
    for case in CASES:
        import_source(FIXTURES / "chatgpt" / case / "export", "fixture", settings=settings)
    review = root / "REVIEW.md"
    review.write_text("synthetic review record\n", encoding="utf-8")
    engine = create_sqlite_engine(database_path(settings))
    with Session(engine) as session:
        # The scorer runs the rule extractors once; the dashboard never does.
        report = score_extraction(session, GOLD, ReviewerKind.AI_SESSION, review_file=review).report
        session.commit()
    engine.dispose()
    return settings, report, review


def _key(review: Path, kind: ReviewerKind = ReviewerKind.AI_SESSION) -> KeySource:
    return KeySource(GOLD, kind, review)


def test_overview_matches_the_scorer_and_says_who_checked(
    scored: tuple[Settings, ExtractionReport, Path],
) -> None:
    settings, report, review = scored
    status, body = _call(settings, "/evaluation", _key(review))
    assert status == "200 OK"
    assert AI_HEADING in body and OWNER_HEADING not in body
    assert "agent-reviewed, not owner-approved" in body
    total = report.total
    assert total.true_pos > 0
    row = re.search(r'<tr class="total"><td>all types</td>(.*?)</tr>', body)
    assert row is not None
    cells = re.findall(r"<td>([^<]*)</td>", row.group(1))
    assert cells == [
        str(total.true_pos),
        str(total.false_pos),
        str(total.false_neg),
        f"{total.precision:.3f}",
        f"{total.recall:.3f}",
        f"{total.f1:.3f}",
    ]
    assert ("PASSED" if report.passed else "FAILED") in body


def test_each_output_has_the_scorers_verdict(
    scored: tuple[Settings, ExtractionReport, Path],
) -> None:
    settings, report, review = scored
    status, body = _call(settings, "/evaluation/outputs", _key(review))
    assert status == "200 OK"
    total = report.total
    assert body.count('class="verdict matched"') == total.true_pos
    assert body.count('class="verdict extra"') == total.false_pos
    missed = body.split("Expected but missed", 1)[1] if total.false_neg else ""
    assert missed.count("<tr><td>") == total.false_neg
    # Filters narrow the list and keep the key block.
    status, body = _call(settings, "/evaluation/outputs?verdict=matched", _key(review))
    assert body.count('class="verdict matched"') == total.true_pos
    assert 'class="verdict extra"' not in body and AI_HEADING in body


def test_one_output_shows_quotes_check_history_and_comparison(
    scored: tuple[Settings, ExtractionReport, Path],
) -> None:
    settings, _, review = scored
    _, listing = _call(settings, "/evaluation/outputs?verdict=matched", _key(review))
    record_id = re.search(r'href="/evaluation/outputs/(krec_[0-9a-f]{32})"', listing)
    assert record_id is not None
    status, body = _call(settings, f"/evaluation/outputs/{record_id.group(1)}", _key(review))
    assert status == "200 OK"
    assert "matches the answer key" in body
    assert "<td>actor</td>" in body and "agrees" in body
    assert '<blockquote class="quote">' in body and "said it" in body
    assert "automatic evidence check (code, not a person)" in body
    assert AI_HEADING in body
    status, _ = _call(settings, "/evaluation/outputs/krec_" + "0" * 32, _key(review))
    assert status == "404 Not Found"


def test_owner_heading_only_for_an_owner_reviewed_key(
    scored: tuple[Settings, ExtractionReport, Path],
) -> None:
    settings, _, review = scored
    _, body = _call(settings, "/evaluation", _key(review, ReviewerKind.OWNER))
    assert OWNER_HEADING in body and AI_HEADING not in body


def test_without_a_key_nothing_is_scored(scored: tuple[Settings, ExtractionReport, Path]) -> None:
    settings, _, _ = scored
    status, body = _call(settings, "/evaluation")
    assert status == "200 OK"
    assert "No answer key loaded" in body and "Precision" not in body
    _, body = _call(settings, "/evaluation/outputs")
    assert "no answer key loaded" in body and 'class="verdict matched"' not in body
    _, body = _call(settings, "/evaluation", KeySource(Path("nope.json"), ReviewerKind.NONE))
    assert "wasn&#39;t found" in body or "wasn't found" in body


def test_dashboard_only_reads(scored: tuple[Settings, ExtractionReport, Path]) -> None:
    settings, _, review = scored
    engine = create_sqlite_engine(database_path(settings))
    with Session(engine) as session:
        before = sorted(
            (r.record_id, r.trust, r.updated_at)
            for r in session.scalars(select(KnowledgeRecordRow))
        )
    for page in ("/evaluation", "/evaluation/outputs"):
        status, body = _call(settings, page, _key(review))
        assert '<form method="post"' not in body.lower()
        status, _ = _call(settings, page, _key(review), method="POST")
        assert status in ("403 Forbidden", "405 Method Not Allowed")
    with Session(engine) as session:
        after = sorted(
            (r.record_id, r.trust, r.updated_at)
            for r in session.scalars(select(KnowledgeRecordRow))
        )
    engine.dispose()
    assert before == after


def test_ui_needs_a_reviewer_with_a_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from knowledge_engine.cli.main import main

    monkeypatch.setenv("KE_WORKSPACE_ROOT", str(tmp_path / "ws"))
    assert main(["--json", "ui", "--no-browser", "--gold", str(GOLD)]) != 0
    assert json.loads(capsys.readouterr().out)["error"]["code"] == "reviewer_required"


def test_extra_missed_and_forbidden_outputs_are_shown(
    scored: tuple[Settings, ExtractionReport, Path], tmp_path: Path
) -> None:
    settings, _, _ = scored
    # A changed copy of the synthetic key, in a temp folder (the committed
    # key is untouched): one expected proposal becomes a question, so the
    # produced proposal is extra and the question is missed; and the
    # reference quoting the same message is forbidden.
    gold = json.loads(GOLD.read_text(encoding="utf-8"))
    conversation = next(c for c in gold["conversations"] if c.get("records_annotated"))
    first = conversation["records"][0]
    reference = next(r for r in conversation["records"] if r["record_type"] == "reference")
    first["record_type"] = "question"
    conversation["forbidden"] = [
        {
            "record_type": "reference",
            "actor": reference["actor"],
            "message_id": reference["message_id"],
            "reason": "synthetic test rule",
        }
    ]
    changed = tmp_path / "gold.json"
    changed.write_text(json.dumps(gold), encoding="utf-8")
    key = KeySource(changed, ReviewerKind.NONE)
    engine = create_sqlite_engine(database_path(settings))
    with Session(engine) as session:
        report = score_extraction(session, changed, ReviewerKind.NONE, run_rules=False).report
        session.rollback()
    engine.dispose()
    assert report.total.false_pos >= 1 and report.total.false_neg >= 1
    assert report.forbidden_produced
    _, body = _call(settings, "/evaluation/outputs", key)
    assert body.count('class="verdict forbidden"') == len(report.forbidden_produced)
    # A forbidden record is shown as forbidden even if it also counted as
    # found or extra, so compare the remaining verdicts with that in mind.
    shown = body.count('class="verdict matched"') + body.count('class="verdict extra"')
    assert shown + len(report.forbidden_produced) == report.total.true_pos + report.total.false_pos
    missed = body.split("Expected but missed", 1)[1]
    assert missed.count("<tr><td>") == report.total.false_neg
    assert "not reviewed, not owner-approved" in body
    forbidden_id = report.forbidden_produced[0]
    _, page = _call(settings, f"/evaluation/outputs/{forbidden_id}", key)
    assert "synthetic test rule" in page and "must never be claimed" in page
