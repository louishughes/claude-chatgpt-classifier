"""NOTE-022: once a model extraction covers a segment, its rule records leave the note.

Synthetic chat in two segments (a seven-hour pause): a raised-bed choice,
then soup. The rule extractors run on both. A fake model extractor (NOTE-005)
then runs on the first segment only, so the note should show the model's
record there, keep the rule record of the second segment, and say how many
it held back. Nothing is deleted.
"""

from __future__ import annotations

import json
from functools import partial
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from knowledge_engine.documents.rich_note import rich_conversation_note
from knowledge_engine.extraction import actions, decisions, preferences
from knowledge_engine.extraction.model_knowledge import knowledge_extractor
from knowledge_engine.extraction.runner import RuleExtractor, run
from knowledge_engine.extraction.store import KnowledgeRecordRow
from knowledge_engine.extraction.text import segment_extraction_messages
from knowledge_engine.importer.records import ConversationRow
from knowledge_engine.importer.run import run_import
from knowledge_engine.infrastructure.db import create_sqlite_engine, database_path
from knowledge_engine.providers.base import FakeProvider, ModelRequest
from knowledge_engine.providers.ledger import ModelStageRunner
from knowledge_engine.rendering.markdown import render_note
from knowledge_engine.rendering.transcript import load_conversation
from knowledge_engine.segmentation.overrides import load_segments
from knowledge_engine.settings import EgressPolicy, Settings

T0 = 1704067200.0
HOUR = 3600.0
NODES = [
    ("u1", "user", "Which wood should the raised bed use, cedar or pine?", T0),
    ("a1", "assistant", "I suggest cedar boards because they resist rot.", T0 + 60),
    ("u2", "user", "Yes, let's do that. I'll order the cedar boards tomorrow.", T0 + 120),
    ("u3", "user", "Different thing: what soup should I cook this winter?", T0 + 7 * HOUR),
    ("a3", "assistant", "Try a lentil soup with cumin.", T0 + 7 * HOUR + 60),
    ("u4", "user", "I prefer soups without meat, always.", T0 + 7 * HOUR + 120),
]


def _export(root: Path) -> Path:
    mapping: dict[str, Any] = {
        "root": {"id": "root", "parent": None, "children": [], "message": None}
    }
    parent = "root"
    for node, role, text, t in NODES:
        mapping[node] = {
            "id": node,
            "parent": parent,
            "children": [],
            "message": {
                "id": node,
                "author": {"role": role},
                "create_time": t,
                "content": {"content_type": "text", "parts": [text]},
                "metadata": {},
            },
        }
        mapping[parent]["children"].append(node)
        parent = node
    chat = {
        "id": "c-two",
        "title": "Synthetic two-part chat",
        "create_time": T0,
        "mapping": mapping,
        "current_node": parent,
    }
    root.mkdir(parents=True)
    (root / "conversations.json").write_text(json.dumps([chat]), encoding="utf-8")
    return root


def _model_answer(request: ModelRequest) -> dict[str, Any]:
    return {
        "records": [
            {
                "record_type": "decision",
                "assertion": "Synthetic: build the bed from cedar",
                "actor": "user",
                "acceptance": "explicit",
                "quotes": [{"message_id": "u2", "text": "let's do that"}],
            }
        ]
    }


def test_model_records_replace_rule_records_only_where_the_model_ran(tmp_path: Path) -> None:
    settings = Settings(workspace_root=tmp_path / "ws")
    run_import(_export(tmp_path / "export"), "acct", format_id=None, settings=settings)
    with Session(create_sqlite_engine(database_path(settings))) as session:
        [cid] = session.scalars(select(ConversationRow.conversation_id)).all()
        chat = load_conversation(session, cid)
        segments = [
            (s.segment_id, segment_extraction_messages(chat, s))
            for s in load_segments(session, chat)
        ]
        assert len(segments) == 2, "the pause should start a second segment"
        occurrences = actions.load_occurrences(session, list(chat.revisions.values()))
        rules = [
            RuleExtractor("decisions", decisions.EXTRACTOR_VERSION, decisions.extract_decisions),
            RuleExtractor(
                "preferences", preferences.EXTRACTOR_VERSION, preferences.extract_preferences
            ),
            RuleExtractor(
                "actions",
                actions.EXTRACTOR_VERSION,
                partial(actions.extract_actions, occurrences=occurrences),
            ),
        ]
        run(session, segments, rules)
        before = render_note(rich_conversation_note(session, cid, taxonomy=None).model)
        assert "I'll order the cedar boards tomorrow." in before  # a rule record, segment 1

        runner = ModelStageRunner(session, FakeProvider(_model_answer), EgressPolicy(text_llm=True))
        assert run(session, segments[:1], [knowledge_extractor(runner)]).done
        stored = session.scalar(select(func.count()).select_from(KnowledgeRecordRow))
        after = render_note(rich_conversation_note(session, cid, taxonomy=None).model)

    assert "Synthetic: build the bed from cedar" in after  # the model's record
    assert "I'll order the cedar boards tomorrow." not in after  # segment 1's rule record
    assert "I prefer soups without meat, always." in after  # segment 2: no model run
    assert "3 rule-based record(s) left out: a model extraction covers their segments." in after
    assert "rule-based record(s) left out" not in before
    assert stored == 5  # four rule records and the model's one: nothing deleted
