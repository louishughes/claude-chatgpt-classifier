"""Adapter for the official ChatGPT export: a ZIP, or the folder it unzips to.

The conversations live in ``conversations.json`` or, in bigger exports, in
numbered shards ``conversations-000.json``, ``conversations-001.json``...
Images and other attachments sit next to them (at the top level, or in
folders such as ``user-.../`` and ``dalle-generations/``). Account files
(``user.json`` and friends) are recognised and skipped.

A ZIP is read in place, never extracted. Every member name is checked
first: one unsafe name (``../``, an absolute path, a drive letter) and the
whole archive is refused, because a tampered export shouldn't be trusted
for anything else either.

Talking points:
    - "The official export is read straight from the ZIP; nothing is
      unpacked to disk."
    - "A ZIP with a path-escaping file name is refused outright, not
      partly imported."
    - "Big files are refused by size before they're read, so a corrupt or
      hostile export can't exhaust memory."
"""

from __future__ import annotations

import re
import zipfile
from collections.abc import Iterator
from pathlib import Path, PurePosixPath

from knowledge_engine.ingestion.inventory import sniff_media
from knowledge_engine.ingestion.source import (
    MAX_ARCHIVE_ENTRIES,
    ImportWarning,
    MediaFile,
    NativeConversation,
    ProbeResult,
    SourceFile,
    SourceListing,
    SourceLocator,
    SourceTooLargeError,
    UnsafeArchiveError,
    load_json,
    safe_member_name,
    sha256_of,
)

FORMAT_ID = "chatgpt-export-v1"
_CONVERSATIONS = re.compile(r"^conversations(?:-(\d+))?\.json$")
# Enough bytes to recognise every media type in ingestion.inventory.
_SNIFF_BYTES = 16


def _shard_order(name: str) -> tuple[int, str]:
    match = _CONVERSATIONS.match(PurePosixPath(name).name)
    number = match.group(1) if match else None
    # conversations.json first, then shards in numeric (not text) order.
    return (-1 if number is None else int(number), name)


class ChatGPTExportAdapter:
    """Reads official ChatGPT exports (ZIP or extracted folder)."""

    format_id = FORMAT_ID

    def probe(self, path: Path) -> ProbeResult:
        """Look for ``conversations*.json`` by name only.

        Args:
            path: A folder or a ZIP file.

        Returns:
            Whether this adapter can read it, and why.
        """
        try:
            names = _names(path)
        except (OSError, zipfile.BadZipFile):
            return ProbeResult(False, "not a folder or readable ZIP")
        if any(_is_conversations(n) for n in names):
            return ProbeResult(True, "conversations.json found")
        return ProbeResult(False, "no conversations.json or conversations-NNN.json")

    def open(
        self, path: Path, *, max_bytes: int, max_entries: int = MAX_ARCHIVE_ENTRIES
    ) -> SourceListing:
        """List the export's conversation files and media.

        Args:
            path: A folder or a ZIP file.
            max_bytes: Largest single file that will be read.
            max_entries: Most members a ZIP may list (OPS-002).

        Returns:
            The listing; conversations are read when iterated.

        Raises:
            UnsafeArchiveError: If a ZIP member name is unsafe.
            SourceTooLargeError: If a conversations file exceeds ``max_bytes``,
                or a ZIP lists more than ``max_entries`` members.
        """
        reader = _ZipReader(path, max_entries) if path.is_file() else _DirReader(path)
        names = reader.names()
        conv_names = sorted((n for n in names if _is_conversations(n)), key=_shard_order)

        files: list[SourceFile] = []
        loaded: list[tuple[str, bytes]] = []
        for name in conv_names:
            data = reader.read(name, max_bytes)
            files.append(SourceFile(name, sha256_of(data), len(data)))
            loaded.append((name, data))

        media: list[MediaFile] = []
        for name in names:
            if name in conv_names or not name or name.endswith("/"):
                continue
            if sniff_media(reader.head(name, _SNIFF_BYTES)) is not None:
                media.append(MediaFile(name, reader.size(name)))

        archive = path.name if path.is_file() else None
        warnings: list[ImportWarning] = []
        if any(_shard_order(n)[0] == -1 for n in conv_names) and len(conv_names) > 1:
            warnings.append(ImportWarning("mixed_conversation_files"))

        def stream() -> Iterator[NativeConversation]:
            for name, data in loaded:
                yield from _conversations(name, data, archive)

        return SourceListing(
            format_id=FORMAT_ID,
            files=tuple(files),
            media_files=tuple(sorted(media, key=lambda m: m.path)),
            warnings=tuple(warnings),
            reader=stream,
        )


