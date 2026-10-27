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

from sqlalchemy.orm import Session

from knowledge_engine.domain.enums import DeltaCategory, SourceSystem
from knowledge_engine.domain.ids import (
    conversation_id,
    graph_edge_id,
    message_node_id,
    message_revision_id,
)
from knowledge_engine.graph.conversation import ConversationGraph
from knowledge_engine.graph.nodes import canonical_json, canonical_node
from knowledge_engine.importer.records import (
    ConversationRow,
    GraphEdgeRow,
    MessageNodeRow,
    MessageRevisionRow,
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
    """

    conversation_id: str
    category: DeltaCategory
    messages: Counter[str] = field(default_factory=Counter)
    changed_revisions: list[str] = field(default_factory=list)
    warnings: Counter[str] = field(default_factory=Counter)


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

    delta = ConversationDelta(conv_key, DeltaCategory.NEW)
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
            for warning in canonical.warnings:
                delta.warnings[f"content_{warning.value}"] += 1
            revision_key = message_revision_id(node_key, canonical.canonical_content_hash)
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
        changed = changed_structure or bool(delta.changed_revisions)
        delta.category = DeltaCategory.REVISED if changed else DeltaCategory.UNCHANGED
    session.flush()
    return delta
