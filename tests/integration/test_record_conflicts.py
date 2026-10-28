"""REC-003: conflicts in overlapping scope only, stored unresolved, never decided by date."""

from __future__ import annotations

import hashlib
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
from knowledge_engine.extraction import decisions, preferences
from knowledge_engine.extraction.records import (
    Acceptance,
    CandidateRecord,
    KnowledgeRecord,
    Polarity,
    Provenance,
    RecordType,
)
from knowledge_engine.extraction.runner import RuleExtractor, run
from knowledge_engine.extraction.store import KnowledgeRecordRow, add_candidates
from knowledge_engine.extraction.text import segment_extraction_messages
from knowledge_engine.importer import import_source
from knowledge_engine.importer.records import ConversationRow
from knowledge_engine.infrastructure.db import create_sqlite_engine, database_path
from knowledge_engine.reconciliation.conflicts import (
    ConflictError,
    ConflictKind,
    ConflictState,
    conflicts,
    detect_conflicts,
    find_conflicts,
    review_conflict,
)
from knowledge_engine.reconciliation.relations import Placed
from knowledge_engine.rendering.transcript import load_conversation
from knowledge_engine.segmentation.segmenter import segment_conversation
from knowledge_engine.settings import Settings

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "chatgpt"


def _record(n: int, assertion: str, **extra: Any) -> KnowledgeRecord:
    fields: dict[str, Any] = {
        "record_id": "krec_" + f"{n:032x}",
        "record_type": RecordType.DECISION,
        "assertion": assertion,
        "actor": Role.USER,
        "acceptance": Acceptance.EXPLICIT,
        "scope_id": "seg_synthetic",
        "evidence": (
            EvidenceRef(
                revision_id="rev_" + f"{n:032x}",
                start=0,
                end=9,
                quote_sha256=hashlib.sha256(b"Synthetic").hexdigest(),
                actor=Role.USER,
            ),
        ),
        "provenance": Provenance(
            stage_id="extract.test.v1", stage_key="stg_" + "c" * 64, extractor_version="t"
        ),
        **extra,
    }
    return KnowledgeRecord.model_validate(fields)


def _placed(record: KnowledgeRecord, chat: str, when: float | None) -> Placed:
    return Placed(record, chat, (record.evidence[0].revision_id,), when)


def _kinds(items: list[Placed]) -> dict[tuple[str, str], tuple[ConflictKind, ...]]:
    return {(c.record_a, c.record_b): c.kinds for c in find_conflicts(items)}


def test_each_kind_of_conflict() -> None:
    port_a = _record(1, "Run the server on port 8080")
    port_b = _record(2, "Run the server on port 8081")
    docker = _record(3, "Deploy with Docker")
    no_docker = _record(4, "Don't deploy with Docker")
    tabs_for = _record(5, "I prefer tabs", record_type=RecordType.PREFERENCE, polarity=Polarity.FOR)
    tabs_against = _record(
        6, "I hate tabs", record_type=RecordType.PREFERENCE, polarity=Polarity.AGAINST
    )
    green = _record(7, "Paint the shed green")
    not_green = _record(8, "Paint the shed green", record_type=RecordType.REJECTION)
    found = _kinds(
        [
            _placed(port_a, "conv_a", 1.0),
            _placed(port_b, "conv_a", 2.0),
            _placed(docker, "conv_a", 3.0),
            _placed(no_docker, "conv_a", 4.0),
            _placed(tabs_for, "conv_a", 5.0),
            _placed(tabs_against, "conv_b", 6.0),  # personal preferences apply everywhere
            _placed(green, "conv_a", 7.0),
            _placed(not_green, "conv_a", 8.0),
        ]
    )
    assert found == {
        (port_a.record_id, port_b.record_id): (ConflictKind.NUMBERS,),
        (docker.record_id, no_docker.record_id): (ConflictKind.NEGATION,),
        (tabs_for.record_id, tabs_against.record_id): (ConflictKind.POLARITY,),
        (green.record_id, not_green.record_id): (ConflictKind.ACCEPTED_AND_REJECTED,),
    }


def test_different_projects_and_chats_are_not_false_conflicts() -> None:
    a = _record(1, "Run the server on port 8080", project_ids=("proj_alpha",))
    b = _record(2, "Run the server on port 8081", project_ids=("proj_beta",))
    c = _record(3, "Run the server on port 8082", project_ids=("proj_alpha",))
    d = _record(4, "Run the server on port 8083")  # no project, another chat
    e = _record(
        5,
        "Run the server on port 8084",
        actor=Role.ASSISTANT,
        record_type=RecordType.PROPOSAL,
        acceptance=Acceptance.ABSENT,
    )
    found = _kinds(
        [
            _placed(a, "conv_a", 1.0),
            _placed(b, "conv_b", 2.0),
            _placed(c, "conv_c", 3.0),
            _placed(d, "conv_d", 4.0),
            _placed(e, "conv_a", 5.0),
        ]
    )
    assert list(found) == [(a.record_id, c.record_id)]  # same project, other chat


