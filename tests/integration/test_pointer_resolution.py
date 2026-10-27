"""Slice M2: every pointer resolves to one file, or says why not (MED-002).

Acceptance (MED-002): the fixture covers each pointer scheme, a pointer with
two candidate files (ambiguous) and a manifest-listed but absent file
(missing); no fabricated paths.
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
PROBLEMS = FIXTURES / "asset_problems"
CONVERSATION_ID = "c0000004-0000-4000-8000-000000000001"


def _settings(tmp_path: Path, mode: str = "reference") -> Settings:
    return load_settings(workspace_root=tmp_path / "ws", media_storage_mode=mode)


def _query(settings: Settings, sql: str) -> list[tuple[object, ...]]:
    engine = create_sqlite_engine(database_path(settings))
    try:
        with engine.connect() as conn:
            return [tuple(row) for row in conn.execute(text(sql))]
    finally:
        engine.dispose()


def _occurrences(settings: Settings) -> dict[str, tuple[str, dict[str, object]]]:
    rows = _query(settings, "SELECT pointer, availability, evidence_json FROM asset_occurrences")
    result: dict[str, tuple[str, dict[str, object]]] = {}
    for pointer, state, evidence in rows:
        assert isinstance(pointer, str) and isinstance(state, str) and isinstance(evidence, str)
        result[pointer] = (state, json.loads(evidence))
    return result


def _copy(tmp_path: Path, case: Path) -> Path:
    target = tmp_path / "source"
    shutil.copytree(case / "export", target)
    return target


def test_asset_problems_match_the_answer_key(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    expected = json.loads((PROBLEMS / "manifest.json").read_text(encoding="utf-8"))["expected"]

    report = import_source(PROBLEMS / "export", "fixture", settings=settings)

    assert report.asset_occurrences == expected["asset_occurrences"]
    states = {pointer: state for pointer, (state, _) in _occurrences(settings).items()}
    assert states == expected["occurrence_states_by_pointer"]


def test_problems_carry_evidence_and_no_invented_path(tmp_path: Path) -> None:
    settings = _settings(tmp_path, mode="copy")

    import_source(PROBLEMS / "export", "fixture", settings=settings)

    occurrences = _occurrences(settings)
    assert occurrences["file-service://file-SYNMISSING"][1] == {
        "rule": "no_matching_file",
        "candidates": [],
    }
    assert occurrences["weird-scheme://abc"][1] == {"rule": "unknown_scheme", "candidates": []}
    ambiguous = occurrences["file-service://file-SYN0005"][1]
    assert ambiguous["rule"] == "several_files"
    assert ambiguous["candidates"] == [
        "images/file-SYN0005-a.png",
        "images/file-SYN0005-b.png",
    ]
    # Nothing was available, so nothing was stored, not even the two
    # ambiguous candidates, and no asset points at bytes.
    assert _query(settings, "SELECT count(*) FROM media_blobs") == [(0,)]
    assert _query(settings, "SELECT count(*) FROM media_assets WHERE blob_sha256 IS NOT NULL") == [
        (0,)
    ]
    # An unknown scheme names no file ID, so it has no asset at all.
    assert _query(
        settings,
        "SELECT asset_id IS NULL FROM asset_occurrences WHERE pointer = 'weird-scheme://abc'",
    ) == [(1,)]


def test_manifest_listed_but_absent_file_is_missing_with_that_evidence(tmp_path: Path) -> None:
    source = _copy(tmp_path, PROBLEMS)
    index = {
        "manifest_file": "synthetic-index.json",
        "version": 1,
        "export_files": [{"path": "images/file-SYNMISSING-synthetic.png"}],
        "logical_files": ["images/file-SYN0005-a.png"],
    }
    (source / "conversations" / "synthetic-index.json").write_text(json.dumps(index))
    settings = _settings(tmp_path)

    report = import_source(source, "fixture", settings=settings)

    occurrences = _occurrences(settings)
    assert occurrences["file-service://file-SYNMISSING"] == (
        "missing",
        {"rule": "listed_but_absent", "candidates": []},
    )
    # The audio clip isn't listed anywhere: plainly missing.
    assert occurrences["sediment://file_00000000synthaudio"][1]["rule"] == "no_matching_file"
    assert report.warnings["non_conversation_file_skipped"] == 1


def test_conversation_folder_settles_two_candidates(tmp_path: Path) -> None:
    source = _copy(tmp_path, PROBLEMS)
    own = source / "images" / CONVERSATION_ID
    own.mkdir()
    (source / "images" / "file-SYN0005-b.png").rename(own / "file-SYN0005-b.png")
    settings = _settings(tmp_path)

    import_source(source, "fixture", settings=settings)

    state, evidence = _occurrences(settings)["file-service://file-SYN0005"]
    assert state == "available"
    assert evidence["rule"] == "conversation_folder"
    assert evidence["candidates"] == [
        "images/c0000004-0000-4000-8000-000000000001/file-SYN0005-b.png",
        "images/file-SYN0005-a.png",
    ]


def test_identical_candidates_are_one_file(tmp_path: Path) -> None:
    source = _copy(tmp_path, PROBLEMS)
    shutil.copyfile(
        source / "images" / "file-SYN0005-a.png", source / "images" / "file-SYN0005-b.png"
    )
    settings = _settings(tmp_path)

    import_source(source, "fixture", settings=settings)

    state, evidence = _occurrences(settings)["file-service://file-SYN0005"]
    assert (state, evidence["rule"]) == ("available", "identical_bytes")
    assert _query(settings, "SELECT count(*) FROM media_blobs") == [(1,)]


def test_attachments_are_occurrences_counted_once(tmp_path: Path) -> None:
    source = _copy(tmp_path, FIXTURES / "export_single")
    path = source / "conversations.json"
    conversations = json.loads(path.read_text(encoding="utf-8"))
    for conversation in conversations:
        node = conversation["mapping"].get("c2-u0")
        if node:
            # The image is listed as an attachment too (as real exports do),
            # plus a second, non-image upload that isn't in the export.
            node["message"]["metadata"]["attachments"] = [
                {"id": "file-SYN0001", "name": "synthetic.png"},
                {"id": "file-SYNATTACH", "name": "synthetic.pdf", "size": 10},
            ]
    path.write_text(json.dumps(conversations), encoding="utf-8")
    settings = _settings(tmp_path)

    report = import_source(source, "fixture", settings=settings)

    assert report.asset_occurrences == {"available": 1, "missing": 1}
    rows = _query(
        settings, "SELECT pointer, part_index, content_type, declared_size FROM asset_occurrences"
    )
    assert ("attachment://file-SYNATTACH", 1, "attachment", 10) in rows
    assert len(rows) == 2
