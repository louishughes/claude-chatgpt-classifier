"""NOTE-010: topic and project masters in the readable layout.

The engine_switch chats change their mind about a game engine, so their
decisions are a mix of current and replaced: the case where a master is
most likely to pass an old choice off as today's.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from knowledge_engine.classification.store import record_review
from knowledge_engine.documents.readable_master import (
    readable_project_master,
    readable_topic_master,
    write_readable_project_master,
    write_readable_topic_master,
)
from knowledge_engine.documents.render import Mode
from knowledge_engine.evaluation.end_to_end import check_vault
from knowledge_engine.extraction import decisions
from knowledge_engine.extraction.records import CandidateRecord, KnowledgeRecord, Provenance
from knowledge_engine.extraction.runner import RuleExtractor, run
from knowledge_engine.extraction.store import KnowledgeRecordRow, add_candidates, gate
from knowledge_engine.extraction.text import segment_extraction_messages
from knowledge_engine.importer import import_source
from knowledge_engine.importer.records import ConversationRow
from knowledge_engine.infrastructure.db import create_sqlite_engine, database_path
from knowledge_engine.reconciliation.supersession import reconcile
from knowledge_engine.rendering.markdown import render_note
from knowledge_engine.rendering.transcript import (
    load_conversation,
    node_key_for_anchor,
    write_transcript,
)
from knowledge_engine.segmentation.overrides import load_segments
from knowledge_engine.settings import Settings
from knowledge_engine.taxonomy.registry import (
    Dimension,
    TaxonomyRegistry,
    TaxonomySnapshot,
    TermStatus,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "chatgpt"
PROJECT = "proj_engine"
_CITE = re.compile(r"\[\[([^#\]|]+)#\^([A-Za-z0-9-]+)\|c(\d+)·(m\d+|alt)\]\]")


@dataclass
class World:
    settings: Settings
    session: Session
    taxonomy: TaxonomySnapshot
    filed: dict[str, str]  # project copy's record ID -> assertion


@pytest.fixture
def world(tmp_path: Path) -> Iterator[World]:
    settings = Settings(workspace_root=tmp_path / "ws")
    import_source(FIXTURES / "engine_switch" / "export", "fixture", settings=settings)
    session = Session(create_sqlite_engine(database_path(settings)))
    chats = [
        load_conversation(session, c)
        for c in session.scalars(select(ConversationRow.conversation_id)).all()
    ]
    segments = [
        (seg.segment_id, segment_extraction_messages(chat, seg))
        for chat in chats
        for seg in load_segments(session, chat)
    ]
    rule = RuleExtractor("decisions", decisions.EXTRACTOR_VERSION, decisions.extract_decisions)
    run(session, segments, [rule])
    registry = TaxonomyRegistry(session)
    engines = registry.add_term(
        Dimension.TOPIC,
        "Game engines",
        status=TermStatus.APPROVED,
        definition="Choosing and switching the engine a game is built in.",
    )
    taxonomy = registry.publish("tax-1", author="test")
    for chat in chats:
        for segment in load_segments(session, chat):
            record_review(
                session,
                taxonomy,
                segment.segment_id,
                "topic",
                primary=engines.term_id,
                reviewer="t",
            )
    # Each decision is filed under the project and tagged with the topic, so
    # both masters hold the same mix of current and replaced choices.
    provenance = Provenance(
        stage_id="extract.test.v1", stage_key="stg_" + "e" * 64, extractor_version="t"
    )
    filed: dict[str, str] = {}
    for row in session.scalars(
        select(KnowledgeRecordRow).where(KnowledgeRecordRow.record_type == "decision")
    ).all():
        original = KnowledgeRecord.model_validate_json(row.record_json)
        fields = original.model_dump(
            include=set(CandidateRecord.model_fields) - {"project_ids", "term_ids"}
        )
        [copy] = add_candidates(
            session,
            [CandidateRecord(**fields, project_ids=(PROJECT,), term_ids=(engines.term_id,))],
            provenance,
        )
        gate(session, copy.record_id)
        filed[copy.record_id] = original.assertion
    reconcile(session)
    session.commit()
    yield World(settings, session, taxonomy, filed)
    session.close()


def _headings(text: str) -> list[str]:
    return re.findall(r"^## (.+)$", text, flags=re.MULTILINE)


def _body(text: str) -> str:
    return text.split("\n---\n", 1)[1]


def test_project_master_reads_summary_first_and_labels_every_old_choice(world: World) -> None:
    master = readable_project_master(world.session, PROJECT)
    text = render_note(master.model)
    body = _body(text)
    assert body.split("\n\n")[1].startswith("> [!summary] Summary")
    assert "current" in body.split("\n\n")[1] and "replaced" in body.split("\n\n")[1]
    headings = _headings(body)
    assert headings[:2] == ["Current", "Replaced"]
    assert {"How these connect", "Decision timeline", "Chats"} <= set(headings)
    # Every replaced choice says what replaced it, in words.
    replaced = body.split("\n## Replaced\n", 1)[1].split("\n## ", 1)[0]
    items = [line for line in replaced.splitlines() if line.startswith("- ")]
    assert items and all('. Replaced by "' in line for line in items)
    # IDs live in the sidecar, not in front of the reader.
    assert not re.search(r"krec_|kev_|kdoc_|rel_", text)
    assert sorted(master.meta["record_ids"]) == sorted(world.filed)  # type: ignore[arg-type]
    assert master.model.properties["replaced"] == len(items)


def test_modes_split_what_holds_now_from_history(world: World) -> None:
    current = render_note(readable_project_master(world.session, PROJECT, mode=Mode.CURRENT).model)
    assert "## Replaced" not in current and "## Decision timeline" not in current
    history = render_note(readable_project_master(world.session, PROJECT, mode=Mode.HISTORY).model)
    assert "## Replaced" in history and "## Current" not in history


def test_topic_master_names_its_chats_and_where_the_topic_comes_up(world: World) -> None:
    text = render_note(readable_topic_master(world.session, "Game engines", world.taxonomy).model)
    assert "Choosing and switching the engine" in text.split("\n## ", 1)[0]
    where = text.split("\n## Where this topic comes up\n", 1)[1].split("\n## ", 1)[0]
    chats = text.split("\n## Chats\n", 1)[1]
    numbered = re.findall(r"^- c(\d+): \[\[", chats, flags=re.MULTILINE)
    assert numbered == [str(n) for n in range(1, len(numbered) + 1)]
    assert len(re.findall(r"^- c\d+: \d+ segment\(s\), labelled in topic", where, re.M)) == len(
        numbered
    )


def test_written_masters_pass_docs_check_and_cite_the_right_message(
    world: World, tmp_path: Path
) -> None:
    session, vault = world.session, tmp_path / "vault"
    store = world.settings.workspace_root / "archive"
    stems = {}
    for conversation_id in session.scalars(select(ConversationRow.conversation_id)).all():
        chat = load_conversation(session, conversation_id)
        path, _ = write_transcript(session, chat, vault, store)
        stems[Path(path).stem] = chat
    project = write_readable_project_master(session, PROJECT, vault)
    topic = write_readable_topic_master(session, "Game engines", world.taxonomy, vault)
    check = check_vault(vault)
    assert check.readable == 2 and check.readability == [], check.readability
    assert check.clean, check.broken_links
    for written in (project, topic):
        text = (vault / written).read_text(encoding="utf-8")
        cites = _CITE.findall(text)
        assert cites
        for stem, anchor, _, label in cites:
            chat = stems[stem]
            natives = {key: native for native, key in chat.node_keys.items()}
            number = chat.graph.message_number(natives[node_key_for_anchor(anchor)])
            assert label == (f"m{number}" if number is not None else "alt")
        sidecar = vault / written.parent / ".meta" / f"{written.stem}.json"
        assert json.loads(sidecar.read_text(encoding="utf-8"))["record_ids"]
    # Same input, same bytes.
    before = (vault / project).read_text(encoding="utf-8")
    write_readable_project_master(session, PROJECT, vault)
    assert (vault / project).read_text(encoding="utf-8") == before


def test_cli_template_v2_for_project_and_topic(
    world: World,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    from knowledge_engine.cli.main import main

    world.session.close()
    monkeypatch.setenv("KE_WORKSPACE_ROOT", str(world.settings.workspace_root))
    vault = tmp_path / "vault"
    assert (
        main(["--json", "docs", "project", PROJECT, "--vault", str(vault), "--template", "v2"]) == 0
    )
    note = json.loads(capsys.readouterr().out)["data"]["note"]
    assert "note-010-master-v2" in (vault / note).read_text(encoding="utf-8")
    args = ["--json", "docs", "topic", "Game engines", "--vault", str(vault), "--taxonomy", "tax-1"]
    assert main([*args, "--template", "v2"]) == 0
    note = json.loads(capsys.readouterr().out)["data"]["note"]
    assert "## Where this topic comes up" in (vault / note).read_text(encoding="utf-8")
