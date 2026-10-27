"""The message tree of one conversation, worked out once and shared by everyone.

A ChatGPT conversation is not a list of messages. It's a tree: every
message points at its parent, and when the user edits a question or asks
for a new answer, the old and new versions sit side by side as siblings.
``current_node`` marks the leaf the user last saw; walking up from it to the
root gives the *active path*, the version of the conversation the user
actually ended up with. The other branches are kept, never thrown away and
never spliced into the active path.

This module is pure: no files, no database. Give it a ``mapping`` and a
``current_node`` and it gives back the tree, the active path and stable
message numbers. Everything else (import, notes, the M3 evidence checks)
uses these answers instead of walking the tree itself, so "message 7"
means the same thing everywhere (docs/plans/M1_CONSOLIDATION.md §2.1).

Talking points:
    - "A chat is a tree, not a list. Edits and regenerated answers are
      branches, and I keep every branch."
    - "The version the user ended on is found by walking up from the last
      message they saw, not by sorting on timestamps."
    - "Children are rebuilt from parent links, because some exports leave
      the child lists out."
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class GraphNode:
    """One node of the tree, reduced to what the structure needs.

    Attributes:
        node_id: The mapping key, used exactly as exported.
        parent_id: The parent's node ID, or None for a root.
        children: Child node IDs, rebuilt from parent links.
        has_message: False for the empty root node exports start with.
        role: The author role (``user``, ``assistant``, ``system``, ``tool``)
            or None.
        create_time: The message's own timestamp, or None. Kept as given;
            never invented.
    """

    node_id: str
    parent_id: str | None
    children: tuple[str, ...]
    has_message: bool
    role: str | None
    create_time: float | None


class ConversationGraph:
    """The native message tree of one conversation.

    Build it with ``from_mapping``. All answers are computed once, at
    construction, and the object is read-only afterwards.
    """

    def __init__(
        self,
        nodes: Mapping[str, GraphNode],
        current_node: str | None,
        active_path: tuple[str, ...],
    ) -> None:
        """Store precomputed results. Use ``from_mapping`` instead.

        Args:
            nodes: Every node by ID.
            current_node: The exported ``current_node`` if it exists in
                ``nodes``, else None.
            active_path: Node IDs from the root down to ``current_node``.
        """
        self._nodes = dict(nodes)
        self._current_node = current_node
        self._active_path = active_path
        self._active_messages = tuple(n for n in active_path if self._nodes[n].has_message)
        self._numbers = {node_id: i for i, node_id in enumerate(self._active_messages, start=1)}

    @classmethod
    def from_mapping(
        cls, mapping: Mapping[str, Any], current_node: str | None
    ) -> ConversationGraph:
        """Build the graph from an export's ``mapping`` and ``current_node``.

        Args:
            mapping: Node ID -> ``{"parent": ..., "message": ..., "children": ...}``
                as exported. ``children`` is optional and ignored: parent links
                are the single source of truth, because the split export
                drops ``children`` and the two must never disagree silently.
            current_node: The exported current node ID, or None.

        Returns:
            The graph. Malformed entries (not an object) are skipped here;
            reporting them is the integrity checker's job (NRM-002).
        """
        raw = {key: value for key, value in mapping.items() if isinstance(value, Mapping)}
        kids: dict[str, list[str]] = {key: [] for key in raw}
        for key, value in raw.items():
            parent = value.get("parent")
            if isinstance(parent, str) and parent in kids and parent != key:
                kids[parent].append(key)

        nodes: dict[str, GraphNode] = {}
        for key, value in raw.items():
            message = value.get("message")
            message = message if isinstance(message, Mapping) else None
            parent = value.get("parent")
            nodes[key] = GraphNode(
                node_id=key,
                parent_id=parent if isinstance(parent, str) else None,
                children=tuple(sorted(kids[key], key=lambda k: _sort_key(raw[k], k))),
                has_message=message is not None,
                role=_role(message),
                create_time=_create_time(message),
            )

        current = current_node if current_node in nodes else None
        return cls(nodes, current, _path_to_root(nodes, current))

    @property
    def nodes(self) -> Mapping[str, GraphNode]:
        """Every node, by node ID."""
        return self._nodes

    @property
    def current_node(self) -> str | None:
        """The exported current node, or None if missing or unknown."""
        return self._current_node

    @property
    def active_path(self) -> tuple[str, ...]:
        """Node IDs from the root down to ``current_node`` (empty without one)."""
        return self._active_path

    @property
    def active_messages(self) -> tuple[str, ...]:
        """The active path without empty (message-less) nodes."""
        return self._active_messages

    def message_number(self, node_id: str) -> int | None:
        """Return a node's 1-based position among the active path's messages.

        Args:
            node_id: A node ID.

        Returns:
            The number, or None if the node is off the active path or has no
            message. Numbers depend only on the tree, never on timestamps.
        """
        return self._numbers.get(node_id)

    def children(self, node_id: str) -> tuple[str, ...]:
        """Return a node's children (empty for an unknown node).

        Args:
            node_id: A node ID.

        Returns:
            Child IDs, ordered by timestamp where present, then by ID.
        """
        node = self._nodes.get(node_id)
        return node.children if node else ()


def _path_to_root(nodes: Mapping[str, GraphNode], leaf: str | None) -> tuple[str, ...]:
    path: list[str] = []
    seen: set[str] = set()
    node_id = leaf
    # Stops at a root, a dangling parent, or a cycle. A cycle can't loop
    # forever, and the path keeps what was reached before it.
    while node_id is not None and node_id in nodes and node_id not in seen:
        seen.add(node_id)
        path.append(node_id)
        node_id = nodes[node_id].parent_id
    return tuple(reversed(path))


def _role(message: Mapping[str, Any] | None) -> str | None:
    if message is None:
        return None
    author = message.get("author")
    role = author.get("role") if isinstance(author, Mapping) else None
    return role if isinstance(role, str) else None


def _create_time(message: Mapping[str, Any] | None) -> float | None:
    if message is None:
        return None
    value = message.get("create_time")
    # bool is an int in Python; a true/false timestamp is not a time.
    if isinstance(value, int | float) and not isinstance(value, bool):
        return float(value)
    return None


def _sort_key(node: Mapping[str, Any], node_id: str) -> tuple[int, float, str]:
    # Siblings with timestamps come first in time order; siblings without
    # one follow, by ID. Order never invents a time that wasn't exported.
    message = node.get("message")
    created = _create_time(message if isinstance(message, Mapping) else None)
    return (0, created, node_id) if created is not None else (1, 0.0, node_id)
