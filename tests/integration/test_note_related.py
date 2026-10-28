"""NOTE-009: a note links its related chats, and a shared pasted prompt links nothing.

Synthetic chats. Two open with the same long pasted setup prompt ("You
are ...") and then ask about unrelated things (bread, tax); without the
NOTE-009 filter that prompt (plus the same one-word reply) read as a
copied opening, a ``forked_from`` link. Two others are labelled with the same project,
so each one's rich note must name the other and say why.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from knowledge_engine.classification.store import record_review
from knowledge_engine.documents.notes import knowledge_path
from knowledge_engine.documents.rich_note import rich_conversation_note
from knowledge_engine.extraction.preamble import looks_like_preamble
from knowledge_engine.importer.records import ConversationRow
from knowledge_engine.importer.run import run_import
from knowledge_engine.infrastructure.db import create_sqlite_engine, database_path
from knowledge_engine.relationships.related import suggest_related
from knowledge_engine.relationships.store import ConversationRelationshipRow
from knowledge_engine.rendering.markdown import render_note
from knowledge_engine.rendering.transcript import load_conversation
from knowledge_engine.segmentation.overrides import load_segments
from knowledge_engine.settings import Settings
from knowledge_engine.taxonomy.registry import TaxonomyRegistry, TaxonomySnapshot, TermStatus

T0 = 1704067200.0
DAY = 86400.0

SETUP = (
    "You are a careful and patient assistant. Answer in plain British English, "
    "keep every answer short, explain any jargon you use, never invent facts, say "
    "when you are unsure, and finish each answer with one practical next step for me."
)

# native id -> (day, [user, assistant, user, assistant...])
CHATS = {
    "c-bread": (0, [SETUP, "Understood.", "Why does my sourdough loaf collapse?", "Overproofed."]),
    "c-tax": (1, [SETUP, "Understood.", "When is the self assessment return due?", "January."]),
    "c-shed-1": (2, ["Help me plan a timber garden shed base.", "Use a concrete slab."]),
    "c-shed-2": (3, ["Which felt suits the garden shed roof?", "Torch-on felt."]),
}


def _export(root: Path) -> Path:
    chats = []
    for cid, (day, turns) in CHATS.items():
        mapping: dict[str, Any] = {"root": {"id": "root", "parent": None, "children": []}}
        parent = "root"
        for n, words in enumerate(turns):
            node = f"{cid}-{n}"  # distinct native IDs, or chats would read as forks
            mapping[node] = {
                "id": node,
                "parent": parent,
                "children": [],
                "message": {
                    "id": node,
                    "author": {"role": "user" if n % 2 == 0 else "assistant"},
                    "create_time": T0 + day * DAY + 60 * n,
                    "content": {"content_type": "text", "parts": [words]},
                    "metadata": {},
                },
            }
            mapping[parent]["children"].append(node)
            parent = node
        chats.append(
            {
                "id": cid,
                "title": f"Synthetic {cid}",
                "create_time": T0 + day * DAY,
                "mapping": mapping,
                "current_node": parent,
            }
        )
    root.mkdir(parents=True)
    (root / "conversations.json").write_text(json.dumps(chats), encoding="utf-8")
    return root


@dataclass
class World:
    settings: Settings
    session: Session
    chats: dict[str, str]  # native -> conv_
    taxonomy: TaxonomySnapshot
    project_id: str


@pytest.fixture
def world(tmp_path: Path) -> Iterator[World]:
    settings = Settings(workspace_root=tmp_path / "ws")
    run_import(_export(tmp_path / "export"), "acct", format_id=None, settings=settings)
    session = Session(create_sqlite_engine(database_path(settings)))
    chats = dict(
        session.execute(
            select(ConversationRow.native_conversation_id, ConversationRow.conversation_id)
        )
        .tuples()
        .all()
    )
    registry = TaxonomyRegistry(session)
    project = registry.add_project("Shed build", status=TermStatus.APPROVED)
    taxonomy = registry.publish("tax-1", author="test")
    for native in ("c-shed-1", "c-shed-2"):
        chat = load_conversation(session, chats[native])
        for segment in load_segments(session, chat):
            record_review(
                session,
                taxonomy,
                segment.segment_id,
                "projects",
                primary=project.project_id,
                reviewer="test",
                conversation_id=chats[native],
            )
    workspace_id = session.scalars(select(ConversationRow.workspace_id)).first() or ""
    suggest_related(session, workspace_id=workspace_id, taxonomy=taxonomy, egress=settings.egress)
    session.commit()
    yield World(settings, session, chats, taxonomy, project.project_id)
    session.close()


def _links(world: World, *natives: str) -> list[ConversationRelationshipRow]:
    ids = [world.chats[n] for n in natives]
    return list(
        world.session.scalars(
            select(ConversationRelationshipRow).where(
                ConversationRelationshipRow.from_conversation_id.in_(ids),
                ConversationRelationshipRow.to_conversation_id.in_(ids),
            )
        )
    )


def test_the_setup_prompt_is_recognised() -> None:
    assert looks_like_preamble("user", SETUP)
    assert not looks_like_preamble("assistant", SETUP)  # only what the user pasted
    assert not looks_like_preamble("user", "You are right, thanks.")  # too short to be one


def test_a_shared_pasted_prompt_makes_no_link(world: World) -> None:
    assert [(r.kind, r.detector) for r in _links(world, "c-bread", "c-tax")] == []


def test_both_notes_name_the_other_chat_and_say_why(world: World) -> None:
    [link] = [r for r in _links(world, "c-shed-1", "c-shed-2") if r.kind == "same_project"]
    assert link.review_state == "candidate"
    for here, there in (("c-shed-1", "c-shed-2"), ("c-shed-2", "c-shed-1")):
        note = rich_conversation_note(world.session, world.chats[here], taxonomy=world.taxonomy)
        text = render_note(note.model)
        part = text.split("\n## Related chats\n", 1)[1].split("\n## ", 1)[0]
        other = knowledge_path(world.chats[there], f"Synthetic {there}").stem
        [line] = [line for line in part.splitlines() if "same project" in line]
        assert f"[[{other}]]" in line  # the other chat's knowledge note, not its transcript
        assert f"Why: both chats are labelled with project {world.project_id}" in line
        assert "candidate" in line  # a suggestion is shown as one
