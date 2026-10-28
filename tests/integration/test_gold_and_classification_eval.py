"""EVAL-001 / EVAL-003: the golden set format, and the classification evaluation."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from knowledge_engine.classification.classifier import SegmentClassifier
from knowledge_engine.evaluation.classification_eval import (
    Predicted,
    evaluate_classification,
    predicted_from,
    stability,
)
from knowledge_engine.evaluation.gold import GoldSet, load_gold
from knowledge_engine.importer import import_source
from knowledge_engine.importer.records import ConversationRow
from knowledge_engine.infrastructure.db import create_sqlite_engine, database_path
from knowledge_engine.infrastructure.migrations import upgrade_to_head
from knowledge_engine.providers.base import FakeProvider, ModelRequest
from knowledge_engine.providers.ledger import ModelStageRunner, schema_failures
from knowledge_engine.rendering.transcript import StoredConversation, load_conversation
from knowledge_engine.segmentation.segmenter import Segment, segment_conversation
from knowledge_engine.settings import EgressPolicy, Settings

ROOT = Path(__file__).resolve().parents[1] / "fixtures"
GOLD_PATH = ROOT / "gold" / "synthetic-v1" / "gold.json"
GOLD = load_gold(GOLD_PATH)
Pairs = list[tuple[StoredConversation, Segment]]


def _import(cases: set[str], root: Path) -> Settings:
    settings = Settings(workspace_root=root)
    for case in sorted(cases):
        import_source(ROOT / "chatgpt" / case / "export", "fixture", settings=settings)
    return settings


@pytest.fixture(scope="module")
def stored(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Pairs]:
    cases = {c.fixture_case for c in GOLD.conversations if c.segments and c.fixture_case}
    settings = _import(cases, tmp_path_factory.mktemp("gold"))
    engine = create_sqlite_engine(database_path(settings))
    with Session(engine) as session:
        pairs: Pairs = []
        for conversation_id in session.scalars(
            select(ConversationRow.conversation_id).order_by(ConversationRow.native_conversation_id)
        ).all():
            conv = load_conversation(session, conversation_id)
            pairs += [(conv, seg) for seg in segment_conversation(conv)]
    engine.dispose()
    yield pairs


def test_synthetic_gold_points_at_real_fixture_messages() -> None:
    # An independent check of the answer key itself: every message it names exists.
    for conversation in GOLD.conversations:
        assert conversation.fixture_case is not None
        export = ROOT / "chatgpt" / conversation.fixture_case / "export"
        text = "".join(p.read_text("utf-8") for p in sorted(export.rglob("*.json")))
        assert conversation.native_conversation_id in text
        named = [s.first_message for s in conversation.segments]
        named += [r.message_id for r in conversation.records]
        named += [f.message_id for f in conversation.forbidden]
        for message_id in named:
            assert f'"{message_id}"' in text, message_id
    assert GOLD.synthetic and GOLD.snapshot().version == GOLD.taxonomy_version


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"synthetic": False}, "only a synthetic set"),
        ({"colour": "blue"}, "Extra inputs"),
        ({"schema_version": "gold-v0"}, "gold-v1"),
    ],
)
def test_annotation_schema_refuses_bad_sets(change: dict[str, Any], message: str) -> None:
    data = json.loads(GOLD_PATH.read_text("utf-8"))
    data.update(change)
    with pytest.raises(ValidationError, match=message):
        GoldSet.model_validate(data)
    segment = {"first_message": "m1", "labels": {"topic": {"secondary": ["term_x"]}}}
    with pytest.raises(ValidationError, match="need a primary"):
        GoldSet.model_validate(
            {
                **json.loads(GOLD_PATH.read_text("utf-8")),
                "conversations": [
                    {"native_conversation_id": "c", "annotator": "a", "segments": [segment]}
                ],
            }
        )


def test_template_is_private_ids_only_and_seeded(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from knowledge_engine.cli.main import main

    settings = _import({"mixed_projects", "extraction_rules", "topic_segments"}, tmp_path / "ws")
    monkeypatch.setenv("KE_WORKSPACE_ROOT", str(settings.workspace_root))
    args = ["--json", "gold", "template", "--count", "4", "--taxonomy", "tax-1"]
    assert main(args) == 0
    data = json.loads(capsys.readouterr().out)["data"]
    path = settings.workspace_root / "gold" / data["file"]
    first = path.read_text("utf-8")
    gold = load_gold(path)
    assert len(gold.conversations) == data["conversations"] == 4 and not gold.synthetic
    assert "Synthetic" not in first  # no titles, no text: IDs only
    # Annotation is hours of work: a second template never overwrites it.
    assert main(args) != 0
    assert path.read_text("utf-8") == first
    path.rename(path.with_suffix(".old"))
    assert main(args) == 0
    assert path.read_text("utf-8") == first  # same seed, same choice
    assert main(["--json", "gold", "schema"]) == 0


def test_committed_gold_sets_are_synthetic_only() -> None:
    # A real golden set holds private conversations and must never be committed.
    for path in sorted((ROOT / "gold").rglob("*.json")):
        gold = load_gold(path)
        assert gold.synthetic, path
        assert (path.parent / "SYNTHETIC").exists(), path
        for conversation in gold.conversations:
            assert conversation.fixture_case is not None
            assert (ROOT / "chatgpt" / conversation.fixture_case / "SYNTHETIC").exists()


@pytest.mark.parametrize(
    ("conversation", "message"),
    [
        ({"annotator": "a", "reviewed_by": "A"}, "must not be the annotator"),
        (
            {
                "annotator": "a",
                "records": [{"record_type": "action", "actor": "user", "message_id": "m"}],
            },
            "records_annotated",
        ),
        (
            {"annotator": "a", "segments": [{"first_message": "m"}, {"first_message": "m"}]},
            "share a first message",
        ),
        (
            {
                "annotator": "a",
                "segments": [{"first_message": "m", "labels": {"topic": {"primary": "nope"}}}],
            },
            "not in the topic vocabulary",
        ),
    ],
)
def test_annotation_rules(conversation: dict[str, Any], message: str) -> None:
    data = json.loads(GOLD_PATH.read_text("utf-8"))
    data["conversations"] = [{"native_conversation_id": "c", **conversation}]
    with pytest.raises(ValidationError, match=message):
        GoldSet.model_validate(data)


def test_baseline_report_has_confusion_and_versions(stored: Pairs) -> None:
    snapshot = GOLD.snapshot()
    classifier = SegmentClassifier(snapshot)
    predicted = predicted_from(stored, classifier.classify(stored))
    report = evaluate_classification(GOLD, predicted, {"classifier": classifier.method})
    assert report.gold_segments == 6 and report.unmatched_segments == 0
    assert report.versions == {"classifier": "keyword"}
    assert report.taxonomy_version == "tax-gold-1"
    topic = report.fields["topic"]
    assert topic.segments == 6
    assert sum(sum(row.values()) for row in topic.confusion.values()) == 6
    assert report.project_accuracy == report.fields["projects"].primary_accuracy
    text = report.as_markdown()
    assert "Confusion: topic" in text and "Synthetic" not in text
    # A second run under the same versions labels everything the same way.
    again = predicted_from(stored, classifier.classify(stored))
    assert stability([predicted, again]) == 1.0


def test_scores_by_hand() -> None:
    gold = GoldSet.model_validate(
        {
            "name": "hand",
            "synthetic": True,
            "taxonomy_version": "t",
            "conversations": [
                {
                    "native_conversation_id": "c",
                    "annotator": "a",
                    "segments": [
                        {
                            "first_message": "m1",
                            "labels": {"topic": {"primary": "a", "secondary": ["b"]}},
                        },
                        {"first_message": "m2", "labels": {"topic": {"primary": "b"}}},
                        {"first_message": "m3", "ambiguous": True},
                        {"first_message": "m4", "ambiguous": True},
                    ],
                }
            ],
        }
    )
    predicted = [
        Predicted("s1", "c", ("m1",), {"topic": ("a", ("c",))}),
        Predicted("s2", "c", ("m2",), {"topic": ("a", ())}),
        Predicted("s3", "c", ("m3",), {}, review=True),
        Predicted("s4", "c", ("m4",), {"topic": ("a", ())}),
    ]
    report = evaluate_classification(gold, predicted, {})
    topic = report.fields["topic"]
    # Gold {a,b} vs {a,c}; gold {b} vs {a}: tp 1, fp 2, fn 2.
    assert (topic.true_pos, topic.false_pos, topic.false_neg) == (1, 2, 2)
    assert topic.primary_accuracy == 0.5
    assert topic.confusion == {"a": {"a": 1}, "b": {"a": 1}}
    assert (report.ambiguous_flagged, report.ambiguous_missed) == (1, 1)
    changed = [Predicted("s1", "c", ("m1",), {"topic": ("b", ())}), *predicted[1:]]
    assert stability([predicted, changed]) == 0.75


def test_schema_failure_rate(tmp_path: Path) -> None:
    from pydantic import BaseModel, ConfigDict

    class Answer(BaseModel):
        model_config = ConfigDict(extra="forbid")
        ok: bool

    def request(n: int) -> ModelRequest:
        return ModelRequest(
            f"stg_{n:064x}", "test.stage.v1", "Synthetic.", "Synthetic.", Answer, "p1", "s1"
        )

    engine = create_sqlite_engine(tmp_path / "k.db")
    upgrade_to_head(engine)
    with Session(engine) as session:
        good = '{"ok": true}'
        provider = FakeProvider(lambda r: good if r.request_id.endswith("1") else "not json")
        runner = ModelStageRunner(session, provider, EgressPolicy(text_llm=True))
        requests = [request(1), request(2)]
        runner.submit(requests)
        runner.collect(requests)  # 1 stored; 2 gets its repair
        runner.collect(requests)  # the repair fails too
        assert schema_failures(session) == {
            "requests": 2,
            "repaired": 0,
            "review_required": 1,
            "first_try_failure_rate": 0.5,
        }
    engine.dispose()
