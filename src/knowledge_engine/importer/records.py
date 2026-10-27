"""The logical records an import creates: conversations, message nodes, revisions, edges.

These rows are the archive's long-term memory, and their keys are the
ADR-0003 identities from ``domain/ids.py``:

* a **conversation** is (workspace, source system, account, native ID);
* a **message node** is (conversation, native node ID);
* a **message revision** is (node, canonical content hash): new content in
  a later export makes a new revision, unchanged content reuses the old one;
* a **graph edge** is (child node, parent node).

Every key has a unique constraint, so importing the same thing twice can't
create a second row even if the code above had a bug. That's the database
half of the "re-import adds nothing" guarantee.

Talking points:
    - "Every table's key is the thing's identity, and the database enforces
      it, so a duplicate can't be written even by mistake."
    - "A message whose content changes gets a new revision; the old one is
      kept, so history is never overwritten."
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from knowledge_engine.infrastructure.db import Base


def _utc_now() -> datetime:
    return datetime.now(UTC)


class ConversationRow(Base):
    """One logical conversation, stable across every re-export."""

    __tablename__ = "conversations"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id", "source_system", "account_namespace", "native_conversation_id"
        ),
        CheckConstraint("presence IN ('present','not_seen')", name="presence_valid"),
    )

    conversation_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.workspace_id"))
    source_system: Mapped[str] = mapped_column(String(20))
    account_namespace: Mapped[str] = mapped_column(String(63))
    native_conversation_id: Mapped[str] = mapped_column(String(200))
    # Display only, and private: the latest title seen. Never part of a key.
    title: Mapped[str | None] = mapped_column(Text, default=None)
    create_time: Mapped[float | None] = mapped_column(Float, default=None)
    current_node: Mapped[str | None] = mapped_column(String(200), default=None)
    presence: Mapped[str] = mapped_column(String(10), default="present")
    first_import_id: Mapped[str] = mapped_column(ForeignKey("import_batches.import_id"))
    last_import_id: Mapped[str] = mapped_column(ForeignKey("import_batches.import_id"))


class MessageNodeRow(Base):
    """One node of a conversation's message tree."""

    __tablename__ = "message_nodes"
    __table_args__ = (
        UniqueConstraint("conversation_id", "native_node_id"),
        CheckConstraint("presence IN ('present','not_seen')", name="presence_valid"),
    )

    node_key: Mapped[str] = mapped_column(String(40), primary_key=True)
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.conversation_id"), index=True
    )
    native_node_id: Mapped[str] = mapped_column(String(200))
    presence: Mapped[str] = mapped_column(String(10), default="present")
    first_import_id: Mapped[str] = mapped_column(ForeignKey("import_batches.import_id"))
    last_import_id: Mapped[str] = mapped_column(ForeignKey("import_batches.import_id"))


class MessageRevisionRow(Base):
    """One version of a message's content."""

    __tablename__ = "message_revisions"
    __table_args__ = (UniqueConstraint("node_key", "canonical_content_hash"),)

    revision_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    node_key: Mapped[str] = mapped_column(ForeignKey("message_nodes.node_key"), index=True)
    canonical_content_hash: Mapped[str] = mapped_column(String(64))
    raw_payload_hash: Mapped[str] = mapped_column(String(64))
    role: Mapped[str | None] = mapped_column(String(20), default=None)
    content_type: Mapped[str | None] = mapped_column(String(60), default=None)
    create_time: Mapped[float | None] = mapped_column(Float, default=None)
    # The exported content object, canonical JSON. Private message text
    # lives here, in the private workspace database only.
    content_json: Mapped[str] = mapped_column(Text)
    first_snapshot_id: Mapped[str] = mapped_column(ForeignKey("source_snapshots.snapshot_id"))
    first_import_id: Mapped[str] = mapped_column(ForeignKey("import_batches.import_id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)


class GraphEdgeRow(Base):
    """A parent-to-child link in a conversation's message tree."""

    __tablename__ = "graph_edges"
    __table_args__ = (UniqueConstraint("child_node_key", "parent_node_key"),)

    edge_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.conversation_id"), index=True
    )
    child_node_key: Mapped[str] = mapped_column(ForeignKey("message_nodes.node_key"))
    parent_node_key: Mapped[str | None] = mapped_column(
        ForeignKey("message_nodes.node_key"), default=None
    )
    first_import_id: Mapped[str] = mapped_column(ForeignKey("import_batches.import_id"))


class RevisionObservationRow(Base):
    """One exact raw form in which a revision was seen (ADR-0003's raw hash).

    The revision says *what the message says*; observations say *how each
    export wrote it down*. Metadata drift between exports adds an
    observation, never a revision, so nothing downstream is redone.
    """

    __tablename__ = "revision_observations"
    __table_args__ = (UniqueConstraint("revision_id", "raw_payload_hash"),)

    observation_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    revision_id: Mapped[str] = mapped_column(
        ForeignKey("message_revisions.revision_id"), index=True
    )
    raw_payload_hash: Mapped[str] = mapped_column(String(64))
    first_snapshot_id: Mapped[str] = mapped_column(ForeignKey("source_snapshots.snapshot_id"))
    first_import_id: Mapped[str] = mapped_column(ForeignKey("import_batches.import_id"))
