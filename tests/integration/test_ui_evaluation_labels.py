"""UI-006 part 2: segment labels and the model ledger on the evaluation dashboard."""

from __future__ import annotations

import io
import re
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from knowledge_engine.classification.classifier import SegmentClassifier
from knowledge_engine.classification.store import save
from knowledge_engine.evaluation.classification_eval import (
    ClassificationReport,
    evaluate_classification,
    predicted_from,
)
from knowledge_engine.evaluation.gold import load_gold
from knowledge_engine.evaluation.report_labels import AI_HEADING, OWNER_HEADING, ReviewerKind
from knowledge_engine.importer import import_source
from knowledge_engine.importer.records import ConversationRow
from knowledge_engine.infrastructure.db import create_sqlite_engine, database_path
from knowledge_engine.rendering.transcript import load_conversation
from knowledge_engine.segmentation.overrides import load_segments
from knowledge_engine.settings import Settings
from knowledge_engine.ui.app import make_app
from knowledge_engine.ui.evaluation import KeySource

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
GOLD = FIXTURES / "gold" / "synthetic-v1" / "gold.json"


def _call(settings: Settings, target: str, key: KeySource | None = None) -> tuple[str, str]:
    captured: dict[str, Any] = {}

    def start_response(status: str, headers: list[tuple[str, str]]) -> None:
        captured["status"] = status

    path, _, query = target.partition("?")
    environ: dict[str, Any] = {
        "REQUEST_METHOD": "GET",
        "PATH_INFO": path,
        "QUERY_STRING": query,
        "HTTP_HOST": "127.0.0.1:8765",
        "CONTENT_LENGTH": "0",
        "wsgi.input": io.BytesIO(b""),
    }
    body: Iterable[bytes] = make_app(settings, key)(environ, start_response)
    return captured["status"], b"".join(body).decode("utf-8")


@pytest.fixture(scope="module")
def classified(
    tmp_path_factory: pytest.TempPathFactory,
) -> tuple[Settings, ClassificationReport, Path]:
    root = tmp_path_factory.mktemp("ui6b")
    settings = Settings(workspace_root=root / "ws")
    gold = load_gold(GOLD)
    cases = sorted({c.fixture_case for c in gold.conversations if c.segments and c.fixture_case})
    for case in cases:
        import_source(FIXTURES / "chatgpt" / case / "export", "fixture", settings=settings)
    review = root / "REVIEW.md"
    review.write_text("synthetic review record\n", encoding="utf-8")
    engine = create_sqlite_engine(database_path(settings))
    with Session(engine) as session:
        pairs = [
            (conv, seg)
            for cid in session.scalars(select(ConversationRow.conversation_id)).all()
            for conv in [load_conversation(session, cid)]
            for seg in load_segments(session, conv)
        ]
        classifier = SegmentClassifier(gold.snapshot())
        results = classifier.classify(pairs)
        save(session, results)
        session.commit()
        # What the EVAL-003 report says about the same labels.
        report = evaluate_classification(
            gold, predicted_from(pairs, results), {"classifier": classifier.method}
        )
    engine.dispose()
    return settings, report, review


def test_field_scores_match_the_classification_scorer(
    classified: tuple[Settings, ClassificationReport, Path],
) -> None:
    settings, report, review = classified
    status, body = _call(
        settings, "/evaluation/classifications", KeySource(GOLD, ReviewerKind.AI_SESSION, review)
    )
    assert status == "200 OK"
    assert AI_HEADING in body and OWNER_HEADING not in body
    assert report.fields
    for name, score in report.fields.items():
        row = re.search(rf"<tr><td>{name}</td>(.*?)</tr>", body)
        assert row is not None, name
        cells = re.findall(r"<td>([^<]*)</td>", row.group(1))
        assert cells == [
            str(score.segments),
            f"{score.precision:.3f}",
            f"{score.recall:.3f}",
            f"{score.micro_f1:.3f}",
            f"{score.macro_f1:.3f}",
            f"{score.primary_accuracy:.3f}",
        ]
    assert f"not classified: {report.unmatched_segments}" in body
    assert body.count('<section class="segment">') == report.gold_segments
    # Readable names from the key's own vocabulary, not only IDs.
    gold = load_gold(GOLD)
    assert any(term.label in body for term in gold.terms)


def test_labels_page_without_a_key_scores_nothing(
    classified: tuple[Settings, ClassificationReport, Path],
) -> None:
    settings, _, _ = classified
    status, body = _call(settings, "/evaluation/classifications")
    assert status == "200 OK"
    assert "No answer key loaded" in body and "Primary right" not in body
    assert "Stored classifications:" in body


def test_overview_lists_model_requests_without_text(
    classified: tuple[Settings, ClassificationReport, Path],
) -> None:
    from knowledge_engine.providers.ledger import ModelRequestRow

    settings, _, _ = classified
    engine = create_sqlite_engine(database_path(settings))
    with Session(engine) as session:
        session.add(
            ModelRequestRow(
                stage_key="stg_" + "1" * 64,
                stage_id="classify.segment.v1",
                provider_id="fake",
                state="done",
                attempts=2,
                waiting_id="w1",
                characters=1234,
                transient_failures=1,
            )
        )
        session.commit()
    engine.dispose()
    _, body = _call(settings, "/evaluation")
    assert "<h2>Model requests</h2>" in body
    assert "<td><code>classify.segment.v1</code></td><td>fake</td><td>done</td>" in body
    assert "<td>1</td><td>2</td><td>1</td><td>1234</td>" in body


def test_ui_needs_the_review_record_for_a_reviewed_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import json

    from knowledge_engine.cli.main import main

    monkeypatch.setenv("KE_WORKSPACE_ROOT", str(tmp_path / "ws"))
    args = ["--json", "ui", "--no-browser", "--gold", str(GOLD), "--reviewer", "ai_session"]
    assert main(args) != 0
    assert json.loads(capsys.readouterr().out)["error"]["code"] == "review_required"
