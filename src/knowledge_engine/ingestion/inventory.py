"""Read-only inventory of a raw source folder or ZIP: what's there, by metadata.

Before importing anything, the engine looks at a raw root and lists every
file: its size, SHA-256, and what kind of file it is (an official export,
a split-wrapper conversation, a media file, a derived file left over from
an earlier tool, and so on). It never parses a derived file as if it were
a conversation, and it never writes into the root.

To prove "never writes", the inventory takes a snapshot of the tree
(every path, size and modification time) before it starts and again when
it finishes. If anything changed, the report says so and is marked as not
trustworthy.

Reports are redacted by default: file names in ``raw/`` are often
conversation titles, which are private, so each file is shown as a short
token derived from its path. ``show_names=True`` is for local use only.

Talking points:
    - "Before touching the data, I take an inventory that reads metadata
      only, and it proves it changed nothing by comparing before and after."
    - "Leftover files from older tools are recognised and set aside, not
      mistaken for conversations."
    - "The report hides file names by default, because in a chat export the
      file names are the chat titles."
"""

from __future__ import annotations

import hashlib
import json
import zipfile
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Any

_CHUNK = 1024 * 1024
INVENTORY_VERSION = "src-inventory-v1"

# Files the official ChatGPT export ships besides the conversations. They
# are recognised by name, because their structure varies between exports.
_ACCOUNT_FILES = frozenset(
    {
        "user.json",
        "message_feedback.json",
        "model_comparisons.json",
        "shared_conversations.json",
        "group_chats.json",
        "sora.json",
        "user_settings.json",
    }
)

# Magic bytes for media types the importer cares about. Checked on content,
# not extension, because a renamed file shouldn't change what it is.
_MAGIC: tuple[tuple[bytes, str], ...] = (
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
    (b"%PDF-", "application/pdf"),
    (b"ID3", "audio/mpeg"),
    (b"OggS", "audio/ogg"),
)


class FileKind(StrEnum):
    """What a file in a raw root is, judged from metadata and structure."""

    OFFICIAL_CONVERSATIONS = "official_conversations"  # list of conversations
    SPLIT_CONVERSATION = "split_conversation"  # one wrapped conversation
    NATIVE_CONVERSATION = "native_conversation"  # one bare conversation object
    ACCOUNT_METADATA = "account_metadata"  # user.json and friends
    EXPORT_MANIFEST = "export_manifest"  # a list of the files an export tool wrote
    DERIVED_JSON = "derived_json"  # JSON that isn't a conversation
    INVALID_JSON = "invalid_json"
    HTML_EXPORT = "html_export"  # chat.html
    MEDIA = "media"
    ARCHIVE = "archive"  # a ZIP inside the root (not opened)
    OVERSIZED = "oversized"  # over the size limit, not read
    OTHER = "other"


class SourceFormat(StrEnum):
    """The overall layout detected for a raw root."""

    CHATGPT_EXPORT = "chatgpt-export"
    CHATGPT_SPLIT_V1 = "chatgpt-split-v1"
    MIXED = "mixed"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class InventoryEntry:
    """One file in the inventory.

    Attributes:
        path: Path relative to the root, with ``/`` separators. Private.
        size: Size in bytes.
        sha256: SHA-256 of the bytes, or None if the file was too big to read.
        kind: What the file is.
        mime: Media type for media files.
        conversations: How many conversations the file holds (0 for others).
    """

    path: str
    size: int
    sha256: str | None
    kind: FileKind
    mime: str | None = None
    conversations: int = 0

    @property
    def token(self) -> str:
        """A stable, non-reversible stand-in for the path, safe for reports."""
        return "f_" + hashlib.sha256(self.path.encode("utf-8")).hexdigest()[:12]

    @property
    def extension(self) -> str:
        """The lower-case extension, or "" if it isn't short and plain."""
        suffix = PurePosixPath(self.path).suffix.lower()
        return suffix if 1 < len(suffix) <= 6 and suffix[1:].isalnum() else ""


