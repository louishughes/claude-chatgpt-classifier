"""NOTE-027: a claim stated several times in one chat gets one line in its note.

A synthetic chat where the user asks for a quiz three times: twice for ten
questions with no repeats, once for twelve. The records are added as an
extractor would store them. The note should show the two "ten" requirements
on one line citing both messages, keep "twelve" apart (a near miss: the
numbers differ), and never fold a preference into a requirement.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from knowledge_engine.documents.rich_note import rich_conversation_note
from knowledge_engine.domain.enums import Role
from knowledge_engine.domain.models import EvidenceRef
from knowledge_engine.extraction.records import CandidateRecord, Provenance, RecordType, Scope
from knowledge_engine.extraction.store import KnowledgeRecordRow, add_candidates
from knowledge_engine.graph.offsets import quote_hash
from knowledge_engine.importer.records import ConversationRow
from knowledge_engine.importer.run import run_import
from knowledge_engine.infrastructure.db import create_sqlite_engine, database_path
from knowledge_engine.rendering.markdown import render_note
from knowledge_engine.rendering.transcript import StoredConversation, load_conversation
from knowledge_engine.settings import Settings

T0 = 1704067200.0
ASKS = {
    "u1": "Synthetic: make a quiz with 10 questions and no repeats.",
    "u2": "Synthetic: again, a quiz of 10 questions with no repeats please.",
    "u3": "Synthetic: now make it 12 questions with no repeats.",
}


def _export(root: Path) -> Path:
    turns = []
    for n, words in ASKS.items():
        turns += [(n, "user", words), (f"a{n[1]}", "assistant", "Synthetic: here is the quiz.")]
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
    chat = {"id": "c-quiz", "title": "Synthetic quiz", "create_time": T0,
            "mapping": mapping, "current_node": parent}  # fmt: skip
    root.mkdir(parents=True)
    (root / "conversations.json").write_text(json.dumps([chat]), encoding="utf-8")
    return root


def _record(
    chat: StoredConversation, native: str, assertion: str, kind: RecordType = RecordType.REQUIREMENT
) -> CandidateRecord:
    cid = chat.conversation_id
    words = chat.messages[native].text or ""
    return CandidateRecord(
        record_type=kind,
        assertion=assertion,
        actor=Role.USER,
        scope=Scope.CONVERSATION,
        scope_id=cid,
        evidence=(
            EvidenceRef(
                revision_id=chat.revisions[native],
                start=0,
                end=len(words),
                quote_sha256=quote_hash(words),
                actor=Role.USER,
            ),
        ),
    )


def test_a_repeated_claim_shares_one_line_and_a_near_miss_does_not(tmp_path: Path) -> None:
    settings = Settings(workspace_root=tmp_path / "ws")
    run_import(_export(tmp_path / "export"), "acct", format_id=None, settings=settings)
    with Session(create_sqlite_engine(database_path(settings))) as session:
        [cid] = session.scalars(select(ConversationRow.conversation_id)).all()
        chat = load_conversation(session, cid)
        add_candidates(
            session,
            [
                _record(chat, "u1", "Quiz of 10 questions, no repeats"),
                _record(chat, "u2", "10 questions in the quiz, no repeats"),
                _record(chat, "u3", "Quiz of 12 questions, no repeats"),
                _record(chat, "u1", "Quiz of 10 questions, no repeats", RecordType.PREFERENCE),
            ],
            Provenance(
                stage_id="extract.test.v1", stage_key="stg_" + "e" * 64, extractor_version="t"
            ),
        )
        session.commit()
        text = render_note(rich_conversation_note(session, cid).model)
        stored = session.scalar(select(func.count()).select_from(KnowledgeRecordRow))

    lines = [line for line in text.splitlines() if "questions" in line and line.startswith("- **")]
    ten = [line for line in lines if "10 questions" in line and "Requirement" in line]
    assert len(ten) == 1
    assert "Stated 2 times." in ten[0]
    assert re.findall(r"\|(m\d+)\]\]", ten[0]) == ["m1", "m3"]  # both asks, in order
    assert 'm3 (user): "Synthetic: again' in text  # and both quotes in its evidence
    assert sum("12 questions" in line for line in lines) == 1  # numbers differ: its own line
    assert sum("Preference" in line for line in lines) == 1  # another type: its own line
    assert "1 repeated record(s) shown on the line of the claim they repeat." in text
    assert stored == 4  # the records themselves are untouched
