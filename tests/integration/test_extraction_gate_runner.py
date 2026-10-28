"""EXT-007 / EXT-008: the promotion gate, reviewer decisions, and the extraction runner."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from knowledge_engine.domain.enums import Role
from knowledge_engine.extraction import decisions, preferences
from knowledge_engine.extraction.decisions import extract_decisions
from knowledge_engine.extraction.preferences import extract_preferences
from knowledge_engine.extraction.records import (
    Acceptance,
    CandidateRecord,
    Provenance,
    RecordType,
    Trust,
)
from knowledge_engine.extraction.runner import (
    DONE,
    FAILED,
    MAX_ATTEMPTS,
    ExtractionRunRow,
    ModelExtractor,
    RuleExtractor,
    run,
)
from knowledge_engine.extraction.store import (
    Decision,
    GateError,
    KnowledgeRecordRow,
    add_candidates,
    current_truth,
    decide,
    gate,
    history,
    review_queue,
)
from knowledge_engine.extraction.text import ExtractionMessage, segment_extraction_messages
from knowledge_engine.importer import import_source
from knowledge_engine.importer.records import ConversationRow
from knowledge_engine.infrastructure.db import create_sqlite_engine, database_path
from knowledge_engine.providers.base import FakeProvider, ModelRequest
from knowledge_engine.providers.ledger import ModelStageRunner
from knowledge_engine.rendering.transcript import load_conversation
from knowledge_engine.segmentation.segmenter import segment_conversation
from knowledge_engine.settings import EgressPolicy, Settings

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "chatgpt"
PROVENANCE = Provenance(
    stage_id="extract.test.v1", stage_key="stg_" + "a" * 64, extractor_version="test-v1"
)
Segments = list[tuple[str, list[ExtractionMessage]]]


@pytest.fixture
def world(tmp_path: Path) -> Iterator[tuple[Session, Segments]]:
    settings = Settings(workspace_root=tmp_path / "ws")
    import_source(FIXTURES / "extraction_rules" / "export", "fixture", settings=settings)
    engine = create_sqlite_engine(database_path(settings))
    with Session(engine) as session:
        segments: Segments = []
        for conversation_id in session.scalars(
            select(ConversationRow.conversation_id).order_by(ConversationRow.native_conversation_id)
        ).all():
            conv = load_conversation(session, conversation_id)
            segments += [
                (seg.segment_id, segment_extraction_messages(conv, seg))
                for seg in segment_conversation(conv)
            ]
        yield session, segments
    engine.dispose()


def _candidates(segments: Segments) -> list[CandidateRecord]:
    found = []
    for segment_id, messages in segments:
        found += extract_decisions(messages, segment_id=segment_id)
        found += extract_preferences(messages, segment_id=segment_id)
    return found


def test_unsupported_candidate_is_blocked_from_current_truth(
    world: tuple[Session, Segments],
) -> None:
    session, segments = world
    records = add_candidates(session, _candidates(segments), PROVENANCE)
    assert current_truth(session) == []  # nothing is true before the gate
    gated = [gate(session, r.record_id) for r in records]
    by_trust: dict[Trust, list[Any]] = {}
    for record in gated:
        by_trust.setdefault(record.trust, []).append(record)
    truth = {r.record_id for r in current_truth(session)}
    assert truth == {r.record_id for r in by_trust[Trust.SUPPORTED]}
    # Reported views wait for a person and stay out of current truth.
    waiting = by_trust[Trust.REVIEW_REQUIRED]
    assert waiting and all(r.attributed_to == "external" for r in waiting)
    assert {r.record_id for r in review_queue(session)} == {r.record_id for r in waiting}
    assert not truth & {r.record_id for r in waiting}
    # Re-adding the same extraction stores nothing new.
    count = session.query(KnowledgeRecordRow).count()
    add_candidates(session, _candidates(segments), PROVENANCE)
    assert session.query(KnowledgeRecordRow).count() == count


def test_malformed_and_unaccepted_records_never_reach_truth(
    world: tuple[Session, Segments],
) -> None:
    session, segments = world
    decision = next(r for r in _candidates(segments) if r.record_type is RecordType.DECISION)
    broken = decision.model_copy(
        update={"evidence": (decision.evidence[0].model_copy(update={"start": 0, "end": 3}),)}
    )
    # Good quotes, but the user never accepted: a suggestion isn't a decision.
    unaccepted = decision.model_copy(
        update={"acceptance": Acceptance.ABSENT, "review_reason": None}
    )
    [bad, unsure] = add_candidates(session, [broken, unaccepted], PROVENANCE)
    assert gate(session, bad.record_id).trust is Trust.REJECTED
    assert gate(session, unsure.record_id).trust is Trust.REVIEW_REQUIRED
    events = history(session, bad.record_id)
    assert [(e.from_trust, e.to_trust, e.actor) for e in events] == [
        (None, "candidate", "extract.test.v1"),
        ("candidate", "rejected", "validator"),
    ]
    assert "quote_mismatch" in events[-1].problems_json
    assert history(session, unsure.record_id)[-1].problems_json == '["record_rules"]'
    # A reviewer can't turn it into the user's decision either.
    with pytest.raises(ValueError, match="acceptance"):
        decide(session, unsure.record_id, Decision.SUPPORT, reviewer="reviewer-a")
    assert current_truth(session) == []


def test_reviewer_decisions_are_logged(world: tuple[Session, Segments]) -> None:
    session, segments = world
    records = add_candidates(session, _candidates(segments), PROVENANCE)
    with pytest.raises(GateError, match="gate first"):
        decide(session, records[0].record_id, Decision.CONFIRM, reviewer="reviewer-a")
    gated = [gate(session, r.record_id) for r in records]
    supported = next(r for r in gated if r.trust is Trust.SUPPORTED)
    waiting = next(r for r in gated if r.trust is Trust.REVIEW_REQUIRED)
    with pytest.raises(GateError, match="named reviewer"):
        decide(session, supported.record_id, Decision.CONFIRM, reviewer="validator")
    confirmed = decide(
        session, supported.record_id, Decision.CONFIRM, reviewer="reviewer-a", note="seen it"
    )
    assert (confirmed.trust, confirmed.reviewer) == (Trust.CONFIRMED, "reviewer-a")
    rejected = decide(
        session,
        waiting.record_id,
        Decision.REJECT,
        reviewer="reviewer-a",
        note="the client's view, not the user's",
    )
    assert rejected.trust is Trust.REJECTED
    assert history(session, waiting.record_id)[-1].note == "the client's view, not the user's"
    assert confirmed.record_id in {r.record_id for r in current_truth(session)}
    assert rejected.record_id not in {r.record_id for r in current_truth(session)}


def _rules() -> list[RuleExtractor]:
    return [
        RuleExtractor("decisions", decisions.EXTRACTOR_VERSION, extract_decisions),
        RuleExtractor("preferences", preferences.EXTRACTOR_VERSION, extract_preferences),
    ]


def test_runner_skips_done_work(world: tuple[Session, Segments]) -> None:
    session, segments = world
    first = run(session, segments, _rules())
    assert first.done and not (first.failed or first.pending)
    records = session.query(KnowledgeRecordRow).count()
    assert records == first.records > 0
    second = run(session, segments, _rules())
    assert (second.done, second.records) == ([], 0)
    assert sorted(second.skipped) == sorted(first.done)
    assert session.query(KnowledgeRecordRow).count() == records


def test_partial_failure_preserves_successful_stages_and_retry_is_bounded(
    world: tuple[Session, Segments],
) -> None:
    session, segments = world
    calls = {"n": 0}

    def broken(messages: Sequence[ExtractionMessage], *, segment_id: str) -> list[CandidateRecord]:
        calls["n"] += 1
        found = extract_decisions(messages, segment_id=segment_id)
        add_candidates(session, found, PROVENANCE)  # written, then the crash...
        raise RuntimeError("Synthetic crash after writing")

    extractors = [*_rules(), RuleExtractor("broken", "broken-v1", broken)]
    report = run(session, segments, extractors)
    assert len(report.failed) == len(segments)  # only the broken one failed
    assert len(report.done) == 2 * len(segments)  # the others all finished
    # ...and its half-written records were rolled back with it.
    stage_keys = {row.stage_key for row in session.scalars(select(KnowledgeRecordRow))}
    assert PROVENANCE.stage_key not in stage_keys
    for _ in range(MAX_ATTEMPTS + 2):
        report = run(session, segments, extractors)
    assert calls["n"] == MAX_ATTEMPTS * len(segments)  # never a fourth try
    assert len(report.gave_up) == len(segments)
    failed = session.scalars(select(ExtractionRunRow).where(ExtractionRunRow.state == FAILED))
    assert {(r.attempts, r.error) for r in failed} == {(MAX_ATTEMPTS, "RuntimeError")}
    done = session.scalars(select(ExtractionRunRow).where(ExtractionRunRow.state == DONE)).all()
    assert len(done) == 2 * len(segments)


def test_model_extractor_through_the_stage_runner(world: tuple[Session, Segments]) -> None:
    session, segments = world
    shed = next(msgs for _, msgs in segments if any("cedar" in m.text for m in msgs))
    target = next(m for m in shed if "cedar" in m.text)
    answers: dict[str, Any] = {"ready": False}

    def answer(request: ModelRequest) -> dict[str, Any] | None:
        if not answers["ready"]:
            return None  # not answered yet
        if "cedar" not in request.input_text:
            return {"records": []}
        return {
            "records": [
                {
                    "record_type": "decision",
                    "assertion": "Synthetic: cedar cladding",
                    "actor": "user",
                    "acceptance": "explicit",
                    "quotes": [
                        {
                            "message_id": target.native_id,
                            "text": "I've decided to use cedar cladding.",
                        }
                    ],
                },
                {
                    "record_type": "decision",
                    "assertion": "Synthetic: invented",
                    "actor": "user",
                    "acceptance": "explicit",
                    "quotes": [{"message_id": target.native_id, "text": "words never said"}],
                },
            ]
        }

    provider = FakeProvider(answer)
    runner = ModelStageRunner(session, provider, EgressPolicy(text_llm=True))
    extractor = ModelExtractor(
        "model_decisions", "model-v1", "prompt-v1", "Synthetic instructions.", runner
    )
    waiting = run(session, segments, [extractor])
    assert len(waiting.pending) == len(segments) and not waiting.failed
    answers["ready"] = True
    finished = run(session, segments, [extractor])
    assert len(finished.done) == len(segments)
    records = [
        r
        for r in current_truth(session)
        if r.provenance and r.provenance.prompt_version == "prompt-v1"
    ]
    assert [r.assertion for r in records] == ["Synthetic: cedar cladding"]
    assert records[0].actor is Role.USER  # the invented quote was not found: dropped
    calls = len(provider.submitted)
    run(session, segments, [extractor])
    assert len(provider.submitted) == calls  # done work: zero model requests
