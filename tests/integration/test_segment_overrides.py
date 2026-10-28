"""NRM-005: reviewer splits and merges, append-only, re-applied on every rerun."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DatabaseError
from sqlalchemy.orm import Session

from knowledge_engine.extraction.runner import ExtractionRunRow
from knowledge_engine.importer import import_source
from knowledge_engine.importer.records import ConversationRow
from knowledge_engine.infrastructure.db import create_sqlite_engine, database_path
from knowledge_engine.rendering.transcript import StoredConversation, load_conversation
from knowledge_engine.segmentation.overrides import (
    Action,
    OverrideError,
    SegmentOverrideRow,
    active_overrides,
    load_segments,
    orphaned,
    record_override,
    revalidation,
)
from knowledge_engine.segmentation.segmenter import (
    Segment,
    exchange_starts,
    section_messages,
    segment_conversation,
    truncation_count,
)
from knowledge_engine.settings import Settings

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "chatgpt"
EXPORT = FIXTURES / "topic_segments" / "export"
TITLE = "Synthetic three topics"


@pytest.fixture
def world(tmp_path: Path) -> Iterator[tuple[Settings, Session, StoredConversation]]:
    settings = Settings(workspace_root=tmp_path / "ws")
    import_source(EXPORT, "fixture", settings=settings)
    engine = create_sqlite_engine(database_path(settings))
    with Session(engine) as session:
        conv_id = session.scalars(
            select(ConversationRow.conversation_id).where(ConversationRow.title == TITLE)
        ).one()
        yield settings, session, load_conversation(session, conv_id)
    engine.dispose()


def _covered(conversation: StoredConversation, segments: list[Segment]) -> None:
    # Every message of the chat lands in exactly one segment.
    members = [m for s in segments for m in s.messages]
    assert sorted(members) == sorted(
        m for _, msgs in section_messages(conversation) for m in [x.native_id for x in msgs]
    )
    assert len(members) == len(set(members))
    assert truncation_count(segments) == 0


def test_merge_keeps_every_message_and_records_lineage(
    world: tuple[Settings, Session, StoredConversation],
) -> None:
    _, session, conv = world
    automatic = segment_conversation(conv)
    assert [s.messages[0] for s in automatic[1:]] == ["bread-u1", "py-u1"]
    record_override(
        session, conv, "bread-u1", Action.MERGE, reviewer="review-session-1", note="one topic"
    )
    merged = load_segments(session, conv)
    _covered(conv, merged)
    assert [s.messages[0] for s in merged[1:]] == ["py-u1"]
    assert merged[0].derived_from == (automatic[0].segment_id, automatic[1].segment_id)
    assert merged[1].segment_id == automatic[2].segment_id and merged[1].derived_from == ()


def test_split_only_where_an_exchange_starts(
    world: tuple[Settings, Session, StoredConversation],
) -> None:
    _, session, conv = world
    automatic = segment_conversation(conv)
    starts = {s.messages[0] for s in automatic}
    [(_, active)] = section_messages(conv)[:1]
    openers = exchange_starts(active)
    assert "shed-u4" not in openers  # the short "no" answers what came before
    with pytest.raises(OverrideError, match="exchange starts"):
        record_override(session, conv, "shed-u4", Action.SPLIT, reviewer="r")
    target = next(n for n in openers[1:] if n not in starts)
    record_override(session, conv, target, Action.SPLIT, reviewer="r")
    split = load_segments(session, conv)
    _covered(conv, split)
    assert len(split) == len(automatic) + 1
    [new] = [s for s in split if s.messages[0] == target]
    assert new.reason == "reviewer_split" and new.derived_from


def test_bad_decisions_are_refused(world: tuple[Settings, Session, StoredConversation]) -> None:
    _, session, conv = world
    first = segment_conversation(conv)[0].messages[0]
    with pytest.raises(OverrideError, match="named reviewer"):
        record_override(session, conv, "bread-u1", Action.MERGE, reviewer=" ")
    with pytest.raises(OverrideError, match="later segment"):
        record_override(session, conv, first, Action.MERGE, reviewer="r")
    with pytest.raises(OverrideError, match="already starts"):
        record_override(session, conv, "py-u1", Action.SPLIT, reviewer="r")
    with pytest.raises(OverrideError, match="nothing|no decision"):
        record_override(session, conv, "py-u1", Action.CLEAR, reviewer="r")
    assert session.scalars(select(SegmentOverrideRow)).all() == []


def test_overrides_survive_reimport_and_clear_restores(
    world: tuple[Settings, Session, StoredConversation],
) -> None:
    settings, session, conv = world
    record_override(session, conv, "bread-u1", Action.MERGE, reviewer="r")
    session.commit()
    expected = [s.segment_id for s in load_segments(session, conv)]
    import_source(EXPORT, "fixture", settings=settings)  # the same export again
    engine = create_sqlite_engine(database_path(settings))
    with Session(engine) as fresh:
        again = load_conversation(fresh, conv.conversation_id)
        assert [s.segment_id for s in load_segments(fresh, again)] == expected
        record_override(fresh, again, "bread-u1", Action.CLEAR, reviewer="r", note="undo")
        assert active_overrides(fresh, again.conversation_id) == {}
        assert load_segments(fresh, again) == segment_conversation(again)
        assert len(fresh.scalars(select(SegmentOverrideRow)).all()) == 2  # history kept
        fresh.commit()
    engine.dispose()


def test_log_is_append_only(world: tuple[Settings, Session, StoredConversation]) -> None:
    _, session, conv = world
    record_override(session, conv, "bread-u1", Action.MERGE, reviewer="r")
    session.commit()
    for statement in (
        "UPDATE segment_overrides SET reviewer = 'x'",
        "DELETE FROM segment_overrides",
    ):
        with pytest.raises(DatabaseError, match="append-only"):
            session.execute(text(statement))
        session.rollback()


def test_orphaned_decision_is_reported_and_ignored(
    world: tuple[Settings, Session, StoredConversation],
) -> None:
    _, session, conv = world
    # As if the chat had changed under an older decision: skip validation.
    session.add(
        SegmentOverrideRow(
            conversation_id=conv.conversation_id,
            native_message_id="shed-u4",
            action="split",
            reviewer="r",
        )
    )
    session.add(
        SegmentOverrideRow(
            conversation_id=conv.conversation_id,
            native_message_id="gone-u9",
            action="merge",
            reviewer="r",
        )
    )
    session.flush()
    assert orphaned(session, conv) == ["gone-u9", "shed-u4"]
    assert load_segments(session, conv) == segment_conversation(conv)


def test_revalidation_lists_work_to_redo(
    world: tuple[Settings, Session, StoredConversation],
) -> None:
    _, session, conv = world
    before = load_segments(session, conv)
    session.add(
        ExtractionRunRow(
            stage_key="stg_" + "b" * 64,
            extractor="decisions",
            segment_id=before[1].segment_id,
            state="done",
            versions_json="{}",
        )
    )
    record_override(session, conv, "bread-u1", Action.MERGE, reviewer="r")
    after = load_segments(session, conv)
    redo = revalidation(session, before, after)
    assert set(redo.retired) == {before[0].segment_id, before[1].segment_id}
    assert redo.added == (after[0].segment_id,)
    assert redo.extraction_runs == ("stg_" + "b" * 64,)
    assert redo.classifications == ()
    assert session.get(ExtractionRunRow, "stg_" + "b" * 64) is not None  # nothing deleted


def test_cli_records_a_merge(
    world: tuple[Settings, Session, StoredConversation],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from knowledge_engine.cli.main import main

    settings, session, conv = world
    session.close()
    monkeypatch.setenv("KE_WORKSPACE_ROOT", str(settings.workspace_root))
    assert main(["--json", "segments", conv.conversation_id, "--merge", "bread-u1"]) != 0
    capsys.readouterr()
    args = ["--json", "segments", conv.conversation_id, "--merge", "bread-u1", "--reviewer", "r"]
    assert main(args) == 0
    data = json.loads(capsys.readouterr().out)["data"]
    assert [s["reason"] for s in data["segments"]] == ["start", "gap"]
    assert len(data["segments"][0]["derived_from"]) == 2
    assert len(data["revalidation"]["retired"]) == 2
    assert data["orphaned_overrides"] == [] and data["automatic_segments"] == 3
    assert main(args) != 0  # no segment starts there any more
