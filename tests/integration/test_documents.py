"""DOC-001: document content as data, and a changed record maps to exactly its documents."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DatabaseError
from sqlalchemy.orm import Session

from knowledge_engine.documents.dependencies import (
    DocumentBuildRow,
    affected_documents,
    latest_builds,
    register,
)
from knowledge_engine.documents.model import (
    DocumentKind,
    build_all,
    build_document,
    document_id,
)
from knowledge_engine.extraction import decisions
from knowledge_engine.extraction.records import CandidateRecord, KnowledgeRecord, Provenance
from knowledge_engine.extraction.runner import RuleExtractor, run
from knowledge_engine.extraction.store import KnowledgeRecordRow, add_candidates
from knowledge_engine.extraction.text import segment_extraction_messages
from knowledge_engine.importer import import_source
from knowledge_engine.importer.records import ConversationRow
from knowledge_engine.infrastructure.db import create_sqlite_engine, database_path
from knowledge_engine.reconciliation.supersession import reconcile
from knowledge_engine.rendering.transcript import load_conversation
from knowledge_engine.segmentation.segmenter import segment_conversation
from knowledge_engine.settings import Settings

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "chatgpt"


@pytest.fixture
def switch(tmp_path: Path) -> Iterator[tuple[Settings, Session]]:
    settings = Settings(workspace_root=tmp_path / "switch")
    import_source(FIXTURES / "engine_switch" / "export", "fixture", settings=settings)
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
    yield settings, session
    session.close()


def _chats(session: Session) -> dict[str, str]:
    """Native conversation ID suffix (1 or 2) -> conv_ ID."""
    return {
        native[-1]: conv
        for conv, native in session.execute(
            select(ConversationRow.conversation_id, ConversationRow.native_conversation_id)
        )
    }


def _records_in(session: Session, conversation_id: str) -> list[str]:
    return list(build_document(session, DocumentKind.CONVERSATION, conversation_id).record_ids)


def test_documents_are_data_with_statuses_in_a_fixed_order(
    switch: tuple[Settings, Session],
) -> None:
    _, session = switch
    chats = _chats(session)
    before = build_document(session, DocumentKind.CONVERSATION, chats["2"])
    assert before.document_id == document_id(DocumentKind.CONVERSATION, chats["2"])
    assert [s.key for s in before.sections] == ["current"]
    assert before == build_document(session, DocumentKind.CONVERSATION, chats["2"])
    reconcile(session)
    session.commit()
    after = build_document(session, DocumentKind.CONVERSATION, chats["2"])
    assert [s.key for s in after.sections] == ["current", "superseded"]
    [replaced] = after.sections[1].items
    assert replaced.superseded_by and replaced.because  # the label and the reason
    assert after.content_hash != before.content_hash
    assert after.revision_ids and set(after.record_ids) == set(before.record_ids)


def test_a_changed_record_maps_to_exactly_its_documents(
    switch: tuple[Settings, Session],
) -> None:
    _, session = switch
    chats = _chats(session)
    built = build_all(session)
    assert {d.kind for d in built} == {DocumentKind.CONVERSATION}  # no projects or topics here
    assert all(register(session, d).changed for d in built)
    session.commit()
    first_chat, second_chat = _records_in(session, chats["1"]), _records_in(session, chats["2"])
    one = first_chat[0]
    [hit] = affected_documents(session, [one])
    assert hit.document_id == document_id(DocumentKind.CONVERSATION, chats["1"])
    assert hit.reasons == (f"depends:{one}", f"selects:{one}")
    both = affected_documents(session, [one, second_chat[0]])
    assert {a.subject_id for a in both} == {chats["1"], chats["2"]}
    assert affected_documents(session, ["krec_" + "0" * 32]) == []
    # A revision maps to the documents that cite it.
    [cited] = build_document(session, DocumentKind.CONVERSATION, chats["1"]).revision_ids[:1]
    assert [a.subject_id for a in affected_documents(session, [cited])] == [chats["1"]]


def test_a_new_record_is_caught_by_the_selector(switch: tuple[Settings, Session]) -> None:
    _, session = switch
    chats = _chats(session)
    for document in build_all(session):
        register(session, document)
    session.commit()
    existing = KnowledgeRecord.model_validate_json(
        session.get_one(KnowledgeRecordRow, _records_in(session, chats["2"])[0]).record_json
    )
    fields = existing.model_dump(include=set(CandidateRecord.model_fields) - {"project_ids"})
    provenance = Provenance(
        stage_id="extract.test.v1", stage_key="stg_" + "e" * 64, extractor_version="t"
    )
    [added] = add_candidates(
        session, [CandidateRecord(**fields, project_ids=("proj_engine",))], provenance
    )
    session.commit()
    found = {
        (a.kind, a.subject_id): a.reasons for a in affected_documents(session, [added.record_id])
    }
    # Its chat's document (never built with it) and its project's (never built at all).
    assert found == {
        (DocumentKind.CONVERSATION, chats["2"]): (f"selects:{added.record_id}",),
        (DocumentKind.PROJECT, "proj_engine"): (f"selects:{added.record_id}",),
    }


def test_rebuilding_unchanged_documents_adds_nothing(switch: tuple[Settings, Session]) -> None:
    _, session = switch
    for document in build_all(session):
        register(session, document)
    session.commit()
    count = len(session.scalars(select(DocumentBuildRow)).all())
    assert not any(register(session, d).changed for d in build_all(session))
    assert len(session.scalars(select(DocumentBuildRow)).all()) == count
    reconcile(session)
    session.commit()
    changed = [d for d in build_all(session) if register(session, d).changed]
    session.commit()
    assert len(changed) == 1  # only the chat where Unity was replaced
    assert latest_builds(session)[changed[0].document_id].sequence == 2
    with pytest.raises(DatabaseError, match="append-only"):
        session.execute(text("DELETE FROM document_builds"))
    session.rollback()


def test_cli_docs(
    switch: tuple[Settings, Session],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from knowledge_engine.cli.main import main

    settings, session = switch
    chats = _chats(session)
    record = _records_in(session, chats["1"])[0]
    session.close()
    monkeypatch.setenv("KE_WORKSPACE_ROOT", str(settings.workspace_root))
    assert main(["--json", "docs", "build"]) == 0
    data = json.loads(capsys.readouterr().out)["data"]
    assert data["by_kind"] == {"conversation": 2} and len(data["changed"]) == 2
    assert main(["--json", "docs", "build"]) == 0
    assert json.loads(capsys.readouterr().out)["data"]["changed"] == []
    assert main(["--json", "docs", "affected", record]) == 0
    [doc] = json.loads(capsys.readouterr().out)["data"]["documents"]
    assert doc["subject_id"] == chats["1"]
