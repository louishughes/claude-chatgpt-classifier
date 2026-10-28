"""LEG-001: regression cases for failures of the owner's earlier pipelines.

Each test's docstring cites the preprocessing step it guards, from
``docs/reference/previous-attempts-review.md`` §2a. The fixture is
``tests/fixtures/chatgpt/legacy_regressions`` (synthetic, generated).

Already covered elsewhere, so not repeated here: one image used by two
messages gives 1 asset and 2 occurrences (``repeated_image`` in
``test_media_import.py``), and an edit plus a regeneration as separate
cases (``branches_edit`` / ``branches_regen``).
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from knowledge_engine.importer import import_source
from knowledge_engine.importer.media import AssetOccurrenceRow
from knowledge_engine.importer.records import ConversationRow
from knowledge_engine.infrastructure.db import create_sqlite_engine, database_path
from knowledge_engine.rendering.markdown import render_note
from knowledge_engine.rendering.transcript import (
    StoredConversation,
    load_conversation,
    transcript_model,
)
from knowledge_engine.settings import Settings

CASE = Path(__file__).resolve().parents[1] / "fixtures" / "chatgpt" / "legacy_regressions"
EXPECTED: dict[str, Any] = json.loads((CASE / "manifest.json").read_text(encoding="utf-8"))[
    "expected"
]


@pytest.fixture(scope="module")
def conversations(
    tmp_path_factory: pytest.TempPathFactory,
) -> Iterator[dict[str, StoredConversation]]:
    settings = Settings(workspace_root=tmp_path_factory.mktemp("ws"))
    import_source(CASE / "export", "fixture", settings=settings)
    engine = create_sqlite_engine(database_path(settings))
    try:
        with Session(engine) as session:
            loaded = {
                row.native_conversation_id: load_conversation(session, row.conversation_id)
                for row in session.scalars(select(ConversationRow))
            }
            occurrences = session.scalars(select(AssetOccurrenceRow)).all()
            loaded["_occurrences"] = occurrences  # type: ignore[assignment]
            yield loaded
    finally:
        engine.dispose()


def _by_title(conversations: dict[str, Any], title: str) -> list[StoredConversation]:
    return [c for k, c in conversations.items() if not k.startswith("_") and c.title == title]


def test_interleaved_branches_are_never_stitched_together(
    conversations: dict[str, StoredConversation],
) -> None:
    """§2a P4: sorting every node by time mixed edited and regenerated branches.

    Here the timestamps interleave across an edit and a regeneration; the
    active path is still exactly one branch, and the note's active section
    holds no message from the others.
    """
    [mixed] = _by_title(conversations, "Synthetic interleaved")
    assert list(mixed.graph.active_messages) == EXPECTED["active_path_node_ids"]
    assert not set(EXPECTED["inactive_node_ids"]) & set(mixed.graph.active_messages)
    note = render_note(transcript_model(mixed))
    active = note.split("## Alternate branches")[0]
    for node in EXPECTED["inactive_node_ids"]:
        assert mixed.messages[node].text not in active


def test_same_title_chats_stay_separate(conversations: dict[str, StoredConversation]) -> None:
    """§2a P1: files were named by title and date, so same-title chats collided."""
    twins = _by_title(conversations, "Synthetic same title")
    assert len(twins) == 2
    assert len({c.conversation_id for c in twins}) == 2


def test_short_replies_are_kept_as_messages(conversations: dict[str, StoredConversation]) -> None:
    """§2a P6 (and v1 stage 1): "no", "ok" scored as filler and were dropped.

    They're kept verbatim, each with its own anchored line in the note.
    """
    [short] = [
        c
        for c in _by_title(conversations, "Synthetic same title")
        if len(c.graph.active_messages) == 7
    ]
    texts = [short.messages[n].text for n in short.graph.active_messages]
    for reply in EXPECTED["short_replies"]:
        assert reply in texts
    note = render_note(transcript_model(short))
    for reply in EXPECTED["short_replies"]:
        assert re.search(rf"^{re.escape(reply)} \^node-", note, re.MULTILINE)


def test_code_and_execution_output_are_kept_and_numbered(
    conversations: dict[str, StoredConversation],
) -> None:
    """§2a v1 stage 0 and P4: a parser dropped code and tool output.

    Dropping them also shifts every later message number, the answer-key
    numbering bug found in REV-003; numbers here count every message.
    """
    [code] = _by_title(conversations, "Synthetic code run")
    numbers = {n: code.graph.message_number(n) for n in EXPECTED["message_numbers"]}
    assert numbers == EXPECTED["message_numbers"]
    assert code.messages["code-a0"].content_type == "code"
    assert code.messages["code-a0"].text == "print('synthetic')"
    assert code.messages["code-t0"].content_type == "execution_output"
    assert code.messages["code-t0"].text == "synthetic"


def test_image_occurrence_is_recorded_on_its_message(
    conversations: dict[str, Any],
) -> None:
    """§2a P2/P3: 0 of 931 images were linked to the chats that used them."""
    [code] = _by_title(conversations, "Synthetic code run")
    occurrences = conversations["_occurrences"]
    states: dict[str, int] = {}
    for occurrence in occurrences:
        states[occurrence.availability] = states.get(occurrence.availability, 0) + 1
    assert states == EXPECTED["asset_occurrences"]
    [occurrence] = occurrences
    assert occurrence.revision_id == code.revisions["code-a1"]
    assert code.media[code.revisions["code-a1"]][0].availability == "available"


def test_unreferenced_image_files_are_reported(tmp_path: Path) -> None:
    """§2a P2: images were copied and catalogued with no record of their use.

    An image file in the export that no message uses is counted as
    unreferenced in the import report, not silently attached anywhere.
    """
    report = import_source(
        CASE / "export", "fixture", settings=Settings(workspace_root=tmp_path / "ws")
    )
    media_files = report.integrity["media_files"]
    assert media_files["listed"] == EXPECTED["image_files"]
    assert media_files["unreferenced"] == EXPECTED["unreferenced_image_files"]


def test_active_path_lengths_match_the_answer_key(
    conversations: dict[str, StoredConversation],
) -> None:
    """§2a P7: branches were guessed from file names; here the real tree decides."""
    lengths = {
        native: len(c.graph.active_messages)
        for native, c in conversations.items()
        if not native.startswith("_")
    }
    assert lengths == EXPECTED["active_path_messages"]
