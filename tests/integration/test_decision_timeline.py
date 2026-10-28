"""REC-004 / REC-005: an append-only decision timeline; replacement only on explicit intent."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DatabaseError
from sqlalchemy.orm import Session

from knowledge_engine.domain.enums import Role
from knowledge_engine.domain.models import EvidenceRef
from knowledge_engine.extraction import decisions
from knowledge_engine.extraction.evidence import revision_text
from knowledge_engine.extraction.records import (
    Acceptance,
    CandidateRecord,
    KnowledgeRecord,
    Provenance,
    RecordType,
    Scope,
    Trust,
)
from knowledge_engine.extraction.runner import RuleExtractor, run
from knowledge_engine.extraction.store import (
    Decision,
    KnowledgeRecordRow,
    add_candidates,
    decide,
    gate,
)
from knowledge_engine.extraction.text import segment_extraction_messages
from knowledge_engine.graph.offsets import quote_hash
from knowledge_engine.importer import import_source
from knowledge_engine.importer.records import ConversationRow, MessageNodeRow, MessageRevisionRow
from knowledge_engine.infrastructure.db import create_sqlite_engine, database_path
from knowledge_engine.reconciliation.relations import Placed, place
from knowledge_engine.reconciliation.supersession import Outcome, reconcile
from knowledge_engine.reconciliation.timeline import (
    DecisionEventRow,
    Transition,
    TransitionError,
    build_events,
    record_event,
    revoke,
    timeline,
)
from knowledge_engine.rendering.transcript import load_conversation
from knowledge_engine.segmentation.segmenter import segment_conversation
from knowledge_engine.settings import Settings

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "chatgpt"
SWITCH: dict[str, Any] = json.loads(
    (FIXTURES / "engine_switch" / "manifest.json").read_text(encoding="utf-8")
)["expected"]


def _world(case: str, root: Path) -> tuple[Settings, Session]:
    settings = Settings(workspace_root=root / case)
    import_source(FIXTURES / case / "export", "fixture", settings=settings)
    session = Session(create_sqlite_engine(database_path(settings)))
    segments = []
    for conversation_id in session.scalars(select(ConversationRow.conversation_id)).all():
        conv = load_conversation(session, conversation_id)
        segments += [
            (seg.segment_id, segment_extraction_messages(conv, seg))
            for seg in segment_conversation(conv)
        ]
    rule = RuleExtractor("decisions", decisions.EXTRACTOR_VERSION, decisions.extract_decisions)
    run(session, segments, [rule])
    return settings, session


@pytest.fixture
def rules(tmp_path: Path) -> Iterator[Session]:
    _, session = _world("extraction_rules", tmp_path)
    yield session
    session.close()


@pytest.fixture
def switch(tmp_path: Path) -> Iterator[tuple[Settings, Session]]:
    settings, session = _world("engine_switch", tmp_path)
    yield settings, session
    session.close()


def _placed(session: Session) -> dict[str, Placed]:
    rows = session.scalars(select(KnowledgeRecordRow))
    records = [KnowledgeRecord.model_validate_json(r.record_json) for r in rows]
    return {p.record.record_id: p for p in place(session, records)}


def _by_message(session: Session) -> dict[str, str]:
    """Native ID of the user message a decision cites -> its record ID."""
    native = {
        rev: node
        for rev, node in session.execute(
            select(MessageRevisionRow.revision_id, MessageNodeRow.native_node_id).join(
                MessageNodeRow, MessageNodeRow.node_key == MessageRevisionRow.node_key
            )
        )
    }
    found = {}
    for item in _placed(session).values():
        if item.record.record_type is RecordType.DECISION:
            [user] = [e for e in item.record.evidence if e.actor is Role.USER]
            found[native[user.revision_id]] = item.record.record_id
    return found


def test_proposals_acceptances_and_rejections(rules: Session) -> None:
    report = build_events(rules)
    placed = _placed(rules)
    events = rules.scalars(select(DecisionEventRow)).all()
    assert report.added["proposes"] == sum(
        1 for p in placed.values() if p.record.record_type is RecordType.PROPOSAL
    )
    assert report.added["accepts"] >= 1 and report.added["rejects"] >= 1
    for event in events:
        source = placed[event.from_record].record if event.from_record else None
        target = placed[event.to_record].record if event.to_record else None
        if event.predicate == "accepts":
            assert source and target
            assert (source.record_type, target.record_type) == (
                RecordType.DECISION,
                RecordType.PROPOSAL,
            )
            assert {(e.revision_id, e.start, e.end) for e in source.evidence} & {
                (e.revision_id, e.start, e.end) for e in target.evidence
            }
            evidence = json.loads(event.evidence_json)
            assert evidence["from_revisions"] and evidence["to_revisions"]
        if event.predicate == "rejects":
            assert source and source.record_type is RecordType.REJECTION
    again = build_events(rules)
    assert again.added == {} and again.known == len(events)
    times = [e.happened_at for e in timeline(rules) if e.happened_at is not None]
    assert times == sorted(times)


def test_history_is_append_only_and_revocation_keeps_the_original(rules: Session) -> None:
    build_events(rules)
    accept = rules.scalars(
        select(DecisionEventRow).where(DecisionEventRow.predicate == "accepts")
    ).first()
    assert accept is not None
    with pytest.raises(TransitionError, match="reviewer and a reason"):
        revoke(rules, accept.event_id, reviewer="r", note="")
    revoke(rules, accept.event_id, reviewer="review-session-6", note="Synthetic: wrong proposal")
    with pytest.raises(TransitionError, match="already revoked"):
        revoke(rules, accept.event_id, reviewer="someone-else", note="again")
    entries = {e.event_id: e for e in timeline(rules, [accept.from_record])}
    assert entries[accept.event_id].revoked  # still there, marked
    [withdrawal] = [e for e in entries.values() if e.revokes_event == accept.event_id]
    assert withdrawal.predicate == "revokes" and withdrawal.actor == "review-session-6"
    rules.commit()
    for statement in ("UPDATE decision_events SET actor = 'x'", "DELETE FROM decision_events"):
        with pytest.raises(DatabaseError, match="append-only"):
            rules.execute(text(statement))
        rules.rollback()


def test_events_between_the_wrong_records_are_refused(rules: Session) -> None:
    placed = list(_placed(rules).values())
    proposal = next(p for p in placed if p.record.record_type is RecordType.PROPOSAL)
    decision = next(p for p in placed if p.record.record_type is RecordType.DECISION)
    with pytest.raises(TransitionError, match="from a decision to a proposal"):
        record_event(rules, Transition.ACCEPTS, proposal, decision, actor="r")
    with pytest.raises(TransitionError, match="needs a target"):
        record_event(rules, Transition.SUPERSEDES, decision, None, actor="r")
    with pytest.raises(TransitionError, match="decisions or requirements"):
        record_event(rules, Transition.SUPERSEDES, decision, proposal, actor="r")
    other = next(
        p
        for p in placed
        if p.record.record_type is RecordType.DECISION
        and p.record.record_id != decision.record.record_id
    )
    later, earlier = sorted((decision, other), key=lambda p: p.first_time or 0.0, reverse=True)
    with pytest.raises(TransitionError, match="later record to an earlier one"):
        record_event(rules, Transition.SUPERSEDES, earlier, later, actor="r")
    with pytest.raises(TransitionError, match="revoke"):
        record_event(rules, Transition.REVOKES, later, earlier, actor="r")


def test_only_the_explicit_switch_replaces_the_decision(switch: tuple[Settings, Session]) -> None:
    _, session = switch
    records = _by_message(session)
    kept, replaced = SWITCH["kept"], SWITCH["replaced"]
    assert kept["hypothetical"] not in records  # wondering is not deciding
    report = reconcile(session)
    assert report.superseded == ((records[replaced["switch"]], records[replaced["decision"]]),)
    # The same Unity decision in the other chat is untouched: no shared scope.
    events = session.scalars(
        select(DecisionEventRow).where(DecisionEventRow.predicate == "supersedes")
    ).all()
    assert [(e.from_record, e.to_record) for e in events] == list(report.superseded)
    assert records[kept["decision"]] not in {e.to_record for e in events}
    assert reconcile(session).superseded == report.superseded  # re-run adds nothing new
    assert (
        len(
            session.scalars(
                select(DecisionEventRow).where(DecisionEventRow.predicate == "supersedes")
            ).all()
        )
        == 1
    )


def test_a_hypothetical_decision_record_cannot_supersede(switch: tuple[Settings, Session]) -> None:
    _, session = switch
    records = _by_message(session)
    kept = SWITCH["kept"]
    # As if a model had wrongly turned "what if we switched to Godot?" into a decision.
    revision = session.scalars(
        select(MessageRevisionRow.revision_id)
        .join(MessageNodeRow, MessageNodeRow.node_key == MessageRevisionRow.node_key)
        .where(MessageNodeRow.native_node_id == kept["hypothetical"])
    ).one()
    stored = revision_text(session, revision)
    assert stored is not None
    words = stored[0]
    unity = _placed(session)[records[kept["decision"]]].record
    hypothetical = CandidateRecord(
        record_type=RecordType.DECISION,
        assertion="Switch to Godot for the game engine",
        actor=Role.USER,
        acceptance=Acceptance.EXPLICIT,
        scope=Scope.SEGMENT,
        scope_id=unity.scope_id,
        evidence=(
            EvidenceRef(
                revision_id=revision,
                start=0,
                end=len(words),
                quote_sha256=quote_hash(words),
                actor=Role.USER,
            ),
        ),
    )
    provenance = Provenance(
        stage_id="extract.model.test", stage_key="stg_" + "e" * 64, extractor_version="t"
    )
    [added] = add_candidates(session, [hypothetical], provenance)
    # The evidence gate already sends a question to review; suppose a reviewer
    # wrongly supported it anyway. REC-005 must still refuse the replacement.
    assert gate(session, added.record_id).trust is Trust.REVIEW_REQUIRED
    decide(session, added.record_id, Decision.SUPPORT, reviewer="careless-reviewer")
    report = reconcile(session)
    [verdict] = [v for v in report.review_required if v.later == added.record_id]
    assert verdict.earlier == unity.record_id
    assert verdict.outcome is Outcome.REVIEW_REQUIRED
    assert verdict.failed == ("hypothetical",)  # "switched to" alone is not enough
    assert added.record_id not in {later for later, _ in report.superseded}


def test_cli_timeline_build(
    switch: tuple[Settings, Session],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from knowledge_engine.cli.main import main

    settings, session = switch
    session.commit()
    session.close()
    monkeypatch.setenv("KE_WORKSPACE_ROOT", str(settings.workspace_root))
    assert main(["--json", "timeline", "--build"]) == 0
    data = json.loads(capsys.readouterr().out)["data"]
    assert data["superseded"] == 1
    assert [e["predicate"] for e in data["events"]] == ["supersedes"]
    assert "Godot" not in json.dumps(data)  # no message text
