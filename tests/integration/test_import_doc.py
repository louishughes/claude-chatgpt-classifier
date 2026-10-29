"""ING-012: a Markdown or text note is stored, searchable and its links are found.

Acceptance: importing a synthetic note twice adds zero records the second
time; a word in it is found with its line locator; its YouTube URL shows up
as an occurrence on the video's page. The source file is never modified.
"""

from __future__ import annotations

import hashlib
import io
import json
import sqlite3
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from knowledge_engine.api.app import PREFIX, create_app
from knowledge_engine.cli.main import ExitCode, main
from knowledge_engine.infrastructure.db import database_path
from knowledge_engine.settings import Settings, load_settings
from knowledge_engine.ui.app import make_app

VIDEO = "dQw4w9WgXcQ"
# Synthetic note: a heading, a paragraph with a rare word, a YouTube link.
NOTE = (
    "# Synthetic research note\n"
    "\n"
    "The zanthoxylum idea came up twice.\n"
    "\n"
    f"See https://www.youtube.com/watch?v={VIDEO}&t=90s and https://example.org/page\n"
)
TABLES = ("source_documents", "document_revisions", "document_blocks", "document_links")


@pytest.fixture
def note(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("KE_WORKSPACE_ROOT", str(tmp_path / "ws"))
    path = tmp_path / "notes" / "synthetic.md"
    path.parent.mkdir()
    path.write_bytes(NOTE.encode("utf-8"))
    return path


def _ke(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, dict[str, Any]]:
    code = main(["--json", *argv])
    out: dict[str, Any] = json.loads(capsys.readouterr().out)
    return code, out


def _page(settings: Settings, path: str) -> tuple[str, str]:
    captured: dict[str, Any] = {}

    def start_response(status: str, headers: list[tuple[str, str]]) -> None:
        captured["status"] = status

    environ: dict[str, Any] = {
        "REQUEST_METHOD": "GET",
        "PATH_INFO": path,
        "QUERY_STRING": "",
        "HTTP_HOST": "127.0.0.1:8765",
        "CONTENT_LENGTH": "0",
        "wsgi.input": io.BytesIO(b""),
    }
    body: Iterable[bytes] = make_app(settings)(environ, start_response)
    return captured["status"], b"".join(body).decode("utf-8")


def _counts() -> dict[str, int]:
    db = sqlite3.connect(database_path(load_settings()))
    try:
        tables = (*TABLES, "link_targets", "youtube_videos", "source_snapshots")
        return {t: db.execute(f'SELECT count(*) FROM "{t}"').fetchone()[0] for t in tables}
    finally:
        db.close()


def test_import_twice_adds_nothing_the_second_time(
    capsys: pytest.CaptureFixture[str], note: Path
) -> None:
    before = hashlib.sha256(note.read_bytes()).hexdigest()
    mtime = note.stat().st_mtime_ns

    code, first = _ke(capsys, "import-doc", str(note))
    assert code == ExitCode.OK
    assert first["data"]["outcome"] == "new"
    assert first["data"]["counts"]["links"] == 2
    assert first["data"]["counts"]["youtube_mentions"] == 1
    after_first = _counts()

    code, second = _ke(capsys, "import-doc", str(note))

    assert code == ExitCode.OK
    assert second["data"]["outcome"] == "unchanged"
    assert second["data"]["document_id"] == first["data"]["document_id"]
    assert second["data"]["counts"] == {
        "blocks": 0,
        "links": 0,
        "youtube_mentions": 0,
        "new_targets": 0,
    }
    assert _counts() == after_first
    # The source file was only read.
    assert hashlib.sha256(note.read_bytes()).hexdigest() == before
    assert note.stat().st_mtime_ns == mtime


def test_changed_bytes_add_a_revision_and_search_sees_only_the_new_text(
    capsys: pytest.CaptureFixture[str], note: Path
) -> None:
    _, first = _ke(capsys, "import-doc", str(note))
    note.write_bytes((NOTE + "\nA later quokkabird line.\n").encode("utf-8"))

    _, second = _ke(capsys, "import-doc", str(note))

    assert second["data"]["outcome"] == "revised"
    assert second["data"]["revision_id"] != first["data"]["revision_id"]
    assert _counts()["document_revisions"] == 2
    _, out = _ke(capsys, "search", "quokkabird")
    assert [h["locator"] for h in out["data"]["document_hits"]] == ["L7"]
    # The unchanged paragraph is in both revisions but found once.
    _, out = _ke(capsys, "search", "zanthoxylum")
    assert len(out["data"]["document_hits"]) == 1


def test_a_word_is_found_with_its_locator(capsys: pytest.CaptureFixture[str], note: Path) -> None:
    _, imported = _ke(capsys, "import-doc", str(note))

    code, out = _ke(capsys, "search", "zanthoxylum")

    assert code == ExitCode.OK
    data = out["data"]
    assert data["hits"] == []  # chat hits are unchanged: there are no chats
    [hit] = data["document_hits"]
    assert hit["locator"] == "L3"
    assert hit["name"] == "synthetic.md"
    assert hit["document_id"] == imported["data"]["document_id"]
    assert "[zanthoxylum]" in hit["snippet"]


def test_api_search_returns_document_hits(note: Path) -> None:
    assert main(["--json", "import-doc", str(note)]) == ExitCode.OK
    client = TestClient(create_app(load_settings()), base_url="http://127.0.0.1:8766")
    response = client.get(f"{PREFIX}/search", params={"q": "zanthoxylum"})
    assert response.status_code == 200
    body = response.json()
    assert [h["locator"] for h in body["document_hits"]] == ["L3"]


def test_youtube_url_shows_on_the_video_page(
    capsys: pytest.CaptureFixture[str], note: Path
) -> None:
    _ke(capsys, "import-doc", str(note))
    db = sqlite3.connect(database_path(load_settings()))
    try:
        rows = db.execute(
            "SELECT l.original_text, l.t_seconds, l.start, l.end, t.kind "
            "FROM document_links l JOIN link_targets t ON t.target_id = l.target_id "
            "WHERE l.video_id = ?",
            (VIDEO,),
        ).fetchall()
    finally:
        db.close()
    [(written, t_seconds, start, end, kind)] = rows
    assert written == f"https://www.youtube.com/watch?v={VIDEO}&t=90s"
    assert NOTE[start:end] == written  # the span points at the exact characters
    assert (t_seconds, kind) == (90, "youtube_video")

    settings = load_settings()
    status, page = _page(settings, f"/videos/{VIDEO}")
    assert status == "200 OK"
    assert "In your notes" in page and "synthetic.md" in page and "L5" in page
    _, listing = _page(settings, "/videos")
    assert f'href="/videos/{VIDEO}"' in listing


def test_unsupported_and_missing_files_exit_2(
    capsys: pytest.CaptureFixture[str], note: Path
) -> None:
    other = note.with_suffix(".pdf")
    other.write_bytes(b"%PDF-1.4")
    code, out = _ke(capsys, "import-doc", str(other))
    assert code == ExitCode.USAGE and out["error"] == {"code": "unsupported"}
    code, out = _ke(capsys, "import-doc", str(note.with_name("missing.md")))
    assert code == ExitCode.USAGE and out["error"] == {"code": "not_found"}
