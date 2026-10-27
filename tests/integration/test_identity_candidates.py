"""Slice I4: identity is native-ID-first, and unsafe identity goes to review (IMP-002).

Acceptance (IMP-002): the same conversation across two exports maps to one
logical ID; two conversations with identical titles stay distinct; an ID
collision with different content creates a candidate match, not a merge.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from sqlalchemy import text

from knowledge_engine.importer import import_source
from knowledge_engine.infrastructure.db import create_sqlite_engine, database_path
from knowledge_engine.settings import Settings, load_settings

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "chatgpt"


def _settings(tmp_path: Path) -> Settings:
    return load_settings(workspace_root=tmp_path / "ws")


def _expected(case: str) -> dict[str, object]:
    manifest = json.loads((FIXTURES / case / "manifest.json").read_text(encoding="utf-8"))
    expected: dict[str, object] = manifest["expected"]
    return expected


def _query(settings: Settings, sql: str) -> list[tuple[object, ...]]:
    engine = create_sqlite_engine(database_path(settings))
    try:
        with engine.connect() as conn:
            return [tuple(row) for row in conn.execute(text(sql))]
    finally:
        engine.dispose()


def test_id_collision_becomes_candidates_never_a_merge(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    expected = _expected("id_collision")

    report = import_source(FIXTURES / "id_collision" / "export", "fixture", settings=settings)

    assert report.candidate_matches == expected["candidate_matches"]
    assert sum(report.conversations.values()) == expected["conversations_in_file"]
    # merged: 0. One logical conversation for the shared ID, holding only the
    # first chat's messages; the second chat was not folded into it.
    first = json.loads(
        (FIXTURES / "id_collision" / "export" / "conversations.json").read_text(encoding="utf-8")
    )[0]
    first_messages = sum(1 for node in first["mapping"].values() if node.get("message"))
    assert _query(settings, "SELECT count(*) FROM conversations") == [(1,)]
    assert _query(settings, "SELECT count(*) FROM message_revisions") == [(first_messages,)]
    rows = _query(
        settings,
        "SELECT reason, status, native_conversation_id IS NULL, "
        "existing_conversation_id IS NULL FROM identity_candidates ORDER BY reason",
    )
    assert rows == [
        ("id_collision", "review_required", 0, 0),
        ("missing_native_id", "review_required", 1, 1),
    ]


def test_reimporting_candidates_adds_nothing(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    root = FIXTURES / "id_collision" / "export"
    import_source(root, "fixture", settings=settings)

    second = import_source(root, "fixture", settings=settings)

    assert second.candidate_matches == {"id_collision": 1, "missing_native_id": 1}
    assert second.changed_revisions == ()
    assert _query(settings, "SELECT count(*) FROM identity_candidates") == [(2,)]


def test_same_title_conversations_stay_distinct(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    expected = _expected("same_title_different_chat")

    report = import_source(
        FIXTURES / "same_title_different_chat" / "export", "fixture", settings=settings
    )

    assert report.conversations == {"new": expected["conversations"]}
    assert report.candidate_matches == {}
    assert _query(settings, "SELECT count(*) FROM conversations") == [(2,)]


def test_same_conversation_in_two_exports_is_one_logical_id(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    import_source(FIXTURES / "export_single" / "export", "fixture", settings=settings)

    second = import_source(FIXTURES / "export_sharded" / "export", "fixture", settings=settings)

    assert second.conversations == {"unchanged": 3}
    assert _query(settings, "SELECT count(*) FROM conversations") == [(3,)]


def test_exact_duplicate_in_one_export_is_not_a_candidate(tmp_path: Path) -> None:
    source = tmp_path / "dup"
    shutil.copytree(FIXTURES / "export_single" / "export", source)
    conversations = json.loads((source / "conversations.json").read_text(encoding="utf-8"))
    conversations.append(conversations[0])
    (source / "conversations.json").write_text(json.dumps(conversations), encoding="utf-8")

    report = import_source(source, "fixture", settings=_settings(tmp_path))

    assert report.conversations == {"new": 3}
    assert report.warnings["duplicate_conversation_in_source"] == 1
    assert report.candidate_matches == {}
