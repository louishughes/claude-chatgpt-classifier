"""EVAL-012 follow-up: a forked chat is linked to its direct parent only.

Built here, not as a fixture folder: chat A, two forks of A (B and C, so
siblings), and D, a fork of B (so A is D's grandparent). ChatGPT copies the
parent's messages, IDs included, into each fork, so every pair here shares
node IDs. Only B->A, C->A and D->B are true ``forked_from`` links.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from knowledge_engine.importer import import_source
from knowledge_engine.importer.records import ConversationRow
from knowledge_engine.infrastructure.db import create_sqlite_engine, database_path
from knowledge_engine.relationships.store import ConversationRelationshipRow
from knowledge_engine.settings import Settings

START = 1_707_000_000.0


def _node(
    node_id: str, parent: str | None, role: str | None, text: str, at: float
) -> dict[str, Any]:
    message = None
    if role is not None:
        message = {
            "id": node_id,
            "author": {"role": role, "name": None, "metadata": {}},
            "create_time": at,
            "content": {"content_type": "text", "parts": [text]},
            "status": "finished_successfully",
            "metadata": {},
            "recipient": "all",
        }
    return {"id": node_id, "message": message, "parent": parent, "children": []}


def _chat(cid: str, at: float, messages: list[tuple[str, str, str]]) -> dict[str, Any]:
    """A chat whose active path is root -> messages, in order."""
    mapping = {f"{cid}-root": _node(f"{cid}-root", None, None, "", at)}
    parent = f"{cid}-root"
    for offset, (node_id, role, text) in enumerate(messages, start=1):
        mapping[node_id] = _node(node_id, parent, role, text, at + offset)
        mapping[parent]["children"].append(node_id)
        parent = node_id
    return {
        "title": f"Synthetic {cid}",
        "create_time": at,
        "update_time": at + 100,
        "current_node": parent,
        "conversation_id": cid,
        "id": cid,
        "mapping": mapping,
    }


def _ids(n: int) -> str:
    return f"f0000000-0000-4000-8000-00000000000{n}"


A, B, C, D = (_ids(n) for n in range(1, 5))
OPENING = [
    ("a-u0", "user", "Synthetic: plan a small vegetable bed."),
    ("a-a0", "assistant", "Synthetic: pick a sunny spot and build a raised frame."),
]


def _export(folder: Path) -> Path:
    b_own = [("b-u1", "user", "Synthetic: which soil mix?")]
    chats = [
        _chat(A, START, OPENING),
        _chat(B, START + 1000, OPENING + b_own),
        _chat(C, START + 2000, OPENING + [("c-u1", "user", "Synthetic: what about watering?")]),
        _chat(D, START + 3000, OPENING + b_own + [("d-u2", "user", "Synthetic: and compost?")]),
    ]
    folder.mkdir(parents=True)
    (folder / "conversations.json").write_text(json.dumps(chats), encoding="utf-8")
    return folder


def test_siblings_and_grandparents_are_not_parents(tmp_path: Path) -> None:
    settings = Settings(workspace_root=tmp_path / "ws")
    import_source(_export(tmp_path / "export"), "fixture", settings=settings)
    engine = create_sqlite_engine(database_path(settings))
    try:
        with Session(engine) as session:
            native = {
                row.conversation_id: row.native_conversation_id
                for row in session.scalars(select(ConversationRow))
            }
            links = sorted(
                (native[r.from_conversation_id], r.kind, native[r.to_conversation_id])
                for r in session.scalars(select(ConversationRelationshipRow))
            )
    finally:
        engine.dispose()
    assert links == [
        (B, "forked_from", A),
        (C, "forked_from", A),
        (D, "forked_from", B),
    ]
