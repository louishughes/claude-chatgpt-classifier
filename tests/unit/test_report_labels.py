"""LEG-002 / REV-012: every scored report says what key it used and who reviewed it."""

from __future__ import annotations

from pathlib import Path

import pytest

from knowledge_engine.evaluation.classification_eval import Predicted, evaluate_classification
from knowledge_engine.evaluation.extraction_eval import evaluate_extraction
from knowledge_engine.evaluation.gold import GoldSet, load_gold
from knowledge_engine.evaluation.report_labels import (
    AI_HEADING,
    OWNER_HEADING,
    AnswerKey,
    ReviewerKind,
    key_from_file,
)

ROOT = Path(__file__).resolve().parents[2]
GOLD_PATH = ROOT / "tests" / "fixtures" / "gold" / "synthetic-v1" / "gold.json"
REVIEW = ROOT / "docs" / "reviews" / "GOLD_SYNTHETIC_V1_REVIEW.md"
SHA = "a" * 64


def _gold() -> GoldSet:
    return GoldSet.model_validate(
        {
            "name": "hand",
            "synthetic": True,
            "taxonomy_version": "t",
            "conversations": [
                {
                    "native_conversation_id": "c",
                    "annotator": "a",
                    "segments": [{"first_message": "m1", "labels": {"topic": {"primary": "x"}}}],
                }
            ],
        }
    )


def _reports(key: AnswerKey | None) -> list[str]:
    gold = _gold()
    predicted = [Predicted("s1", "c", ("m1",), {"topic": ("x", ())})]
    classification = evaluate_classification(gold, predicted, {}, key=key)
    extraction = evaluate_extraction(gold, [], {}, key=key)
    if key is None:  # evaluate fills a default key; take it away to test "unscored"
        classification.key = extraction.key = None
    return [classification.as_markdown(), extraction.as_markdown()]


@pytest.mark.parametrize("kind", ["ai_session", "same_model", "none", ReviewerKind.AI_SESSION])
def test_a_non_owner_review_never_renders_as_owner(kind: str) -> None:
    key = AnswerKey("hand (gold-v1)", SHA, kind, review_sha256=SHA)  # type: ignore[arg-type]
    for text in _reports(key):
        assert OWNER_HEADING not in text
        assert AI_HEADING in text and "not owner-approved" in text


def test_only_the_owner_gets_the_owner_heading() -> None:
    for text in _reports(AnswerKey("hand (gold-v1)", SHA, ReviewerKind.OWNER, SHA)):
        assert f"## {OWNER_HEADING}" in text and "owner-approved" in text


@pytest.mark.parametrize(
    ("key", "message"),
    [
        (AnswerKey(" ", SHA, ReviewerKind.NONE), "version"),
        (AnswerKey("v", "", ReviewerKind.NONE), "SHA-256"),
        (AnswerKey("v", SHA, ReviewerKind.AI_SESSION), "review file"),
    ],
)
def test_a_scored_report_missing_a_field_fails_to_render(key: AnswerKey, message: str) -> None:
    gold = _gold()
    report = evaluate_classification(gold, [], {}, key=key)
    with pytest.raises(ValueError, match=message):
        report.as_markdown()
    with pytest.raises(ValueError, match=message):
        evaluate_extraction(gold, [], {}, key=key).as_markdown()
    with pytest.raises(ValueError):
        AnswerKey("v", SHA, "boss")  # type: ignore[arg-type]


def test_no_key_prints_unscored_and_no_numbers() -> None:
    for text in _reports(None):
        assert "unscored" in text and "F1" not in text and "Precision" not in text


def test_default_key_claims_no_review_and_the_synthetic_key_is_agent_reviewed() -> None:
    text = _reports(AnswerKey("hand (gold-v1)", SHA, ReviewerKind.NONE))[0]
    assert "not reviewed, not owner-approved" in text
    key = key_from_file(GOLD_PATH, ReviewerKind.AI_SESSION, REVIEW)
    assert key.version == f"{load_gold(GOLD_PATH).name} (gold-v1)"
    assert key.label == "agent-reviewed, not owner-approved" and key.heading == AI_HEADING
    assert key.review_sha256 is not None and len(key.sha256) == 64
