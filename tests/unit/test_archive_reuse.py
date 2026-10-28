"""PERF-001: storing bytes that are already stored writes nothing and still checks.

A re-import used to copy every unchanged file to a temporary file, fsync it,
then hash the stored copy twice. Now known bytes are hashed once and the
stored copy is checked once; corruption is still caught.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from knowledge_engine.importer import archive
from knowledge_engine.importer.archive import BlobCorruptError, BlobStore, remove_stored


def _writes(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    made: list[str] = []
    real = archive.tempfile.mkstemp

    def counting(*args: object, **kwargs: object) -> tuple[int, str]:
        fd, name = real(*args, **kwargs)  # type: ignore[call-overload]
        made.append(name)
        return fd, name

    monkeypatch.setattr(archive.tempfile, "mkstemp", counting)
    return made


@pytest.mark.parametrize("big", [False, True])
def test_known_bytes_are_not_written_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, big: bool
) -> None:
    if big:
        monkeypatch.setattr(archive, "_IN_MEMORY", 4)  # take the streaming path
    store = BlobStore(tmp_path / "store")
    source = tmp_path / "conversations.json"
    source.write_bytes(b"synthetic export bytes")
    first = store.put_file(source)
    stamp = first.location.stat().st_mtime_ns
    writes = _writes(monkeypatch)
    again = store.put_file(source)
    assert again == first
    assert writes == []  # no temporary copy, no fsync
    assert first.location.stat().st_mtime_ns == stamp
    assert store.put_bytes(b"synthetic export bytes") == first
    assert writes == []


@pytest.mark.parametrize("big", [False, True])
def test_a_damaged_stored_copy_is_still_caught(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, big: bool
) -> None:
    if big:
        monkeypatch.setattr(archive, "_IN_MEMORY", 4)
    store = BlobStore(tmp_path / "store")
    source = tmp_path / "image.png"
    source.write_bytes(b"synthetic image")
    blob = store.put_file(source)
    remove_stored(blob.location)
    blob.location.write_bytes(b"tampered")
    with pytest.raises(BlobCorruptError):
        store.put_file(source)
    assert blob.location.read_bytes() == b"tampered"  # reported, never "fixed"


def test_new_big_files_are_stored_whole(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(archive, "_IN_MEMORY", 4)
    store = BlobStore(tmp_path / "store")
    source = tmp_path / "big.bin"
    data = os.urandom(3 * 1024 * 1024 + 5)
    source.write_bytes(data)
    blob = store.put_file(source)
    assert blob.location.read_bytes() == data and blob.size == len(data)
