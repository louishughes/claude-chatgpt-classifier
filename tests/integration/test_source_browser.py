"""Slice R3: browse what the archive holds (BRW-001).

Acceptance (BRW-001): a fixture conversation renders with every node
reachable, branches labelled, images linked and anchors resolving to
logical message IDs.
"""

from __future__ import annotations

import json
import re
import shutil
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from knowledge_engine.cli.main import main
from knowledge_engine.importer import import_source
from knowledge_engine.importer.media import AssetOccurrenceRow
from knowledge_engine.importer.records import ConversationRow, MessageNodeRow, MessageRevisionRow
from knowledge_engine.infrastructure.db import create_sqlite_engine, database_path
from knowledge_engine.rendering.markdown import render_note
from knowledge_engine.rendering.transcript import (
    find_conversation,
    load_conversation,
    node_key_for_anchor,
    transcript_model,
    write_transcript,
)
from knowledge_engine.settings import Settings, load_settings

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "chatgpt"
CASES = sorted(p.name for p in FIXTURES.iterdir() if (p / "manifest.json").is_file())
_ANCHOR_RE = re.compile(r" \^(node-[0-9a-f]{32})$", re.MULTILINE)


def _root(case: str) -> Path:
    export = FIXTURES / case / "export"
    zips = list(export.glob("*.zip"))
    return zips[0] if zips else export


@pytest.fixture
def settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Settings:
    monkeypatch.setenv("KE_WORKSPACE_ROOT", str(tmp_path / "ws"))
    return load_settings(workspace_root=tmp_path / "ws")


def _session(settings: Settings) -> Iterator[Session]:
    engine = create_sqlite_engine(database_path(settings))
    try:
        with Session(engine) as session:
            yield session
    finally:
        engine.dispose()


@pytest.mark.parametrize("case", CASES)
def test_every_message_is_reachable_and_anchored(
    case: str, settings: Settings, tmp_path: Path
) -> None:
    import_source(_root(case), "fixture", settings=settings)
    vault = tmp_path / "vault"

    for session in _session(settings):
        conversation_ids = session.scalars(select(ConversationRow.conversation_id)).all()
        assert conversation_ids
        for conversation_id in conversation_ids:
            conversation = load_conversation(session, conversation_id)
            text = render_note(transcript_model(conversation))
            anchors = _ANCHOR_RE.findall(text)

            # Every stored message appears exactly once...
            with_messages = set(
                session.scalars(
                    select(MessageNodeRow.node_key)
                    .join(
                        MessageRevisionRow, MessageRevisionRow.node_key == MessageNodeRow.node_key
                    )
                    .where(MessageNodeRow.conversation_id == conversation_id)
                ).all()
            )
            assert len(anchors) == len(set(anchors))
            # ...and each anchor resolves to that logical message ID.
            assert {node_key_for_anchor(a) for a in anchors} == with_messages

            # Images are linked, and every link resolves in the vault.
            available = session.scalars(
                select(AssetOccurrenceRow.occurrence_id).where(
                    AssetOccurrenceRow.revision_id.in_(conversation.revisions.values()),
                    AssetOccurrenceRow.availability == "available",
                )
            ).all()
            assert text.count("![[_attachments/") == len(available)
            _, broken = write_transcript(
                session, conversation, vault, settings.workspace_root / "archive"
            )
            assert broken == []


@pytest.mark.parametrize(
    ("case", "kind"), [("branches_edit", "edit"), ("branches_regen", "regeneration")]
)
def test_branches_are_labelled_and_kept_apart(case: str, kind: str, settings: Settings) -> None:
    import_source(_root(case), "fixture", settings=settings)
    expected = json.loads((FIXTURES / case / "manifest.json").read_text(encoding="utf-8"))[
        "expected"
    ]

    for session in _session(settings):
        conversation_id = session.scalars(select(ConversationRow.conversation_id)).one()
        conversation = load_conversation(session, conversation_id)
        text = render_note(transcript_model(conversation))

    active, _, alternates = text.partition("## Alternate branches")
    assert conversation.graph.active_messages == tuple(expected["active_path_node_ids"])
    # Inactive messages only ever appear in the alternates section.
    for native_id in expected["inactive_node_ids"]:
        anchor = conversation.node_keys[native_id].replace("_", "-", 1)
        assert anchor not in active
        assert anchor in alternates
    assert f"### Alternate ({kind})" in alternates
    assert "Branches off after message" in alternates


def test_newest_revision_is_shown_after_an_edit(settings: Settings) -> None:
    import_source(_root("reexport_v1"), "fixture", settings=settings)
    import_source(_root("reexport_v2"), "fixture", settings=settings)

    for session in _session(settings):
        revised = session.scalars(
            select(MessageRevisionRow.node_key)
            .group_by(MessageRevisionRow.node_key)
            .having(func.count() > 1)
        ).all()
        assert len(revised) == 1
        newest = session.scalars(
            select(MessageRevisionRow)
            .where(MessageRevisionRow.node_key == revised[0])
            .order_by(MessageRevisionRow.created_at.desc())
        ).first()
        assert newest is not None
        node = session.get(MessageNodeRow, revised[0])
        assert node is not None
        conversation = load_conversation(session, node.conversation_id)
        assert conversation.revisions[node.native_node_id] == newest.revision_id


def test_message_with_a_missing_parent_is_still_shown(settings: Settings, tmp_path: Path) -> None:
    source = tmp_path / "source"
    shutil.copytree(_root("export_single"), source)
    path = source / "conversations.json"
    conversations = json.loads(path.read_text(encoding="utf-8"))
    first = conversations[0]
    leaf = first["current_node"]
    first["mapping"][leaf]["parent"] = "synthetic-missing-parent"
    path.write_text(json.dumps(conversations), encoding="utf-8")
    report = import_source(source, "fixture", settings=settings)

    for session in _session(settings):
        conversation_id = find_conversation(session, first["conversation_id"])
        assert conversation_id is not None
        conversation = load_conversation(session, conversation_id)
        text = render_note(transcript_model(conversation))

    # The import reports the dangling parent; the note still shows the message.
    assert report.warnings["graph_missing_parent"] == 1
    assert conversation.node_keys[leaf].replace("_", "-", 1) in text
    assert len(_ANCHOR_RE.findall(text)) == len(conversation.messages)


def _cli(capsys: pytest.CaptureFixture[str], *args: str) -> tuple[int, dict[str, Any]]:
    capsys.readouterr()
    code = main(["--json", "inspect", *args])
    return code, json.loads(capsys.readouterr().out)


def test_inspect_shows_structure_without_private_text(
    settings: Settings, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    code, payload = _cli(capsys)
    assert (code, payload["error"]) == (1, {"code": "no_imports"})
    import_source(_root("branches_regen"), "fixture", settings=settings)

    code, listing = _cli(capsys)
    _, detail = _cli(capsys, "c0000002-0000-4000-8000-000000000002", "--note", str(tmp_path / "v"))
    code_missing, missing = _cli(capsys, "no-such-conversation")

    assert code == 0 and listing["data"]["count"] == 1
    data = detail["data"]
    assert data["branch_points"] == {"regeneration": 1}
    assert (data["messages"], data["active_path_messages"], data["alternate_paths"]) == (5, 3, 2)
    assert data["broken_embeds"] == 0
    assert (code_missing, missing["error"]) == (1, {"code": "not_found"})
    output = json.dumps([listing, detail])
    assert "Synthetic" not in output  # no titles, no message text
    notes = list((tmp_path / "v" / "Sources").glob("*.md"))
    assert len(notes) == 1 and "Synthetic answer v3" in notes[0].read_text(encoding="utf-8")
