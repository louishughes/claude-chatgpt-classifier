"""ING-002 + ING-004 (slice A1): the adapter seam and the official export adapter."""

from __future__ import annotations

import json
import shutil
import zipfile
from pathlib import Path
from typing import Any

import pytest

from knowledge_engine.evaluation.synthetic import tiny_png
from knowledge_engine.ingestion.chatgpt_export import ChatGPTExportAdapter
from knowledge_engine.ingestion.source import (
    ImportWarning,
    NativeConversation,
    ProbeResult,
    SourceAdapter,
    SourceListing,
    SourceLocator,
    SourceTooLargeError,
    UnsafeArchiveError,
    UnsupportedFormatError,
    load_json,
    safe_member_name,
    select_adapter,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "chatgpt"
LIMIT = 10 * 1024 * 1024
ADAPTER = ChatGPTExportAdapter()


def _root(case: str) -> Path:
    export = FIXTURES / case / "export"
    zips = list(export.glob("*.zip"))
    return zips[0] if zips else export


def _natives(path: Path) -> list[Any]:
    return [c.native for c in ADAPTER.open(path, max_bytes=LIMIT).conversations()]


# ---------------------------------------------------------------- the seam


class _FakeAdapter:
    """A minimal adapter: proves the protocol is small enough to implement."""

    format_id = "fake-v1"

    def probe(self, path: Path) -> ProbeResult:
        return ProbeResult(path.suffix == ".fake", "suffix check")

    def open(self, path: Path, *, max_bytes: int) -> SourceListing:
        def stream() -> Any:
            yield NativeConversation({"mapping": {}}, SourceLocator(path.name))

        return SourceListing(self.format_id, (), (), reader=stream)


def test_fake_adapter_satisfies_the_contract(tmp_path: Path) -> None:
    adapter: SourceAdapter = _FakeAdapter()
    source = tmp_path / "x.fake"
    source.write_text("")

    chosen = select_adapter(source, [ADAPTER, adapter])
    (conv,) = list(chosen.open(source, max_bytes=LIMIT).conversations())

    assert chosen is adapter
    assert conv.locator == SourceLocator("x.fake")


def test_unsupported_format_is_a_clear_error(tmp_path: Path) -> None:
    (tmp_path / "notes.txt").write_text("hello")
    with pytest.raises(UnsupportedFormatError, match="no adapter"):
        select_adapter(tmp_path, [ADAPTER, _FakeAdapter()])
    with pytest.raises(UnsupportedFormatError, match="unknown format"):
        select_adapter(tmp_path, [ADAPTER], format_id="nope")
    with pytest.raises(UnsupportedFormatError, match="not a chatgpt-export-v1"):
        select_adapter(tmp_path, [ADAPTER], format_id="chatgpt-export-v1")


def test_ambiguous_match_asks_for_a_format(tmp_path: Path) -> None:
    class Greedy(_FakeAdapter):
        format_id = "greedy-v1"

        def probe(self, path: Path) -> ProbeResult:
            return ProbeResult(True, "matches anything")

    source = _root("export_single")
    with pytest.raises(UnsupportedFormatError, match="several formats"):
        select_adapter(source, [ADAPTER, Greedy()])
    assert select_adapter(source, [ADAPTER, Greedy()], format_id=ADAPTER.format_id) is ADAPTER


def test_duplicate_json_keys_are_reported() -> None:
    value, warnings = load_json(b'{"mapping": {"a": 1, "a": 2}}', "x.json")
    assert value == {"mapping": {"a": 2}}
    assert warnings == [ImportWarning("duplicate_json_key", "x.json")]


def test_bom_is_accepted() -> None:
    value, warnings = load_json(b"\xef\xbb\xbf[1]", "x.json")
    assert (value, warnings) == ([1], [])


@pytest.mark.parametrize(
    ("name", "safe"),
    [
        ("conversations.json", True),
        ("user-abc/file-1.png", True),
        ("../evil.json", False),
        ("a/../../evil", False),
        ("/etc/passwd", False),
        ("C:/Windows/x", False),
        ("a\\b.json", False),
        ("a//b", False),
        ("", False),
    ],
)
def test_safe_member_names(name: str, safe: bool) -> None:
    assert safe_member_name(name) is safe


# ---------------------------------------------------------------- the official adapter


def test_single_sharded_and_zip_layouts_give_the_same_conversations() -> None:
    single = _natives(_root("export_single"))
    sharded = _natives(_root("export_sharded"))
    zipped = _natives(_root("export_zip"))

    assert len(single) == 3
    assert single == sharded == zipped


def test_probe_matches_official_layouts_only() -> None:
    for case in ("export_single", "export_sharded", "export_zip"):
        assert ADAPTER.probe(_root(case)).matched
    assert not ADAPTER.probe(_root("split_wrapper")).matched


def test_locators_and_file_hashes() -> None:
    listing = ADAPTER.open(_root("export_sharded"), max_bytes=LIMIT)
    locators = [c.locator for c in listing.conversations()]

    assert [f.path for f in listing.files] == ["conversations-000.json", "conversations-001.json"]
    assert all(len(f.sha256) == 64 for f in listing.files)
    assert locators[0] == SourceLocator("conversations-000.json", 0, None)
    assert locators[-1].file == "conversations-001.json"

    zipped = ADAPTER.open(_root("export_zip"), max_bytes=LIMIT)
    assert next(zipped.conversations()).locator.archive == "export.zip"


def test_media_files_are_listed_by_content(tmp_path: Path) -> None:
    root = Path(shutil.copytree(_root("export_single"), tmp_path / "export"))
    (root / "dalle-generations").mkdir()
    (root / "dalle-generations" / "gen.webp").write_bytes(b"RIFF\0\0\0\0WEBPVP8 ")
    (root / "user-x").mkdir()
    (root / "user-x" / "file-ABC-photo.dat").write_bytes(tiny_png((1, 2, 3)))
    (root / "user.json").write_text("{}")
    (root / "notes.txt").write_text("not media")

    listing = ADAPTER.open(root, max_bytes=LIMIT)

    assert [m.path for m in listing.media_files] == [
        "dalle-generations/gen.webp",
        "file-SYN0001-synthetic.png",
        "user-x/file-ABC-photo.dat",
    ]
    assert listing.media_files[2].name == "file-ABC-photo.dat"


def test_shards_are_ordered_numerically(tmp_path: Path) -> None:
    for number in (10, 2, 1):
        conv = {"mapping": {}, "id": f"c{number}"}
        (tmp_path / f"conversations-{number:03d}.json").write_text(json.dumps([conv]))
    (tmp_path / "conversations-0010.json").write_text(json.dumps([{"mapping": {}, "id": "c10b"}]))

    ids = [c.native["id"] for c in ADAPTER.open(tmp_path, max_bytes=LIMIT).conversations()]

    # Numeric order, not text order (10 after 2). Two files with the same
    # number fall back to their names.
    assert ids == ["c1", "c2", "c10b", "c10"]


def test_malicious_zip_names_refuse_the_archive(tmp_path: Path) -> None:
    archive = tmp_path / "evil.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("conversations.json", "[]")
        zf.writestr("../escape.png", tiny_png((0, 0, 0)))

    with pytest.raises(UnsafeArchiveError):
        ADAPTER.open(archive, max_bytes=LIMIT)


def test_oversized_conversations_file_is_refused(tmp_path: Path) -> None:
    (tmp_path / "conversations.json").write_text("[" + " " * 200 + "]")
    with pytest.raises(SourceTooLargeError):
        ADAPTER.open(tmp_path, max_bytes=100)

    archive = tmp_path / "big.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("conversations.json", "[" + " " * 5000 + "]")
    with pytest.raises(SourceTooLargeError):
        ADAPTER.open(archive, max_bytes=100)


def test_unknown_files_and_bad_entries_become_warnings(tmp_path: Path) -> None:
    good = {"mapping": {}, "id": "ok"}
    (tmp_path / "conversations.json").write_text(json.dumps([good, "junk", {"no": "mapping"}]))
    (tmp_path / "mystery.bin").write_bytes(b"\x01\x02")
    (tmp_path / "nested").mkdir()
    (tmp_path / "nested" / "conversations.json").write_text("not ours")

    listing = ADAPTER.open(tmp_path, max_bytes=LIMIT)
    convs = list(listing.conversations())

    assert [f.path for f in listing.files] == ["conversations.json"]
    assert listing.media_files == ()
    assert convs[0].native == good and convs[0].warnings == ()
    assert [w.code for c in convs[1:] for w in c.warnings] == ["invalid_conversation_entry"] * 2


def test_conversations_file_that_is_not_a_list(tmp_path: Path) -> None:
    (tmp_path / "conversations.json").write_text('{"mapping": {}}')
    (conv,) = ADAPTER.open(tmp_path, max_bytes=LIMIT).conversations()
    assert conv.warnings == (ImportWarning("not_a_list", "conversations.json"),)


def test_adapter_never_writes_to_the_source(tmp_path: Path) -> None:
    from knowledge_engine.ingestion.inventory import tree_signature

    root = Path(shutil.copytree(_root("export_sharded"), tmp_path / "export"))
    before = tree_signature(root)
    list(ADAPTER.open(root, max_bytes=LIMIT).conversations())
    assert tree_signature(root) == before
