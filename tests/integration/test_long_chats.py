"""LEG-005: no clipping. Long segments are split into overlapping parts, never cut."""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from knowledge_engine.classification.classifier import REVIEW_REQUIRED, SegmentClassifier
from knowledge_engine.domain.enums import Role
from knowledge_engine.evaluation.classification_eval import (
    Predicted,
    evaluate_classification,
    predicted_from,
)
from knowledge_engine.evaluation.extraction_eval import evaluate_extraction
from knowledge_engine.evaluation.gold import GoldSet
from knowledge_engine.evaluation.semantic_smoke import smoke_taxonomy
from knowledge_engine.extraction import decisions
from knowledge_engine.extraction.records import RecordType, Trust
from knowledge_engine.extraction.runner import ModelExtractor, RuleExtractor, run
from knowledge_engine.extraction.store import current_truth
from knowledge_engine.extraction.text import segment_extraction_messages
from knowledge_engine.importer import import_source
from knowledge_engine.importer.records import ConversationRow
from knowledge_engine.infrastructure.db import create_sqlite_engine, database_path
from knowledge_engine.providers.base import FakeProvider, ModelRequest
from knowledge_engine.providers.ledger import ModelStageRunner
from knowledge_engine.rendering.transcript import StoredConversation, load_conversation
from knowledge_engine.segmentation.segmenter import (
    Segment,
    SegmenterSettings,
    segment_conversation,
    truncation_count,
)
from knowledge_engine.settings import EgressPolicy, Settings

CASE = Path(__file__).resolve().parents[1] / "fixtures" / "chatgpt" / "late_rejection"
EXPECTED = json.loads((CASE / "manifest.json").read_text("utf-8"))["expected"]
BUDGET = SegmenterSettings().max_characters
World = tuple[Session, StoredConversation, list[Segment]]


@pytest.fixture
def world(tmp_path: Path) -> Iterator[World]:
    settings = Settings(workspace_root=tmp_path / "ws")
    import_source(CASE / "export", "fixture", settings=settings)
    engine = create_sqlite_engine(database_path(settings))
    with Session(engine) as session:
        [conversation_id] = session.scalars(select(ConversationRow.conversation_id)).all()
        conv = load_conversation(session, conversation_id)
        yield session, conv, segment_conversation(conv)
    engine.dispose()


def _last(segments: list[Segment]) -> Segment:
    return next(s for s in segments if EXPECTED["rejection"] in s.messages)


def test_a_long_chat_is_split_into_overlapping_parts_with_nothing_clipped(world: World) -> None:
    _, conv, segments = world
    assert sum(len(n.text) for n in conv.messages.values()) > BUDGET
    segment = _last(segments)
    assert EXPECTED["proposal"] in segment.messages  # the "No." stays with its suggestion
    assert len(segment.parts) > 1
    assert truncation_count(segments) == 0
    covered = [m for part in segment.parts for m in part.messages]
    assert set(covered) == set(segment.messages)
    assert segment.parts[0].messages[0] == segment.messages[0]  # head kept
    assert segment.parts[-1].messages[-1] == segment.messages[-1]  # tail kept
    for left, right in zip(segment.parts, segment.parts[1:], strict=False):
        assert set(left.messages) & set(right.messages)  # neighbours overlap


def test_the_late_no_comes_out_as_the_users_rejection(world: World) -> None:
    session, conv, segments = world
    pairs = [(s.segment_id, segment_extraction_messages(conv, s)) for s in segments]
    extractor = RuleExtractor("decisions", decisions.EXTRACTOR_VERSION, decisions.extract_decisions)
    run(session, pairs, [extractor])
    [rejection] = current_truth(session, types=[RecordType.REJECTION])
    assert rejection.actor is Role.USER and rejection.trust is Trust.SUPPORTED
    quoted = {conv.revisions[native] for native in (EXPECTED["rejection"], EXPECTED["proposal"])}
    assert {ref.revision_id for ref in rejection.evidence} == quoted


def _markers(request: ModelRequest) -> list[str]:
    return re.findall(r"\[m:([^\]]+)\]", request.input_text)


