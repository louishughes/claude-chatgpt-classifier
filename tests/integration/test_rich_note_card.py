"""NOTE-024: the knowledge card shows no number-only names and no empty "not stated" rows.

A synthetic chat says "playing 48 levels" (the game cue catches "48") and
"playing Celeste". Its digest has a purpose but no outcome. The card must
list Celeste but not 48, show the purpose, and leave the outcome row out
rather than write "not stated" next to a digest.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from knowledge_engine.digest.contract import DigestAnswer, resolve_digest
from knowledge_engine.documents.rich_note import rich_conversation_note
from knowledge_engine.extraction import entities
from knowledge_engine.extraction.runner import RuleExtractor, run
from knowledge_engine.extraction.text import segment_extraction_messages
from knowledge_engine.importer.records import ConversationRow
from knowledge_engine.importer.run import run_import
from knowledge_engine.infrastructure.db import create_sqlite_engine, database_path
from knowledge_engine.rendering.markdown import render_note
from knowledge_engine.rendering.transcript import load_conversation
from knowledge_engine.segmentation.overrides import load_segments
from knowledge_engine.settings import Settings

T0 = 1704067200.0
USER = "I keep playing 48 levels a night and I am also playing Celeste. Plan my game nights."
REPLY = "Alternate the two games across the week."


def _export(root: Path) -> Path:
    def node(n: str, parent: str, role: str, text: str, t: float) -> dict[str, object]:
        return {
            "id": n,
            "parent": parent,
            "children": [],
            "message": {
                "id": n,
                "author": {"role": role},
                "create_time": t,
                "content": {"content_type": "text", "parts": [text]},
                "metadata": {},
            },
        }

    mapping = {
        "root": {"id": "root", "parent": None, "children": ["u1"], "message": None},
        "u1": node("u1", "root", "user", USER, T0),
        "a1": node("a1", "u1", "assistant", REPLY, T0 + 60),
    }
    mapping["u1"]["children"] = ["a1"]  # type: ignore[index]
    chat = {"id": "c-games", "title": "Synthetic games", "create_time": T0,
            "mapping": mapping, "current_node": "a1"}  # fmt: skip
    root.mkdir(parents=True)
    (root / "conversations.json").write_text(json.dumps([chat]), encoding="utf-8")
    return root


def _card(text: str) -> str:
    return text.split("\n## Knowledge card\n", 1)[1].split("\n## ", 1)[0]


def test_card_drops_number_only_names_and_empty_digest_rows(tmp_path: Path) -> None:
    settings = Settings(workspace_root=tmp_path / "ws")
    run_import(_export(tmp_path / "export"), "acct", format_id=None, settings=settings)
    with Session(create_sqlite_engine(database_path(settings))) as session:
        [cid] = session.scalars(select(ConversationRow.conversation_id)).all()
        chat = load_conversation(session, cid)
        segments = [
            (seg.segment_id, segment_extraction_messages(chat, seg))
            for seg in load_segments(session, chat)
        ]
        extractor = RuleExtractor("entities", entities.EXTRACTOR_VERSION, entities.extract_entities)
        run(session, segments, [extractor])
        session.commit()
        messages = [m for _, msgs in segments for m in msgs]
        user = next(m.native_id for m in messages if m.text == USER)
        answer = DigestAnswer.model_validate(
            {
                "summary": [
                    {"text": "Planning game nights.", "quotes": [{"message_id": user,
                                                                  "text": "Plan my game nights"}]}
                ],
                "purpose": {"text": "Plan game nights.",
                            "quotes": [{"message_id": user, "text": "Plan my game nights"}]},
                "status": {"value": "open",
                           "quotes": [{"message_id": user, "text": "Plan my game nights"}]},
                "intent": {"value": "plan", "text": "Plan a routine.",
                           "quotes": [{"message_id": user, "text": "Plan my game nights"}]},
            }
        )  # fmt: skip
        digest = resolve_digest(answer, messages)
        assert digest.purpose is not None and digest.outcome is None

        card = _card(render_note(rich_conversation_note(session, cid, digest=digest).model))
        tools = re.search(r"^\| \*\*Tools and names\*\* \| (.*) \|$", card, re.MULTILINE)
        assert tools is not None
        assert "Celeste" in tools.group(1)  # a real name stays
        assert "48" not in tools.group(1)  # a bare number is not a name
        assert "| **Purpose** | Plan game nights." in card
        assert "not stated" not in card and "**Outcome**" not in card

        # With no digest at all, both rows still say the digest hasn't run.
        waiting = _card(render_note(rich_conversation_note(session, cid).model))
        assert "| **Purpose** | not written yet |" in waiting
        assert "| **Outcome** | not written yet |" in waiting
