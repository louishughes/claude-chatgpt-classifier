"""One exported message, turned into a clean, typed node with two fingerprints.

Each node in a ChatGPT export carries a ``message`` with a ``content`` object
whose shape depends on its ``content_type``: plain text, code, images mixed
with text, the model's "thoughts", quoted web pages and so on. This module
reads all of them into one shape, ``CanonicalNode``, with ordered content
parts and a list of asset pointers (the references to images and other
files). Anything it doesn't recognise is kept as an ``other`` part with its
raw value, never dropped. Hidden and reasoning content is flagged, not
removed.

Every node gets two hashes (ADR-0003, OD-13):

* ``raw_payload_hash``: the whole exported node, exactly. Any change at
  all, even a cosmetic metadata change, gives a new raw hash, so the
  archive can show exactly what each export said.
* ``canonical_content_hash``: only role, content and create time. This
  decides whether derived work (classification, extraction) must be redone,
  so a model label changing between exports costs nothing.

The input is never modified: parts keep a read-only view of the raw values.

Talking points:
    - "Two fingerprints per message: one says 'the export changed', the
      other says 'the meaning changed'. Only the second triggers rework."
    - "Unknown content is kept, not thrown away. The parser is honest about
      what it doesn't understand."
    - "Hidden and reasoning messages are flagged, not deleted, so nothing
      disappears from the evidence."
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Any

from knowledge_engine.domain.ids import sha256_hex

# Bump when the canonical-content rule changes: every stored revision's
# hash depends on it.
CANONICAL_HASH_VERSION = "ke-content-v1"
RAW_HASH_VERSION = "ke-raw-v1"

_KNOWN_SCHEMES = {"file-service", "sediment"}
# Content types whose text is the model's private working, or context the
# user never typed in the chat. Flagged so views can hide them by default.
_REASONING_TYPES = {"thoughts", "reasoning_recap"}
_CONTEXT_TYPES = {"user_editable_context"}


class PartKind(StrEnum):
    """What one content part is."""

    TEXT = "text"
    ASSET_POINTER = "asset_pointer"
    OTHER = "other"  # kept as raw value; not understood (yet)


class NodeFlag(StrEnum):
    """Facts about a node that views and later stages need to know."""

    HIDDEN = "hidden"  # metadata says it isn't shown in the chat
    REASONING = "reasoning"  # the model's thoughts or a summary of them
    CONTEXT = "context"  # custom instructions / profile, not typed in the chat
    UNKNOWN_CONTENT_TYPE = "unknown_content_type"


class NodeWarning(StrEnum):
    """Problems with a node's content, reported by code (never with text)."""

    UNSUPPORTED_POINTER_SCHEME = "unsupported_pointer_scheme"
    ASSET_PART_WITHOUT_POINTER = "asset_part_without_pointer"
    MALFORMED_CONTENT = "malformed_content"


@dataclass(frozen=True)
class AssetPointer:
    """A reference from a message to an image, audio clip or other file.

    Attributes:
        pointer: The pointer string exactly as exported.
        scheme: ``file-service``, ``sediment``, another scheme, or None.
        file_id: The file ID inside the pointer for known schemes, else None.
        part_index: Which content part holds it.
        content_type: The part's own type, e.g. ``image_asset_pointer``.
        size_bytes: Declared size, if the export gives one.
        width: Declared width, if given.
        height: Declared height, if given.
    """

    pointer: str
    scheme: str | None
    file_id: str | None
    part_index: int
    content_type: str | None
    size_bytes: int | None
    width: int | None
    height: int | None


@dataclass(frozen=True)
class ContentPart:
    """One ordered piece of a message's content.

    Attributes:
        index: Position within the message's content.
        kind: Text, asset pointer, or other.
        text: The text for text parts, else None.
        pointer: The asset pointer for pointer parts, else None.
        raw: The exported value, read-only.
    """

    index: int
    kind: PartKind
    text: str | None
    pointer: AssetPointer | None
    raw: Any


@dataclass(frozen=True)
class CanonicalNode:
    """A message node in one consistent shape.

    Attributes:
        node_id: The mapping key.
        message_id: The message's own ``id``, if any.
        role: Author role, or None.
        author_name: Author name (tools have names), or None.
        content_type: The content's type, or None.
        parts: Ordered content parts.
        create_time: As exported, or None. Never invented.
        update_time: As exported, or None.
        flags: Hidden / reasoning / context / unknown-type markers.
        warnings: Content problems, by code.
        raw_payload_hash: SHA-256 of the whole node, sorted-key JSON.
        canonical_content_hash: SHA-256 of role, content and create time.
    """

    node_id: str
    message_id: str | None
    role: str | None
    author_name: str | None
    content_type: str | None
    parts: tuple[ContentPart, ...]
    create_time: float | None
    update_time: float | None
    flags: frozenset[NodeFlag]
    warnings: tuple[NodeWarning, ...]
    raw_payload_hash: str
    canonical_content_hash: str

    @property
    def text(self) -> str:
        """All text parts joined with blank lines (for display and search)."""
        return "\n\n".join(p.text for p in self.parts if p.text)

    @property
    def asset_pointers(self) -> tuple[AssetPointer, ...]:
        """Every asset pointer, in part order."""
        return tuple(p.pointer for p in self.parts if p.pointer is not None)


