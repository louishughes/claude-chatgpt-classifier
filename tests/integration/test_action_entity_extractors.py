"""EXT-005 / EXT-006: tasks, open questions, artefacts and named references."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from knowledge_engine.domain.enums import Role
from knowledge_engine.extraction.actions import extract_actions, load_occurrences
from knowledge_engine.extraction.entities import extract_entities
from knowledge_engine.extraction.evidence import Verdict, check_record
from knowledge_engine.extraction.records import CandidateRecord, RecordType
from knowledge_engine.extraction.text import ExtractionMessage, segment_extraction_messages
from knowledge_engine.importer import import_source
from knowledge_engine.importer.records import ConversationRow
from knowledge_engine.infrastructure.db import create_sqlite_engine, database_path
from knowledge_engine.rendering.transcript import StoredConversation, load_conversation
from knowledge_engine.segmentation.segmenter import segment_conversation
from knowledge_engine.settings import Settings
from knowledge_engine.taxonomy.aliases import AliasResolver
from knowledge_engine.taxonomy.registry import (
    ProjectRow,
    SnapshotProject,
    SnapshotTerm,
    TaxonomyProposalRow,
    TaxonomySnapshot,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "chatgpt"
EXPECTED: dict[str, Any] = json.loads(
    (FIXTURES / "actions_entities" / "manifest.json").read_text(encoding="utf-8")
)["expected"]
SNAPSHOT = TaxonomySnapshot(
    "tax-9",
    "f" * 64,
    terms=(SnapshotTerm("term_celeste", "topic", "Celeste", None, None, ()),),
    projects=(SnapshotProject("proj_garden", "Garden plan", ()),),
)
Chat = tuple[StoredConversation, list[tuple[str, list[ExtractionMessage]]]]


@pytest.fixture(scope="module")
def world(tmp_path_factory: pytest.TempPathFactory) -> Iterator[tuple[Session, dict[str, Chat]]]:
    settings = Settings(workspace_root=tmp_path_factory.mktemp("ext5"))
    import_source(FIXTURES / "actions_entities" / "export", "fixture", settings=settings)
    engine = create_sqlite_engine(database_path(settings))
    with Session(engine) as session:
        chats = {}
        for conversation_id in session.scalars(select(ConversationRow.conversation_id)):
            conv = load_conversation(session, conversation_id)
            chats[conv.title or ""] = (
                conv,
                [
                    (seg.segment_id, segment_extraction_messages(conv, seg))
                    for seg in segment_conversation(conv)
                ],
            )
        yield session, chats
    engine.dispose()


def _first_message(conv: StoredConversation, record: CandidateRecord) -> str | None:
    if not record.evidence:
        return None
    by_revision = {rev: native for native, rev in conv.revisions.items()}
    return by_revision[record.evidence[0].revision_id]


def _actions(session: Session, chat: Chat) -> list[CandidateRecord]:
    conv, segments = chat
    occurrences = load_occurrences(session, list(conv.revisions.values()))
    return [
        record
        for segment_id, messages in segments
        for record in extract_actions(messages, segment_id=segment_id, occurrences=occurrences)
    ]


def test_suggested_task_is_not_a_user_commitment_and_missing_artefact_is_reported(
    world: tuple[Session, dict[str, Chat]],
) -> None:
    session, chats = world
    chat = chats["Synthetic workshop tasks"]
    records = _actions(session, chat)
    got = [[r.record_type.value, r.actor.value, _first_message(chat[0], r)] for r in records]
    assert got == EXPECTED["actions"]
    suggested = [
        r for r in records if r.record_type is RecordType.ACTION and r.actor is Role.ASSISTANT
    ]
    assert suggested and all(r.acceptance.value == "absent" for r in suggested)
    [image] = [r for r in records if r.asset_occurrences]
    counts = {
        "available": len(image.asset_occurrences) - len(image.missing_occurrences),
        "missing": len(image.missing_occurrences),
    }
    assert counts == EXPECTED["artefact_occurrences"]
    check = check_record(session, image)
    assert check.verdict is Verdict.REVIEW_REQUIRED
    assert "artefact_bytes_missing" in [p.code for p in check.problems]
    # Every candidate's references are sound.
    for record in records:
        assert check_record(session, record).verdict is not Verdict.INVALID


def test_misstated_artefact_occurrences_are_rejected(
    world: tuple[Session, dict[str, Chat]],
) -> None:
    session, chats = world
    [image] = [
        r for r in _actions(session, chats["Synthetic workshop tasks"]) if r.asset_occurrences
    ]
    hidden = image.model_copy(update={"missing_occurrences": ()})  # pretends all are there
    assert check_record(session, hidden).verdict is Verdict.INVALID
    invented = image.model_copy(
        update={"asset_occurrences": ("occ_" + "0" * 32,), "missing_occurrences": ()}
    )
    assert [p.code for p in check_record(session, invented).problems][0] == "occurrence_missing"


def test_named_game_does_not_create_a_project(world: tuple[Session, dict[str, Chat]]) -> None:
    session, chats = world
    conv, segments = chats["Synthetic media chat"]
    resolver = AliasResolver(SNAPSHOT)
    projects = session.scalar(select(func.count()).select_from(ProjectRow))
    proposals = session.scalar(select(func.count()).select_from(TaxonomyProposalRow))
    records = [
        r
        for segment_id, messages in segments
        for r in extract_entities(messages, segment_id=segment_id, resolver=resolver)
    ]
    got = [
        [r.entity.entity_type.value, r.entity.name, len(r.evidence), r.entity.details]
        for r in records
        if r.entity
    ]
    assert got == EXPECTED["entities"][conv.native_conversation_id]
    by_name = {r.entity.name: r.entity for r in records if r.entity}
    assert by_name["Celeste"].matched_id == "term_celeste"  # an approved alias: linked
    assert by_name["Hollow Knight"].matched_id is None  # unknown game: nothing created
    assert session.scalar(select(func.count()).select_from(ProjectRow)) == projects
    assert session.scalar(select(func.count()).select_from(TaxonomyProposalRow)) == proposals
    for record in records:
        assert check_record(session, record).verdict is Verdict.VALID


def test_links_are_not_re_detected_as_entities() -> None:
    message = ExtractionMessage(
        "m1",
        "rev_" + "1" * 32,
        Role.USER,
        "Synthetic: see https://example.com/the%20game Hades and https://x.example/use Godot",
    )
    names = [r.entity.name for r in extract_entities([message], segment_id="s") if r.entity]
    assert names == []
