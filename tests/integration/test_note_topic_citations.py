"""NOTE-026: topics that cite the same message share one citation on their line.

A synthetic chat: the user asks about raised beds, cedar and drainage in one
message, then about watering in a second. The digest gives four topics,
three from the first message and one from the second. Before, the topics
line repeated the first message's link three times.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from knowledge_engine.digest.contract import DigestAnswer, resolve_digest
from knowledge_engine.documents.rich_note import rich_conversation_note
from knowledge_engine.extraction.text import segment_extraction_messages
from knowledge_engine.importer.records import ConversationRow
from knowledge_engine.importer.run import run_import
from knowledge_engine.infrastructure.db import create_sqlite_engine, database_path
from knowledge_engine.rendering.markdown import render_note
from knowledge_engine.rendering.transcript import load_conversation
from knowledge_engine.segmentation.overrides import load_segments
from knowledge_engine.settings import Settings

T0 = 1704067200.0
FIRST = "Help me build raised beds from cedar with good drainage."
SECOND = "How often should I water them in summer?"


def _export(root: Path) -> Path:
    turns = [
        ("u1", "user", FIRST),
        ("a1", "assistant", "Use 30 cm cedar boards and a gravel base."),
        ("u2", "user", SECOND),
        ("a2", "assistant", "Water deeply twice a week."),
    ]
    mapping: dict[str, dict[str, object]] = {
        "root": {"id": "root", "parent": None, "children": [], "message": None}
    }
    parent = "root"
    for i, (n, role, text) in enumerate(turns):
        mapping[n] = {
            "id": n,
            "parent": parent,
            "children": [],
            "message": {
                "id": n,
                "author": {"role": role},
                "create_time": T0 + 60 * i,
                "content": {"content_type": "text", "parts": [text]},
                "metadata": {},
            },
        }
        mapping[parent]["children"].append(n)  # type: ignore[attr-defined]
        parent = n
    chat = {"id": "c-beds", "title": "Synthetic beds", "create_time": T0,
            "mapping": mapping, "current_node": parent}  # fmt: skip
    root.mkdir(parents=True)
    (root / "conversations.json").write_text(json.dumps([chat]), encoding="utf-8")
    return root


def _topic(text: str, message_id: str, words: str) -> dict[str, object]:
    return {"text": text, "quotes": [{"message_id": message_id, "text": words}]}


def test_topics_from_one_message_share_one_citation(tmp_path: Path) -> None:
    settings = Settings(workspace_root=tmp_path / "ws")
    run_import(_export(tmp_path / "export"), "acct", format_id=None, settings=settings)
    with Session(create_sqlite_engine(database_path(settings))) as session:
        [cid] = session.scalars(select(ConversationRow.conversation_id)).all()
        chat = load_conversation(session, cid)
        messages = [
            m
            for seg in load_segments(session, chat)
            for m in segment_extraction_messages(chat, seg)
        ]
        first = next(m.native_id for m in messages if m.text == FIRST)
        second = next(m.native_id for m in messages if m.text == SECOND)
        quote = {"message_id": first, "text": "raised beds"}
        answer = DigestAnswer.model_validate(
            {
                "summary": [{"text": "Building raised beds.", "quotes": [quote]}],
                "purpose": {"text": "Build raised beds.", "quotes": [quote]},
                "status": {"value": "open", "quotes": [quote]},
                "intent": {"value": "plan", "text": "Plan a build.", "quotes": [quote]},
                "topics": [
                    _topic("raised beds", first, "raised beds"),
                    _topic("cedar", first, "beds from cedar"),
                    _topic("watering", second, "water them in summer"),
                    _topic("drainage", first, "good drainage"),
                ],
            }
        )
        digest = resolve_digest(answer, messages)
        text = render_note(rich_conversation_note(session, cid, digest=digest).model)

    section = text.split("\n## Keywords and topics\n", 1)[1].split("\n## ", 1)[0]
    [line] = [x for x in section.splitlines() if x.startswith("- ")]
    links = re.findall(r"\[\[[^\]]*\|m(\d+)\]\]", line)
    assert links == ["1", "3"]  # each message cited once on the line
    assert re.match(r"- raised beds, cedar, drainage \[\[[^\]]*\|m1\]\]; watering \[\[", line)
