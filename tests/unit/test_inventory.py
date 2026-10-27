"""SRC-001: read-only raw inventory over the synthetic fixtures."""

from __future__ import annotations

import hashlib
import json
import shutil
import zipfile
from pathlib import Path

import pytest

from knowledge_engine.cli.main import main
from knowledge_engine.ingestion.inventory import (
    FileKind,
    RawTreeChangedError,
    SourceFormat,
    inventory,
    tree_signature,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "chatgpt"
LIMIT = 10 * 1024 * 1024


def _content_hash(root: Path) -> str:
    """Hash every path and every byte under a root (stronger than the signature)."""
    digest = hashlib.sha256()
    paths = [root] if root.is_file() else sorted(root.rglob("*"))
    for path in paths:
        digest.update(path.as_posix().encode())
        if path.is_file():
            digest.update(path.read_bytes())
    return digest.hexdigest()


@pytest.fixture
def split_root(tmp_path: Path) -> Path:
    return Path(shutil.copytree(FIXTURES / "split_wrapper" / "export", tmp_path / "raw"))


@pytest.mark.parametrize("case", sorted(p.name for p in FIXTURES.iterdir() if p.is_dir()))
def test_fixture_tree_is_byte_identical_after_inventory(case: str) -> None:
    root = FIXTURES / case / "export"
    zips = list(root.glob("*.zip"))
    target = zips[0] if zips else root
    before = _content_hash(target)

    report = inventory(target, max_bytes=LIMIT)

    assert report.unchanged
    assert _content_hash(target) == before


def test_split_layout_is_detected_and_derived_file_is_not_a_conversation(
    split_root: Path,
) -> None:
    report = inventory(split_root, max_bytes=LIMIT)

    kinds = {e.path: e.kind for e in report.entries}
    assert report.detected_format is SourceFormat.CHATGPT_SPLIT_V1
    assert kinds["conversations/classification_output.json"] is FileKind.DERIVED_JSON
    assert sum(k is FileKind.SPLIT_CONVERSATION for k in kinds.values()) == 3
    assert sum(e.conversations for e in report.entries) == 3
    media = [e for e in report.entries if e.kind is FileKind.MEDIA]
    assert [e.mime for e in media] == ["image/png"]


def test_official_single_and_sharded_layouts(tmp_path: Path) -> None:
    single = inventory(FIXTURES / "export_single" / "export", max_bytes=LIMIT)
    sharded = inventory(FIXTURES / "export_sharded" / "export", max_bytes=LIMIT)

    assert single.detected_format is SourceFormat.CHATGPT_EXPORT
    assert sharded.detected_format is SourceFormat.CHATGPT_EXPORT
    assert single.to_dict()["conversations"] == 3
    assert sharded.to_dict()["conversations"] == 3


def test_zip_root_is_read_without_extracting(tmp_path: Path) -> None:
    archive = next((FIXTURES / "export_zip" / "export").glob("*.zip"))

    report = inventory(archive, max_bytes=LIMIT)

    assert report.root_type == "zip"
    assert report.detected_format is SourceFormat.CHATGPT_EXPORT
    assert {e.path for e in report.entries} >= {"conversations.json"}
    assert not list(tmp_path.iterdir())


def test_report_redacts_names_by_default(split_root: Path) -> None:
    report = inventory(split_root, max_bytes=LIMIT)

    text = json.dumps(report.to_dict())
    for entry in report.entries:
        stem = Path(entry.path).stem
        assert stem not in text
    assert all(row["file"].startswith("f_") for row in report.to_dict()["entries"])


def test_show_names_reveals_paths(split_root: Path) -> None:
    rows = inventory(split_root, max_bytes=LIMIT).to_dict(show_names=True)["entries"]

    assert "conversations/classification_output.json" in {row["file"] for row in rows}


def test_tokens_are_stable(split_root: Path) -> None:
    first = inventory(split_root, max_bytes=LIMIT).to_dict()["entries"]
    second = inventory(split_root, max_bytes=LIMIT).to_dict()["entries"]

    assert first == second


def test_malformed_unknown_and_account_files(tmp_path: Path) -> None:
    root = tmp_path / "raw"
    root.mkdir()
    (root / "broken.json").write_bytes(b"{not json")
    (root / "notes.txt").write_bytes(b"hello")
    (root / "user.json").write_bytes(b'{"id": "x"}')
    (root / "chat.html").write_bytes(b"<html></html>")
    (root / "list.json").write_bytes(b"[1, 2]")
    (root / "empty.json").write_bytes(b"")

    kinds = {e.path: e.kind for e in inventory(root, max_bytes=LIMIT).entries}

    assert kinds == {
        "broken.json": FileKind.INVALID_JSON,
        "notes.txt": FileKind.OTHER,
        "user.json": FileKind.ACCOUNT_METADATA,
        "chat.html": FileKind.HTML_EXPORT,
        "list.json": FileKind.DERIVED_JSON,
        "empty.json": FileKind.INVALID_JSON,
    }


def test_export_manifest_is_recognised_by_key_names(tmp_path: Path) -> None:
    root = tmp_path / "raw"
    root.mkdir()
    (root / "index.json").write_text(json.dumps({"manifest_file": "x", "export_files": []}))
    (root / "titles.json").write_text(json.dumps({"conversations": [{"title": "t"}]}))

    kinds = {e.path: e.kind for e in inventory(root, max_bytes=LIMIT).entries}

    assert kinds == {"index.json": FileKind.EXPORT_MANIFEST, "titles.json": FileKind.DERIVED_JSON}


def test_report_includes_the_tree_hash(split_root: Path) -> None:
    report = inventory(split_root, max_bytes=LIMIT)

    assert report.to_dict()["tree_hash"] == tree_signature(split_root)


def test_media_detected_by_content_not_extension(tmp_path: Path) -> None:
    root = tmp_path / "raw"
    root.mkdir()
    (root / "photo.txt").write_bytes(b"\xff\xd8\xff\xe0 jpeg body")

    (entry,) = inventory(root, max_bytes=LIMIT).entries

    assert (entry.kind, entry.mime) == (FileKind.MEDIA, "image/jpeg")


def test_oversized_files_are_listed_not_read(tmp_path: Path) -> None:
    root = tmp_path / "raw"
    root.mkdir()
    (root / "big.json").write_bytes(b"[" + b" " * 100 + b"]")

    (entry,) = inventory(root, max_bytes=10).entries

    assert (entry.kind, entry.sha256, entry.size) == (FileKind.OVERSIZED, None, 102)


def test_zip_member_lying_about_its_size_is_capped(tmp_path: Path) -> None:
    archive = tmp_path / "export.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("conversations.json", b"[" + b" " * 5000 + b"]")

    (entry,) = inventory(archive, max_bytes=100).entries

    assert entry.kind is FileKind.OVERSIZED


def test_duplicates_are_counted(tmp_path: Path) -> None:
    root = tmp_path / "raw"
    root.mkdir()
    for name in ("a.png", "b.png", "c.png"):
        (root / name).write_bytes(b"\x89PNG\r\n\x1a\nsame")

    assert inventory(root, max_bytes=LIMIT).to_dict()["duplicate_files"] == 2


def test_tree_signature_sees_new_files_but_not_reads(split_root: Path) -> None:
    before = tree_signature(split_root)
    for path in split_root.rglob("*.json"):
        path.read_bytes()
    assert tree_signature(split_root) == before

    (split_root / "new-file.txt").write_bytes(b"x")
    assert tree_signature(split_root) != before


def test_strict_mode_raises_when_tree_changes(
    split_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import knowledge_engine.ingestion.inventory as module

    real_entry = module._entry
    calls: list[int] = []

    def entry_and_tamper(*args: object) -> module.InventoryEntry:
        # Write a new file during each run, so both runs see a change.
        calls.append(1)
        (split_root / f"late-{len(calls)}.txt").write_bytes(b"late")
        return real_entry(*args)  # type: ignore[arg-type]

    monkeypatch.setattr(module, "_entry", entry_and_tamper)

    assert not module.inventory(split_root, max_bytes=LIMIT).unchanged
    with pytest.raises(RawTreeChangedError):
        module.inventory(split_root, max_bytes=LIMIT, strict=True)


def test_missing_root(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        inventory(tmp_path / "nope", max_bytes=LIMIT)


def test_cli_inventory_json_is_redacted(
    split_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(["--json", "raw", "inventory", str(split_root)])

    out = capsys.readouterr().out
    payload = json.loads(out)
    assert code == 0
    assert payload["data"]["detected_format"] == "chatgpt-split-v1"
    assert "synthetic-plain-chat" not in out
    assert str(split_root) not in out


def test_cli_inventory_text_summary(split_root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["raw", "inventory", str(split_root)])

    out = capsys.readouterr().out
    assert code == 0
    assert "detected_format: chatgpt-split-v1" in out
    assert "f_" not in out  # per-file rows are JSON-only


def test_cli_inventory_missing_root(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--json", "raw", "inventory", str(tmp_path / "nope")]) == 2
    assert json.loads(capsys.readouterr().out)["error"] == {"code": "not_found"}
