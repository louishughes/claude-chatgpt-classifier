"""UI-010: one image or file, and every message that uses it (page and CLI)."""

from __future__ import annotations

import io
import json
import re
import shutil
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from knowledge_engine.cli.main import main
from knowledge_engine.importer import import_source
from knowledge_engine.importer.media import MediaAssetRow
from knowledge_engine.infrastructure.db import create_sqlite_engine, database_path
from knowledge_engine.settings import Settings
from knowledge_engine.ui.app import make_app

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "chatgpt"


def _get(settings: Settings, target: str) -> tuple[str, str]:
    captured: dict[str, Any] = {}

    def start_response(status: str, headers: list[tuple[str, str]]) -> None:
        captured["status"] = status

    environ: dict[str, Any] = {
        "REQUEST_METHOD": "GET",
        "PATH_INFO": target,
        "QUERY_STRING": "",
        "HTTP_HOST": "127.0.0.1:8765",
        "CONTENT_LENGTH": "0",
        "wsgi.input": io.BytesIO(b""),
    }
    body: Iterable[bytes] = make_app(settings)(environ, start_response)
    return captured["status"], b"".join(body).decode("utf-8")


def _imported(root: Path, case: str) -> tuple[Settings, dict[str | None, str]]:
    """Import a fixture; return settings and native file ID -> asset ID."""
    settings = Settings(workspace_root=root / case)
    import_source(FIXTURES / case / "export", "fixture", settings=settings)
    engine = create_sqlite_engine(database_path(settings))
    with Session(engine) as session:
        assets = dict(
            session.execute(select(MediaAssetRow.native_file_id, MediaAssetRow.asset_id))
            .tuples()
            .all()
        )
    engine.dispose()
    return settings, assets


@pytest.fixture(scope="module")
def repeated(tmp_path_factory: pytest.TempPathFactory) -> tuple[Settings, dict[str | None, str]]:
    return _imported(tmp_path_factory.mktemp("ui10"), "repeated_image")


def test_one_file_in_three_messages_is_one_page_with_three_uses(
    repeated: tuple[Settings, dict[str | None, str]],
) -> None:
    settings, assets = repeated
    status, page = _get(settings, f"/assets/{assets['file-SYN0001']}")
    assert status == "200 OK"
    assert "Used in 3 messages across 2 chats" in page
    uses = re.findall(r'<td><a href="(/chats/[^"#]+)#([^"]+)">', page)
    assert len(uses) == 3 and len({chat for chat, _ in uses}) == 2
    for chat, anchor in uses:  # every row opens the exact message
        chat_status, chat_page = _get(settings, chat)
        assert chat_status == "200 OK" and f'id="{anchor}"' in chat_page
    # The picture itself is shown once, from its one stored blob.
    assert len(re.findall(r'<img src="/media/[0-9a-f]{64}"', page)) == 1


def test_identical_bytes_under_another_file_id_stay_a_separate_asset(
    repeated: tuple[Settings, dict[str | None, str]],
) -> None:
    settings, assets = repeated
    _, page = _get(settings, f"/assets/{assets['file-SYN0003']}")
    assert "Used in 1 message across 1 chat" in page
    assert "the same bytes are also stored as 1 other file" in page


def test_chat_page_links_each_image_to_its_asset_page(
    repeated: tuple[Settings, dict[str | None, str]],
) -> None:
    settings, assets = repeated
    _, page = _get(settings, f"/assets/{assets['file-SYN0001']}")
    chat = re.findall(r'<td><a href="(/chats/[^"#]+)#', page)[0]
    _, chat_page = _get(settings, chat)
    assert f'href="/assets/{assets["file-SYN0001"]}"' in chat_page
    assert "Every message using this file" in chat_page


