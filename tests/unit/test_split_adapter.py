"""ING-011 (slice A2): the split-wrapper adapter."""

from __future__ import annotations

import json
import shutil
from collections import Counter
from pathlib import Path
from typing import Any

import pytest

from knowledge_engine.evaluation.synthetic import without_children
from knowledge_engine.ingestion.chatgpt_export import ChatGPTExportAdapter
from knowledge_engine.ingestion.chatgpt_split import ChatGPTSplitAdapter, SourceChangedError
from knowledge_engine.ingestion.inventory import tree_signature
from knowledge_engine.ingestion.registry import default_adapters
from knowledge_engine.ingestion.source import (
    ImportWarning,
    SourceTooLargeError,
    select_adapter,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "chatgpt"
LIMIT = 10 * 1024 * 1024
SPLIT = ChatGPTSplitAdapter()
OFFICIAL = ChatGPTExportAdapter()


def _split_root(case: str = "split_wrapper") -> Path:
    return FIXTURES / case / "export"


@pytest.fixture
def copy_root(tmp_path: Path) -> Path:
    return Path(shutil.copytree(_split_root(), tmp_path / "raw"))


def test_split_gives_the_same_conversations_as_the_official_export() -> None:
    official = [
        without_children(dict(c.native))
        for c in OFFICIAL.open(
            FIXTURES / "export_single" / "export", max_bytes=LIMIT
        ).conversations()
    ]
    split = [c.native for c in SPLIT.open(_split_root(), max_bytes=LIMIT).conversations()]

    key = lambda c: c["conversation_id"]  # noqa: E731
    assert sorted(split, key=key) == sorted(official, key=key)


def test_derived_file_and_count_mismatch_are_warnings_not_records() -> None:
    listing = SPLIT.open(_split_root(), max_bytes=LIMIT)
    convs = list(listing.conversations())
    codes = Counter(w.code for c in convs for w in c.warnings)

    assert len(convs) == 3
    assert [f.path for f in listing.files] == sorted(f.path for f in listing.files)
    assert all(f.path.startswith("conversations/") for f in listing.files)
    assert (
        ImportWarning("non_conversation_file_skipped", "conversations/classification_output.json")
        in listing.warnings
    )
    assert ImportWarning("format_lacks_account_id") in listing.warnings
    assert codes == {"wrapper_message_count_mismatch": 1}


def test_media_and_locators() -> None:
    listing = SPLIT.open(_split_root(), max_bytes=LIMIT)

    assert [m.path for m in listing.media_files] == ["images/file-SYN0001-synthetic.png"]
    locators = [c.locator for c in listing.conversations()]
    assert all(loc.index is None and loc.archive is None for loc in locators)
    assert {loc.file for loc in locators} == {f.path for f in listing.files}


def test_probe_and_registry_pick_the_right_adapter() -> None:
    assert SPLIT.probe(_split_root()).matched
    assert SPLIT.probe(_split_root() / "conversations").matched
    assert not SPLIT.probe(FIXTURES / "export_single" / "export").matched
    assert not SPLIT.probe(FIXTURES / "export_zip" / "export" / "export.zip").matched

    adapters = default_adapters()
    assert select_adapter(_split_root(), adapters).format_id == "chatgpt-split-v1"
    assert select_adapter(FIXTURES / "export_sharded" / "export", adapters).format_id == (
        "chatgpt-export-v1"
    )


def test_every_split_fixture_is_readable() -> None:
    for case in sorted(p.name for p in FIXTURES.iterdir()):
        root = _split_root(case)
        if not SPLIT.probe(root).matched:
            continue
        manifest = json.loads((FIXTURES / case / "manifest.json").read_text("utf-8"))
        convs = list(SPLIT.open(root, max_bytes=LIMIT).conversations())
        assert len(convs) == manifest["expected"]["conversations"], case


def _rewrite(path: Path, change: dict[str, Any]) -> None:
    wrapper = json.loads(path.read_text("utf-8"))
    wrapper.update(change)
    path.write_text(json.dumps(wrapper), "utf-8")


def test_wrapper_disagreements_are_reported(copy_root: Path) -> None:
    files = sorted((copy_root / "conversations").glob("2024-*.json"))
    _rewrite(files[1], {"title": "Different", "conversation_id": "other", "create_time": 1.0})
    _rewrite(files[2], {"user_message_count": 99, "assistant_message_count": 99})
    # A missing hint is not a disagreement.
    wrapper = json.loads(files[2].read_text("utf-8"))
    del wrapper["image_references"], wrapper["date"]
    files[2].write_text(json.dumps(wrapper), "utf-8")

    convs = list(SPLIT.open(copy_root, max_bytes=LIMIT).conversations())
    by_file = {c.locator.file.split("/")[-1]: {w.code for w in c.warnings} for c in convs}

    assert by_file[files[1].name] == {
        "wrapper_title_mismatch",
        "wrapper_id_mismatch",
        "wrapper_create_time_mismatch",
    }
    assert by_file[files[2].name] == {
        "wrapper_user_count_mismatch",
        "wrapper_assistant_count_mismatch",
    }


def test_invalid_json_is_skipped_with_a_warning(copy_root: Path) -> None:
    (copy_root / "conversations" / "broken.json").write_bytes(b"{nope")
    listing = SPLIT.open(copy_root, max_bytes=LIMIT)

    assert ImportWarning("invalid_json_skipped", "conversations/broken.json") in listing.warnings
    assert len(list(listing.conversations())) == 3


def test_file_changed_after_listing_stops_the_import(copy_root: Path) -> None:
    listing = SPLIT.open(copy_root, max_bytes=LIMIT)
    victim = copy_root / listing.files[0].path
    _rewrite(victim, {"title": "edited after listing"})

    with pytest.raises(SourceChangedError):
        list(listing.conversations())


def test_oversized_file_is_refused(copy_root: Path) -> None:
    with pytest.raises(SourceTooLargeError):
        SPLIT.open(copy_root, max_bytes=100)


def test_reading_never_writes(copy_root: Path) -> None:
    before = tree_signature(copy_root)
    list(SPLIT.open(copy_root, max_bytes=LIMIT).conversations())
    assert tree_signature(copy_root) == before


def test_open_without_a_folder_fails_clearly(tmp_path: Path) -> None:
    assert not SPLIT.probe(tmp_path).matched
    with pytest.raises(FileNotFoundError):
        SPLIT.open(tmp_path, max_bytes=LIMIT)
