"""ING-001 (slice I1): archive store, corruption and overwrite rejection."""

from __future__ import annotations

import hashlib
import os
import stat
from pathlib import Path

import pytest

from knowledge_engine.importer.archive import (
    BlobCorruptError,
    BlobMissingError,
    BlobStore,
    BlobTooLargeError,
    StoredBlob,
    hash_file,
)


def _write(path: Path, data: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def _tamper(path: Path, data: bytes) -> None:
    path.chmod(stat.S_IREAD | stat.S_IWRITE)
    path.write_bytes(data)


@pytest.fixture
def store(tmp_path: Path) -> BlobStore:
    return BlobStore(tmp_path / "store")


def test_put_file_stores_bytes_under_their_hash(store: BlobStore, tmp_path: Path) -> None:
    data = b"hello export"
    source = _write(tmp_path / "src" / "conversations.json", data)

    blob = store.put_file(source)

    sha = hashlib.sha256(data).hexdigest()
    assert blob == StoredBlob(sha, len(data), "copy", store.root / sha[:2] / sha)
    assert blob.location.read_bytes() == data
    assert store.read_bytes(blob) == data


def test_source_file_is_unchanged(store: BlobStore, tmp_path: Path) -> None:
    source = _write(tmp_path / "src" / "a.bin", b"\x00\x01raw")
    before = (source.read_bytes(), source.stat().st_mtime_ns)

    store.put_file(source)
    store.put_reference(source)

    assert (source.read_bytes(), source.stat().st_mtime_ns) == before


def test_storing_the_same_bytes_twice_keeps_one_copy(store: BlobStore, tmp_path: Path) -> None:
    first = store.put_file(_write(tmp_path / "x" / "one.json", b"same"))
    second = store.put_file(_write(tmp_path / "y" / "two.json", b"same"))

    assert first == second
    blobs = [p for p in store.root.rglob("*") if p.is_file()]
    assert blobs == [first.location]


def test_stored_blob_is_read_only(store: BlobStore, tmp_path: Path) -> None:
    blob = store.put_file(_write(tmp_path / "s" / "f", b"evidence"))

    assert not blob.location.stat().st_mode & stat.S_IWUSR


def test_no_temporary_files_left_behind(store: BlobStore, tmp_path: Path) -> None:
    store.put_file(_write(tmp_path / "s" / "f", b"one"))
    store.put_file(_write(tmp_path / "s" / "g", b"one"))

    assert not [p for p in store.root.iterdir() if p.name.startswith(".incoming-")]


def test_existing_corrupt_blob_is_reported_not_overwritten(
    store: BlobStore, tmp_path: Path
) -> None:
    source = _write(tmp_path / "s" / "f", b"original bytes")
    blob = store.put_file(source)
    _tamper(blob.location, b"tampered")

    with pytest.raises(BlobCorruptError):
        store.put_file(source)

    # The store refused to "repair" it: the tampered bytes are still there
    # for a person to investigate.
    assert blob.location.read_bytes() == b"tampered"


def test_verify_and_read_detect_corruption(store: BlobStore, tmp_path: Path) -> None:
    blob = store.put_file(_write(tmp_path / "s" / "f", b"good"))
    _tamper(blob.location, b"bad!")

    with pytest.raises(BlobCorruptError):
        store.verify(blob)
    with pytest.raises(BlobCorruptError):
        store.read_bytes(blob)


def test_verify_detects_a_missing_blob(store: BlobStore, tmp_path: Path) -> None:
    blob = store.put_file(_write(tmp_path / "s" / "f", b"gone soon"))
    blob.location.chmod(stat.S_IREAD | stat.S_IWRITE)
    blob.location.unlink()

    with pytest.raises(BlobMissingError):
        store.verify(blob)
    with pytest.raises(BlobMissingError):
        store.read_bytes(blob)


def test_reference_mode_writes_nothing_and_detects_change(store: BlobStore, tmp_path: Path) -> None:
    source = _write(tmp_path / "raw" / "images" / "pic.png", b"\x89PNG fake")

    blob = store.put_reference(source)

    assert blob.mode == "reference"
    assert blob.location == source
    assert not any(store.root.iterdir())
    store.verify(blob)

    source.write_bytes(b"\x89PNG edited")
    with pytest.raises(BlobCorruptError):
        store.verify(blob)


def test_size_limit_is_checked_before_reading(tmp_path: Path) -> None:
    store = BlobStore(tmp_path / "store", max_bytes=4)
    source = _write(tmp_path / "s" / "big", b"12345")

    with pytest.raises(BlobTooLargeError):
        store.put_file(source)
    with pytest.raises(BlobTooLargeError):
        store.put_reference(source)
    assert not [p for p in store.root.rglob("*") if p.is_file()]


def test_file_at_the_limit_is_accepted(tmp_path: Path) -> None:
    store = BlobStore(tmp_path / "store", max_bytes=4)
    blob = store.put_file(_write(tmp_path / "s" / "ok", b"1234"))

    assert blob.size == 4


def test_missing_source_raises(store: BlobStore, tmp_path: Path) -> None:
    with pytest.raises(BlobMissingError):
        store.put_file(tmp_path / "nope")
    with pytest.raises(BlobMissingError):
        store.put_reference(tmp_path / "nope")


def test_empty_file_is_a_valid_blob(store: BlobStore, tmp_path: Path) -> None:
    blob = store.put_file(_write(tmp_path / "s" / "empty", b""))

    assert blob.sha256 == hashlib.sha256(b"").hexdigest()
    assert blob.size == 0


def test_errors_never_name_the_source_path(store: BlobStore, tmp_path: Path) -> None:
    source = _write(tmp_path / "raw" / "private-title.png", b"x")
    blob = store.put_reference(source)
    source.write_bytes(b"y")

    with pytest.raises(BlobCorruptError) as excinfo:
        store.verify(blob)
    assert "private-title" not in str(excinfo.value)


def test_hash_file_streams_large_files(tmp_path: Path) -> None:
    data = os.urandom(3 * 1024 * 1024 + 7)
    source = _write(tmp_path / "big.bin", data)

    assert hash_file(source) == (hashlib.sha256(data).hexdigest(), len(data))


@pytest.mark.parametrize("bad", ["", "abc", "A" * 64, "g" * 64])
def test_path_for_rejects_malformed_hashes(store: BlobStore, bad: str) -> None:
    with pytest.raises(ValueError):
        store.path_for(bad)


def test_put_bytes_matches_put_file(store: BlobStore, tmp_path: Path) -> None:
    data = b"zip member bytes"
    from_bytes = store.put_bytes(data)
    from_file = store.put_file(_write(tmp_path / "s" / "m", data))

    assert from_bytes == from_file
    assert store.read_bytes(from_bytes) == data


def test_put_bytes_respects_the_limit(tmp_path: Path) -> None:
    store = BlobStore(tmp_path / "store", max_bytes=3)
    with pytest.raises(BlobTooLargeError):
        store.put_bytes(b"1234")
