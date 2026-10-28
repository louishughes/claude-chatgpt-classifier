"""NRM-004 / LEG-005: annotated topic boundaries, full coverage, nothing clipped."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from knowledge_engine.importer import import_source
from knowledge_engine.importer.records import ConversationRow
from knowledge_engine.infrastructure.db import create_sqlite_engine, database_path
from knowledge_engine.rendering.transcript import StoredConversation, load_conversation
from knowledge_engine.segmentation.segmenter import (
    boundary_scores,
    segment_conversation,
    truncation_count,
)
from knowledge_engine.settings import Settings

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "chatgpt"
EXPECTED: dict[str, Any] = json.loads(
    (FIXTURES / "topic_segments" / "manifest.json").read_text(encoding="utf-8")
)["expected"]


def _load(case: str, root: Path) -> dict[str, StoredConversation]:
    settings = Settings(workspace_root=root / case)
    import_source(FIXTURES / case / "export", "fixture", settings=settings)
    engine = create_sqlite_engine(database_path(settings))
    try:
        with Session(engine) as session:
            return {
                row.native_conversation_id: load_conversation(session, row.conversation_id)
                for row in session.scalars(select(ConversationRow))
            }
    finally:
        engine.dispose()


@pytest.fixture(scope="module")
def chats(tmp_path_factory: pytest.TempPathFactory) -> Iterator[dict[str, StoredConversation]]:
    yield _load("topic_segments", tmp_path_factory.mktemp("seg"))


def test_annotated_boundaries_are_found(chats: dict[str, StoredConversation]) -> None:
    for native, gold in EXPECTED["topic_starts"].items():
        segments = segment_conversation(chats[native])
        predicted = [s.messages[0] for s in segments[1:]]
        assert boundary_scores(predicted, gold) == {"precision": 1.0, "recall": 1.0, "f1": 1.0}
        for segment in segments[1:]:
            assert segment.reason == EXPECTED["boundary_reasons"][segment.messages[0]]


def test_a_short_no_stays_with_what_it_rejects(chats: dict[str, StoredConversation]) -> None:
    [native] = [n for n, gold in EXPECTED["topic_starts"].items() if gold]
    segments = segment_conversation(chats[native])
    for group in EXPECTED["same_segment"]:
        owners = {s.segment_id for s in segments for m in group if m in s.messages}
        assert len(owners) == 1


@pytest.mark.parametrize("case", ["topic_segments", "branches_edit", "branches_regen"])
def test_every_message_lands_in_exactly_one_segment(case: str, tmp_path: Path) -> None:
    for chat in _load(case, tmp_path).values():
        segments = segment_conversation(chat)
        placed = [m for s in segments for m in s.messages]
        assert sorted(placed) == sorted(chat.messages)  # all of them, once each
        assert truncation_count(segments) == 0
        # Branches are segmented apart: a segment never mixes sections.
        active = set(chat.graph.active_messages)
        for segment in segments:
            assert (segment.section == "active") == bool(set(segment.messages) & active)


def test_segment_ids_are_stable(chats: dict[str, StoredConversation]) -> None:
    for chat in chats.values():
        first = [s.segment_id for s in segment_conversation(chat)]
        assert first == [s.segment_id for s in segment_conversation(chat)]
        assert len(set(first)) == len(first)


def test_cli_segments(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from knowledge_engine.cli.main import main

    settings = Settings(workspace_root=tmp_path / "ws")
    import_source(FIXTURES / "topic_segments" / "export", "fixture", settings=settings)
    monkeypatch.setenv("KE_WORKSPACE_ROOT", str(settings.workspace_root))
    engine = create_sqlite_engine(database_path(settings))
    with Session(engine) as session:
        conv = session.scalars(
            select(ConversationRow.conversation_id).where(
                ConversationRow.title == "Synthetic three topics"
            )
        ).one()
    engine.dispose()
    assert main(["--json", "segments", conv]) == 0
    data = json.loads(capsys.readouterr().out)["data"]
    assert data["truncation_count"] == 0
    assert [s["reason"] for s in data["segments"]] == ["start", "vocabulary", "gap"]
    assert "Synthetic" not in json.dumps(data)  # no message text
    assert main(["--json", "segments", "conv_missing"]) != 0
