"""NOTE-017: a long chat digested in parts reads as one ordered digest.

The late_rejection fixture is split into parts with a small budget. The
fake model writes what real sessions wrote in the first score: two
sentences per part, worded "In this part..." and "This part ...". The
merged digest must keep chat order and lose the part wording, and the
note check must fail a note that still has it.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from knowledge_engine.digest.stage import (
    PART_WORDING,
    DigestStage,
    chat_messages,
    without_part_wording,
)
from knowledge_engine.documents.rich_note import rich_conversation_note
from knowledge_engine.evaluation.note_checks import CheckStatus, check_note
from knowledge_engine.importer import import_source
from knowledge_engine.importer.records import ConversationRow
from knowledge_engine.infrastructure.db import create_sqlite_engine, database_path
from knowledge_engine.providers.base import FakeProvider, ModelRequest
from knowledge_engine.providers.ledger import ModelStageRunner
from knowledge_engine.rendering.markdown import render_note
from knowledge_engine.rendering.transcript import load_conversation
from knowledge_engine.settings import EgressPolicy, Settings

LONG = Path(__file__).resolve().parents[1] / "fixtures" / "chatgpt" / "late_rejection"
_TAG = re.compile(r"^\[m:([^\]]+)\] (\w+):\n(.+)$", re.M)
_PART = re.compile(r"^Part (\d+) of (\d+) of a longer chat\.", re.M)


def _per_part(request: ModelRequest) -> dict[str, Any]:
    part = _PART.search(request.input_text)
    n = part.group(1) if part else "1"
    message_id, _, text = _TAG.findall(request.input_text)[0]
    cite = [{"message_id": f"[m:{message_id}]", "text": " ".join(text.split()[:4])}]
    return {
        "summary": [
            {"text": f"In this part, step {n} begins.", "quotes": cite},
            {"text": f"This part ends with step {n} done.", "quotes": cite},
        ],
        "purpose": {"text": "In this part of the chat, the user plans.", "quotes": cite},
        "status": {"value": "open", "quotes": cite},
        "intent": {"value": "plan", "text": "Plan this part.", "quotes": cite},
        "insights": [{"text": f"This section shows idea {n}.", "quotes": cite}],
    }


def test_a_three_part_chat_gives_one_ordered_summary_and_a_clean_note(tmp_path: Path) -> None:
    settings = Settings(workspace_root=tmp_path / "ws")
    import_source(LONG / "export", "fixture", settings=settings)
    engine = create_sqlite_engine(database_path(settings))
    with Session(engine) as session:
        [cid] = session.scalars(select(ConversationRow.conversation_id)).all()
        chat = load_conversation(session, cid)
        total = sum(len(m.text) for m in chat_messages(chat))
        provider = FakeProvider(_per_part)
        # A budget that cuts this chat into at least three parts.
        budget = max(max(len(m.text) for m in chat_messages(chat)) * 2, total // 3)
        stage = DigestStage(
            ModelStageRunner(session, provider, EgressPolicy(text_llm=True)), max_characters=budget
        )
        outcome = stage.run(chat)
        parts = len(provider.submitted)
        assert parts >= 3 and outcome.digest is not None
        digest = outcome.digest

        texts = [item.text for item in digest.summary]
        steps = [int(re.search(r"step (\d+)", t, re.I).group(1)) for t in texts]  # type: ignore[union-attr]
        assert steps == sorted(steps)  # chat order, not round-robin order
        assert len(set(steps)) == min(4, parts)  # every part kept while there is room
        everything = [*texts, digest.purpose.text, digest.intent_item.text]  # type: ignore[union-attr]
        everything += [i.text for i in digest.insights]
        assert not [t for t in everything if PART_WORDING.search(t)], everything
        assert texts[0] == "Step 1 begins."

        text = render_note(rich_conversation_note(session, cid, digest=digest).model)
        findings = {f.check: f.status for f in check_note(session, cid, text).findings}
        assert findings["part_wording"] is CheckStatus.PASS
        # A note that still says "this part" fails that check, and only that one.
        stale = text.replace("Step 1 begins.", "In this part, step 1 begins.", 1)
        assert stale != text
        report = check_note(session, cid, stale)
        assert {f.check for f in report.findings if f.status is CheckStatus.FAIL} == {
            "part_wording"
        }
    engine.dispose()


def test_part_wording_is_rewritten_without_changing_the_point() -> None:
    assert without_part_wording("In this part, the user picks cedar.") == "The user picks cedar."
    assert without_part_wording("This part ends in a plan.") == "The chat ends in a plan."
    assert without_part_wording("The user drops this section of the chat.") == (
        "The user drops the chat."
    )
    assert without_part_wording("The section on taxes is long.") == "The section on taxes is long."
