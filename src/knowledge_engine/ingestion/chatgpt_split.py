"""Adapter for the split export: one wrapped conversation per JSON file.

Louis's ``raw/`` folder was produced by an earlier tool that split the
official export into one file per conversation. Each file is a small
*wrapper* (``conversation_id``, ``title``, ``create_time``, ``date``,
``filename``, ``message_count``, ``user_message_count``,
``assistant_message_count``, ``image_references``) around the native
conversation object under ``conversation``. Key names were checked against
the real files, names only (REV-007).

The native object is what gets imported; the wrapper's fields are only
*hints*, cross-checked and reported when they disagree. Other JSON files in
the folder (an old classifier's output, an index, a manifest) are skipped
with a warning, never imported as conversations. The format carries no
account ID, which is reported once per import so the report is honest
about what this source can't prove.

Talking points:
    - "The wrapper is a hint, the native conversation is the evidence. When
      they disagree, I report it and trust the evidence."
    - "Leftover files from older tools are skipped with a warning, never
      imported by accident."
    - "If a file changes between listing and reading, the import stops
      instead of mixing two versions."
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any

from knowledge_engine.ingestion.inventory import sniff_media
from knowledge_engine.ingestion.source import (
    ImportWarning,
    MediaFile,
    NativeConversation,
    ProbeResult,
    SourceFile,
    SourceListing,
    SourceLocator,
    SourceTooLargeError,
    load_json,
    sha256_of,
)

FORMAT_ID = "chatgpt-split-v1"
_SNIFF_BYTES = 16


class SourceChangedError(RuntimeError):
    """A file changed between listing and reading; the import must stop."""


class ChatGPTSplitAdapter:
    """Reads a folder of per-conversation wrapper files."""

    format_id = FORMAT_ID

    def probe(self, path: Path) -> ProbeResult:
        """Check for wrapper files: a ``conversations/`` folder of JSON objects.

        Reads only the first JSON file's top-level keys.

        Args:
            path: The raw root, or its ``conversations/`` folder.

        Returns:
            Whether this adapter can read it, and why.
        """
        folder = _conversation_folder(path)
        if folder is None:
            return ProbeResult(False, "no folder of per-conversation JSON files")
        for file in sorted(folder.glob("*.json")):
            try:
                value, _ = load_json(file.read_bytes(), file.name)
            except (OSError, ValueError):
                continue
            if _is_wrapper(value):
                return ProbeResult(True, "per-conversation wrapper files found")
        return ProbeResult(False, "JSON files found, but none wraps a conversation")

    def open(self, path: Path, *, max_bytes: int) -> SourceListing:
        """List wrapper files and media, hashing each conversation file.

        Args:
            path: The raw root, or its ``conversations/`` folder.
            max_bytes: Largest single file that will be read.

        Returns:
            The listing; conversations are re-read (and re-checked against
            their hash) when iterated, so memory stays flat.

        Raises:
            SourceTooLargeError: If a JSON file exceeds ``max_bytes``.
            FileNotFoundError: If there is no conversation folder.
        """
        folder = _conversation_folder(path)
        if folder is None:
            raise FileNotFoundError("no per-conversation folder found")
        root = folder.parent if folder != path else path
        files: list[SourceFile] = []
        warnings: list[ImportWarning] = [ImportWarning("format_lacks_account_id")]
        for file in sorted(folder.glob("*.json")):
            rel = file.relative_to(root).as_posix()
            data = _read(file, max_bytes)
            try:
                value, _ = load_json(data, rel)
            except ValueError:
                warnings.append(ImportWarning("invalid_json_skipped", rel))
                continue
            if _is_wrapper(value):
                files.append(SourceFile(rel, sha256_of(data), len(data)))
            else:
                warnings.append(ImportWarning("non_conversation_file_skipped", rel))

        media = [
            MediaFile(p.relative_to(root).as_posix(), p.stat().st_size)
            for p in sorted(root.rglob("*"))
            if p.is_file() and not p.is_symlink() and _is_media(p)
        ]

        def stream() -> Iterator[NativeConversation]:
            for source in files:
                data = _read(root / source.path, max_bytes)
                if sha256_of(data) != source.sha256:
                    raise SourceChangedError("a conversation file changed during the import")
                value, json_warnings = load_json(data, source.path)
                yield NativeConversation(
                    value["conversation"],
                    SourceLocator(source.path),
                    (*json_warnings, *_cross_check(value, source.path)),
                )

        return SourceListing(
            format_id=FORMAT_ID,
            files=tuple(files),
            media_files=tuple(media),
            warnings=tuple(warnings),
            reader=stream,
        )


def _conversation_folder(path: Path) -> Path | None:
    if not path.is_dir():
        return None
    nested = path / "conversations"
    if nested.is_dir() and any(nested.glob("*.json")):
        return nested
    if any(path.glob("*.json")) and not (path / "conversations.json").exists():
        return path
    return None


def _is_wrapper(value: Any) -> bool:
    return (
        isinstance(value, dict)
        and isinstance(value.get("conversation"), dict)
        and isinstance(value["conversation"].get("mapping"), dict)
    )


def _read(path: Path, max_bytes: int) -> bytes:
    if path.stat().st_size > max_bytes:
        raise SourceTooLargeError(f"{path.name} is over the size limit")
    return path.read_bytes()


def _is_media(path: Path) -> bool:
    with path.open("rb") as handle:
        return sniff_media(handle.read(_SNIFF_BYTES)) is not None


def _cross_check(wrapper: Mapping[str, Any], locator: str) -> list[ImportWarning]:
    """Compare the wrapper's hints with the native conversation."""
    native: Mapping[str, Any] = wrapper["conversation"]
    mapping: Mapping[str, Any] = native["mapping"]
    messages = [
        node["message"]
        for node in mapping.values()
        if isinstance(node, Mapping) and isinstance(node.get("message"), Mapping)
    ]

    def role_count(role: str) -> int:
        return sum(
            1
            for m in messages
            if isinstance(m.get("author"), Mapping) and m["author"].get("role") == role
        )

    checks = {
        "wrapper_id_mismatch": ("conversation_id", native.get("conversation_id")),
        "wrapper_title_mismatch": ("title", native.get("title")),
        "wrapper_create_time_mismatch": ("create_time", native.get("create_time")),
        "wrapper_message_count_mismatch": ("message_count", len(messages)),
        "wrapper_user_count_mismatch": ("user_message_count", role_count("user")),
        "wrapper_assistant_count_mismatch": ("assistant_message_count", role_count("assistant")),
    }
    # How the old tool counted is unknown, so only a hint that is present
    # and different counts as a disagreement; a missing hint is not one.
    return [
        ImportWarning(code, locator)
        for code, (key, actual) in checks.items()
        if key in wrapper and wrapper[key] != actual
    ]
