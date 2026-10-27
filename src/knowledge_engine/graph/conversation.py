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

Branch points (REL-001): a node with more than one child is a fork. If
the children are all user messages, the user edited their question; if
they're all assistant messages, the answer was regenerated; anything else
is ``other``. Integrity problems (NRM-002) such as a missing parent, a
cycle or a node that can't be reached from the root are listed in
``issues``. They are reported, never "fixed": no node is dropped.

Talking points:
    - "A chat is a tree, not a list. Edits and regenerated answers are
      branches, and I keep every branch."
    - "The version the user ended on is found by walking up from the last
      message they saw, not by sorting on timestamps."
    - "Children are rebuilt from parent links, because some exports leave
      the child lists out."
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from knowledge_engine.domain.enums import BranchKind

# Bump when the branch-kind rule changes, so stored branch points can be
# recomputed (DATA_MODEL_AND_CONTRACTS: branch_points.classifier version).
BRANCH_CLASSIFIER_VERSION = "rel-001-v1"


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


@dataclass(frozen=True)
class BranchPoint:
    """A node with several children: where the conversation forked.

    Attributes:
        parent_id: The node that has several children.
        children: The children, in ``GraphNode.children`` order.
        kind: ``edit`` (all user), ``regeneration`` (all assistant) or ``other``.
        active_child: The child on the active path, or None.
    """

    parent_id: str
    children: tuple[str, ...]
    kind: BranchKind
    active_child: str | None


class IssueCode(StrEnum):
    """Kinds of structural problem the integrity check reports (NRM-002)."""

    INVALID_NODE = "invalid_node"  # mapping value isn't an object
    MISSING_PARENT = "missing_parent"  # parent ID not in the mapping
    SELF_PARENT = "self_parent"  # a node is its own parent
    CYCLE = "cycle"  # parent links loop
    UNREACHABLE = "unreachable"  # can't be reached from any root
    MULTIPLE_ROOTS = "multiple_roots"  # more than one node without a parent
    ID_MISMATCH = "id_mismatch"  # node's own "id" differs from its mapping key
    DUPLICATE_MESSAGE_ID = "duplicate_message_id"  # two nodes carry one message ID
    CHILDREN_MISMATCH = "children_mismatch"  # exported children list disagrees
    CURRENT_NODE_MISSING = "current_node_missing"  # current_node absent or unknown


