"""Write one conversation's records and work out what changed (IMP-002/IMP-003).

For each conversation in an export, this module computes its logical keys
(ADR-0003), looks up what's already stored, and inserts only what is new:
a node never seen, a content revision never seen, an edge never seen.
Existing rows are never overwritten; the "last seen" bookkeeping is the only
thing that moves. The answer is a ``ConversationDelta`` saying whether the
conversation and each message was new, unchanged or revised.

Talking points:
    - "Insert only what's new, never overwrite: that's what makes importing
      the same export twice a no-op."
    - "Each message is compared by its content fingerprint, so 'changed'
      means the words changed, not the metadata."
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from knowledge_engine.domain.enums import DeltaCategory, SourceSystem
from knowledge_engine.domain.ids import (
    conversation_id,
    graph_edge_id,
    message_node_id,
    message_revision_id,
    sha256_hex,
)
from knowledge_engine.graph.conversation import ConversationGraph
from knowledge_engine.graph.nodes import (
    AssetPointer,
    PartKind,
    attachment_pointers,
    canonical_json,
    canonical_node,
)
from knowledge_engine.importer.records import (
    ConversationRow,
    GraphEdgeRow,
    MessageNodeRow,
    MessageRevisionRow,
    RevisionObservationRow,
)


class MissingNativeIdError(ValueError):
    """The conversation has no native ID, so it can't be keyed safely."""


@dataclass
class ConversationDelta:
    """What one conversation's import found.

    Attributes:
        conversation_id: The ``conv_`` ID.
        category: ``new``, ``unchanged`` or ``revised``.
        messages: Message delta category -> count.
        changed_revisions: New revision IDs (new or revised messages).
        warnings: Warning code -> count.
        new_branches: Forks that appeared in this import (a node gaining a
            second child, e.g. a regenerated answer).
        raw_observations: New raw forms of existing or new revisions.
        pointers: ``(revision_id, pointer)`` for every asset pointer and
            attachment in the conversation's current revisions, for the
            media step.
        nodes: Graph nodes written or confirmed (for ING-007's reconciliation).
        content_types: Message content type -> count.
        unparsed_parts: Content parts kept only as raw JSON because their
            shape isn't understood yet. Kept, never dropped, but counted.
    """

    conversation_id: str
    category: DeltaCategory
    messages: Counter[str] = field(default_factory=Counter)
    changed_revisions: list[str] = field(default_factory=list)
    warnings: Counter[str] = field(default_factory=Counter)
    new_branches: int = 0
    raw_observations: int = 0
    pointers: list[tuple[str, AssetPointer]] = field(default_factory=list)
    nodes: int = 0
    content_types: Counter[str] = field(default_factory=Counter)
    unparsed_parts: int = 0


