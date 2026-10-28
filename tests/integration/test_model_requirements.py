"""NOTE-025 and NOTE-023 (extractor half): short constraints and open endings.

Synthetic chats through the NOTE-005 model extractor with ``FakeProvider``:

* "No repeats, 10 questions" from the user is stored as the user's
  requirement;
* the same words quoted only from the assistant become its proposal (the
  existing rule 1, unchanged);
* a pasted setup prompt that says the same gives no record (rule 3);
* a draft letter the user never said was sent is kept as an open question.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from knowledge_engine.domain.enums import Role
from knowledge_engine.extraction.model_knowledge import (
    INSTRUCTIONS,
    PROMPT_VERSION,
    knowledge_extractor,
)
from knowledge_engine.extraction.records import RecordType
from knowledge_engine.extraction.runner import run
from knowledge_engine.extraction.store import KnowledgeRecordRow, load
from knowledge_engine.extraction.text import segment_extraction_messages
from knowledge_engine.importer.records import ConversationRow
from knowledge_engine.importer.run import run_import
from knowledge_engine.infrastructure.db import create_sqlite_engine, database_path
from knowledge_engine.providers.base import FakeProvider, ModelRequest
from knowledge_engine.providers.ledger import ModelStageRunner
from knowledge_engine.rendering.transcript import load_conversation
from knowledge_engine.segmentation.overrides import load_segments
from knowledge_engine.settings import EgressPolicy, Settings

SETUP = (
    "You are a quiz master for a synthetic pub quiz. Always write 10 questions, never "
    "repeat a question, keep every question under 20 words and give the answers at the end. "
    "Use British spelling throughout and keep a friendly tone for every round you write."
)
CHATS = {
    "quiz": [
        ("user", "Write a synthetic quiz about rivers. No repeats, 10 questions."),
        ("assistant", "Here are 10 questions about rivers, none repeated."),
    ],
    "offer": [
        ("user", "Write a synthetic quiz about mountains."),
        ("assistant", "I could do no repeats, 10 questions. Shall I?"),
    ],
    "setup": [
        ("user", SETUP),
        ("assistant", "Ready when you are."),
    ],
    "draft": [
        ("user", "Write my synthetic landlord a short letter about the boiler."),
        (
            "assistant",
            "Here is a draft:\n\nDear Ms Synthetic,\n\nThe boiler stopped on Monday.\n\n"
            "Kind regards,\nSam",
        ),
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
    return {
        "id": cid,
        "title": f"Synthetic {cid}",
        "create_time": 1704067200.0,
        "mapping": mapping,
        "current_node": parent,
    }


def _answer(request: ModelRequest) -> dict[str, Any]:
    """What a model would say for each synthetic chat."""
    text = request.input_text

    def record(kind: str, actor: str, node: str, words: str) -> dict[str, Any]:
        return {
            "record_type": kind,
            "assertion": f"Synthetic {kind}",
            "actor": actor,
            "acceptance": "not_applicable",
            "quotes": [{"message_id": node, "text": words}],
        }

    if "[m:quiz-0]" in text:
        return {"records": [record("requirement", "user", "quiz-0", "No repeats, 10 questions")]}
    if "[m:offer-1]" in text:
        # Mislabelled: the assistant's words, called the user's requirement.
        return {"records": [record("requirement", "user", "offer-1", "no repeats, 10 questions")]}
    if "[m:setup-0]" in text:
        return {"records": [record("requirement", "user", "setup-0", "Always write 10 questions")]}
    if "[m:draft-1]" in text:
        return {"records": [record("question", "user", "draft-1", "Kind regards,\nSam")]}
    return {"records": []}


@pytest.fixture
def records(tmp_path: Path) -> Any:
    export = tmp_path / "export"
    export.mkdir()
    chats = [_chat(cid, turns) for cid, turns in CHATS.items()]
    (export / "conversations.json").write_text(json.dumps(chats), encoding="utf-8")
    settings = Settings(workspace_root=tmp_path / "ws")
    run_import(export, "acct", format_id=None, settings=settings)
    engine = create_sqlite_engine(database_path(settings))
    with Session(engine) as session:
        segments = []
        names = {}
        for cid, native in session.execute(
            select(ConversationRow.conversation_id, ConversationRow.native_conversation_id)
        ).all():
            chat = load_conversation(session, cid)
            for seg in load_segments(session, chat):
                segments.append((seg.segment_id, segment_extraction_messages(chat, seg)))
            names.update(dict.fromkeys(chat.revisions.values(), native))
        runner = ModelStageRunner(session, FakeProvider(_answer), EgressPolicy(text_llm=True))
        report = run(session, segments, [knowledge_extractor(runner)])
        assert report.done and not report.failed
        stored = [
            load(session, rid) for rid in session.scalars(select(KnowledgeRecordRow.record_id))
        ]
        yield {
            name: [r for r in stored if names.get(r.evidence[0].revision_id) == name]
            for name in CHATS
        }
    engine.dispose()


def test_the_prompt_names_requirements_and_open_endings() -> None:
    assert PROMPT_VERSION == "knowledge-v2"
    assert "- requirement:" in INSTRUCTIONS and "no repeats" in INSTRUCTIONS
    assert "never said was sent" in INSTRUCTIONS and "report back" in INSTRUCTIONS


def test_a_users_short_constraint_is_their_requirement(records: dict[str, Any]) -> None:
    [found] = records["quiz"]
    assert (found.record_type, found.actor) == (RecordType.REQUIREMENT, Role.USER)


def test_the_same_words_from_the_assistant_are_its_proposal(records: dict[str, Any]) -> None:
    [found] = records["offer"]
    assert (found.record_type, found.actor) == (RecordType.PROPOSAL, Role.ASSISTANT)


def test_a_pasted_setup_prompt_gives_no_requirement(records: dict[str, Any]) -> None:
    assert records["setup"] == []


def test_an_unsent_draft_is_kept_as_an_open_question(records: dict[str, Any]) -> None:
    [found] = records["draft"]
    assert found.record_type is RecordType.QUESTION
