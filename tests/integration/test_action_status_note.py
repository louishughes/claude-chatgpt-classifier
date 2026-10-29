"""EXT-009 and EXT-010 end to end: stored action records, a proposed dependency, the note.

Two synthetic chats. In the shed chat the user plans two jobs, says one
waits for the other, then reports the first done. The second chat uses the
same words about a roof it never planned, so no link may cross chats.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from knowledge_engine.documents.rich_note import rich_conversation_note
from knowledge_engine.extraction import actions
from knowledge_engine.extraction.runner import RuleExtractor, run
from knowledge_engine.extraction.text import segment_extraction_messages
from knowledge_engine.importer.records import ConversationRow
from knowledge_engine.importer.run import run_import
from knowledge_engine.infrastructure.db import create_sqlite_engine, database_path
from knowledge_engine.reconciliation.relations import (
    LinkState,
    RecordLinkRow,
    propose_links,
    review_link,
)
from knowledge_engine.rendering.markdown import render_note
from knowledge_engine.rendering.transcript import load_conversation
from knowledge_engine.segmentation.segmenter import segment_conversation
from knowledge_engine.settings import Settings

CHATS = {
    "c-shed": [
        ("user", "Synthetic: I'll fix the shed roof. I'll paint the shed walls."),
        ("assistant", "Synthetic: good plan."),
        ("user", "Paint the walls after the roof is fixed."),
        ("assistant", "Synthetic: that order makes sense."),
        ("user", "Update: the shed roof is fixed now."),
        ("assistant", "Synthetic: done, nice work."),
    ],
    "c-other": [
        ("user", "Synthetic: I'll paint the garage walls. I'll clean the brushes."),
        ("assistant", "Synthetic: sounds good."),
        ("user", "Paint the walls after the roof is fixed."),
    ],
}


def _chat(cid: str, turns: list[tuple[str, str]]) -> dict[str, Any]:
    mapping: dict[str, Any] = {"root": {"id": "root", "parent": None, "children": []}}
    parent = "root"
    for i, (role, text) in enumerate(turns):
        node = f"{cid}-{i}"
        mapping[node] = {
            "id": node,
            "parent": parent,
            "children": [],
            "message": {
                "id": node,
                "author": {"role": role},
                "create_time": 1704067200.0 + 60 * i,
                "content": {"content_type": "text", "parts": [text]},
                "metadata": {},
            },
        }
        mapping[parent]["children"].append(node)
        parent = node
    return {"id": cid, "title": f"Synthetic {cid}", "create_time": 1704067200.0,
            "mapping": mapping, "current_node": parent}  # fmt: skip


@pytest.fixture
def session(tmp_path: Path) -> Iterator[Session]:
    export = tmp_path / "export"
    export.mkdir()
    chats = [_chat(cid, turns) for cid, turns in CHATS.items()]
    (export / "conversations.json").write_text(json.dumps(chats), encoding="utf-8")
    settings = Settings(workspace_root=tmp_path / "ws")
    run_import(export, "acct", format_id=None, settings=settings)
    engine = create_sqlite_engine(database_path(settings))
    with Session(engine) as s:
        conversations = [
            load_conversation(s, c)
            for c in s.scalars(select(ConversationRow.conversation_id)).all()
        ]
        segments = [
            (seg.segment_id, segment_extraction_messages(conv, seg))
            for conv in conversations
            for seg in segment_conversation(conv)
        ]
        run(
            s,
            segments,
            [RuleExtractor("actions", actions.EXTRACTOR_VERSION, actions.extract_actions)],
        )
        s.commit()
        yield s
    engine.dispose()


def _cid(session: Session, native: str) -> str:
    cid = session.scalar(
        select(ConversationRow.conversation_id).where(
            ConversationRow.native_conversation_id == native
        )
    )
    assert cid is not None
    return cid


def _actions_section(session: Session, native: str) -> str:
    text = render_note(rich_conversation_note(session, _cid(session, native)).model)
    return text.split("\n## Action items\n", 1)[1].split("\n## ", 1)[0]


def test_one_dependency_inside_the_chat_and_none_across(session: Session) -> None:
    report = propose_links(session)
    assert report.by_predicate.get("depends_on") == 1
    [link] = session.scalars(select(RecordLinkRow).where(RecordLinkRow.predicate == "depends_on"))
    assert link.state == "candidate"  # proposed, never trusted
    assert link.detector == "ext-010-rules-v1"
    evidence = json.loads(link.evidence_json)
    assert evidence["cue"] == "after" and evidence["sentence"]["quote_sha256"]
    assert "Paint" not in link.evidence_json  # IDs and hashes, no text
    assert propose_links(session).added == ()  # a re-run adds nothing


def test_the_note_shows_status_and_what_an_action_waits_for(session: Session) -> None:
    propose_links(session)
    section = _actions_section(session, "c-shed")
    lines = [line for line in section.splitlines() if line.startswith("- **")]
    [roof] = [line for line in lines if line.startswith("- **Synthetic: I'll fix")]
    [paint] = [line for line in lines if line.startswith("- **I'll paint")]
    assert "Reported done" in roof and "|m5]]" in roof  # the user's update
    assert "Open." in paint and "Waits for “Synthetic: I'll fix the shed roof.”" in paint
    other = _actions_section(session, "c-other")
    assert "Waits for" not in other and "Reported done" not in other


def test_a_rejected_dependency_is_not_shown(session: Session) -> None:
    propose_links(session)
    [link] = session.scalars(select(RecordLinkRow).where(RecordLinkRow.predicate == "depends_on"))
    review_link(session, link.link_id, LinkState.REJECTED, reviewer="synthetic-reviewer")
    assert "Waits for" not in _actions_section(session, "c-shed")
