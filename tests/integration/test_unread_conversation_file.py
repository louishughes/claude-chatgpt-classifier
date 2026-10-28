"""IMP-007: a JSON file of chats the official adapter doesn't read is reported."""

from __future__ import annotations

import json
import shutil
import zipfile
from pathlib import Path

import pytest

from knowledge_engine.importer import import_source
from knowledge_engine.ingestion.chatgpt_export import ChatGPTExportAdapter
from knowledge_engine.settings import Settings

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "chatgpt"
CHATS = FIXTURES / "branches_edit" / "export" / "conversations.json"


def _export(tmp_path: Path, extra: dict[str, object]) -> Path:
    export = tmp_path / "export"
    export.mkdir()
    shutil.copy(FIXTURES / "similar_unrelated" / "export" / "conversations.json", export)
    for name, value in extra.items():
        target = export / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(value), encoding="utf-8")
    return export


def _codes(export: Path) -> list[tuple[str, str | None]]:
    listing = ChatGPTExportAdapter().open(export, max_bytes=10_000_000)
    return [(w.code, w.locator) for w in listing.warnings]


def test_a_stray_chat_file_warns_and_is_not_imported(tmp_path: Path) -> None:
    chats = json.loads(CHATS.read_text("utf-8"))
    export = _export(tmp_path, {"stray.json": chats, "old/one-chat.json": chats[0]})
    assert sorted(_codes(export)) == [
        ("unread_conversation_file", "old/one-chat.json"),
        ("unread_conversation_file", "stray.json"),
    ]
    report = import_source(export, "fixture", settings=Settings(workspace_root=tmp_path / "ws"))
    assert report.warnings["unread_conversation_file"] == 2
    assert report.conversations.get("new") == 2  # only conversations.json was read


@pytest.mark.parametrize(
    "extra",
    [
        {"user.json": {"id": "user-synthetic", "mapping": {}}},  # a known side file
        {"message_feedback.json": [{"mapping": {}}]},
        {"notes.json": {"settings": True}},  # JSON, but no chats
        {"broken.json": "not json at all"},
    ],
)
def test_other_files_do_not_warn(tmp_path: Path, extra: dict[str, object]) -> None:
    export = _export(tmp_path, extra)
    if "broken.json" in extra:
        (export / "broken.json").write_text("{not json", encoding="utf-8")
    assert _codes(export) == []


def test_the_zip_layout_warns_too(tmp_path: Path) -> None:
    archive = tmp_path / "export.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.write(
            FIXTURES / "similar_unrelated" / "export" / "conversations.json", "conversations.json"
        )
        zf.writestr("stray.json", CHATS.read_text("utf-8"))
    listing = ChatGPTExportAdapter().open(archive, max_bytes=10_000_000)
    assert [w.code for w in listing.warnings] == ["unread_conversation_file"]