def canonical_json(value: Any) -> str:
    """Serialise JSON deterministically: sorted keys, no spaces, real Unicode.

    Args:
        value: Any JSON-compatible value.

    Returns:
        The canonical string. Equal values always give equal strings.
    """
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def raw_payload_hash(node: Mapping[str, Any]) -> str:
    """Hash a whole exported node exactly.

    Args:
        node: The mapping entry ``{"id", "message", "parent", ...}``.

    Returns:
        64 hex characters.
    """
    return sha256_hex(canonical_json([RAW_HASH_VERSION, node]).encode("utf-8"))


def canonical_content_hash(role: str | None, content: Any, create_time: float | None) -> str:
    """Hash what a message *says*: its role, content and create time (OD-13).

    The whole ``content`` object is included (parts, code language, quoted
    URL), so a change to any of them counts. Message metadata (model name,
    finish details, feedback) is left out on purpose.

    Args:
        role: Author role.
        content: The exported ``content`` object.
        create_time: The message's create time.

    Returns:
        64 hex characters.
    """
    return sha256_hex(
        canonical_json([CANONICAL_HASH_VERSION, role, content, create_time]).encode("utf-8")
    )


def canonical_node(node_id: str, node: Mapping[str, Any]) -> CanonicalNode | None:
    """Turn one exported mapping entry into a ``CanonicalNode``.

    Args:
        node_id: The mapping key.
        node: The mapping entry. Not modified.

    Returns:
        The canonical node, or None if the entry has no message (the empty
        root node exports start with).
    """
    message = node.get("message")
    if not isinstance(message, Mapping):
        return None
    author = message.get("author")
    author = author if isinstance(author, Mapping) else {}
    role = _str(author.get("role"))
    content = message.get("content")
    content_type = _str(content.get("content_type")) if isinstance(content, Mapping) else None
    create_time = _time(message.get("create_time"))

    warnings: list[NodeWarning] = []
    flags: set[NodeFlag] = set()
    parts = _parts(content, warnings, flags)

    metadata = message.get("metadata")
    if isinstance(metadata, Mapping) and metadata.get("is_visually_hidden_from_conversation"):
        flags.add(NodeFlag.HIDDEN)
    if content_type in _REASONING_TYPES:
        flags.add(NodeFlag.REASONING)
    if content_type in _CONTEXT_TYPES:
        flags.add(NodeFlag.CONTEXT)

    return CanonicalNode(
        node_id=node_id,
        message_id=_str(message.get("id")),
        role=role,
        author_name=_str(author.get("name")),
        content_type=content_type,
        parts=tuple(parts),
        create_time=create_time,
        update_time=_time(message.get("update_time")),
        flags=frozenset(flags),
        warnings=tuple(warnings),
        raw_payload_hash=raw_payload_hash(node),
        canonical_content_hash=canonical_content_hash(role, content, create_time),
    )


def parse_pointer(pointer: str) -> tuple[str | None, str | None]:
    """Split an asset pointer into scheme and file ID.

    Args:
        pointer: e.g. ``file-service://file-abc`` or ``sediment://file_00..``.

    Returns:
        ``(scheme, file_id)``. ``file_id`` is None for unknown schemes or an
        empty ID; ``scheme`` is None when there is no ``://``.
    """
    scheme, sep, rest = pointer.partition("://")
    if not sep or not scheme:
        return None, None
    if scheme not in _KNOWN_SCHEMES:
        return scheme, None
    file_id = rest.strip("/")
    return scheme, file_id or None


ATTACHMENT_SCHEME = "attachment"