@dataclass(frozen=True)
class InventoryReport:
    """The result of inventorying one raw root.

    Attributes:
        root_type: ``directory`` or ``zip``.
        detected_format: Overall layout.
        entries: Every file, sorted by path.
        unchanged: True if the tree looked the same before and after.
        tree_hash: ``tree_signature`` of the root taken before reading.
            Comparing it with a later import's hash shows whether the raw
            folder changed in between.
    """

    root_type: str
    detected_format: SourceFormat
    entries: tuple[InventoryEntry, ...]
    unchanged: bool
    tree_hash: str
    version: str = field(default=INVENTORY_VERSION)

    def to_dict(self, *, show_names: bool = False) -> dict[str, Any]:
        """Return a JSON-ready summary.

        Args:
            show_names: Include real relative paths. Only for local use;
                the default shows a token per file instead.

        Returns:
            Counts by kind and extension, totals, duplicate count and one
            row per file.
        """
        by_hash = Counter(e.sha256 for e in self.entries if e.sha256 is not None)
        return {
            "inventory_version": self.version,
            "root_type": self.root_type,
            "detected_format": self.detected_format.value,
            "unchanged": self.unchanged,
            "tree_hash": self.tree_hash,
            "files": len(self.entries),
            "total_bytes": sum(e.size for e in self.entries),
            "conversations": sum(e.conversations for e in self.entries),
            "by_kind": dict(sorted(Counter(e.kind.value for e in self.entries).items())),
            "by_extension": dict(
                sorted(Counter(e.extension or "(none)" for e in self.entries).items())
            ),
            "duplicate_files": sum(n - 1 for n in by_hash.values() if n > 1),
            "entries": [
                {
                    "file": e.path if show_names else e.token,
                    "extension": e.extension,
                    "size": e.size,
                    "sha256": e.sha256,
                    "kind": e.kind.value,
                    "mime": e.mime,
                    "conversations": e.conversations,
                }
                for e in self.entries
            ],
        }


class RawTreeChangedError(RuntimeError):
    """The raw root changed while it was being inventoried."""


def inventory(root: Path, *, max_bytes: int, strict: bool = False) -> InventoryReport:
    """Inventory a raw root folder or ZIP without changing it.

    Args:
        root: A folder, or a ``.zip`` export.
        max_bytes: Files larger than this are listed but not read.
        strict: Raise instead of returning ``unchanged=False`` if the tree
            changed during the run.

    Returns:
        The report.

    Raises:
        FileNotFoundError: If ``root`` does not exist.
        RawTreeChangedError: In strict mode, if the tree changed.
    """
    if not root.exists():
        raise FileNotFoundError("raw root not found")
    before = tree_signature(root)
    if root.is_dir():
        entries = [_entry(path, read, size, max_bytes) for path, size, read in _walk_dir(root)]
        root_type = "directory"
    else:
        entries = list(_walk_zip(root, max_bytes))
        root_type = "zip"
    entries.sort(key=lambda e: e.path)
    unchanged = tree_signature(root) == before
    if strict and not unchanged:
        raise RawTreeChangedError("the raw root changed during the inventory")
    return InventoryReport(root_type, _detect_format(entries), tuple(entries), unchanged, before)


def tree_signature(root: Path) -> str:
    """Fingerprint a tree's metadata: every path, size and modification time.

    Cheap (no file contents are read) but catches any write, rename, new
    or deleted file.

    Args:
        root: A folder or a single file.

    Returns:
        A SHA-256 hex digest.
    """
    digest = hashlib.sha256()
    paths = [root] if root.is_file() else sorted(p for p in root.rglob("*"))
    for path in paths:
        stat = path.stat()
        rel = path.name if path == root else path.relative_to(root).as_posix()
        digest.update(json.dumps([rel, path.is_dir(), stat.st_size, stat.st_mtime_ns]).encode())
    return digest.hexdigest()


# ---------------------------------------------------------------- walking


class _Reader:
    """Reads a file's bytes lazily, so oversized files are never opened."""

    def __init__(self, path: Path) -> None:
        self._path = path

    def __call__(self) -> bytes:
        return self._path.read_bytes()


def _walk_dir(root: Path) -> Iterator[tuple[str, int, _Reader]]:
    for path in sorted(root.rglob("*")):
        # Symlinks could point outside the root; list nothing they lead to.
        if path.is_symlink() or not path.is_file():
            continue
        yield path.relative_to(root).as_posix(), path.stat().st_size, _Reader(path)


