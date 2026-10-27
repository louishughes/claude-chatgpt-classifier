"""Stable identifiers: the same real thing always gets the same ID.

The owner re-exports the whole ChatGPT history again and again. If IDs were
random, every re-import would create a second copy of every conversation.
Instead, each ID is a hash of the thing's *identity key*: the facts that
define it and never change, such as "conversation ``abc`` in account
``louis-personal`` from ChatGPT" (ADR-0003). Feed in the same key, get the
same ID, on any machine, in any order.

Rules the helpers enforce:
    - Keys use native IDs from the source and content hashes, never display
      labels such as titles, which can be edited (CLAUDE.md §5).
    - Native IDs are used exactly as given. ``"A1"`` and ``"a1"`` are
      different IDs; only social handles are lower-cased, because platforms
      treat them case-insensitively.
    - Every ID kind has its own prefix and its own key layout, so an ID for a
      conversation can never equal an ID for a message, even with the same
      native string.
    - Missing native IDs are an error here. Deciding what to do then (a
      candidate match for review, never a guess) is IMP-002's job.

Talking points:
    - "Re-importing is safe because IDs come from identity, not from timing."
    - "Each ID is a SHA-256 of a typed, versioned key, so IDs of different
      kinds can't collide, and changing the scheme later is explicit."
    - "A title is never part of an ID. Rename a chat and it's the same chat."
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Annotated

from pydantic import StringConstraints

# Bump only with a migration plan: every stored ID depends on it.
ID_SCHEME_VERSION = "ke-id-v1"

# 32 hex characters = 128 bits of the SHA-256. With the scale of a personal
# archive (millions of rows at most) an accidental collision is not a
# realistic concern, and shorter IDs are easier to read in notes and logs.
_HASH_CHARS = 32

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
# Account namespaces use the same rule as settings.AccountNamespace.
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
# Fixed vocabulary words (source systems, platforms, origins, kinds).
_TOKEN_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,62}$")
_YOUTUBE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")

PREFIXES = {
    "conversation": "conv",
    "message_node": "node",
    "message_revision": "rev",
    "graph_edge": "edge",
    "snapshot": "snap",
    "media_asset": "asset",
    "asset_occurrence": "occ",
    "link_target": "link",
    "link_occurrence": "lnkocc",
    "social_account": "acct",
    "relationship": "rel",
}


# Pydantic field types: a model field typed ``ConversationId`` rejects any
# string that isn't shaped like a conversation ID.
ConversationId = Annotated[str, StringConstraints(pattern=r"^conv_[0-9a-f]{32}$")]
MessageNodeId = Annotated[str, StringConstraints(pattern=r"^node_[0-9a-f]{32}$")]
MessageRevisionId = Annotated[str, StringConstraints(pattern=r"^rev_[0-9a-f]{32}$")]
SnapshotId = Annotated[str, StringConstraints(pattern=r"^snap_[0-9a-f]{32}$")]
MediaAssetId = Annotated[str, StringConstraints(pattern=r"^asset_[0-9a-f]{32}$")]
AssetOccurrenceId = Annotated[str, StringConstraints(pattern=r"^occ_[0-9a-f]{32}$")]
Sha256Hex = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


def _stable_id(kind: str, *parts: str | int) -> str:
    """Hash a typed key into ``<prefix>_<32 hex>``.

    The key is encoded as a JSON list (scheme version, kind, parts...). JSON
    quoting keeps boundaries unambiguous: ``("ab", "c")`` and ``("a", "bc")``
    encode differently, which a plain string join would not guarantee.
    """
    for part in parts:
        # bool is a subclass of int; it would encode as true/false and is
        # never a legitimate key part.
        if isinstance(part, bool) or not isinstance(part, str | int):
            raise TypeError(f"ID key parts must be str or int, got {type(part).__name__}")
    key = [ID_SCHEME_VERSION, kind, *parts]
    encoded = json.dumps(key, ensure_ascii=False, separators=(",", ":"))
    digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
    return f"{PREFIXES[kind]}_{digest[:_HASH_CHARS]}"


def _require_native(value: str, what: str) -> str:
    if not isinstance(value, str) or value == "":
        raise ValueError(f"{what} must be a non-empty string")
    return value


def _require_slug(value: str, what: str) -> str:
    if not _SLUG_RE.fullmatch(value):
        raise ValueError(f"{what} must be a lowercase slug like 'louis-personal'")
    return value


def _require_token(value: str, what: str) -> str:
    if not _TOKEN_RE.fullmatch(value):
        raise ValueError(f"{what} must be a lowercase word like 'chatgpt' or 'message_text'")
    return value


def _require_sha256(value: str, what: str) -> str:
    if not _SHA256_RE.fullmatch(value):
        raise ValueError(f"{what} must be 64 lowercase hex characters")
    return value


def _require_prefixed(value: str, kind: str) -> str:
    prefix = PREFIXES[kind]
    if not re.fullmatch(rf"{prefix}_[0-9a-f]{{{_HASH_CHARS}}}", value):
        raise ValueError(f"expected a {kind} ID ({prefix}_...), got {value!r}")
    return value


def _require_offsets(start: int, end: int) -> None:
    if start < 0 or end <= start:
        raise ValueError("offsets must form a non-empty half-open range [start, end)")


def sha256_hex(data: bytes) -> str:
    """Return the SHA-256 of some bytes as 64 lowercase hex characters.

    Args:
        data: The bytes to hash.

    Returns:
        The hex digest.
    """
    return hashlib.sha256(data).hexdigest()


def snapshot_id(file_sha256: str) -> str:
    """ID of an immutable source snapshot: the same file bytes, the same ID.

    Args:
        file_sha256: SHA-256 of the file's bytes.

    Returns:
        A ``snap_`` ID.
    """
    return _stable_id("snapshot", _require_sha256(file_sha256, "file_sha256"))


def conversation_id(
    workspace_id: str, source_system: str, account_namespace: str, native_conversation_id: str
) -> str:
    """ID of a logical conversation, stable across every re-export.

    Args:
        workspace_id: The workspace the conversation belongs to.
        source_system: Where it came from, e.g. ``"chatgpt"``.
        account_namespace: The account label from settings (OD-03).
        native_conversation_id: The conversation ID inside the export.

    Returns:
        A ``conv_`` ID.

    Raises:
        ValueError: If any part is empty or malformed.
    """
    return _stable_id(
        "conversation",
        _require_native(workspace_id, "workspace_id"),
        _require_token(source_system, "source_system"),
        _require_slug(account_namespace, "account_namespace"),
        _require_native(native_conversation_id, "native_conversation_id"),
    )


def message_node_id(conversation: str, native_node_id: str) -> str:
    """ID of one node in a conversation's message tree.

    Native node IDs are only unique within their conversation, so the
    conversation ID is part of the key.

    Args:
        conversation: The ``conv_`` ID.
        native_node_id: The node's ID inside the export's ``mapping``.

    Returns:
        A ``node_`` ID.
    """
    return _stable_id(
        "message_node",
        _require_prefixed(conversation, "conversation"),
        _require_native(native_node_id, "native_node_id"),
    )


def message_revision_id(node: str, canonical_content_hash: str) -> str:
    """ID of one version of a message's content.

    If a later export shows the same node with different content, the hash
    changes and so does the revision ID. Unchanged content keeps its ID, so
    no work is redone.

    Args:
        node: The ``node_`` ID.
        canonical_content_hash: SHA-256 of the canonical content (NRM-001).

    Returns:
        A ``rev_`` ID.
    """
    return _stable_id(
        "message_revision",
        _require_prefixed(node, "message_node"),
        _require_sha256(canonical_content_hash, "canonical_content_hash"),
    )


def graph_edge_id(child: str, parent: str | None) -> str:
    """ID of a parent-to-child link in the message tree.

    Args:
        child: The child ``node_`` ID.
        parent: The parent ``node_`` ID, or None for a root.

    Returns:
        An ``edge_`` ID.
    """
    parent_part = "" if parent is None else _require_prefixed(parent, "message_node")
    return _stable_id("graph_edge", _require_prefixed(child, "message_node"), parent_part)


def media_asset_id(
    workspace_id: str,
    source_system: str,
    *,
    native_file_id: str | None = None,
    blob_sha256: str | None = None,
) -> str:
    """ID of a logical media asset (ADR-0004).

    Keyed by the export's file ID when there is one, otherwise by the bytes'
    hash. The two kinds of key are tagged differently, so a file ID can never
    be mistaken for a hash.

    Args:
        workspace_id: The workspace.
        source_system: e.g. ``"chatgpt"``.
        native_file_id: The export's file ID, if known.
        blob_sha256: SHA-256 of the bytes, used only without a file ID.

    Returns:
        An ``asset_`` ID.

    Raises:
        ValueError: If neither key is given.
    """
    if native_file_id is not None:
        key: tuple[str, str] = ("file", _require_native(native_file_id, "native_file_id"))
    elif blob_sha256 is not None:
        key = ("sha256", _require_sha256(blob_sha256, "blob_sha256"))
    else:
        raise ValueError("a media asset needs a native file ID or a blob hash")
    return _stable_id(
        "media_asset",
        _require_native(workspace_id, "workspace_id"),
        _require_token(source_system, "source_system"),
        *key,
    )


def asset_occurrence_id(revision: str, part_index: int, pointer: str) -> str:
    """ID of one place where a message refers to an asset.

    The same image used in three messages is one asset with three
    occurrences, each with its own ID.

    Args:
        revision: The ``rev_`` ID of the message revision.
        part_index: Position of the content part inside the message (0+).
        pointer: The pointer string exactly as the export wrote it.

    Returns:
        An ``occ_`` ID.
    """
    if part_index < 0:
        raise ValueError("part_index must be zero or positive")
    return _stable_id(
        "asset_occurrence",
        _require_prefixed(revision, "message_revision"),
        part_index,
        _require_native(pointer, "pointer"),
    )


def link_target_id(canonical_url: str) -> str:
    """ID of a link destination, shared by every mention of that URL.

    Args:
        canonical_url: The URL after canonicalisation (LNK-001).

    Returns:
        A ``link_`` ID.
    """
    return _stable_id("link_target", _require_native(canonical_url, "canonical_url"))


def link_occurrence_id(revision: str, start: int, end: int, origin: str) -> str:
    """ID of one mention of a URL at an exact place in a message.

    Args:
        revision: The ``rev_`` ID.
        start: Start offset in the canonical text (inclusive).
        end: End offset (exclusive).
        origin: Where it was found, e.g. ``"message_text"``.

    Returns:
        An ``lnkocc_`` ID.
    """
    _require_offsets(start, end)
    return _stable_id(
        "link_occurrence",
        _require_prefixed(revision, "message_revision"),
        start,
        end,
        _require_token(origin, "origin"),
    )


def youtube_video_id(video_id: str) -> str:
    """Validate and return a YouTube video ID, which is already globally unique.

    Args:
        video_id: The 11-character ID from the URL.

    Returns:
        The same ID, unchanged.

    Raises:
        ValueError: If it isn't 11 URL-safe characters.
    """
    if not _YOUTUBE_ID_RE.fullmatch(video_id):
        raise ValueError("YouTube video IDs are 11 characters of A-Z a-z 0-9 _ -")
    return video_id


def social_account_id(
    platform: str, *, stable_platform_id: str | None = None, handle: str | None = None
) -> str:
    """ID of a social account in the registry (SOC-002).

    Prefers the platform's own permanent account ID. Falls back to the
    handle, lower-cased and without a leading ``@``, because handles are
    case-insensitive on the supported platforms. The two key kinds are tagged,
    so an ID and a handle with the same text don't collide.

    Args:
        platform: e.g. ``"github"``.
        stable_platform_id: The platform's permanent ID, if known.
        handle: The account handle, used only without a stable ID.

    Returns:
        An ``acct_`` ID.

    Raises:
        ValueError: If neither key is given or the handle is empty.
    """
    _require_token(platform, "platform")
    if stable_platform_id is not None:
        key: tuple[str, str] = ("id", _require_native(stable_platform_id, "stable_platform_id"))
    elif handle is not None:
        cleaned = handle.strip().removeprefix("@").lower()
        key = ("handle", _require_native(cleaned, "handle"))
    else:
        raise ValueError("a social account needs a stable platform ID or a handle")
    return _stable_id("social_account", platform, *key)


def relationship_id(from_conversation: str, kind: str, to_conversation: str, detector: str) -> str:
    """ID of a proposed or accepted link between two conversations (ADR-0005).

    Direction matters: A ``continues`` B is a different relationship from B
    ``continues`` A.

    Args:
        from_conversation: The ``conv_`` ID the relationship starts from.
        kind: e.g. ``"continues"``, ``"forked_from"``, ``"related_to"``.
        to_conversation: The ``conv_`` ID it points to.
        detector: Which detector (and version) proposed it.

    Returns:
        A ``rel_`` ID.
    """
    return _stable_id(
        "relationship",
        _require_prefixed(from_conversation, "conversation"),
        _require_token(kind, "kind"),
        _require_prefixed(to_conversation, "conversation"),
        _require_native(detector, "detector"),
    )