def test_the_model_extractor_sends_every_part_and_merges(world: World) -> None:
    session, conv, segments = world
    segment = _last(segments)
    messages = segment_extraction_messages(conv, segment)
    no = next(m for m in messages if m.native_id == EXPECTED["rejection"])

    def answer(request: ModelRequest) -> dict[str, Any]:
        if f"[m:{no.native_id}]" not in request.input_text:
            return {"records": []}
        quote = {"message_id": no.native_id, "text": "No."}
        record = {
            "record_type": "rejection",
            "assertion": "Synthetic: not a red door",
            "actor": "user",
            "acceptance": "explicit",
            "quotes": [quote],
        }
        return {"records": [record]}

    provider = FakeProvider(answer)
    runner = ModelStageRunner(session, provider, EgressPolicy(text_llm=True))
    extractor = ModelExtractor("model_rejections", "m-v1", "p-v1", "Synthetic.", runner)
    report = run(session, [(segment.segment_id, messages)], [extractor])
    assert report.done
    assert len(provider.submitted) == len(segment.parts)
    sent = [m for request in provider.submitted for m in _markers(request)]
    assert set(sent) == {m.native_id for m in messages}  # every message went to the model
    assert all(len(r.input_text) <= BUDGET + 2_000 for r in provider.submitted)
    found = [
        r for r in current_truth(session) if r.provenance and r.provenance.prompt_version == "p-v1"
    ]
    assert len(found) == 1  # found in two overlapping parts at most, stored once


def test_classifier_parts_that_disagree_go_to_review(world: World) -> None:
    session, conv, segments = world
    segment = _last(segments)
    snapshot = smoke_taxonomy()
    labels = ["term_smoke_code", "term_smoke_image"]

    def answer(request: ModelRequest) -> dict[str, Any]:
        first = _markers(request)[0]
        term = labels[0] if first == segment.parts[0].messages[0] else labels[1]
        item = {"term_id": term, "rank": "primary", "confidence": 0.9, "evidence": [first]}
        return {"topic": [item]}

    runner = ModelStageRunner(session, FakeProvider(answer), EgressPolicy(text_llm=True))
    [result] = SegmentClassifier(snapshot, runner=runner).classify([(conv, segment)])
    assert result.state == REVIEW_REQUIRED
    assert any("parts" in p for p in result.problems)


def test_reports_show_truncation_and_length_bands(world: World) -> None:
    _, conv, segments = world
    items = [(conv, s) for s in segments]
    predicted = predicted_from(items, SegmentClassifier(smoke_taxonomy()).classify(items))
    gold = GoldSet.model_validate(
        {
            "name": "long",
            "synthetic": True,
            "taxonomy_version": "smoke-tax-1",
            "conversations": [
                {
                    "native_conversation_id": conv.native_conversation_id,
                    "annotator": "a",
                    "records_annotated": True,
                    "segments": [{"first_message": segments[0].messages[1]}],
                    "records": [
                        {
                            "record_type": "rejection",
                            "actor": "user",
                            "message_id": EXPECTED["rejection"],
                        }
                    ],
                }
            ],
        }
    )
    text = evaluate_classification(gold, predicted, {}).as_markdown()
    assert "Truncated messages: 0 (must be 0)" in text and "long (16k-64k)" in text
    clipped = [
        Predicted(
            p.segment_id,
            p.native_conversation_id,
            p.messages,
            p.labels,
            p.review,
            p.input_messages[:-1] if p.input_messages else (),
            p.chat_chars,
        )
        for p in predicted
    ]
    assert "Truncated messages: 0" not in evaluate_classification(gold, clipped, {}).as_markdown()
    chars = sum(len(n.text) for n in conv.messages.values())
    extraction = evaluate_extraction(
        gold,
        [],
        {},
        lengths={conv.native_conversation_id: chars},
        truncation_count=truncation_count(segments),
    ).as_markdown()
    assert "Truncated messages: 0 (must be 0)" in extraction
    assert "| long (16k-64k) | 1 | 0 | 0.000 |" in extraction
