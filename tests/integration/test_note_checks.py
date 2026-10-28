"""NOTE-011 (code checks): a rich note's citations are real and its claims cited.

The chat is synthetic; its records come from the real rule extractors and
its digest from ``FakeProvider`` through the NOTE-003 stage, so the checks
run on what the engine really writes. Each failure case breaks one thing
in that real note (or in the store) and shows that exactly one check
catches it.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from knowledge_engine.cli.main import main
from knowledge_engine.digest.stage import DigestStage
from knowledge_engine.documents.rich_note import rich_conversation_note
from knowledge_engine.evaluation.note_checks import CheckStatus, NoteCheckReport, check_note
from knowledge_engine.extraction import actions, decisions, preferences
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

_TAG = re.compile(r"^\[m:([^\]]+)\] (\w+):\n(.+)$", re.M)


def _message(node: str, role: str, text: str, t: float) -> dict[str, Any]:
    return {
        "id": node,
        "author": {"role": role},
        "create_time": t,
        "content": {"content_type": "text", "parts": [text]},
        "metadata": {},
    }


def _export(root: Path) -> Path:
    nodes = [
        ("u1", None, "user", "Which wood should the raised bed use, cedar or pine?"),
        ("a1b", "u1", "assistant", "Pine is cheaper, an alternative reply."),
        ("a1", "u1", "assistant", "I suggest cedar boards because they resist rot."),
        ("u2", "a1", "user", "Yes, let's do that. I'll order the cedar boards tomorrow."),
        ("a2", "u2", "assistant", "Good. Line the bed with landscape fabric first."),
    ]
    mapping: dict[str, Any] = {
        "root": {"id": "root", "parent": None, "children": [], "message": None}
    }
    for i, (node, parent, role, text) in enumerate(nodes):
        mapping[node] = {
            "id": node,
            "parent": parent or "root",
            "children": [],
            "message": _message(node, role, text, 1704067200.0 + 60 * i),
        }
        mapping[parent or "root"]["children"].append(node)
    chat = {
        "id": "c-garden",
        "title": "Synthetic garden",
        "create_time": 1704067200.0,
        "mapping": mapping,
        "current_node": "a2",
    }
    root.mkdir(parents=True)
    (root / "conversations.json").write_text(json.dumps([chat]), encoding="utf-8")
    return root


def _digest_answer(request: ModelRequest) -> dict[str, Any]:
    tags = _TAG.findall(request.input_text)
    first_id, _, first_text = tags[0]
    last_id, _, last_text = tags[-1]
    start = [{"message_id": first_id, "text": " ".join(first_text.split()[:3])}]
    end = [{"message_id": last_id, "text": " ".join(last_text.split()[:3])}]
    return {
        "summary": [
            {"text": "The user asked which wood to use.", "quotes": start},
            {"text": "They chose cedar.", "quotes": end},
        ],
        "purpose": {"text": "Pick a wood for a raised bed.", "quotes": start},
        "status": {"value": "settled", "quotes": end},
        "intent": {"value": "decide", "text": "Choose a wood.", "quotes": start},
        "tensions": [{"text": "Price against rot resistance.", "quotes": start}],
        "next_steps": [{"text": "Buy landscape fabric for the lining.", "quotes": end}],
    }


@dataclass
class World:
    settings: Settings
    session: Session
    conversation_id: str
    text: str


@pytest.fixture
def world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[World]:
    settings = Settings(workspace_root=tmp_path / "ws")
    monkeypatch.setenv("KE_WORKSPACE_ROOT", str(settings.workspace_root))
    run_import(_export(tmp_path / "export"), "acct", format_id=None, settings=settings)
    session = Session(create_sqlite_engine(database_path(settings)))
    [cid] = session.scalars(select(ConversationRow.conversation_id)).all()
    chat = load_conversation(session, cid)
    segments = [
        (s.segment_id, segment_extraction_messages(chat, s)) for s in load_segments(session, chat)
    ]
    occurrences = actions.load_occurrences(session, list(chat.revisions.values()))
    run(
        session,
        segments,
        [
            RuleExtractor("decisions", decisions.EXTRACTOR_VERSION, decisions.extract_decisions),
            RuleExtractor(
                "preferences", preferences.EXTRACTOR_VERSION, preferences.extract_preferences
            ),
            RuleExtractor(
                "actions",
                actions.EXTRACTOR_VERSION,
                partial(actions.extract_actions, occurrences=occurrences),
            ),
        ],
    )
    runner = ModelStageRunner(session, FakeProvider(_digest_answer), EgressPolicy(text_llm=True))
    outcome = DigestStage(runner).run(chat)
    assert outcome.state == "done"
    session.commit()
    note = rich_conversation_note(session, cid, digest=outcome.digest)
    yield World(settings, session, cid, render_note(note.model))
    session.close()


def _status(report: NoteCheckReport) -> dict[str, CheckStatus]:
    return {f.check: f.status for f in report.findings}


def _failed(report: NoteCheckReport) -> set[str]:
    return {f.check for f in report.findings if f.status is CheckStatus.FAIL}


def test_the_engines_own_note_passes_every_check(world: World) -> None:
    report = check_note(world.session, world.conversation_id, world.text)

    assert report.passed, report.findings
    assert set(_status(report).values()) == {CheckStatus.PASS}
    assert "Decided" in world.text and "Next steps" in world.text  # it really has content


def test_a_wrong_message_number_is_caught(world: World) -> None:
    broken = world.text.replace("|m3]]", "|m4]]", 1)
    assert broken != world.text
    report = check_note(world.session, world.conversation_id, broken)

    assert _failed(report) == {"citations_real"}
    [finding] = [f for f in report.findings if f.check == "citations_real"]
    assert "m4 should read m3" in finding.problems[0]


def test_an_uncited_claim_is_caught(world: World) -> None:
    broken = re.sub(r"^(- They chose cedar\.) .*$", r"\1", world.text, count=1, flags=re.MULTILINE)
    broken = broken.replace("\n## Next steps\n", "\n## Next steps\n\n- Paint the boards blue.\n", 1)
    report = check_note(world.session, world.conversation_id, broken)

    assert _failed(report) == {"claims_cited"}
    [finding] = [f for f in report.findings if f.check == "claims_cited"]
    assert any("Next steps" in p for p in finding.problems)


def test_an_assistant_held_decision_is_caught(world: World) -> None:
    row = world.session.scalars(select(KnowledgeRecordRow)).all()
    decision = next(r for r in row if json.loads(r.record_json)["record_type"] == "decision")
    data = json.loads(decision.record_json)
    data["actor"] = "assistant"
    world.session.execute(
        update(KnowledgeRecordRow)
        .where(KnowledgeRecordRow.record_id == decision.record_id)
        .values(record_json=json.dumps(data))
    )
    report = check_note(world.session, world.conversation_id, world.text)

    assert _failed(report) == {"decisions_user_held"}


def test_a_next_step_repeating_a_tension_is_a_warning(world: World) -> None:
    broken = world.text.replace(
        "\n## Next steps\n", "\n## Next steps\n\n- Price against rot resistance. [[x#^y|m1]]\n", 1
    )
    report = check_note(world.session, world.conversation_id, broken)

    assert _status(report)["tensions_next_steps"] is CheckStatus.WARN
    assert report.passed  # a warning, not a failure


def test_an_evidence_box_under_an_empty_section_and_an_overlong_note_fail(world: World) -> None:
    broken = world.text.replace(
        "None in this chat.", "None in this chat.\n\n> [!quote]- Evidence\n> m1", 1
    )
    broken += "\n" + "padding " * 20_000
    report = check_note(world.session, world.conversation_id, broken)

    assert _failed(report) == {"empty_sections", "budget"}


def test_cli_rubric_reports_counts_and_fails_nothing(
    world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    capsys.readouterr()
    code = main(["--json", "docs", "rubric", "--all"])
    payload = json.loads(capsys.readouterr().out)

    assert code == 0, payload
    assert payload["data"]["notes"] == 1 and payload["data"]["passed"] == 1
    assert payload["data"]["checks"]["citations_real"]["pass"] == 1
