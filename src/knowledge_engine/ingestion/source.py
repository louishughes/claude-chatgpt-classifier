"""The source seam: how each export format hands conversations to the importer.

Export formats differ in one place only: *where the conversations are*.
The official ChatGPT export keeps them in ``conversations.json`` (or
numbered shards, maybe inside a ZIP); the split export keeps one wrapped
conversation per file. Everything after that (the message tree, hashes,
identity) is shared. So an adapter has just two jobs:

* ``probe(path)``: a cheap look at file names to say "this is mine" or not;
* ``open(path)``: list the input files and media files with their hashes,
  and stream ``NativeConversation`` objects, each the conversation exactly
  as exported plus where it came from.

Adapters never parse messages; ``graph/`` does that once for every format
(docs/plans/M1_CONSOLIDATION.md §2.3).

Talking points:
    - "Formats differ only in where the conversations live, so that's the
      only thing an adapter does. Parsing is shared."
    - "Every conversation carries its locator: which file, which entry, so
      any record can be traced back to its source."
    - "Warnings are codes and counts, never content, so they're safe to
      log and show."
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Protocol


class UnsupportedFormatError(ValueError):
    """No adapter recognises the given path."""


class UnsafeArchiveError(ValueError):
    """A ZIP contains a member name that could escape its folder."""


# Default for ``Limits.max_archive_entries`` (OPS-002).
MAX_ARCHIVE_ENTRIES = 500_000


class SourceTooLargeError(ValueError):
    """An input file is bigger than the configured limit."""


@dataclass(frozen=True)
class ImportWarning:
    """A fidelity or format problem, by code. Never carries private text.

    Attributes:
        code: Short machine-readable name, e.g. ``duplicate_json_key``.
        locator: Which file or entry it concerns (relative path), if any.
    """

    code: str
    locator: str | None = None


@dataclass(frozen=True)
class SourceLocator:
    """Where one conversation came from.

    Attributes:
        file: Path of the JSON file, relative to the source root (inside the
            ZIP for archives), with ``/`` separators.
        index: Position in a conversations list, or None for one-per-file.
        archive: The ZIP's own file name when the source is a ZIP.
    """

    file: str
    index: int | None = None
    archive: str | None = None


@dataclass(frozen=True)
class SourceFile:
    """One input file that conversations were read from.

    Attributes:
        path: Relative path (inside the ZIP for archives).
        sha256: SHA-256 of its bytes.
        size: Size in bytes.
    """

    path: str
    sha256: str
    size: int


@dataclass(frozen=True)
class MediaFile:
    """An image or other attachment file found next to the conversations.

    Attributes:
        path: Relative path (inside the ZIP for archives).
        size: Size in bytes.
    """

    path: str
    size: int

    @property
    def name(self) -> str:
        """The file name without folders."""
        return PurePosixPath(self.path).name


@dataclass(frozen=True)
class ProbeResult:
    """An adapter's answer to "is this yours?".

    Attributes:
        matched: True if the adapter can read the path.
        reason: Short explanation (file names only, never content).
    """

    matched: bool
    reason: str


@dataclass(frozen=True)
class NativeConversation:
    """One conversation exactly as exported, plus where it came from.

    Attributes:
        native: The conversation object (``mapping``, ``current_node``...).
        locator: Its source location.
        warnings: Problems specific to this conversation.
    """

    native: Mapping[str, Any]
    locator: SourceLocator
    warnings: tuple[ImportWarning, ...] = ()


@dataclass(frozen=True)
class SourceListing:
    """What an adapter found at a path.

    Attributes:
        format_id: The adapter that produced it.
        files: Every conversation file, with hashes (for snapshots).
        media_files: Attachment files found alongside.
        warnings: Source-level warnings (e.g. the format lacks account IDs).
        reader: Called to stream the conversations. Use ``conversations()``.
        declared_media: File names an export manifest lists, whether or not
            the file is present. Lets a missing image be reported as
            "listed but absent" rather than just "not found".
    """

    format_id: str
    files: tuple[SourceFile, ...]
    media_files: tuple[MediaFile, ...]
    warnings: tuple[ImportWarning, ...] = ()
    reader: Callable[[], Iterator[NativeConversation]] = field(
        default=lambda: iter(()), repr=False, compare=False
    )
    declared_media: tuple[str, ...] = ()

    def conversations(self) -> Iterator[NativeConversation]:
        """Stream the conversations, one at a time.

        Yields:
            Each conversation in file order, then list order.
        """
        yield from self.reader()


class SourceAdapter(Protocol):
    """What every export-format adapter provides."""

    format_id: str

    def probe(self, path: Path) -> ProbeResult:
        """Say cheaply whether this adapter can read ``path``."""
        ...

    def open(
        self, path: Path, *, max_bytes: int, max_entries: int = MAX_ARCHIVE_ENTRIES
    ) -> SourceListing:
        """List files and media and prepare to stream conversations.

        ``max_entries`` bounds a ZIP's member count; folder formats ignore it.
        """
        ...


def select_adapter(
    path: Path, adapters: Sequence[SourceAdapter], format_id: str | None = None
) -> SourceAdapter:
    """Pick the adapter for a path: the named one, or the only one that matches.

    Args:
        path: Folder or file to import.
        adapters: Candidates, e.g. ``default_adapters()``.
        format_id: Force a specific adapter instead of probing.

    Returns:
        The adapter.

    Raises:
        UnsupportedFormatError: If the named adapter doesn't exist or doesn't
            match, if none match, or if several match (ambiguous: the user
            must say which, rather than the engine guessing).
    """
    if format_id is not None:
        named = [a for a in adapters if a.format_id == format_id]
        if not named:
            raise UnsupportedFormatError(f"unknown format '{format_id}'")
        result = named[0].probe(path)
        if not result.matched:
            raise UnsupportedFormatError(f"not a {format_id} source: {result.reason}")
        return named[0]
    matches = [a for a in adapters if a.probe(path).matched]
    if not matches:
        raise UnsupportedFormatError("no adapter recognises this source")
    if len(matches) > 1:
        names = ", ".join(sorted(a.format_id for a in matches))
        raise UnsupportedFormatError(f"several formats match ({names}); pass --format")
    return matches[0]


# ---------------------------------------------------------------- shared helpers


def load_json(data: bytes, locator: str) -> tuple[Any, list[ImportWarning]]:
    """Parse JSON, reporting duplicate keys instead of silently keeping the last.

    Python's JSON parser keeps only the last value for a repeated key. In a
    ``mapping`` that would silently drop a message, so repeats are counted
    as warnings (the last value still wins, as in every other JSON reader).

    Args:
        data: The file's bytes (UTF-8, optional BOM).
        locator: Relative path, used in warnings.

    Returns:
        ``(value, warnings)``.

    Raises:
        ValueError: If the bytes aren't valid UTF-8 JSON.
    """
    warnings: list[ImportWarning] = []

    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                warnings.append(ImportWarning("duplicate_json_key", locator))
            result[key] = value
        return result

    text = data.decode("utf-8-sig")
    return json.loads(text, object_pairs_hook=pairs), warnings


def sha256_of(data: bytes) -> str:
    """Return the SHA-256 hex digest of some bytes."""
    return hashlib.sha256(data).hexdigest()


def safe_member_name(name: str) -> bool:
    """Return True if a ZIP member name stays inside the extraction folder.

    Rejects absolute paths, drive letters, backslashes and ``..`` parts,
    the usual "zip slip" tricks. The engine never extracts, but member
    names end up in locators and media paths, so they must be clean.

    Args:
        name: The member name as stored in the ZIP.

    Returns:
        Whether the name is safe.
    """
    if not name or "\\" in name or name.startswith("/") or "\x00" in name:
        return False
    if len(name) >= 2 and name[1] == ":":
        return False
    return all(part not in ("..", "") for part in name.rstrip("/").split("/"))
