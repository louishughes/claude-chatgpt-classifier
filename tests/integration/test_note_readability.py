"""NOTE-010: ``ke docs check`` reports notes over budget and empty-section evidence.

Every fixture export is imported, the rule extractors run, a fake provider
writes each chat's digest (so the generated sections are filled too), and
each chat's rich note is written into a vault beside its transcript. The
vault check must then pass for every note: links resolve, and each note is
within its budget with no evidence box in an empty section.
"""

from __future__ import annotations

import json
import re
from functools import partial
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from knowledge_engine.digest.stage import DigestStage
from knowledge_engine.documents.rich_note import TEMPLATE_VERSION, write_rich_note
from knowledge_engine.evaluation.end_to_end import check_vault
from knowledge_engine.extraction import actions, decisions, entities, preferences
from knowledge_engine.extraction.runner import RuleExtractor, run
from knowledge_engine.extraction.text import segment_extraction_messages
from knowledge_engine.importer import import_source
from knowledge_engine.importer.records import ConversationRow
from knowledge_engine.infrastructure.db import create_sqlite_engine, database_path
from knowledge_engine.providers.base import FakeProvider, ModelRequest
from knowledge_engine.providers.ledger import ModelStageRunner
from knowledge_engine.rendering.transcript import load_conversation, write_transcript
from knowledge_engine.segmentation.overrides import load_segments
from knowledge_engine.settings import EgressPolicy, Settings

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "chatgpt"
CASES = sorted(p.parent.name for p in FIXTURES.glob("*/export"))
_TAG = re.compile(r"^\[m:([^\]]+)\] (\w+):\n(.+)$", re.M)


def _digest_answer(request: ModelRequest) -> dict[str, Any]:
    """A digest that fills every section, each item quoting the last message shown."""
    message_id, _, text = _TAG.findall(request.input_text)[-1]
    cite = [{"message_id": f"[m:{message_id}]", "text": text.split()[0]}]
    item = {"text": "Something was discussed.", "quotes": cite}
    return {
        "summary": [item],
        "purpose": item,
        "outcome": item,
        "status": {"value": "open", "quotes": cite},
        "intent": {"value": "learn", "text": "Find out.", "quotes": cite},
        "topics": [item],
        "insights": [item],
        "tensions": [item],
        "open_questions": [item],
        "next_steps": [item],
    }


def _extract(session: Session) -> None:
    chats = [
        load_conversation(session, c)
        for c in session.scalars(select(ConversationRow.conversation_id))
    ]
    segments = [
        (seg.segment_id, segment_extraction_messages(chat, seg))
        for chat in chats
        for seg in load_segments(session, chat)
    ]
    revisions = [r for chat in chats for r in chat.revisions.values()]
    occurrences = actions.load_occurrences(session, revisions)
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
            RuleExtractor("entities", entities.EXTRACTOR_VERSION, entities.extract_entities),
        ],
    )


@pytest.mark.parametrize("case", CASES)
def test_every_fixture_rich_note_passes_docs_check(case: str, tmp_path: Path) -> None:
    settings = Settings(workspace_root=tmp_path / "ws")
    export = FIXTURES / case / "export"
    zipped = sorted(export.glob("*.zip"))  # one case ships its export as the ZIP itself
    import_source(zipped[0] if zipped else export, "fixture", settings=settings)
    vault, store = tmp_path / "vault", settings.workspace_root / "archive"
    engine = create_sqlite_engine(database_path(settings))
    with Session(engine) as session:
        _extract(session)
        stage = DigestStage(
            ModelStageRunner(session, FakeProvider(_digest_answer), EgressPolicy(text_llm=True))
        )
        ids = list(session.scalars(select(ConversationRow.conversation_id)))
        for conversation_id in ids:
            chat = load_conversation(session, conversation_id)
            write_transcript(session, chat, vault, store)
            outcome = stage.run(chat)
            write_rich_note(session, conversation_id, vault, store, digest=outcome.digest)
    engine.dispose()

    check = check_vault(vault)
    assert check.readable == len(ids)  # every rich note had its budget checked
    assert check.readability == [], check.readability
    assert check.clean, (check.broken_links, check.broken_embeds)


def _rich(body: str, messages: int = 3, **extra: str) -> str:
    front = [f"generator: {TEMPLATE_VERSION}", f"messages: {messages}"]
    front += [f"{k}: {v}" for k, v in extra.items()]
    return "---\n" + "\n".join(front) + "\n---\n" + body


def test_cli_reports_budget_and_empty_evidence(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from knowledge_engine.cli.main import main

    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "Long.md").write_text(_rich("# Long\n\n" + "word " * 3_000), encoding="utf-8")
    (vault / "Padded.md").write_text(
        _rich("# Padded\n\n## Decisions\n\nNothing was decided.\n\n> [!quote]- Evidence\n> m1\n"),
        encoding="utf-8",
    )
    (vault / "Fine.md").write_text(
        _rich("# Fine\n\n## Decisions\n\n- **Use cedar.**\n> [!quote]- Evidence\n> m2\n"),
        encoding="utf-8",
    )
    assert main(["--json", "docs", "check", "--vault", str(vault)]) != 0
    out = json.loads(capsys.readouterr().out)
    assert out["error"]["code"] == "readability"
    found = sorted((p["note"], p["check"]) for p in out["data"]["readability"])
    assert found == [("Long.md", "budget"), ("Padded.md", "empty_evidence")]
    assert out["data"]["readable_notes"] == 3

    (vault / "Long.md").unlink()
    (vault / "Padded.md").unlink()
    assert main(["--json", "docs", "check", "--vault", str(vault)]) == 0
    assert "1 rich note(s) within budget" in json.loads(capsys.readouterr().out)["message"]