def test_a_missing_file_still_lists_its_messages(tmp_path: Path) -> None:
    settings, assets = _imported(tmp_path, "asset_problems")
    status, page = _get(settings, f"/assets/{assets['file-SYNMISSING']}")
    assert status == "200 OK"
    assert "isn't in any export imported so far" in page
    assert '<span class="error">missing</span>' in page
    assert "(no file with this ID is in the export)" in page  # the evidence, in words
    assert "<img" not in page  # no bytes, no picture, no invented path
    for chat, anchor in re.findall(r'<td><a href="(/chats/[^"#]+)#([^"]+)">', page):
        chat_status, chat_page = _get(settings, chat)
        assert chat_status == "200 OK" and f'id="{anchor}"' in chat_page


def test_inspect_a_missing_asset_shows_its_state_but_no_paths(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    settings, assets = _imported(tmp_path, "asset_problems")
    monkeypatch.setenv("KE_WORKSPACE_ROOT", str(settings.workspace_root))
    assert main(["--json", "inspect", assets["file-SYNMISSING"]]) == 0
    out = capsys.readouterr().out
    data = json.loads(out)["data"]
    assert data["blob_sha256"] is None
    assert [o["availability"] for o in data["occurrences"]] == ["missing"]
    assert "file-SYNMISSING" not in out and "export" not in out  # no file IDs or paths


def test_an_edited_message_in_a_new_export_is_still_one_use(tmp_path: Path) -> None:
    # Re-exporting the whole history is normal (CLAUDE.md §2C). A message
    # whose text changed gets a new revision; it is still one message.
    export = tmp_path / "export"
    shutil.copytree(FIXTURES / "repeated_image" / "export", export)
    settings = Settings(workspace_root=tmp_path / "ws")
    import_source(export, "fixture", settings=settings)
    chat_file = export / "conversations" / "2024-01-06.synthetic-repeated-image-a.json"
    raw = chat_file.read_text(encoding="utf-8")
    assert "Synthetic: first look." in raw
    chat_file.write_text(
        raw.replace("Synthetic: first look.", "Synthetic: first look, edited."), "utf-8"
    )
    import_source(export, "fixture", settings=settings)
    engine = create_sqlite_engine(database_path(settings))
    with Session(engine) as session:
        asset = session.scalars(
            select(MediaAssetRow.asset_id).where(MediaAssetRow.native_file_id == "file-SYN0001")
        ).one()
    engine.dispose()
    _, page = _get(settings, f"/assets/{asset}")
    assert "Used in 3 messages across 2 chats" in page
    anchors = re.findall(r'<td><a href="/chats/[^"#]+#([^"]+)">', page)
    assert len(anchors) == len(set(anchors)) == 3  # no message listed twice
    assert "earlier version" not in page  # the edit kept the image


def test_unknown_asset_is_a_404(repeated: tuple[Settings, dict[str | None, str]]) -> None:
    settings, _ = repeated
    status, page = _get(settings, "/assets/asset_doesnotexist")
    assert status == "404 Not Found" and "asset_doesnotexist" not in page
    assert _get(settings, "/assets/<script>")[0] == "404 Not Found"


def test_inspect_an_asset_prints_ids_and_places_only(
    repeated: tuple[Settings, dict[str | None, str]],
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings, assets = repeated
    monkeypatch.setenv("KE_WORKSPACE_ROOT", str(settings.workspace_root))
    assert main(["--json", "inspect", assets["file-SYN0001"]]) == 0
    out = capsys.readouterr().out
    data = json.loads(out)["data"]
    assert len(data["occurrences"]) == 3 and data["chats"] == 2
    assert {o["availability"] for o in data["occurrences"]} == {"available"}
    assert all(o["conversation_id"].startswith("conv_") for o in data["occurrences"])
    assert "title" not in out and "Synthetic" not in out  # no chat titles or text
    assert main(["--json", "inspect", "asset_secret-words"]) == 2
    out = capsys.readouterr().out
    assert json.loads(out)["error"]["code"] == "not_found" and "secret-words" not in out
