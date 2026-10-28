"""OPS-004: purging chats removes everything made from them, and proves it."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from knowledge_engine.evaluation.end_to_end import (
    E2E_FIXTURE,
    E2E_QUERY,
    check_vault,
    run_end_to_end,
)
from knowledge_engine.importer import import_source
from knowledge_engine.retention.purge import PurgeError, plan_purge, purge_log, run_purge
from knowledge_engine.settings import Settings

ROOT = Path(__file__).resolve().parents[2]
TAXONOMY = "e2e-tax-1"


@pytest.fixture
def workspace(tmp_path: Path) -> tuple[Settings, Path, dict[str, str]]:
    """The EVAL-006 synthetic workspace: imported, labelled, extracted, vault written."""
    run_end_to_end(ROOT / E2E_FIXTURE, tmp_path, query=E2E_QUERY)
    settings = Settings(workspace_root=tmp_path / "ws")
    with sqlite3.connect(tmp_path / "ws" / "knowledge.db") as db:
        titles = dict(db.execute("SELECT title, conversation_id FROM conversations"))
    return settings, tmp_path / "vault", titles


def _db(settings: Settings) -> sqlite3.Connection:
    return sqlite3.connect(settings.workspace_root / "knowledge.db")


def _counts(settings: Settings) -> dict[str, int]:
    with _db(settings) as db:
        tables = [
            t
            for (t,) in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        ]
        return {t: db.execute(f'SELECT count(*) FROM "{t}"').fetchone()[0] for t in tables}


def _purge(settings: Settings, vault: Path, *conversations: str):  # type: ignore[no-untyped-def]
    plan = plan_purge(settings, conversations)
    return run_purge(
        settings,
        conversations,
        confirm=plan.token,
        reason="synthetic test",
        vault=vault,
        taxonomy_version=TAXONOMY,
    )


def test_nothing_is_deleted_without_the_plans_token(workspace) -> None:  # type: ignore[no-untyped-def]
    settings, vault, titles = workspace
    target = titles["Synthetic garden shed plan"]
    before = _counts(settings)
    plan = plan_purge(settings, [target])
    assert plan.counts()["rows_total"] > 0 and len(plan.token) == 12
    for kwargs in (
        {"confirm": "000000000000", "reason": "test"},
        {"confirm": plan.token, "reason": "  "},
        {"confirm": plan.token, "reason": "test", "taxonomy_version": "nope"},
    ):
        with pytest.raises(PurgeError):
            run_purge(settings, [target], **kwargs)  # type: ignore[arg-type]
    with pytest.raises(PurgeError):
        plan_purge(settings, ["conv_does_not_exist"])
    assert _counts(settings) == before


def test_purge_removes_the_closure_and_proves_it(workspace) -> None:  # type: ignore[no-untyped-def]
    settings, vault, titles = workspace
    from sqlalchemy.orm import Session

    from knowledge_engine.infrastructure.db import create_sqlite_engine, database_path
    from knowledge_engine.rendering.transcript import load_conversation
    from knowledge_engine.segmentation.overrides import Action, record_override
    from knowledge_engine.segmentation.segmenter import exchange_starts, section_messages

    plain = titles["Synthetic plain chat"]
    plan_chat = titles["Synthetic garden shed plan"]
    engine = create_sqlite_engine(database_path(settings))
    with Session(engine) as session:  # a reviewer's correction: an append-only row
        conversation = load_conversation(session, plan_chat)
        [(_, messages)] = section_messages(conversation)
        split_at = exchange_starts(messages, None)[-1]  # the second exchange
        record_override(session, conversation, split_at, Action.SPLIT, reviewer="owner")
        session.commit()
    engine.dispose()

    result = _purge(settings, vault, plain, plan_chat)

    check = result.verification
    assert check.ok, check.to_dict()
    assert check.probes > 0 and check.search_hits == 0 and check.database_bytes_hits == 0
    counts = result.plan.counts()
    assert counts["conversations"] == 2
    assert counts["rows"]["segment_overrides"] == 1
    assert counts["kept_shared"]["videos_mentioned_elsewhere"] == 1  # the follow-up still links it
    assert counts["other_conversations_in_purged_files"] == 3
    with _db(settings) as db:
        assert db.execute("SELECT count(*) FROM conversations").fetchone()[0] == 3
        assert db.execute("SELECT count(*) FROM youtube_videos").fetchone()[0] == 1
        assert db.execute("SELECT count(*) FROM social_accounts").fetchone()[0] == 0
        triggers = {n for (n,) in db.execute("SELECT name FROM sqlite_master WHERE type='trigger'")}
        assert {"segment_overrides_no_delete", "decision_events_no_delete"} <= triggers
        with pytest.raises(sqlite3.DatabaseError):
            db.execute("DELETE FROM purge_events")
    [event] = purge_log(settings)
    assert event["status"] == "verified" and event["counts"]["conversations"] == 2
    assert result.vault["removed"] > 0
    links = check_vault(vault)
    assert not links.broken_links and not links.broken_embeds


def test_an_image_stays_while_another_chat_shows_it(workspace) -> None:  # type: ignore[no-untyped-def]
    settings, vault, titles = workspace
    with _db(settings) as db:
        [(blob,)] = db.execute("SELECT blob_sha256 FROM media_blobs").fetchall()
    stored = settings.workspace_root / "archive" / blob[:2] / blob

    first = _purge(settings, vault, titles["Synthetic image chat"])
    assert first.verification.ok, first.verification.to_dict()
    assert first.plan.counts()["kept_shared"]["images_still_shown_elsewhere"] == 1
    assert stored.is_file()

    second = _purge(settings, vault, titles["Synthetic garden shed follow-up"])
    assert second.verification.ok, second.verification.to_dict()
    assert not stored.exists()
    assert second.verification.vault_images_left == 0
    with _db(settings) as db:
        assert db.execute("SELECT count(*) FROM media_blobs").fetchone()[0] == 0


def test_reimporting_the_same_export_does_not_bring_it_back(workspace) -> None:  # type: ignore[no-untyped-def]
    settings, vault, titles = workspace
    result = _purge(settings, vault, titles["Synthetic garden shed plan"])
    assert result.verification.ok
    archived = list((settings.workspace_root / "archive").rglob("*"))

    report = import_source(ROOT / E2E_FIXTURE, "e2e", settings=settings)

    assert report.conversations.get("purged") == 1
    assert report.integrity["reconciled"]
    assert list((settings.workspace_root / "archive").rglob("*")) == archived
    with _db(settings) as db:
        assert db.execute("SELECT count(*) FROM conversations").fetchone()[0] == 4