def test_no_winner_by_time() -> None:
    a = _record(1, "Run the server on port 8080")
    b = _record(2, "Run the server on port 8081")
    [early] = find_conflicts([_placed(a, "conv_a", 1.0), _placed(b, "conv_a", 9.0)])
    [late] = find_conflicts([_placed(a, "conv_a", 9.0), _placed(b, "conv_a", 1.0)])
    [unknown] = find_conflicts([_placed(a, "conv_a", None), _placed(b, "conv_a", None)])
    assert early.conflict_id == late.conflict_id == unknown.conflict_id
    assert (early.evidence["order"], late.evidence["order"], unknown.evidence["order"]) == (
        "a_first",
        "b_first",
        "unknown",
    )
    assert early.kinds == late.kinds == unknown.kinds  # order is context, never a verdict


@pytest.fixture
def session(tmp_path: Path) -> Iterator[Session]:
    settings = Settings(workspace_root=tmp_path / "ws")
    import_source(FIXTURES / "extraction_rules" / "export", "fixture", settings=settings)
    engine = create_sqlite_engine(database_path(settings))
    with Session(engine) as session:
        segments = []
        for conversation_id in session.scalars(select(ConversationRow.conversation_id)).all():
            conv = load_conversation(session, conversation_id)
            segments += [
                (seg.segment_id, segment_extraction_messages(conv, seg))
                for seg in segment_conversation(conv)
            ]
        run(
            session,
            segments,
            [
                RuleExtractor(
                    "decisions", decisions.EXTRACTOR_VERSION, decisions.extract_decisions
                ),
                RuleExtractor(
                    "preferences", preferences.EXTRACTOR_VERSION, preferences.extract_preferences
                ),
            ],
        )
        yield session
    engine.dispose()


def test_stored_unresolved_with_reasoned_reviews(session: Session) -> None:
    assert detect_conflicts(session).added == ()  # the fixture alone has no conflict
    rejection = next(
        KnowledgeRecord.model_validate_json(r.record_json)
        for r in session.scalars(
            select(KnowledgeRecordRow).where(KnowledgeRecordRow.record_type == "rejection")
        )
    )
    # The same thing, later accepted in the same chat: a genuine conflict.
    fields = rejection.model_dump(
        include=set(CandidateRecord.model_fields) - {"record_type", "acceptance"}
    )
    accepted = CandidateRecord(
        **fields, record_type=RecordType.DECISION, acceptance=Acceptance.EXPLICIT
    )
    provenance = Provenance(
        stage_id="extract.test.v1", stage_key="stg_" + "d" * 64, extractor_version="t"
    )
    [decision] = add_candidates(session, [accepted], provenance)
    report = detect_conflicts(session)
    [conflict] = conflicts(session)
    assert report.added == (conflict.conflict_id,)
    assert json.loads(conflict.kinds_json) == ["accepted_and_rejected"]
    assert {conflict.record_a, conflict.record_b} == {rejection.record_id, decision.record_id}
    evidence = json.loads(conflict.evidence_json)
    assert evidence["a_revisions"] and evidence["b_revisions"]
    assert json.loads(conflict.scope_json)["by"] == "conversation"
    assert detect_conflicts(session).known == (conflict.conflict_id,)
    with pytest.raises(ConflictError, match="say why"):
        review_conflict(
            session, conflict.conflict_id, ConflictState.DISMISSED, reviewer="r", note=" "
        )
    review_conflict(
        session,
        conflict.conflict_id,
        ConflictState.RESOLVED,
        reviewer="review-session-5",
        note="Synthetic: the later acceptance replaces the rejection",
    )
    assert conflicts(session) == []
    detect_conflicts(session)
    assert [c.state for c in conflicts(session, list(ConflictState))] == ["resolved"]
    session.commit()
    for statement in (
        "UPDATE record_conflict_reviews SET note = 'x'",
        "DELETE FROM record_conflict_reviews",
    ):
        with pytest.raises(DatabaseError, match="append-only"):
            session.execute(text(statement))
        session.rollback()


def test_cli_reconcile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from knowledge_engine.cli.main import main

    settings = Settings(workspace_root=tmp_path / "ws")
    monkeypatch.setenv("KE_WORKSPACE_ROOT", str(settings.workspace_root))
    assert main(["--json", "reconcile"]) != 0  # nothing imported
    capsys.readouterr()
    import_source(FIXTURES / "actions_entities" / "export", "fixture", settings=settings)
    assert main(["--json", "reconcile"]) == 0
    data = json.loads(capsys.readouterr().out)["data"]
    assert data == {
        "duplicates_added": 0,
        "links_added": {},
        "conflicts_added": 0,
        "conflicts_unresolved": 0,
    }  # no records extracted yet: nothing to propose