def attachment_pointers(
    message: Mapping[str, Any], skip_file_ids: Iterable[str] = ()
) -> tuple[AssetPointer, ...]:
    """Return a message's uploaded-file attachments as asset pointers.

    Uploaded files are listed in ``metadata.attachments`` rather than in the
    content, so they don't change the content hash. Each one becomes an
    ``attachment://<id>`` pointer whose ``part_index`` is its position in
    that list. An image is often listed both as a content part and as an
    attachment; pass the content parts' file IDs in ``skip_file_ids`` so it
    is counted once.

    Args:
        message: The node's ``message`` object.
        skip_file_ids: File IDs already referenced by the content.

    Returns:
        One pointer per attachment that has a string ``id``.
    """
    metadata = message.get("metadata")
    attachments = metadata.get("attachments") if isinstance(metadata, Mapping) else None
    if not isinstance(attachments, list):
        return ()
    skip = set(skip_file_ids)
    pointers: list[AssetPointer] = []
    for index, attachment in enumerate(attachments):
        if not isinstance(attachment, Mapping):
            continue
        file_id = _str(attachment.get("id"))
        if not file_id or file_id in skip:
            continue
        pointers.append(
            AssetPointer(
                pointer=f"{ATTACHMENT_SCHEME}://{file_id}",
                scheme=ATTACHMENT_SCHEME,
                file_id=file_id,
                part_index=index,
                content_type=ATTACHMENT_SCHEME,
                size_bytes=_int(attachment.get("size")),
                width=_int(attachment.get("width")),
                height=_int(attachment.get("height")),
            )
        )
    return tuple(pointers)


# ---------------------------------------------------------------- content variants


def _parts(content: Any, warnings: list[NodeWarning], flags: set[NodeFlag]) -> list[ContentPart]:
    if not isinstance(content, Mapping):
        if content is not None:
            warnings.append(NodeWarning.MALFORMED_CONTENT)
        return []
    kind = content.get("content_type")
    if kind in ("text", "multimodal_text"):
        raw_parts = content.get("parts")
        if not isinstance(raw_parts, list):
            warnings.append(NodeWarning.MALFORMED_CONTENT)
            return [_other(0, content)]
        return [_part(i, value, warnings) for i, value in enumerate(raw_parts)]
    # Single-text types: where their text lives, by content type.
    text_fields = {
        "code": ("text",),
        "execution_output": ("text",),
        "reasoning_recap": ("content",),
        "tether_quote": ("title", "text"),
        "tether_browsing_display": ("summary", "result"),
        "system_error": ("text",),
        "computer_output": ("text",),
    }
    if kind in text_fields:
        texts = [content.get(f) for f in text_fields[kind]]
        return [_text(i, t) for i, t in enumerate(t for t in texts if isinstance(t, str) and t)]
    if kind == "thoughts":
        thoughts = content.get("thoughts")
        if not isinstance(thoughts, list):
            return [_other(0, content)]
        out: list[ContentPart] = []
        for i, thought in enumerate(thoughts):
            body = thought.get("content") if isinstance(thought, Mapping) else None
            out.append(_text(i, body) if isinstance(body, str) else _other(i, thought))
        return out
    if kind == "user_editable_context":
        texts = [content.get("user_profile"), content.get("user_instructions")]
        return [_text(i, t) for i, t in enumerate(t for t in texts if isinstance(t, str) and t)]
    flags.add(NodeFlag.UNKNOWN_CONTENT_TYPE)
    return [_other(0, content)]


def _part(index: int, value: Any, warnings: list[NodeWarning]) -> ContentPart:
    if isinstance(value, str):
        return _text(index, value)
    if isinstance(value, Mapping):
        pointer = value.get("asset_pointer")
        part_type = _str(value.get("content_type"))
        if isinstance(pointer, str) and pointer:
            scheme, file_id = parse_pointer(pointer)
            if file_id is None:
                warnings.append(NodeWarning.UNSUPPORTED_POINTER_SCHEME)
            asset = AssetPointer(
                pointer=pointer,
                scheme=scheme,
                file_id=file_id,
                part_index=index,
                content_type=part_type,
                size_bytes=_int(value.get("size_bytes")),
                width=_int(value.get("width")),
                height=_int(value.get("height")),
            )
            return ContentPart(index, PartKind.ASSET_POINTER, None, asset, _frozen(value))
        if part_type is not None and part_type.endswith("asset_pointer"):
            warnings.append(NodeWarning.ASSET_PART_WITHOUT_POINTER)
    return _other(index, value)


def _text(index: int, text: str) -> ContentPart:
    return ContentPart(index, PartKind.TEXT, text, None, text)


def _other(index: int, value: Any) -> ContentPart:
    return ContentPart(index, PartKind.OTHER, None, None, _frozen(value))


def _frozen(value: Any) -> Any:
    # A read-only view, so nobody downstream can edit the export by accident.
    return MappingProxyType(dict(value)) if isinstance(value, Mapping) else value


def _str(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def _int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _time(value: Any) -> float | None:
    if isinstance(value, int | float) and not isinstance(value, bool):
        return float(value)
    return None
