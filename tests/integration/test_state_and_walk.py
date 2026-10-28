"""REC-006 / REC-007: current and as-of state, and a walk where every step cites its origin."""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from knowledge_engine.domain.enums import Role
from knowledge_engine.extraction import decisions
from knowledge_engine.extraction.records import (
    Acceptance,
    CandidateRecord,
    KnowledgeRecord,
    Provenance,
    RecordType,
)
from knowledge_engine.extraction.runner import RuleExtractor, run
from knowledge_engine.extraction.store import KnowledgeRecordRow, add_candidates, gate
from knowledge_engine.extraction.text import segment_extraction_messages
from knowledge_engine.importer import import_source
from knowledge_engine.importer.records import ConversationRow, MessageNodeRow, MessageRevisionRow
from knowledge_engine.infrastructure.db import create_sqlite_engine, database_path
from knowledge_engine.reconciliation.conflicts import detect_conflicts
from knowledge_engine.reconciliation.graph import Direction, walk
from knowledge_engine.reconciliation.projection import Status, project
from knowledge_engine.reconciliation.relations import place
from knowledge_engine.reconciliation.supersession import reconcile
from knowledge_engine.reconciliation.timeline import DecisionEventRow, build_events, revoke
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
    session.commit()
    return settings, session


@pytest.fixture
def switch(tmp_path: Path) -> Iterator[tuple[Settings, Session]]:
    settings, session = _world("engine_switch", tmp_path)
    yield settings, session
    session.close()


@pytest.fixture
def rules(tmp_path: Path) -> Iterator[Session]:
    _, session = _world("extraction_rules", tmp_path)
    yield session
    session.close()


def _decisions(session: Session) -> dict[str, tuple[str, float]]:
    """Native ID of the user message a decision cites -> (record ID, source time)."""
    native = dict(
        (rev, node)
        for rev, node in session.execute(
            select(MessageRevisionRow.revision_id, MessageNodeRow.native_node_id).join(
                MessageNodeRow, MessageNodeRow.node_key == MessageRevisionRow.node_key
            )
        )
    )
    rows = session.scalars(select(KnowledgeRecordRow))
    found = {}
    for item in place(session, [KnowledgeRecord.model_validate_json(r.record_json) for r in rows]):
        if item.record.record_type is RecordType.DECISION and item.first_time is not None:
            [user] = [e for e in item.record.evidence if e.actor is Role.USER]
            found[native[user.revision_id]] = (item.record.record_id, item.first_time)
    return found


def test_current_superseded_and_as_of(switch: tuple[Settings, Session]) -> None:
    _, session = switch
    found = _decisions(session)
    unity_kept = found[SWITCH["kept"]["decision"]][0]
    unity_old, _ = found[SWITCH["replaced"]["decision"]]
    godot, switched_at = found[SWITCH["replaced"]["switch"]]
    before = project(session)
    assert set(before.by_status(Status.CURRENT)) == {unity_kept, unity_old, godot}
    understood = datetime.now(UTC)
    reconcile(session)
    session.commit()
    now = project(session)
    assert set(now.by_status(Status.CURRENT)) == {unity_kept, godot}
    [old] = [e for e in now.entries if e.record_id == unity_old]
    assert old.status is Status.SUPERSEDED and old.superseded_by == (godot,)
    [event] = session.scalars(select(DecisionEventRow)).all()
    assert old.because == (event.event_id,)  # the explanation chain
    # Before the switch was said, Unity held in both chats and Godot didn't exist.
    earlier = project(session, as_of=switched_at - 1)
    assert set(earlier.by_status(Status.CURRENT)) == {unity_kept, unity_old}
    # As understood before the reconciler ran: reproducible, whatever came later.
    snapshot = project(session, known_at=understood)
    assert snapshot == project(session, known_at=understood)
    assert set(snapshot.by_status(Status.CURRENT)) == {unity_kept, unity_old, godot}
    # Scope filter: only the switch chat.
    godot_row = session.get_one(KnowledgeRecordRow, godot)
    [placed_godot] = place(session, [KnowledgeRecord.model_validate_json(godot_row.record_json)])
    chat = placed_godot.conversation_id
    assert chat is not None
    assert {e.record_id for e in project(session, conversation_id=chat).entries} == {
        unity_old,
        godot,
    }
    # Withdrawing the replacement puts Unity back, and the old answer stays reproducible.
    revoke(session, event.event_id, reviewer="review-session-7", note="Synthetic: misread")
    session.commit()
    assert set(project(session).by_status(Status.CURRENT)) == {unity_kept, unity_old, godot}
    assert project(session, known_at=understood) == snapshot


