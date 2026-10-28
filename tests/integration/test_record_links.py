"""REC-002: only typed, allowed links between records, each citing its sources."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from functools import partial
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DatabaseError
from sqlalchemy.orm import Session

from knowledge_engine.domain.enums import Role
from knowledge_engine.domain.models import EvidenceRef
from knowledge_engine.extraction import actions, decisions, entities
from knowledge_engine.extraction.records import (
    Acceptance,
    KnowledgeRecord,
    Provenance,
    RecordType,
)
from knowledge_engine.extraction.runner import RuleExtractor, run
from knowledge_engine.extraction.store import KnowledgeRecordRow
from knowledge_engine.extraction.text import segment_extraction_messages
from knowledge_engine.importer import import_source
from knowledge_engine.importer.records import ConversationRow
from knowledge_engine.infrastructure.db import create_sqlite_engine, database_path
from knowledge_engine.reconciliation.relations import (
    LinkCandidate,
    LinkError,
    LinkState,
    Placed,
    Predicate,
    RecordLinkRow,
    allowed,
    find_links,
    links_of,
    propose_links,
    review_link,
    store_link,
)
from knowledge_engine.rendering.transcript import load_conversation
from knowledge_engine.segmentation.segmenter import segment_conversation
from knowledge_engine.settings import Settings

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "chatgpt"


@pytest.fixture
def session(tmp_path: Path) -> Iterator[Session]:
    settings = Settings(workspace_root=tmp_path / "ws")
    import_source(FIXTURES / "actions_entities" / "export", "fixture", settings=settings)
    engine = create_sqlite_engine(database_path(settings))
    with Session(engine) as session:
        conversations = [
            load_conversation(session, c)
            for c in session.scalars(select(ConversationRow.conversation_id)).all()
        ]
        segments = [
            (seg.segment_id, segment_extraction_messages(conv, seg))
            for conv in conversations
            for seg in segment_conversation(conv)
        ]
        occurrences = actions.load_occurrences(
            session, [r for c in conversations for r in c.revisions.values()]
        )
        run(
            session,
            segments,
            [
                RuleExtractor(
                    "decisions", decisions.EXTRACTOR_VERSION, decisions.extract_decisions
                ),
                RuleExtractor(
                    "actions",
                    actions.EXTRACTOR_VERSION,
                    partial(actions.extract_actions, occurrences=occurrences),
                ),
                RuleExtractor("entities", entities.EXTRACTOR_VERSION, entities.extract_entities),
            ],
        )
        yield session
    engine.dispose()


def _records(session: Session) -> dict[str, KnowledgeRecord]:
    rows = session.scalars(select(KnowledgeRecordRow))
    return {r.record_id: KnowledgeRecord.model_validate_json(r.record_json) for r in rows}


def test_fixture_links_are_typed_and_cite_sources(session: Session) -> None:
    before = {r.record_id: r.record_json for r in session.scalars(select(KnowledgeRecordRow))}
    report = propose_links(session)
    assert report.by_predicate == {"creates": 2, "references": 1}
    records = _records(session)
    for row in session.scalars(select(RecordLinkRow)):
        source, target = records[row.from_record], records[row.to_record]
        assert allowed(Predicate(row.predicate), source, target)
        evidence = json.loads(row.evidence_json)
        assert evidence["from_revisions"] and evidence["to_revisions"]
        assert row.state == "candidate"
        if row.predicate == "creates":
            assert target.record_type is RecordType.ARTEFACT
            assert source.actor is Role.USER  # the user's own task, the latest request
        else:
            assert target.record_type is RecordType.REFERENCE
            assert target.entity is not None
            assert target.entity.name.lower() in source.assertion.lower()
    again = propose_links(session)
    assert again.added == () and sorted(again.known) == sorted(report.added)
    after = {r.record_id: r.record_json for r in session.scalars(select(KnowledgeRecordRow))}
    assert after == before  # records are never edited


def test_reviews_are_named_and_append_only(session: Session) -> None:
    [first, *_] = propose_links(session).added
    with pytest.raises(LinkError, match="named reviewer"):
        review_link(session, first, LinkState.ACCEPTED, reviewer="")
    with pytest.raises(LinkError, match="accepted or rejected"):
        review_link(session, first, LinkState.CANDIDATE, reviewer="r")
    review_link(session, first, LinkState.ACCEPTED, reviewer="review-session-4", note="ok")
    with pytest.raises(LinkError, match="already accepted"):
        review_link(session, first, LinkState.ACCEPTED, reviewer="r")
    with pytest.raises(KeyError):
        review_link(session, "krl_missing", LinkState.ACCEPTED, reviewer="r")
    row = session.get_one(RecordLinkRow, first)
    assert [link.link_id for link in links_of(session, row.from_record, [LinkState.ACCEPTED])] == [
        first
    ]
    propose_links(session)
    assert session.get_one(RecordLinkRow, first).state == "accepted"
    session.commit()
    for statement in (
        "UPDATE record_link_reviews SET note = 'x'",
        "DELETE FROM record_link_reviews",
    ):
        with pytest.raises(DatabaseError, match="append-only"):
            session.execute(text(statement))
        session.rollback()


def test_store_refuses_untyped_or_uncited_links(session: Session) -> None:
    records = _records(session)
    question = next(r for r in records.values() if r.record_type is RecordType.QUESTION)
    artefact = next(r for r in records.values() if r.record_type is RecordType.ARTEFACT)
    cited = {"from_revisions": ["rev_x"], "to_revisions": ["rev_y"]}
    with pytest.raises(LinkError, match="not allowed"):
        store_link(
            session,
            LinkCandidate(question.record_id, Predicate.CREATES, artefact.record_id, cited),
        )
    action = next(r for r in records.values() if r.record_type is RecordType.ACTION)
    with pytest.raises(LinkError, match="cite"):
        store_link(
            session,
            LinkCandidate(action.record_id, Predicate.CREATES, artefact.record_id, {}),
        )
    with pytest.raises(LinkError, match="no such record"):
        store_link(
            session, LinkCandidate("krec_missing", Predicate.CREATES, artefact.record_id, cited)
        )
    assert session.scalars(select(RecordLinkRow)).all() == []


# Hand-built records for the detectors that the fixture doesn't exercise.


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


def _placed(record: KnowledgeRecord, chat: str, when: float) -> Placed:
    return Placed(record, chat, (record.evidence[0].revision_id,), when)


def test_elaborates_points_from_later_detail_to_earlier_claim() -> None:
    claim = _record(1, "Use SQLite for storage")
    detail = _record(2, "Use SQLite for storage with WAL mode and nightly backups")
    repeat = _record(3, "use sqlite for storage")  # REC-001's business, not elaboration
    other_person = _record(
        4,
        "Use SQLite for storage with WAL mode",
        actor=Role.ASSISTANT,
        acceptance=Acceptance.ABSENT,
        record_type=RecordType.PROPOSAL,
    )
    links = find_links(
        [
            _placed(claim, "conv_a", 10.0),
            _placed(detail, "conv_a", 20.0),
            _placed(repeat, "conv_a", 30.0),
            _placed(other_person, "conv_a", 40.0),
        ]
    )
    assert [(x.from_record, x.predicate, x.to_record) for x in links] == [
        (detail.record_id, Predicate.ELABORATES, claim.record_id)
    ]
    # Same words a moment *earlier* are not an elaboration of what follows.
    assert find_links([_placed(claim, "conv_a", 30.0), _placed(detail, "conv_a", 20.0)]) == []


def test_same_project_needs_another_chat_and_a_shared_topic() -> None:
    shared = {"project_ids": ("proj_synthetic",)}
    first = _record(1, "Ship the alpha", term_ids=("term_release",), **shared)
    later = _record(2, "Write release notes", term_ids=("term_release",), **shared)
    unrelated_topic = _record(3, "Buy a new chair", term_ids=("term_office",), **shared)
    same_chat = _record(4, "Tag the release", term_ids=("term_release",), **shared)
    links = find_links(
        [
            _placed(first, "conv_a", 10.0),
            _placed(later, "conv_b", 20.0),
            _placed(unrelated_topic, "conv_c", 30.0),
            _placed(same_chat, "conv_a", 40.0),
        ]
    )
    pairs = {(x.from_record, x.to_record) for x in links if x.predicate is Predicate.SAME_PROJECT}
    assert pairs == {(later.record_id, first.record_id), (same_chat.record_id, later.record_id)}
    [link] = [x for x in links if x.from_record == later.record_id]
    assert link.evidence["project_ids"] == ["proj_synthetic"]
    assert link.evidence["term_ids"] == ["term_release"]