def native_conversation_id(native: Mapping[str, Any]) -> str | None:
    """Return the export's own ID for a conversation, or None.

    Args:
        native: The native conversation object.

    Returns:
        ``conversation_id`` if present, else ``id``, else None.
    """
    for key in ("conversation_id", "id"):
        value = native.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def apply_conversation(
    session: Session,
    native: Mapping[str, Any],
    *,
    workspace_id: str,
    account_namespace: str,
    import_id: str,
    snapshot_id: str,
) -> ConversationDelta:
    """Insert what's new for one conversation and report the delta.

    Args:
        session: The batch's write session.
        native: The native conversation object.
        workspace_id: Target workspace.
        account_namespace: The raw root's account label.
        import_id: The running batch.
        snapshot_id: Snapshot of the file the conversation came from.

    Returns:
        The delta.

    Raises:
        MissingNativeIdError: If the conversation has no native ID.
    """
    native_id = native_conversation_id(native)
    if native_id is None:
        raise MissingNativeIdError("conversation has no native ID")
    conv_key = conversation_id(
        workspace_id, SourceSystem.CHATGPT.value, account_namespace, native_id
    )
    mapping: Mapping[str, Any] = native.get("mapping") or {}
    current = native.get("current_node")
    graph = ConversationGraph.from_mapping(mapping, current if isinstance(current, str) else None)

    conversation = session.get(ConversationRow, conv_key)
    is_new_conversation = conversation is None
    title = native.get("title")
    created = native.get("create_time")
    if conversation is None:
        conversation = ConversationRow(
            conversation_id=conv_key,
            workspace_id=workspace_id,
            source_system=SourceSystem.CHATGPT.value,
            account_namespace=account_namespace,
            native_conversation_id=native_id,
            first_import_id=import_id,
            last_import_id=import_id,
        )
        session.add(conversation)
    conversation.title = title if isinstance(title, str) else None
    conversation.create_time = (
        float(created)
        if isinstance(created, int | float) and not isinstance(created, bool)
        else None
    )
    conversation.current_node = graph.current_node
    conversation.presence = "present"
    conversation.last_import_id = import_id

    delta = ConversationDelta(conv_key, DeltaCategory.NEW, nodes=len(graph.nodes))
    for issue in graph.issues:
        delta.warnings[f"graph_{issue.code.value}"] += 1

    changed_structure = False
    for node_id in graph.nodes:
        node_key = message_node_id(conv_key, node_id)
        node_row = session.get(MessageNodeRow, node_key)
        node_is_new = node_row is None
        if node_row is None:
            node_row = MessageNodeRow(
                node_key=node_key,
                conversation_id=conv_key,
                native_node_id=node_id,
                first_import_id=import_id,
                last_import_id=import_id,
            )
            session.add(node_row)
            changed_structure = True
        node_row.presence = "present"
        node_row.last_import_id = import_id

        canonical = canonical_node(node_id, mapping[node_id])
        if canonical is not None:
            delta.content_types[canonical.content_type or "none"] += 1
            delta.unparsed_parts += sum(1 for p in canonical.parts if p.kind is PartKind.OTHER)
            for warning in canonical.warnings:
                delta.warnings[f"content_{warning.value}"] += 1
            revision_key = message_revision_id(node_key, canonical.canonical_content_hash)
            delta.pointers.extend((revision_key, p) for p in canonical.asset_pointers)
            delta.pointers.extend(
                (revision_key, p)
                for p in attachment_pointers(
                    mapping[node_id]["message"],
                    (p.file_id for p in canonical.asset_pointers if p.file_id),
                )
            )
            if session.get(MessageRevisionRow, revision_key) is None:
                message = mapping[node_id]["message"]
                session.add(
                    MessageRevisionRow(
                        revision_id=revision_key,
                        node_key=node_key,
                        canonical_content_hash=canonical.canonical_content_hash,
                        raw_payload_hash=canonical.raw_payload_hash,
                        role=canonical.role,
                        content_type=canonical.content_type,
                        create_time=canonical.create_time,
                        content_json=canonical_json(message.get("content")),
                        first_snapshot_id=snapshot_id,
                        first_import_id=import_id,
                    )
                )
                delta.changed_revisions.append(revision_key)
                delta.messages[
                    DeltaCategory.NEW.value if node_is_new else DeltaCategory.REVISED.value
                ] += 1
            else:
                delta.messages[DeltaCategory.UNCHANGED.value] += 1
            observation_key = _observation_id(revision_key, canonical.raw_payload_hash)
            if session.get(RevisionObservationRow, observation_key) is None:
                session.add(
                    RevisionObservationRow(
                        observation_id=observation_key,
                        revision_id=revision_key,
                        raw_payload_hash=canonical.raw_payload_hash,
                        first_snapshot_id=snapshot_id,
                        first_import_id=import_id,
                    )
                )
                delta.raw_observations += 1

    # Forks are counted before new edges are written: a fork is new if its
    # parent had fewer than two stored children until now.
    session.flush()
    for point in graph.branch_points:
        parent_key = message_node_id(conv_key, point.parent_id)
        stored = session.scalar(
            select(func.count())
            .select_from(GraphEdgeRow)
            .where(GraphEdgeRow.parent_node_key == parent_key)
        )
        if (stored or 0) < 2:
            delta.new_branches += 1

    for node in graph.nodes.values():
        if node.parent_id is None or node.parent_id not in graph.nodes:
            continue  # dangling parents are reported as graph issues
        child_key = message_node_id(conv_key, node.node_id)
        parent_key = message_node_id(conv_key, node.parent_id)
        edge_key = graph_edge_id(child_key, parent_key)
        if session.get(GraphEdgeRow, edge_key) is None:
            session.add(
                GraphEdgeRow(
                    edge_id=edge_key,
                    conversation_id=conv_key,
                    child_node_key=child_key,
                    parent_node_key=parent_key,
                    first_import_id=import_id,
                )
            )
            changed_structure = True

    if not is_new_conversation:
        # Nodes stored before but absent now: unknown, never deleted.
        stored_nodes = session.scalars(
            select(MessageNodeRow).where(
                MessageNodeRow.conversation_id == conv_key,
                MessageNodeRow.presence == "present",
            )
        ).all()
        for row in stored_nodes:
            if row.native_node_id not in graph.nodes:
                row.presence = "not_seen"
                if _has_revision(session, row.node_key):
                    delta.messages[DeltaCategory.NOT_SEEN.value] += 1
                changed_structure = True
        changed = changed_structure or bool(delta.changed_revisions)
        delta.category = DeltaCategory.REVISED if changed else DeltaCategory.UNCHANGED
    session.flush()
    return delta


def mark_not_seen(
    session: Session, *, workspace_id: str, account_namespace: str, import_id: str
) -> tuple[int, int]:
    """Mark conversations this import didn't see as ``not_seen``.

    A conversation missing from a new export is *unknown*, never deleted
    (owner requirement C). Its rows all stay; only the presence flag moves,
    and it moves back to ``present`` if a later export has it again.

    Args:
        session: A write session.
        workspace_id: The workspace.
        account_namespace: Only this account's conversations are affected.
        import_id: The finished import.

    Returns:
        ``(conversations, messages)`` newly marked ``not_seen``.
    """
    missing = session.scalars(
        select(ConversationRow).where(
            ConversationRow.workspace_id == workspace_id,
            ConversationRow.source_system == SourceSystem.CHATGPT.value,
            ConversationRow.account_namespace == account_namespace,
            ConversationRow.presence == "present",
            ConversationRow.last_import_id != import_id,
        )
    ).all()
    messages = 0
    for conversation in missing:
        conversation.presence = "not_seen"
        nodes = session.scalars(
            select(MessageNodeRow).where(
                MessageNodeRow.conversation_id == conversation.conversation_id,
                MessageNodeRow.presence == "present",
            )
        ).all()
        for node in nodes:
            node.presence = "not_seen"
            if _has_revision(session, node.node_key):
                messages += 1
    session.flush()
    return len(missing), messages


def _has_revision(session: Session, node_key: str) -> bool:
    return (
        session.scalar(
            select(func.count())
            .select_from(MessageRevisionRow)
            .where(MessageRevisionRow.node_key == node_key)
        )
        or 0
    ) > 0


def _observation_id(revision_id: str, raw_payload_hash: str) -> str:
    return sha256_hex(f"{revision_id}:{raw_payload_hash}".encode())
