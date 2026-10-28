"""Add the social account registry: accounts, aliases and mentions (SOC-001/002).

Revision ID: 0012_social_accounts
Revises: 0011_video_transcripts
Create Date: 2026-10-28
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0012_social_accounts"
down_revision: str | None = "0011_video_transcripts"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    """Create social_accounts, account_aliases and account_mentions."""
    op.create_table(
        "social_accounts",
        sa.Column("account_id", sa.String(length=40), nullable=False),
        sa.Column("platform", sa.String(length=20), nullable=False),
        sa.Column("stable_platform_id", sa.String(length=100), nullable=True),
        sa.Column("canonical_handle", sa.String(length=300), nullable=True),
        sa.Column("profile_url", sa.Text(), nullable=True),
        sa.Column("identity_status", sa.String(length=12), nullable=False),
        sa.Column("first_import_id", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "identity_status IN ('confirmed','probable','ambiguous','rejected')",
            name=op.f("ck_social_accounts_identity_status_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["first_import_id"],
            ["import_batches.import_id"],
            name=op.f("fk_social_accounts_first_import_id_import_batches"),
        ),
        sa.PrimaryKeyConstraint("account_id", name=op.f("pk_social_accounts")),
        sa.UniqueConstraint(
            "platform",
            "canonical_handle",
            name=op.f("uq_social_accounts_platform_canonical_handle"),
        ),
        sa.UniqueConstraint(
            "platform",
            "stable_platform_id",
            name=op.f("uq_social_accounts_platform_stable_platform_id"),
        ),
    )
    with op.batch_alter_table("social_accounts", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_social_accounts_platform"), ["platform"], unique=False)

    op.create_table(
        "account_aliases",
        sa.Column("alias_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("account_id", sa.String(length=40), nullable=False),
        sa.Column("alias", sa.Text(), nullable=False),
        sa.Column("kind", sa.String(length=12), nullable=False),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["social_accounts.account_id"],
            name=op.f("fk_account_aliases_account_id_social_accounts"),
        ),
        sa.PrimaryKeyConstraint("alias_id", name=op.f("pk_account_aliases")),
        sa.UniqueConstraint(
            "account_id", "kind", "alias", name=op.f("uq_account_aliases_account_id_kind_alias")
        ),
    )
    with op.batch_alter_table("account_aliases", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_account_aliases_account_id"), ["account_id"], unique=False
        )

    op.create_table(
        "account_mentions",
        sa.Column("mention_id", sa.String(length=40), nullable=False),
        sa.Column("revision_id", sa.String(length=40), nullable=False),
        sa.Column("conversation_id", sa.String(length=40), nullable=False),
        sa.Column("origin", sa.String(length=20), nullable=False),
        sa.Column("start", sa.Integer(), nullable=False),
        sa.Column("end", sa.Integer(), nullable=False),
        sa.Column("raw_text", sa.Text(), nullable=False),
        sa.Column("platform", sa.String(length=20), nullable=True),
        sa.Column("handle", sa.String(length=300), nullable=True),
        sa.Column("account_id", sa.String(length=40), nullable=True),
        sa.Column("resolution", sa.String(length=12), nullable=False),
        sa.Column("actor", sa.String(length=20), nullable=True),
        sa.Column("first_import_id", sa.String(length=32), nullable=False),
        sa.CheckConstraint(
            "origin IN ('message_text','citation_metadata')",
            name=op.f("ck_account_mentions_origin_valid"),
        ),
        sa.CheckConstraint(
            "resolution != 'resolved' OR account_id IS NOT NULL",
            name=op.f("ck_account_mentions_resolved_has_account"),
        ),
        sa.CheckConstraint(
            "resolution IN ('resolved','ambiguous','rejected')",
            name=op.f("ck_account_mentions_resolution_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["social_accounts.account_id"],
            name=op.f("fk_account_mentions_account_id_social_accounts"),
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["conversations.conversation_id"],
            name=op.f("fk_account_mentions_conversation_id_conversations"),
        ),
        sa.ForeignKeyConstraint(
            ["first_import_id"],
            ["import_batches.import_id"],
            name=op.f("fk_account_mentions_first_import_id_import_batches"),
        ),
        sa.ForeignKeyConstraint(
            ["revision_id"],
            ["message_revisions.revision_id"],
            name=op.f("fk_account_mentions_revision_id_message_revisions"),
        ),
        sa.PrimaryKeyConstraint("mention_id", name=op.f("pk_account_mentions")),
        sa.UniqueConstraint(
            "revision_id",
            "start",
            "end",
            "origin",
            name=op.f("uq_account_mentions_revision_id_start_end_origin"),
        ),
    )
    with op.batch_alter_table("account_mentions", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_account_mentions_account_id"), ["account_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_account_mentions_conversation_id"), ["conversation_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_account_mentions_revision_id"), ["revision_id"], unique=False
        )


def downgrade() -> None:
    """Drop the registry tables, children first."""
    op.drop_table("account_mentions")
    op.drop_table("account_aliases")
    op.drop_table("social_accounts")
