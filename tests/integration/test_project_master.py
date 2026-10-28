"""DOC-004: the project master labels every choice; old ones never pass for current."""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from knowledge_engine.documents.render import Mode, project_master, record_anchor
from knowledge_engine.documents.render import write_project_master as write_master
from knowledge_engine.extraction import decisions
from knowledge_engine.extraction.records import (
    CandidateRecord,
    KnowledgeRecord,
    Provenance,
    RecordType,
    Trust,
)
from knowledge_engine.extraction.runner import RuleExtractor, run
from knowledge_engine.extraction.store import KnowledgeRecordRow, add_candidates, gate
from knowledge_engine.extraction.text import segment_extraction_messages
from knowledge_engine.importer import import_source
from knowledge_engine.importer.records import ConversationRow
from knowledge_engine.infrastructure.db import create_sqlite_engine, database_path
from knowledge_engine.reconciliation.supersession import reconcile
from knowledge_engine.rendering.markdown import render_note
from knowledge_engine.rendering.transcript import load_conversation, write_transcript
from knowledge_engine.segmentation.segmenter import segment_conversation
from knowledge_engine.settings import Settings

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "chatgpt"
PROJECT = "proj_engine"


@pytest.fixture
def engine_project(tmp_path: Path) -> Iterator[tuple[Settings, Session, dict[str, str]]]:
    """The engine_switch chats, with every decision also filed under one project."""
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
    provenance = Provenance(
        stage_id="extract.test.v1", stage_key="stg_" + "d" * 64, extractor_version="t"
    )
    filed: dict[str, str] = {}  # assertion -> project copy's record ID
    for row in session.scalars(
        select(KnowledgeRecordRow).where(KnowledgeRecordRow.record_type == "decision")
    ).all():
        original = KnowledgeRecord.model_validate_json(row.record_json)
        fields = original.model_dump(include=set(CandidateRecord.model_fields) - {"project_ids"})
        [copy] = add_candidates(
            session, [CandidateRecord(**fields, project_ids=(PROJECT,))], provenance
        )
        assert gate(session, copy.record_id).trust is Trust.SUPPORTED
        filed[copy.record_id] = original.assertion
    reconcile(session)
    session.commit()
    yield settings, session, filed
    session.close()


def _godot(filed: dict[str, str]) -> str:
    [record] = [r for r, text in filed.items() if "Godot" in text]
    return record


def test_replaced_choices_are_labelled_and_linked(
    engine_project: tuple[Settings, Session, dict[str, str]],
) -> None:
    _, session, filed = engine_project
    godot = _godot(filed)
    text = render_note(project_master(session, PROJECT))
    headings = re.findall(r"^## (.+)$", text, flags=re.MULTILINE)
    assert headings[:2] == ["Current", "Replaced"]
    assert {"Dependencies", "Decision timeline", "Sources"} <= set(headings)
    # Every record paragraph is followed by its status label: nothing unlabelled.
    for record in filed:
        anchor = f"^{record_anchor(record)}"
        assert anchor in text
        after = text.split(anchor, 1)[1]
        assert re.match(r"\n\n- \*\*(Current|Replaced)\*\* decision", after), record
    replaced = [r for r in filed if r != godot]
    for record in replaced:
        line = text.split(f"^{record_anchor(record)}", 1)[1].splitlines()[2]
        assert line.startswith("- **Replaced** decision")
        assert f"replaced by [[#^{record_anchor(godot)}]]" in line
    assert f"[[#^{record_anchor(godot)}]] **supersedes**" in text


def test_modes_split_current_from_history(
    engine_project: tuple[Settings, Session, dict[str, str]],
) -> None:
    _, session, filed = engine_project
    godot = _godot(filed)
    current = render_note(project_master(session, PROJECT, mode=Mode.CURRENT))
    assert f"^{record_anchor(godot)}" in current
    assert "## Replaced" not in current and "Decision timeline" not in current
    # No replaced record appears, not even as a link.
    assert not any(record_anchor(r) in current for r in filed if r != godot)
    history = render_note(project_master(session, PROJECT, mode=Mode.HISTORY))
    assert "## Replaced" in history and "## Current" not in history
    assert "Decision timeline" in history


def test_sources_link_to_the_exact_messages(
    engine_project: tuple[Settings, Session, dict[str, str]], tmp_path: Path
) -> None:
    settings, session, _ = engine_project
    vault = tmp_path / "vault"
    for conversation_id in session.scalars(select(ConversationRow.conversation_id)).all():
        write_transcript(
            session,
            load_conversation(session, conversation_id),
            vault,
            settings.workspace_root / "store",
        )
    path = write_master(session, PROJECT, vault)
    text = (vault / path).read_text(encoding="utf-8")
    links = re.findall(r"\[\[([^#\]]+)#\^([A-Za-z0-9-]+)\]\]", text)
    assert links
    for note, anchor in links:  # every source link resolves to a block in a transcript
        [found] = list(vault.glob(f"Sources/{note}.md"))
        assert f"^{anchor}" in found.read_text(encoding="utf-8")
    assert write_master(session, PROJECT, vault) == path
    assert (vault / path).read_text(encoding="utf-8") == text  # same input, same bytes


def test_cli_docs_project(
    engine_project: tuple[Settings, Session, dict[str, str]],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    from knowledge_engine.cli.main import main

    settings, session, _ = engine_project
    session.close()
    monkeypatch.setenv("KE_WORKSPACE_ROOT", str(settings.workspace_root))
    vault = tmp_path / "vault"
    assert (
        main(["--json", "docs", "project", PROJECT, "--vault", str(vault), "--mode", "current"])
        == 0
    )
    note = json.loads(capsys.readouterr().out)["data"]["note"]
    assert note.startswith("Projects/") and (vault / note).is_file()
    assert RecordType.DECISION.value in (vault / note).read_text(encoding="utf-8")