def _walk_zip(archive: Path, max_bytes: int) -> Iterator[InventoryEntry]:
    with zipfile.ZipFile(archive) as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue

            def read(info: zipfile.ZipInfo = info) -> bytes:
                # Read at most one byte past the limit, so a member that lies
                # about its size (a "zip bomb") can't fill memory.
                with zf.open(info) as handle:
                    data = handle.read(max_bytes + 1)
                if len(data) > max_bytes:
                    raise _TooBig
                return data

            yield _entry(info.filename, read, info.file_size, max_bytes)


class _TooBig(Exception):
    pass


# ---------------------------------------------------------------- classifying


def _entry(path: str, read: Any, size: int, max_bytes: int) -> InventoryEntry:
    if size > max_bytes:
        return InventoryEntry(path, size, None, FileKind.OVERSIZED)
    try:
        data: bytes = read()
    except _TooBig:
        return InventoryEntry(path, size, None, FileKind.OVERSIZED)
    sha = hashlib.sha256(data).hexdigest()
    kind, mime, conversations = _classify(PurePosixPath(path).name.lower(), data)
    return InventoryEntry(path, len(data), sha, kind, mime, conversations)


def sniff_media(head: bytes) -> str | None:
    """Return the media type of a file from its first bytes, or None.

    Args:
        head: At least the first 16 bytes of the file.

    Returns:
        A MIME type such as ``image/png``, or None if it isn't a known
        media type.
    """
    for magic, mime in _MAGIC:
        if head.startswith(magic):
            return mime
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    if head[:4] == b"RIFF" and head[8:12] == b"WAVE":
        return "audio/wav"
    if head[4:8] == b"ftyp":
        return "video/mp4"
    return None


def _classify(name: str, data: bytes) -> tuple[FileKind, str | None, int]:
    mime = sniff_media(data[:16])
    if mime is not None:
        return FileKind.MEDIA, mime, 0
    if data.startswith(b"PK\x03\x04"):
        return FileKind.ARCHIVE, "application/zip", 0
    if name.endswith((".html", ".htm")):
        return FileKind.HTML_EXPORT, "text/html", 0
    if not name.endswith(".json"):
        return FileKind.OTHER, None, 0
    if name in _ACCOUNT_FILES:
        return FileKind.ACCOUNT_METADATA, "application/json", 0
    try:
        value = json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return FileKind.INVALID_JSON, "application/json", 0
    kind, count = _json_kind(value)
    return kind, "application/json", count


def _is_conversation(value: Any) -> bool:
    # The one structural marker every ChatGPT conversation has: a "mapping"
    # of node ID -> node. Derived files (an old classifier's output, say)
    # may mention conversations but don't carry a mapping.
    return isinstance(value, dict) and isinstance(value.get("mapping"), dict)


def _json_kind(value: Any) -> tuple[FileKind, int]:
    if isinstance(value, list) and value and all(_is_conversation(v) for v in value):
        return FileKind.OFFICIAL_CONVERSATIONS, len(value)
    if isinstance(value, dict):
        # Key names seen in the manifest file of the real split export
        # (REV-007, names only). Values are never read.
        if value.keys() & {"manifest_file", "export_files", "logical_files"}:
            return FileKind.EXPORT_MANIFEST, 0
        if _is_conversation(value.get("conversation")):
            return FileKind.SPLIT_CONVERSATION, 1
        if _is_conversation(value):
            return FileKind.NATIVE_CONVERSATION, 1
    return FileKind.DERIVED_JSON, 0


def _detect_format(entries: list[InventoryEntry]) -> SourceFormat:
    kinds = {e.kind for e in entries}
    official = FileKind.OFFICIAL_CONVERSATIONS in kinds
    split = FileKind.SPLIT_CONVERSATION in kinds
    if official and split:
        return SourceFormat.MIXED
    if official:
        return SourceFormat.CHATGPT_EXPORT
    if split:
        return SourceFormat.CHATGPT_SPLIT_V1
    return SourceFormat.UNKNOWN