def _conversations(name: str, data: bytes, archive: str | None) -> Iterator[NativeConversation]:
    value, warnings = load_json(data, name)
    if not isinstance(value, list):
        # A conversations file that isn't a list can't be read safely;
        # report it as one entry with a warning rather than guessing.
        yield NativeConversation(
            {}, SourceLocator(name, None, archive), (ImportWarning("not_a_list", name),)
        )
        return
    shared = tuple(warnings)
    for index, item in enumerate(value):
        locator = SourceLocator(name, index, archive)
        if isinstance(item, dict) and isinstance(item.get("mapping"), dict):
            yield NativeConversation(item, locator, shared)
        else:
            yield NativeConversation(
                {}, locator, (*shared, ImportWarning("invalid_conversation_entry", name))
            )


def _is_conversations(name: str) -> bool:
    # Only top-level files count: a conversations.json deeper down belongs
    # to something else (e.g. an unrelated folder inside the ZIP).
    return "/" not in name.strip("/") and bool(_CONVERSATIONS.match(name.strip("/")))


def _names(path: Path) -> list[str]:
    if path.is_dir():
        return [p.name for p in path.iterdir()]
    with zipfile.ZipFile(path) as archive:
        return archive.namelist()


class _DirReader:
    def __init__(self, root: Path) -> None:
        self._root = root

    def names(self) -> list[str]:
        return sorted(
            p.relative_to(self._root).as_posix()
            for p in self._root.rglob("*")
            if p.is_file() and not p.is_symlink()
        )

    def size(self, name: str) -> int:
        return (self._root / name).stat().st_size

    def head(self, name: str, count: int) -> bytes:
        with (self._root / name).open("rb") as handle:
            return handle.read(count)

    def read(self, name: str, max_bytes: int) -> bytes:
        if self.size(name) > max_bytes:
            raise SourceTooLargeError(f"{PurePosixPath(name).name} is over the size limit")
        return (self._root / name).read_bytes()


class _ZipReader:
    def __init__(self, archive: Path, max_entries: int = MAX_ARCHIVE_ENTRIES) -> None:
        self._archive = archive
        with zipfile.ZipFile(archive) as zf:
            # ZipFile has read the member list by now, but refusing here
            # stops the per-member listing, sniffing and hashing that follow.
            if len(zf.filelist) > max_entries:
                raise SourceTooLargeError(f"archive lists over {max_entries} members")
            self._infos = {i.filename: i for i in zf.infolist() if not i.is_dir()}
        unsafe = [n for n in self._infos if not safe_member_name(n)]
        if unsafe:
            raise UnsafeArchiveError(f"{len(unsafe)} unsafe member name(s); archive refused")

    def names(self) -> list[str]:
        return sorted(self._infos)

    def size(self, name: str) -> int:
        return self._infos[name].file_size

    def head(self, name: str, count: int) -> bytes:
        with zipfile.ZipFile(self._archive) as zf, zf.open(self._infos[name]) as handle:
            return handle.read(count)

    def read(self, name: str, max_bytes: int) -> bytes:
        info = self._infos[name]
        if info.file_size > max_bytes:
            raise SourceTooLargeError(f"{PurePosixPath(name).name} is over the size limit")
        with zipfile.ZipFile(self._archive) as zf, zf.open(info) as handle:
            # Read one byte past the limit: a member whose header lies about
            # its size still can't fill memory.
            data = handle.read(max_bytes + 1)
        if len(data) > max_bytes:
            raise SourceTooLargeError(f"{PurePosixPath(name).name} is over the size limit")
        return data
