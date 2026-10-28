"""Source transcript notes and inspect views, built from stored records (BRW-001).

A transcript note shows one conversation exactly as it was imported, with
no AI involved:

* the **active path** (the version the chat app shows), message by message;
* every **alternate branch** (an edited question, a regenerated answer),
  labelled with what kind of fork it is and where it leaves the active path;
* each message's images as embeds or missing markers (MED-004);
* a **block anchor** on every message, derived from its logical message ID,
  so other notes can link to an exact message.

Every message node appears exactly once. Nothing is merged: an alternate
branch is shown as its own sequence, never spliced into the active path.

The inspect views give the same structure as counts only, so they're safe
to run on private data (REV-009).

Talking points:
    - "The transcript is rebuilt from the database, not from the export, so
      it shows what the archive actually holds."
    - "Every message has an anchor made from its permanent ID, so a link to
      a message keeps working across re-imports."
    - "Branches are labelled and kept separate; nothing is stitched together."
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from knowledge_engine.graph.conversation import ConversationGraph
from knowledge_engine.graph.nodes import CanonicalNode, canonical_node
from knowledge_engine.rendering.markdown import (
    Block,
    DocumentModel,
    Heading,
    Paragraph,
    PropertyValue,
    block_anchor,
    render_note,
    safe_filename,
    safe_relative_path,
    write_note,
)
from knowledge_engine.rendering.media import (
    MediaRef,
    blob_sources,
    check_embeds,
    export_attachments,
    load_media_refs,
    media_block,
    media_counts,
)

TRANSCRIPT_VERSION = "brw-001-v1"
SOURCES_DIR = "Sources"


@dataclass(frozen=True)
class StoredConversation:
    """One conversation as the archive holds it.

    Attributes:
        conversation_id: The logical ``conv_`` ID.
        native_conversation_id: The export's own ID.
        title: The latest title seen (private; shown only in notes).
        create_time: As exported, or None.
        presence: ``present`` or ``not_seen``.
        graph: The message tree, rebuilt from stored nodes and edges.
        node_keys: Native node ID -> logical ``node_`` ID.
        revisions: Native node ID -> the latest revision ID, for nodes with
            a message.
        messages: Native node ID -> the canonical message.
        media: Revision ID -> its media uses.
    """

    conversation_id: str
    native_conversation_id: str
    title: str | None
    create_time: float | None
    presence: str
    graph: ConversationGraph
    node_keys: Mapping[str, str]
    revisions: Mapping[str, str]
    messages: Mapping[str, CanonicalNode]
    media: Mapping[str, list[MediaRef]]


def find_conversation(session: Session, ref: str) -> str | None:
    """Return the logical ID for a ``conv_`` ID or a native conversation ID.

    Args:
        session: A read session.
        ref: Either kind of ID.

    Returns:
        The ``conv_`` ID, or None if nothing matches exactly one conversation.
    """
    from knowledge_engine.importer.records import ConversationRow

    if session.get(ConversationRow, ref) is not None:
        return ref
    matches = session.scalars(
        select(ConversationRow.conversation_id).where(ConversationRow.native_conversation_id == ref)
    ).all()
    return matches[0] if len(matches) == 1 else None


def load_conversation(session: Session, conversation_id: str) -> StoredConversation:
    """Rebuild one conversation from stored records.

    A node with several revisions (its content changed in a later export)
    shows its newest; older revisions stay in the database.

    Args:
        session: A read session.
        conversation_id: The ``conv_`` ID.

    Returns:
        The stored conversation.

    Raises:
        KeyError: If there is no such conversation.
    """
    from knowledge_engine.importer.records import (
        ConversationRow,
        GraphEdgeRow,
        MessageNodeRow,
        MessageRevisionRow,
    )

    row = session.get(ConversationRow, conversation_id)
    if row is None:
        raise KeyError("no such conversation")
    nodes = session.scalars(
        select(MessageNodeRow).where(MessageNodeRow.conversation_id == conversation_id)
    ).all()
    native_of = {n.node_key: n.native_node_id for n in nodes}
    parents: dict[str, str | None] = {n.native_node_id: None for n in nodes}
    for edge in session.scalars(
        select(GraphEdgeRow).where(GraphEdgeRow.conversation_id == conversation_id)
    ):
        if edge.parent_node_key in native_of:
            parents[native_of[edge.child_node_key]] = native_of[edge.parent_node_key]
    latest: dict[str, Any] = {}
    for revision in session.scalars(
        select(MessageRevisionRow)
        .where(MessageRevisionRow.node_key.in_(list(native_of)))
        .order_by(MessageRevisionRow.created_at, MessageRevisionRow.revision_id)
    ):
        latest[native_of[revision.node_key]] = revision  # later rows win

    mapping: dict[str, dict[str, Any]] = {}
    for native_id, parent in parents.items():
        current = latest.get(native_id)
        message = None
        if current is not None:
            message = {
                "id": native_id,
                "author": {"role": current.role},
                "content": json.loads(current.content_json),
                "create_time": current.create_time,
            }
        mapping[native_id] = {"id": native_id, "parent": parent, "message": message}
    graph = ConversationGraph.from_mapping(mapping, row.current_node)
    messages = {
        native_id: node
        for native_id in mapping
        if (node := canonical_node(native_id, mapping[native_id])) is not None
    }
    revisions = {native_id: rev.revision_id for native_id, rev in latest.items()}
    return StoredConversation(
        conversation_id=row.conversation_id,
        native_conversation_id=row.native_conversation_id,
        title=row.title,
        create_time=row.create_time,
        presence=row.presence,
        graph=graph,
        node_keys={native: key for key, native in native_of.items()},
        revisions=revisions,
        messages=messages,
        media=load_media_refs(session, revisions.values()),
    )


def message_anchor(node_key: str) -> str:
    """Return the block anchor for a logical message ID (``node_x`` -> ``node-x``)."""
    return block_anchor(node_key.replace("_", "-", 1))


def node_key_for_anchor(anchor: str) -> str:
    """Return the logical message ID an anchor stands for."""
    return anchor.replace("-", "_", 1)


def transcript_model(conversation: StoredConversation) -> DocumentModel:
    """Build the transcript note for one conversation.

    Args:
        conversation: From ``load_conversation``.

    Returns:
        The note model. Every message node appears exactly once.
    """
    graph = conversation.graph
    rendered: set[str] = set()
    blocks: list[Block] = [Heading("Active path", 2)]
    for native_id in graph.active_messages:
        blocks += _message_blocks(conversation, native_id, graph.message_number(native_id))
        rendered.add(native_id)

    kinds = {point.parent_id: point.kind.value for point in graph.branch_points}
    alternates: list[Block] = []
    for path in sorted(graph.alternate_paths()):
        fresh = [n for n in path if n not in rendered and n in conversation.messages]
        if not fresh:
            continue
        start = path.index(fresh[0])
        parent = path[start - 1] if start > 0 else None
        heading, where = _branch_label(conversation, parent, kinds)
        alternates += [Heading(heading, 3), Paragraph(where, trusted=True)]
        for native_id in path[start:]:
            if native_id in conversation.messages and native_id not in rendered:
                alternates += _message_blocks(conversation, native_id, None)
                rendered.add(native_id)
    if alternates:
        blocks += [Heading("Alternate branches", 2), *alternates]

    # Anything a damaged tree left off every path (e.g. inside a loop).
    leftover = sorted(n for n in conversation.messages if n not in rendered)
    if leftover:
        blocks.append(Heading("Messages outside the tree", 2))
        for native_id in leftover:
            blocks += _message_blocks(conversation, native_id, None)

    properties: dict[str, PropertyValue] = {
        "ke_type": "source_transcript",
        "conversation_id": conversation.conversation_id,
        "native_conversation_id": conversation.native_conversation_id,
        "presence": conversation.presence,
        "messages": len(conversation.messages),
        "branch_points": len(graph.branch_points),
        "generator": TRANSCRIPT_VERSION,
    }
    if conversation.create_time is not None:
        properties["created"] = datetime.fromtimestamp(conversation.create_time, UTC)
    return DocumentModel(
        title=conversation.title or "Untitled conversation",
        properties=properties,
        blocks=tuple(blocks),
    )


def inspect_summary(conversation: StoredConversation) -> dict[str, Any]:
    """Return a conversation's structure as counts only (no text, no titles).

    Args:
        conversation: From ``load_conversation``.

    Returns:
        IDs, counts, branch kinds, media states and graph issues.
    """
    graph = conversation.graph
    branch_kinds: dict[str, int] = {}
    for point in graph.branch_points:
        branch_kinds[point.kind.value] = branch_kinds.get(point.kind.value, 0) + 1
    return {
        "conversation_id": conversation.conversation_id,
        "native_conversation_id": conversation.native_conversation_id,
        "presence": conversation.presence,
        "nodes": len(graph.nodes),
        "messages": len(conversation.messages),
        "active_path_messages": len(graph.active_messages),
        "branch_points": dict(sorted(branch_kinds.items())),
        "alternate_paths": sum(1 for _ in graph.alternate_paths()),
        "roles": _tally(m.role or "none" for m in conversation.messages.values()),
        "content_types": _tally(m.content_type or "none" for m in conversation.messages.values()),
        # First 8 characters of each active-path message ID (REV-009): enough
        # to compare with the export by eye, never message content.
        "active_path_ids": [native_id[:8] for native_id in graph.active_messages],
        "media": media_counts(conversation.media),
        "graph_issues": sorted({issue.code.value for issue in graph.issues}),
    }


def _tally(values: Iterable[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items()))


def write_transcript(
    session: Session, conversation: StoredConversation, vault_root: Path, store_root: Path
) -> tuple[PurePosixPath, list[str]]:
    """Write a transcript note and its images into a vault, then check its links.

    Args:
        session: A read session (to find image bytes).
        conversation: From ``load_conversation``.
        vault_root: The vault folder.
        store_root: The workspace's content-addressed store.

    Returns:
        The note's path inside the vault, and any broken embeds (empty when
        every image link resolves).
    """
    text = render_note(transcript_model(conversation))
    export_attachments(
        [ref for uses in conversation.media.values() for ref in uses],
        vault_root,
        blob_sources(session, store_root),
    )
    suffix = conversation.conversation_id.replace("_", "-", 1)[:13]
    relative = safe_relative_path(
        SOURCES_DIR, safe_filename(conversation.title or "Untitled conversation", suffix)
    )
    write_note(vault_root, relative, text)
    return relative, check_embeds(vault_root, text)


def _message_blocks(
    conversation: StoredConversation, native_id: str, number: int | None
) -> list[Block]:
    message = conversation.messages[native_id]
    role = message.role or "unknown"
    label = f"{number} · {role}" if number is not None else role
    anchor = message_anchor(conversation.node_keys[native_id])
    text = message.text or "(no text)"
    blocks: list[Block] = [Heading(label, 4), Paragraph(text, anchor=anchor)]
    revision = conversation.revisions.get(native_id)
    for ref in conversation.media.get(revision or "", []):
        blocks.append(media_block(ref))
    return blocks


def _branch_label(
    conversation: StoredConversation, parent: str | None, kinds: Mapping[str, str]
) -> tuple[str, str]:
    # Returns the heading and a line saying where the branch leaves. The
    # line is built only from numbers and generated anchors, so it is safe
    # to render unescaped (headings are always escaped, links included).
    if parent is None:
        return "Detached messages", "Their parent message is missing from the export."
    kind = kinds.get(parent, "other")
    number = conversation.graph.message_number(parent)
    if number is not None:
        where = f"Branches off after message {number} of the active path."
    elif parent in conversation.messages:
        where = f"Branches off after [[#^{message_anchor(conversation.node_keys[parent])}]]."
    else:
        where = "Branches off at the start of the conversation."
    return f"Alternate ({kind})", where
