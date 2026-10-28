"""Reconcile what the source holds with what the import stored (ING-007).

The import counts the source twice, independently: once straight from the
raw JSON (how many mapping nodes, messages and image pointers the files
contain) and once from what was actually written. If the two disagree,
something was dropped, and the report says so (``reconciled: false`` and an
``integrity_mismatch`` warning) instead of leaving a silent hole.

It also gives a fidelity summary: which message content types appeared,
how many content parts are kept only as raw JSON because their shape isn't
understood yet, and how many media files no message points at.

Talking points:
    - "The importer counts the source and counts what it stored. If those
      don't match, the report says so: nothing goes missing quietly."
    - "Things the parser doesn't understand yet are kept as raw JSON and
      counted, so they're visible, not lost."
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from knowledge_engine.importer.delta import ConversationDelta

# The pairs that must agree: (source count, stored count).
_PAIRS = (
    ("mapping_nodes", "nodes"),
    ("messages", "messages"),
    ("asset_pointers", "asset_pointers"),
)


def source_counts(native: Mapping[str, Any]) -> Counter[str]:
    """Count a conversation's contents straight from its raw JSON.

    Deliberately independent of ``graph/``: it's the second opinion.

    Args:
        native: The native conversation object.

    Returns:
        ``mapping_nodes``, ``messages`` and ``asset_pointers`` counts.
    """
    counts: Counter[str] = Counter()
    mapping = native.get("mapping")
    if not isinstance(mapping, Mapping):
        return counts
    counts["mapping_nodes"] = len(mapping)
    for node in mapping.values():
        message = node.get("message") if isinstance(node, Mapping) else None
        if not isinstance(message, Mapping):
            continue
        counts["messages"] += 1
        content = message.get("content")
        parts = content.get("parts") if isinstance(content, Mapping) else None
        if isinstance(parts, list):
            counts["asset_pointers"] += sum(
                1
                for part in parts
                if isinstance(part, Mapping)
                and isinstance(part.get("asset_pointer"), str)
                and part["asset_pointer"]
            )
    return counts


@dataclass
class IntegrityTally:
    """Running totals for one import.

    Attributes:
        conversations: Outcome -> count: ``imported``, ``failed``,
            ``candidate`` and ``duplicate_in_source``. Every conversation
            read lands in exactly one.
        conversations_read: Conversations the source yielded.
        source: Counts taken from the raw JSON of imported conversations.
        stored: The same counts, taken from what was written.
        content_types: Message content type -> count.
        unparsed_parts: Parts kept only as raw JSON.
        attachments: Attachment occurrences (no raw-side count: they live in
            metadata, which ``source_counts`` doesn't interpret).
    """

    conversations: Counter[str] = field(default_factory=Counter)
    conversations_read: int = 0
    source: Counter[str] = field(default_factory=Counter)
    stored: Counter[str] = field(default_factory=Counter)
    content_types: Counter[str] = field(default_factory=Counter)
    unparsed_parts: int = 0
    attachments: int = 0

    def add(self, native: Mapping[str, Any], delta: ConversationDelta) -> None:
        """Add one imported conversation to both sides.

        Args:
            native: Its raw JSON.
            delta: What the import wrote for it.
        """
        self.conversations["imported"] += 1
        self.source.update(source_counts(native))
        self.stored["nodes"] += delta.nodes
        self.stored["messages"] += sum(
            count for category, count in delta.messages.items() if category != "not_seen"
        )
        attachments = sum(1 for _, p in delta.pointers if p.content_type == "attachment")
        self.stored["asset_pointers"] += len(delta.pointers) - attachments
        self.attachments += attachments
        self.content_types.update(delta.content_types)
        self.unparsed_parts += delta.unparsed_parts

    def mismatches(self) -> list[str]:
        """Return the names of the counts that don't agree, sorted."""
        found = [name for name, stored in _PAIRS if self.source[name] != self.stored[stored]]
        if sum(self.conversations.values()) != self.conversations_read:
            found.append("conversations")
        return sorted(found)

    def to_dict(self, *, media_listed: int, media_referenced: int) -> dict[str, Any]:
        """Return the reconciliation as a JSON-ready dict.

        Args:
            media_listed: Media files the adapter found.
            media_referenced: How many of them some pointer names.

        Returns:
            Counts only: no names, paths or text.
        """
        return {
            "reconciled": not self.mismatches(),
            "mismatches": self.mismatches(),
            "conversations": {
                "read": self.conversations_read,
                **dict(sorted(self.conversations.items())),
            },
            "source": {name: self.source[name] for name, _ in _PAIRS},
            "stored": {stored: self.stored[stored] for _, stored in _PAIRS},
            "attachments": self.attachments,
            "content_types": dict(sorted(self.content_types.items())),
            "unparsed_parts": self.unparsed_parts,
            "media_files": {
                "listed": media_listed,
                "referenced": media_referenced,
                "unreferenced": media_listed - media_referenced,
            },
        }
