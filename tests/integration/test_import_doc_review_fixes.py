"""ING-013 and ING-014: fixes from the clean review of ING-012.

Each test is one probe from that review: a form feed no longer shifts a
note's line numbers, ``[url](url)`` gives two exact links, and the video
list follows a note's current version (and counts its links).
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from knowledge_engine.cli.main import main
from knowledge_engine.infrastructure.db import database_path
from knowledge_engine.ingestion.documents import parse_text
from knowledge_engine.links.extract import find_in_text
from knowledge_engine.settings import load_settings
from knowledge_engine.ui.app import _read
from knowledge_engine.ui.registries import list_videos

VIDEO = "dQw4w9WgXcQ"


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("KE_WORKSPACE_ROOT", str(tmp_path / "ws"))
    folder = tmp_path / "notes"
    folder.mkdir()
    return folder


def _ke(capsys: pytest.CaptureFixture[str], *argv: str) -> dict[str, Any]:
    main(["--json", *argv])
    out: dict[str, Any] = json.loads(capsys.readouterr().out)
    return out


@pytest.mark.parametrize("odd", ["\x0c", " ", "\x85"])
def test_a_character_inside_a_line_does_not_shift_the_line_numbers(
    capsys: pytest.CaptureFixture[str], workspace: Path, odd: str
) -> None:
    note = workspace / "synthetic.md"
    note.write_bytes(f"page one{odd}page two\n\nzanthoxylum\n".encode())
    _ke(capsys, "import-doc", str(note))
    [hit] = _ke(capsys, "search", "zanthoxylum")["data"]["document_hits"]
    assert hit["locator"] == "L3"  # what an editor shows


def test_crlf_and_lone_cr_line_numbers_are_unchanged() -> None:
    parsed = parse_text(b"a\r\nb\rc\n\nzanthoxylum")
    assert parsed.blocks[-1].locator == "L5"


def test_a_markdown_link_whose_label_is_the_url_gives_two_exact_links() -> None:
    text = "See [https://example.org/same](https://example.org/same) now."
    found = find_in_text(text, markdown_links=True)
    assert [f.original for f in found] == ["https://example.org/same"] * 2
    assert all(text[f.span.start : f.span.end] == f.original for f in found)


def test_chat_link_finding_is_unchanged_without_the_option() -> None:
    # Chats keep the old reading until they get their own repair plan:
    # changing it would add new rows when an old chat is re-imported.
    text = "See [https://example.org/same](https://example.org/same) now."
    assert [f.original for f in find_in_text(text)] == [
        "https://example.org/same](https://example.org/same)"
    ]


def test_an_imported_note_stores_both_links(
    capsys: pytest.CaptureFixture[str], workspace: Path
) -> None:
    note = workspace / "synthetic.md"
    text = "# Links\n\n[https://example.org/same](https://example.org/same)\n"
    note.write_bytes(text.encode())
    _ke(capsys, "import-doc", str(note))
    db = sqlite3.connect(database_path(load_settings()))
    try:
        rows = db.execute("SELECT original_text, start, end FROM document_links").fetchall()
    finally:
        db.close()
    assert sorted(rows) == sorted(
        ("https://example.org/same", s, s + 24) for s in (text.index("[") + 1, text.index("(") + 1)
    )


def _videos() -> list[dict[str, Any]]:
    videos: list[dict[str, Any]] = _read(load_settings(), list_videos)
    return videos


def test_the_video_list_counts_current_note_links_and_drops_removed_ones(
    capsys: pytest.CaptureFixture[str], workspace: Path
) -> None:
    note = workspace / "synthetic.md"
    note.write_bytes(f"Twice: https://youtu.be/{VIDEO} and https://youtu.be/{VIDEO}\n".encode())
    _ke(capsys, "import-doc", str(note))
    assert _videos() == [
        {
            "video_id": VIDEO,
            "transcript_status": "not_requested",
            "mentions": 2,
            "conversations": 0,
        }
    ]

    note.write_bytes(b"The link was taken out of this note.\n")
    _ke(capsys, "import-doc", str(note))
    assert _videos() == []  # the video page shows no note either
    db = sqlite3.connect(database_path(load_settings()))
    try:
        kept = db.execute("SELECT count(*) FROM document_links WHERE video_id = ?", (VIDEO,))
        assert kept.fetchone()[0] == 2  # the old version's links stay as history
    finally:
        db.close()


def test_two_bracketed_targets_in_a_row_give_two_links() -> None:
    # From the clean review of this fix.
    text = "[label](https://a.org)(https://b.org)"
    found = find_in_text(text, markdown_links=True)
    assert [f.original for f in found] == ["https://a.org", "https://b.org"]
    assert all(text[f.span.start : f.span.end] == f.original for f in found)