def test_unresolved_conflicts_stay_visible(rules: Session) -> None:
    rejection = next(
        KnowledgeRecord.model_validate_json(r.record_json)
        for r in rules.scalars(
            select(KnowledgeRecordRow).where(KnowledgeRecordRow.record_type == "rejection")
        )
    )
    fields = rejection.model_dump(
        include=set(CandidateRecord.model_fields) - {"record_type", "acceptance"}
    )
    accepted = CandidateRecord(
        **fields, record_type=RecordType.DECISION, acceptance=Acceptance.EXPLICIT
    )
    provenance = Provenance(
        stage_id="extract.test.v1", stage_key="stg_" + "f" * 64, extractor_version="t"
    )
    [decision] = add_candidates(rules, [accepted], provenance)
    gate(rules, decision.record_id)
    [conflict] = detect_conflicts(rules).added
    build_events(rules)
    state = project(rules)
    assert state.unresolved_conflicts == (conflict,)
    flagged = {e.record_id: e for e in state.entries if e.status is Status.CONFLICTED}
    assert set(flagged) == {rejection.record_id, decision.record_id}
    assert flagged[decision.record_id].conflicts_with == (rejection.record_id,)
    assert conflict in flagged[decision.record_id].because
    # Both a yes and a no point at the proposal: the later answer counts, both are kept.
    answered = [p for p in state.proposals if len(p.because) == 2]
    assert len(answered) == 1


def test_walk_follows_typed_edges_with_origins(rules: Session) -> None:
    build_events(rules)
    accept = rules.scalars(
        select(DecisionEventRow).where(DecisionEventRow.predicate == "accepts")
    ).first()
    assert accept is not None and accept.from_record and accept.to_record
    steps = walk(rules, accept.from_record)
    assert steps[0].depth == 0 and steps[0].status is Status.CURRENT
    reached = {s.record_id: s for s in steps[1:]}
    assert accept.to_record in reached
    edge = reached[accept.to_record].via
    assert edge is not None and edge.kind == "accepts" and edge.origin == "rec-004-v1"
    for step in steps[1:]:
        assert step.via is not None
        assert step.via.source_revisions and step.via.target_revisions  # every step cites
    # Filters: the decision points *to* the proposal, so walking inward finds nothing.
    assert [s.record_id for s in walk(rules, accept.from_record, direction=Direction.IN)] == [
        accept.from_record
    ]
    assert len(walk(rules, accept.from_record, kinds=["rejects"])) == 1
    back = walk(rules, accept.to_record, kinds=["accepts"], direction=Direction.IN)
    assert accept.from_record in {s.record_id for s in back}
    with pytest.raises(KeyError):
        walk(rules, "krec_missing")


def test_cli_state_and_walk(
    switch: tuple[Settings, Session],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from knowledge_engine.cli.main import main

    settings, session = switch
    found = _decisions(session)
    unity_old = found[SWITCH["replaced"]["decision"]][0]
    reconcile(session)
    session.commit()
    session.close()
    monkeypatch.setenv("KE_WORKSPACE_ROOT", str(settings.workspace_root))
    assert main(["--json", "state"]) == 0
    data = json.loads(capsys.readouterr().out)["data"]
    statuses = {e["record_id"]: e["status"] for e in data["entries"]}
    assert statuses[unity_old] == "superseded"
    assert main(["--json", "state", "--as-of", "not a date"]) != 0
    capsys.readouterr()
    assert main(["--json", "walk", unity_old, "--direction", "in"]) == 0
    steps = json.loads(capsys.readouterr().out)["data"]["steps"]
    assert [s["via"]["kind"] for s in steps[1:]] == ["supersedes"]
    assert "Godot" not in json.dumps(steps)