@dataclass(frozen=True)
class GraphIssue:
    """One structural problem, by code and node. Never contains message text.

    Attributes:
        code: What is wrong.
        node_id: The node concerned, or None for a whole-graph issue.
    """

    code: IssueCode
    node_id: str | None = None


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
        issues: tuple[GraphIssue, ...] = (),
    ) -> None:
        """Store precomputed results. Use ``from_mapping`` instead.

        Args:
            nodes: Every node by ID.
            current_node: The exported ``current_node`` if it exists in
                ``nodes``, else None.
            active_path: Node IDs from the root down to ``current_node``.
            issues: Structural problems found while building.
        """
        self._nodes = dict(nodes)
        self._current_node = current_node
        self._active_path = active_path
        self._active_messages = tuple(n for n in active_path if self._nodes[n].has_message)
        self._numbers = {node_id: i for i, node_id in enumerate(self._active_messages, start=1)}
        self._issues = issues
        on_path = set(active_path)
        self._branch_points = tuple(
            BranchPoint(
                node.node_id,
                node.children,
                _branch_kind([self._nodes[c].role for c in node.children]),
                next((c for c in node.children if c in on_path), None),
            )
            for node in self._nodes.values()
            if len(node.children) > 1
        )

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
            The graph. Malformed entries (not an object) are left out of
            ``nodes`` and reported in ``issues``.
        """
        raw = {key: value for key, value in mapping.items() if isinstance(value, Mapping)}
        issues = [
            GraphIssue(IssueCode.INVALID_NODE, key)
            for key, value in mapping.items()
            if not isinstance(value, Mapping)
        ]
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
        if current is None:
            issues.append(GraphIssue(IssueCode.CURRENT_NODE_MISSING))
        issues += _check(raw, nodes)
        issues.sort(key=lambda i: (i.code.value, i.node_id or ""))
        return cls(nodes, current, _path_to_root(nodes, current), tuple(issues))

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

    @property
    def branch_points(self) -> tuple[BranchPoint, ...]:
        """Every fork in the tree, in node order."""
        return self._branch_points

    @property
    def issues(self) -> tuple[GraphIssue, ...]:
        """Structural problems, sorted by code then node. Empty for a clean tree."""
        return self._issues

    def alternate_paths(self) -> Iterator[tuple[str, ...]]:
        """Yield every root-to-leaf path except the active one.

        In a damaged tree a path starts where its parent chain stops (a
        missing parent or a loop); ``issues`` names those nodes.

        Each path is a whole, separate version of the conversation. Paths are
        never merged or spliced into the active path.

        Yields:
            Node ID tuples from a root down to a leaf, in node order.
        """
        for node in self._nodes.values():
            if not node.children and node.node_id != self._current_node:
                path = _path_to_root(self._nodes, node.node_id)
                if path:
                    yield path

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


def _branch_kind(roles: list[str | None]) -> BranchKind:
    if roles and all(role == "user" for role in roles):
        return BranchKind.EDIT
    if roles and all(role == "assistant" for role in roles):
        return BranchKind.REGENERATION
    return BranchKind.OTHER


def _check(
    raw: Mapping[str, Mapping[str, Any]], nodes: Mapping[str, GraphNode]
) -> list[GraphIssue]:
    issues: list[GraphIssue] = []
    roots = [n.node_id for n in nodes.values() if n.parent_id is None]
    if len(roots) > 1:
        issues.append(GraphIssue(IssueCode.MULTIPLE_ROOTS))
    message_ids: dict[str, str] = {}
    for key, value in raw.items():
        node = nodes[key]
        if node.parent_id == key:
            issues.append(GraphIssue(IssueCode.SELF_PARENT, key))
        elif node.parent_id is not None and node.parent_id not in nodes:
            issues.append(GraphIssue(IssueCode.MISSING_PARENT, key))
        own_id = value.get("id")
        if own_id is not None and own_id != key:
            issues.append(GraphIssue(IssueCode.ID_MISMATCH, key))
        message = value.get("message")
        message_id = message.get("id") if isinstance(message, Mapping) else None
        if isinstance(message_id, str):
            if message_id in message_ids:
                issues.append(GraphIssue(IssueCode.DUPLICATE_MESSAGE_ID, key))
            else:
                message_ids[message_id] = key
        listed = value.get("children")
        if isinstance(listed, list) and set(listed) != set(node.children):
            issues.append(GraphIssue(IssueCode.CHILDREN_MISMATCH, key))
    # Reachability from the roots. Anything not reached is either on a
    # cycle (its parent chain never ends) or hangs below one.
    reached: set[str] = set()
    stack = list(roots)
    while stack:
        node_id = stack.pop()
        if node_id not in reached:
            reached.add(node_id)
            stack.extend(nodes[node_id].children)
    for node_id in nodes:
        if node_id in reached or nodes[node_id].parent_id == node_id:
            continue
        if node_id in _path_to_root_cycle(nodes, node_id):
            issues.append(GraphIssue(IssueCode.CYCLE, node_id))
        elif nodes[node_id].parent_id in nodes:
            issues.append(GraphIssue(IssueCode.UNREACHABLE, node_id))
    return issues


def _path_to_root_cycle(nodes: Mapping[str, GraphNode], start: str) -> set[str]:
    # The nodes of the loop that the parent chain from ``start`` runs into,
    # or an empty set if the chain ends at a root or a missing parent.
    order: list[str] = []
    node_id: str | None = start
    while node_id is not None and node_id in nodes and node_id not in order:
        order.append(node_id)
        node_id = nodes[node_id].parent_id
    if node_id is not None and node_id in order:
        return set(order[order.index(node_id) :])
    return set()


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
