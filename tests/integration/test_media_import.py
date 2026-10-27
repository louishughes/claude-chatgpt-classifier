"""Slice M1: images stored once, every use recorded (MED-001, MED-003).

Acceptance (MED-001): one blob shared by many occurrences; an occurrence
without bytes is representable as missing; a derived thumbnail never
replaces the original. (MED-003): the same image in two conversations
yields one blob and two occurrences; re-import adds zero blobs or
occurrences; raw files unchanged.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from sqlalchemy import text

from knowledge_engine.importer import import_source
from knowledge_engine.infrastructure.db import create_sqlite_engine, database_path
from knowledge_engine.ingestion.inventory import tree_signature
from knowledge_engine.settings import Settings, load_settings

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "chatgpt"


def _settings(tmp_path: Path, mode: str = "reference") -> Settings:
    return load_settings(workspace_root=tmp_path / "ws", media_storage_mode=mode)


def _expected(case: str) -> dict[str, object]:
    manifest = json.loads((FIXTURES / case / "manifest.json").read_text(encoding="utf-8"))
    expected: dict[str, object] = manifest["expected"]
    return expected


def _root(case: str) -> Path:
    export = FIXTURES / case / "export"
    zips = list(export.glob("*.zip"))
    return zips[0] if zips else export


def _query(settings: Settings, sql: str) -> list[tuple[object, ...]]:
    engine = create_sqlite_engine(database_path(settings))
    try:
        with engine.connect() as conn:
            return [tuple(row) for row in conn.execute(text(sql))]
    finally:
        engine.dispose()


def _count(settings: Settings, table: str) -> int:
    value = _query(settings, f"SELECT count(*) FROM {table}")[0][0]  # noqa: S608 - fixed names
    assert isinstance(value, int)
    return value


def test_repeated_image_matches_the_answer_key(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    expected = _expected("repeated_image")

    report = import_source(_root("repeated_image"), "fixture", settings=settings)

    assert report.asset_occurrences == expected["asset_occurrences"]
    assert _count(settings, "media_assets") == expected["assets"]
    assert _count(settings, "media_blobs") == expected["blobs"]
    per_asset = _query(
        settings,
        "SELECT a.native_file_id, count(*) FROM asset_occurrences o "
        "JOIN media_assets a ON a.asset_id = o.asset_id GROUP BY a.native_file_id",
    )
    assert {row[0]: row[1] for row in per_asset} == expected["occurrences_per_asset"]
    # Header facts only: type and size, read without decoding the picture.
    assert set(_query(settings, "SELECT media_type, width, height FROM media_blobs")) == {
        ("image/png", 4, 4)
    }


def test_same_image_in_two_conversations_is_one_blob(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    import_source(_root("repeated_image"), "fixture", settings=settings)

    rows = _query(
        settings,
        "SELECT count(DISTINCT n.conversation_id), count(DISTINCT a.blob_sha256) "
        "FROM asset_occurrences o "
        "JOIN media_assets a ON a.asset_id = o.asset_id "
        "JOIN message_revisions r ON r.revision_id = o.revision_id "
        "JOIN message_nodes n ON n.node_key = r.node_key "
        "WHERE a.native_file_id = 'file-SYN0001'",
    )
    assert rows == [(2, 1)]


def test_reimport_adds_no_blobs_or_occurrences(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    root = _root("repeated_image")
    raw_before = tree_signature(root)
    import_source(root, "fixture", settings=settings)
    tables = ("media_blobs", "media_assets", "asset_occurrences")
    before = {t: _count(settings, t) for t in tables}

    second = import_source(root, "fixture", settings=settings)

    assert second.media == {"new_assets": 0, "new_blobs": 0, "new_occurrences": 0}
    assert second.asset_occurrences == {"available": 5}
    assert {t: _count(settings, t) for t in tables} == before
    assert tree_signature(root) == raw_before


def test_reexport_reports_new_media(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    import_source(_root("reexport_v1"), "fixture", settings=settings)

    second = import_source(_root("reexport_v2"), "fixture", settings=settings)

    assert second.media["new_assets"] == _expected("reexport_v2")["new_media"]
    assert second.media["new_blobs"] == 1


def test_zip_folder_and_copy_mode_store_the_same_blob(tmp_path: Path) -> None:
    folder = load_settings(workspace_root=tmp_path / "a")
    zipped = load_settings(workspace_root=tmp_path / "b")
    copied = load_settings(workspace_root=tmp_path / "c", media_storage_mode="copy")

    reports = [
        import_source(_root("export_single"), "fixture", settings=folder),
        import_source(_root("export_zip"), "fixture", settings=zipped),
        import_source(_root("export_single"), "fixture", settings=copied),
    ]

    expected = _expected("export_single")
    blobs = [
        _query(s, "SELECT blob_sha256, storage_mode, location IS NULL FROM media_blobs")
        for s in (folder, zipped, copied)
    ]
    sha = blobs[0][0][0]
    # Reference mode remembers where the file is; a ZIP member and copy mode
    # are copied into the workspace store instead.
    assert blobs == [[(sha, "reference", 0)], [(sha, "copy", 1)], [(sha, "copy", 1)]]
    assert all(r.asset_occurrences == expected["asset_occurrences"] for r in reports)
    assert all(_count(s, "media_assets") == expected["assets"] for s in (folder, zipped))
    assert all(_count(s, "derived_media_artifacts") == 0 for s in (folder, zipped, copied))
    assert isinstance(sha, str)
    assert (tmp_path / "c" / "archive" / sha[:2] / sha).is_file()


def test_missing_image_is_recorded_then_found_later(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    without = tmp_path / "without"
    shutil.copytree(_root("export_single"), without)
    for image in without.glob("*.png"):
        image.unlink()

    first = import_source(without, "fixture", settings=settings)
    # The reference is kept and marked missing: no blob, no invented path.
    assert first.asset_occurrences == {"missing": 1}
    assert _query(settings, "SELECT blob_sha256 FROM media_assets") == [(None,)]

    second = import_source(_root("export_single"), "fixture", settings=settings)
    assert second.asset_occurrences == {"available": 1}
    assert second.media == {"new_assets": 0, "new_blobs": 1, "new_occurrences": 0}
    assert _query(settings, "SELECT availability FROM asset_occurrences") == [("available",)]
