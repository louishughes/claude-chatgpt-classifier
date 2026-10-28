"""LNK-001: links become one target per destination and one occurrence per mention."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from knowledge_engine.importer.run import run_import
from knowledge_engine.infrastructure.db import create_sqlite_engine, database_path
from knowledge_engine.links.store import LinkOccurrenceRow, LinkTargetRow
from knowledge_engine.settings import Settings

# Synthetic chat: one URL written three times in three messages (two
# spellings), plus one web citation in the assistant's metadata.
URL = "https://example.org/guide"


def _message(
    node: str, role: str, text: str, metadata: dict[str, Any] | None = None
) -> dict[str, Any]:
    return {
        "id": node,
        "author": {"role": role, "name": None, "metadata": {}},
        "create_time": 1704067200.0,
        "content": {"content_type": "text", "parts": [text]},
        "metadata": metadata or {},
    }


def _export(root: Path, assistant_text: str = f"Read {URL}.") -> Path:
    nodes = [
        ("root", None, None),
        ("u0", "user", f"Is {URL} any good?"),
        ("a0", "assistant", assistant_text),
        ("u1", "user", f"Thanks! (Saved <{URL}#intro>)"),
    ]
    mapping: dict[str, Any] = {}
    for i, (node, role, text) in enumerate(nodes):
        parent = nodes[i - 1][0] if i else None
        child = [nodes[i + 1][0]] if i + 1 < len(nodes) else []
        metadata = (
            {"citations": [{"metadata": {"url": "https://docs.example.org/ref"}}]}
            if node == "a0"
            else None
        )
        mapping[node] = {
            "id": node,
            "parent": parent,
            "children": child,
            "message": _message(node, role, text or "", metadata) if role else None,
        }
    root.mkdir(parents=True, exist_ok=True)
    conversation = {
        "id": "c-links-1",
        "title": "Synthetic links",
        "create_time": 1704067200.0,
        "mapping": mapping,
        "current_node": "u1",
    }
    (root / "conversations.json").write_text(json.dumps([conversation]), encoding="utf-8")
    return root


def _rows(settings: Settings) -> tuple[list[LinkTargetRow], list[LinkOccurrenceRow]]:
    engine = create_sqlite_engine(database_path(settings))
    try:
        with Session(engine) as session:
            targets = list(
                session.scalars(select(LinkTargetRow).order_by(LinkTargetRow.canonical_url))
            )
            occurrences = list(
                session.scalars(select(LinkOccurrenceRow).order_by(LinkOccurrenceRow.occurrence_id))
            )
            session.expunge_all()
            return targets, occurrences
    finally:
        engine.dispose()


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(workspace_root=tmp_path / "ws")


def test_three_mentions_one_target_and_reimport_adds_nothing(
    settings: Settings, tmp_path: Path
) -> None:
    export = _export(tmp_path / "export")
    report = run_import(export, "acct", format_id=None, settings=settings)
    targets, occurrences = _rows(settings)
    assert [t.canonical_url for t in targets] == [
        "https://docs.example.org/ref",
        "https://example.org/guide",
    ]
    guide = targets[1].target_id
    text_mentions = [o for o in occurrences if o.target_id == guide]
    assert len(text_mentions) == 3
    assert {o.actor for o in text_mentions} == {"user", "assistant"}
    assert {o.original_text for o in text_mentions} == {URL, f"{URL}#intro"}
    assert all(o.origin == "message_text" for o in text_mentions)
    [citation] = [o for o in occurrences if o.target_id != guide]
    assert (citation.origin, citation.start, citation.end) == ("citation_metadata", 0, 1)
    assert report.links == {"new_occurrences": 4, "new_targets": 2, "seen_occurrences": 4}

    again = run_import(export, "acct", format_id=None, settings=settings)
    assert again.links.get("new_occurrences", 0) == 0
    assert again.links.get("new_targets", 0) == 0
    assert len(_rows(settings)[1]) == 4


def test_spans_select_the_url_in_the_stored_text(settings: Settings, tmp_path: Path) -> None:
    from knowledge_engine.rendering.transcript import load_conversation

    run_import(_export(tmp_path / "export"), "acct", format_id=None, settings=settings)
    engine = create_sqlite_engine(database_path(settings))
    try:
        with Session(engine) as session:
            from knowledge_engine.importer.records import ConversationRow

            conversation_id = session.scalars(select(ConversationRow.conversation_id)).one()
            conversation = load_conversation(session, conversation_id)
            text_by_revision = {
                conversation.revisions[n]: conversation.messages[n].text
                for n in conversation.messages
            }
            for occurrence in session.scalars(
                select(LinkOccurrenceRow).where(LinkOccurrenceRow.origin == "message_text")
            ):
                text = text_by_revision[occurrence.revision_id]
                assert text[occurrence.start : occurrence.end] == occurrence.original_text
    finally:
        engine.dispose()


def test_an_edited_message_gets_new_mentions_and_keeps_the_old(
    settings: Settings, tmp_path: Path
) -> None:
    run_import(_export(tmp_path / "v1"), "acct", format_id=None, settings=settings)
    _, before = _rows(settings)
    run_import(
        _export(tmp_path / "v2", assistant_text=f"Updated: {URL}"),
        "acct",
        format_id=None,
        settings=settings,
    )
    targets, after = _rows(settings)
    assert len(targets) == 2
    # The old revision's mentions are evidence of what it said: kept.
    assert {o.occurrence_id for o in before} <= {o.occurrence_id for o in after}
    assert len(after) == len(before) + 2  # new text mention + its citation

    engine = create_sqlite_engine(database_path(settings))
    try:
        with Session(engine) as session:
            assert session.scalar(select(func.count()).select_from(LinkTargetRow)) == 2
    finally:
        engine.dispose()
