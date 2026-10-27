"""Add conversations, message nodes, revisions and graph edges (slice I2).

Revision ID: 0004_conversations
Revises: 0003_import_ledger
Create Date: 2026-10-27
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0004_conversations"
down_revision: str | None = "0003_import_ledger"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    """Create the logical record tables with their ADR-0003 unique keys."""
    op.create_table(
        "conversations",
        sa.Column("conversation_id", sa.String(length=40), nullable=False),
        sa.Column("workspace_id", sa.String(length=32), nullable=False),
        sa.Column("source_system", sa.String(length=20), nullable=False),
        sa.Column("account_namespace", sa.String(length=63), nullable=False),
        sa.Column("native_conversation_id", sa.String(length=200), nullable=False),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("create_time", sa.Float(), nullable=True),
        sa.Column("current_node", sa.String(length=200), nullable=True),
        sa.Column("presence", sa.String(length=10), nullable=False),
        sa.Column("first_import_id", sa.String(length=32), nullable=False),
        sa.Column("last_import_id", sa.String(length=32), nullable=False),
        sa.CheckConstraint(
            "presence IN ('present','not_seen')", name=op.f("ck_conversations_presence_valid")
        ),
        sa.ForeignKeyConstraint(
            ["first_import_id"],
            ["import_batches.import_id"],
            name=op.f("fk_conversations_first_import_id_import_batches"),
        ),
        sa.ForeignKeyConstraint(
            ["last_import_id"],
            ["import_batches.import_id"],
            name=op.f("fk_conversations_last_import_id_import_batches"),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.workspace_id"],
            name=op.f("fk_conversations_workspace_id_workspaces"),
        ),
        sa.PrimaryKeyConstraint("conversation_id", name=op.f("pk_conversations")),
        sa.UniqueConstraint(
            "workspace_id",
            "source_system",
            "account_namespace",
            "native_conversation_id",
            name=op.f(
                "uq_conversations_workspace_id_source_system_account_namespace_native_conversation_id"
            ),
        ),
    )
    op.create_table(
        "message_nodes",
        sa.Column("node_key", sa.String(length=40), nullable=False),
        sa.Column("conversation_id", sa.String(length=40), nullable=False),
        sa.Column("native_node_id", sa.String(length=200), nullable=False),
        sa.Column("presence", sa.String(length=10), nullable=False),
        sa.Column("first_import_id", sa.String(length=32), nullable=False),
        sa.Column("last_import_id", sa.String(length=32), nullable=False),
        sa.CheckConstraint(
            "presence IN ('present','not_seen')", name=op.f("ck_message_nodes_presence_valid")
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["conversations.conversation_id"],
            name=op.f("fk_message_nodes_conversation_id_conversations"),
        ),
        sa.ForeignKeyConstraint(
            ["first_import_id"],
            ["import_batches.import_id"],
            name=op.f("fk_message_nodes_first_import_id_import_batches"),
        ),
        sa.ForeignKeyConstraint(
            ["last_import_id"],
            ["import_batches.import_id"],
            name=op.f("fk_message_nodes_last_import_id_import_batches"),
        ),
        sa.PrimaryKeyConstraint("node_key", name=op.f("pk_message_nodes")),
        sa.UniqueConstraint(
            "conversation_id",
            "native_node_id",
            name=op.f("uq_message_nodes_conversation_id_native_node_id"),
        ),
    )
    with op.batch_alter_table("message_nodes", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_message_nodes_conversation_id"), ["conversation_id"], unique=False
        )

    op.create_table(
        "graph_edges",
        sa.Column("edge_id", sa.String(length=40), nullable=False),
        sa.Column("conversation_id", sa.String(length=40), nullable=False),
        sa.Column("child_node_key", sa.String(length=40), nullable=False),
        sa.Column("parent_node_key", sa.String(length=40), nullable=True),
        sa.Column("first_import_id", sa.String(length=32), nullable=False),
        sa.ForeignKeyConstraint(
            ["child_node_key"],
            ["message_nodes.node_key"],
            name=op.f("fk_graph_edges_child_node_key_message_nodes"),
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["conversations.conversation_id"],
            name=op.f("fk_graph_edges_conversation_id_conversations"),
        ),
        sa.ForeignKeyConstraint(
            ["first_import_id"],
            ["import_batches.import_id"],
            name=op.f("fk_graph_edges_first_import_id_import_batches"),
        ),
        sa.ForeignKeyConstraint(
            ["parent_node_key"],
            ["message_nodes.node_key"],
            name=op.f("fk_graph_edges_parent_node_key_message_nodes"),
        ),
        sa.PrimaryKeyConstraint("edge_id", name=op.f("pk_graph_edges")),
        sa.UniqueConstraint(
            "child_node_key",
            "parent_node_key",
            name=op.f("uq_graph_edges_child_node_key_parent_node_key"),
        ),
    )
    with op.batch_alter_table("graph_edges", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_graph_edges_conversation_id"), ["conversation_id"], unique=False
        )

    op.create_table(
        "message_revisions",
        sa.Column("revision_id", sa.String(length=40), nullable=False),
        sa.Column("node_key", sa.String(length=40), nullable=False),
        sa.Column("canonical_content_hash", sa.String(length=64), nullable=False),
        sa.Column("raw_payload_hash", sa.String(length=64), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=True),
        sa.Column("content_type", sa.String(length=60), nullable=True),
        sa.Column("create_time", sa.Float(), nullable=True),
        sa.Column("content_json", sa.Text(), nullable=False),
        sa.Column("first_snapshot_id", sa.String(length=40), nullable=False),
        sa.Column("first_import_id", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["first_import_id"],
            ["import_batches.import_id"],
            name=op.f("fk_message_revisions_first_import_id_import_batches"),
        ),
        sa.ForeignKeyConstraint(
            ["first_snapshot_id"],
            ["source_snapshots.snapshot_id"],
            name=op.f("fk_message_revisions_first_snapshot_id_source_snapshots"),
        ),
        sa.ForeignKeyConstraint(
            ["node_key"],
            ["message_nodes.node_key"],
            name=op.f("fk_message_revisions_node_key_message_nodes"),
        ),
        sa.PrimaryKeyConstraint("revision_id", name=op.f("pk_message_revisions")),
        sa.UniqueConstraint(
            "node_key",
            "canonical_content_hash",
            name=op.f("uq_message_revisions_node_key_canonical_content_hash"),
        ),
    )
    with op.batch_alter_table("message_revisions", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_message_revisions_node_key"), ["node_key"], unique=False
        )


def downgrade() -> None:
    """Drop the logical record tables."""
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table("message_revisions", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_message_revisions_node_key"))

    op.drop_table("message_revisions")
    with op.batch_alter_table("graph_edges", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_graph_edges_conversation_id"))

    op.drop_table("graph_edges")
    with op.batch_alter_table("message_nodes", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_message_nodes_conversation_id"))

    op.drop_table("message_nodes")
    op.drop_table("conversations")
