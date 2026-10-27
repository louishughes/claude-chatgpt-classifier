"""IMP-003 (slice I3): exact deltas between exports, not_seen, raw observations."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sqlalchemy import text

from knowledge_engine.importer import ImportReport, import_source
from knowledge_engine.infrastructure.db import create_sqlite_engine, database_path
from knowledge_engine.settings import Settings, load_settings

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "chatgpt"


def _expected(case: str) -> dict[str, Any]:
    expected: dict[str, Any] = json.loads((FIXTURES / case / "manifest.json").read_text("utf-8"))[
        "expected"
    ]
    return expected


def _import(settings: Settings, case: str, *, full_export: bool = True) -> ImportReport:
    return import_source(
        FIXTURES / case / "export", "fixture", settings=settings, full_export=full_export
    )


def _query(settings: Settings, sql: str) -> list[tuple[Any, ...]]:
    engine = create_sqlite_engine(database_path(settings))
    try:
        with engine.connect() as conn:
            return [tuple(row) for row in conn.execute(text(sql))]
    finally:
        engine.dispose()


def test_v1_to_v2_reports_the_exact_answer_key(tmp_path: Path) -> None:
    settings = load_settings(workspace_root=tmp_path / "ws")
    _import(settings, "reexport_v1")

    report = _import(settings, "reexport_v2")
    expected = _expected("reexport_v2")

    assert report.conversations == expected["conversation_delta"]
    assert report.messages == expected["message_delta"]
    assert report.new_branches == expected["new_branches"]
    assert report.model_calls_triggered == expected["model_calls_triggered"]
    # Only new and revised content is handed on: 5 new + 1 revised.
    assert len(report.changed_revisions) == 6


def test_absent_conversation_is_kept_as_not_seen(tmp_path: Path) -> None:
    settings = load_settings(workspace_root=tmp_path / "ws")
    _import(settings, "reexport_v1")
    _import(settings, "reexport_v2")

    rows = dict(_query(settings, "SELECT native_conversation_id, presence FROM conversations"))
    by_id = _expected("reexport_v2")["conversation_delta_by_id"]
    for native_id, category in by_id.items():
        assert rows[native_id] == ("not_seen" if category == "not_seen" else "present")
    absent = next(k for k, v in by_id.items() if v == "not_seen")
    revisions = _query(
        settings,
        "SELECT count(*) FROM message_revisions r JOIN message_nodes n USING (node_key) "
        f"JOIN conversations c USING (conversation_id) WHERE c.native_conversation_id = '{absent}'",
    )
    assert revisions == [(3,)]  # nothing deleted


def test_seen_again_comes_back_present(tmp_path: Path) -> None:
    settings = load_settings(workspace_root=tmp_path / "ws")
    _import(settings, "reexport_v1")
    _import(settings, "reexport_v2")
    back = _import(settings, "reexport_v1")

    presences = {row[0] for row in _query(settings, "SELECT presence FROM conversations")}
    # E isn't in v1, so now it's the one not seen; D is present again.
    assert back.conversations.get("not_seen") == 1
    assert presences == {"present", "not_seen"}


def test_revised_message_keeps_its_old_revision(tmp_path: Path) -> None:
    settings = load_settings(workspace_root=tmp_path / "ws")
    _import(settings, "reexport_v1")
    _import(settings, "reexport_v2")

    per_node = _query(
        settings,
        "SELECT node_key, count(*) FROM message_revisions GROUP BY node_key HAVING count(*) > 1",
    )
    assert len(per_node) == 1 and per_node[0][1] == 2


def test_metadata_drift_adds_observations_not_revisions(tmp_path: Path) -> None:
    settings = load_settings(workspace_root=tmp_path / "ws")
    _import(settings, "reexport_v1")

    # The drift fixture holds one conversation, not a whole history.
    report = _import(settings, "metadata_drift", full_export=False)
    expected = _expected("metadata_drift")

    assert report.messages == expected["message_delta"]
    assert report.conversations["unchanged"] == 1
    assert report.changed_revisions == ()
    assert report.model_calls_triggered == expected["model_calls_triggered"]
    assert (report.raw_observations > 0) is expected["new_raw_observations"]
    assert report.raw_observations == 3


def test_branch_points_count_once(tmp_path: Path) -> None:
    settings = load_settings(workspace_root=tmp_path / "ws")
    first = _import(settings, "branches_regen")
    second = _import(settings, "branches_regen")

    assert first.new_branches == 1
    assert second.new_branches == 0


def test_a_full_import_of_a_subset_marks_the_rest_not_seen(tmp_path: Path) -> None:
    settings = load_settings(workspace_root=tmp_path / "ws")
    _import(settings, "reexport_v1")
    full = _import(settings, "metadata_drift")
    assert full.conversations.get("not_seen") == 3
