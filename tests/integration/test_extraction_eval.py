"""EVAL-004: extraction precision/recall, actors, anchors and forbidden records."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from functools import partial
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from knowledge_engine.domain.enums import Role
from knowledge_engine.evaluation.extraction_eval import (
    ScoredRecord,
    evaluate_extraction,
    scored_records,
)
from knowledge_engine.evaluation.gold import GoldSet, load_gold
from knowledge_engine.extraction import actions, decisions, entities, preferences
from knowledge_engine.extraction.evidence import VALIDATOR_VERSION
from knowledge_engine.extraction.records import (
    Acceptance,
    KnowledgeRecord,
    Provenance,
    RecordType,
    Trust,
)
from knowledge_engine.extraction.runner import RuleExtractor, run
from knowledge_engine.extraction.store import KnowledgeRecordRow, add_candidates, load
from knowledge_engine.extraction.text import ExtractionMessage, segment_extraction_messages
from knowledge_engine.importer import import_source
from knowledge_engine.importer.records import ConversationRow
from knowledge_engine.infrastructure.db import create_sqlite_engine, database_path
from knowledge_engine.rendering.transcript import load_conversation
from knowledge_engine.segmentation.segmenter import segment_conversation
from knowledge_engine.settings import Settings

ROOT = Path(__file__).resolve().parents[1] / "fixtures"
GOLD = load_gold(ROOT / "gold" / "synthetic-v1" / "gold.json")
CASES = ("actions_entities", "extraction_rules")
Segments = list[tuple[str, list[ExtractionMessage]]]


@pytest.fixture
def world(tmp_path: Path) -> Iterator[tuple[Session, Segments]]:
    settings = Settings(workspace_root=tmp_path / "ws")
    for case in CASES:
        import_source(ROOT / "chatgpt" / case / "export", "fixture", settings=settings)
    engine = create_sqlite_engine(database_path(settings))
    with Session(engine) as session:
        segments: Segments = []
        revisions: list[str] = []
        for conversation_id in session.scalars(
            select(ConversationRow.conversation_id).order_by(ConversationRow.native_conversation_id)
        ).all():
            conv = load_conversation(session, conversation_id)
            revisions += list(conv.revisions.values())
            segments += [
                (seg.segment_id, segment_extraction_messages(conv, seg))
                for seg in segment_conversation(conv)
            ]
        occurrences = actions.load_occurrences(session, revisions)
        extractors = [
            RuleExtractor("decisions", decisions.EXTRACTOR_VERSION, decisions.extract_decisions),
            RuleExtractor(
                "preferences", preferences.EXTRACTOR_VERSION, preferences.extract_preferences
            ),
            RuleExtractor(
                "actions",
                actions.EXTRACTOR_VERSION,
                partial(actions.extract_actions, occurrences=occurrences),
            ),
            RuleExtractor("entities", entities.EXTRACTOR_VERSION, entities.extract_entities),
        ]
        report = run(session, segments, extractors)
        assert report.done and not report.failed
        yield session, segments
    engine.dispose()


def _all(session: Session) -> list[KnowledgeRecord]:
    return [
        load(session, record_id)
        for record_id in session.scalars(
            select(KnowledgeRecordRow.record_id).order_by(KnowledgeRecordRow.record_id)
        )
    ]


def test_rule_extractors_pass_the_gate_on_the_synthetic_gold(
    world: tuple[Session, Segments],
) -> None:
    session, _ = world
    versions = {
        "decisions": decisions.EXTRACTOR_VERSION,
        "preferences": preferences.EXTRACTOR_VERSION,
        "actions": actions.EXTRACTOR_VERSION,
        "entities": entities.EXTRACTOR_VERSION,
        "validator": VALIDATOR_VERSION,
    }
    report = evaluate_extraction(GOLD, scored_records(session, _all(session)), versions)
    assert report.passed
    assert report.forbidden_in_truth == [] and report.unsupported_truth_decisions == []
    assert report.anchor_validity == 1.0
    # Twin records on one message (the user's preference and a client's)
    # are paired with the right gold record.
    assert report.agreement["attributed_to"].rate == 1.0
    total = report.total
    assert total.true_pos + total.false_neg == sum(
        len(c.records) for c in GOLD.conversations if c.records_annotated
    )
    assert "Synthetic" not in report.as_markdown()


def test_a_decision_that_skipped_the_gate_fails_the_evaluation(
    world: tuple[Session, Segments],
) -> None:
    # Failing-case reproduction: a bug writes an assistant suggestion into
    # current truth as the user's confirmed decision, bypassing the gate.
    session, segments = world
    proposal = next(
        r
        for r in _all(session)
        if r.record_type is RecordType.PROPOSAL and r.actor is Role.ASSISTANT
    )
    forged = proposal.model_copy(
        update={
            "record_type": RecordType.DECISION,
            "actor": Role.USER,
            "acceptance": Acceptance.EXPLICIT,
        }
    )
    [stored] = add_candidates(
        session,
        [forged],
        Provenance(
            stage_id="extract.bug.v1", stage_key="stg_" + "b" * 64, extractor_version="bug-v1"
        ),
    )
    row = session.get(KnowledgeRecordRow, stored.record_id)
    assert row is not None
    bypassed = stored.model_copy(update={"trust": Trust.CONFIRMED, "reviewer": "bug"})
    row.trust, row.record_json = bypassed.trust.value, bypassed.model_dump_json()
    session.flush()
    report = evaluate_extraction(GOLD, scored_records(session, _all(session)), {})
    assert not report.passed
    assert report.unsupported_truth_decisions == [stored.record_id]
    assert "FAILED" in report.as_markdown()


def _record(
    record_type: RecordType, actor: Role, n: int, trust: Trust = Trust.SUPPORTED
) -> KnowledgeRecord:
    # Built without validation: the evaluator only reads these fields.
    return KnowledgeRecord.model_construct(
        record_id=f"krec_{n:032x}",
        record_type=record_type,
        assertion="x",
        actor=actor,
        trust=trust,
        acceptance=Acceptance.EXPLICIT
        if record_type is RecordType.DECISION
        else Acceptance.NOT_APPLICABLE,
    )


def _item(
    record: KnowledgeRecord, messages: Sequence[str], conversation: str = "c"
) -> ScoredRecord:
    return ScoredRecord(record, conversation, tuple(messages), anchors_valid=True, user_words=True)


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
                    "records_annotated": True,
                    "records": [
                        {"record_type": "decision", "actor": "user", "message_id": "u1"},
                        {"record_type": "action", "actor": "user", "message_id": "u2"},
                        {"record_type": "proposal", "actor": "assistant", "message_id": "a1"},
                    ],
                    "forbidden": [
                        {
                            "record_type": "decision",
                            "actor": "user",
                            "message_id": "a1",
                            "reason": "a suggestion",
                        }
                    ],
                },
                {"native_conversation_id": "d", "annotator": "a"},
            ],
        }
    )
    produced = [
        _item(_record(RecordType.DECISION, Role.USER, 1), ["u1"]),  # right
        _item(_record(RecordType.ACTION, Role.ASSISTANT, 2), ["u2"]),  # right type, wrong actor
        _item(_record(RecordType.DECISION, Role.USER, 3), ["a1"]),  # forbidden, in truth
        _item(_record(RecordType.ACTION, Role.USER, 4, Trust.REJECTED), ["u9"]),  # ignored
        _item(_record(RecordType.ACTION, Role.USER, 5), ["d1"], "d"),  # unscored
    ]
    report = evaluate_extraction(gold, produced, {})
    assert {k: (s.true_pos, s.false_pos, s.false_neg) for k, s in report.by_type.items()} == {
        "action": (1, 0, 0),
        "decision": (1, 1, 0),
        "proposal": (0, 0, 1),
    }
    assert (report.agreement["actor"].checked, report.agreement["actor"].right) == (2, 1)
    assert (report.produced, report.unscored) == (4, 1)
    assert (
        report.forbidden_in_truth
        == report.unsupported_truth_decisions
        == ["krec_" + "0" * 31 + "3"]
    )
    assert not report.passed
