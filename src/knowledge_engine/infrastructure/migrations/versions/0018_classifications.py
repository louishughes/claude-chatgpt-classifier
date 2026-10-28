"""Store classifications, their labels and reviewer corrections (CLS-004).

Revision ID: 0018_classifications
Revises: 0017_taxonomy_changes
Create Date: 2026-10-28
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0018_classifications"
down_revision: str | None = "0017_taxonomy_changes"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    """Create classifications, classification_labels and classification_reviews."""
    op.create_table(
        "classification_reviews",
        sa.Column("review_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("segment_id", sa.String(length=40), nullable=False),
        sa.Column("field", sa.String(length=20), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("taxonomy_version", sa.String(length=40), nullable=False),
        sa.Column("primary_id", sa.String(length=40), nullable=True),
        sa.Column("secondary_json", sa.Text(), nullable=False),
        sa.Column("reviewer", sa.String(length=100), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("review_id", name=op.f("pk_classification_reviews")),
        sa.UniqueConstraint(
            "segment_id",
            "field",
            "sequence",
            name=op.f("uq_classification_reviews_segment_id_field_sequence"),
        ),
    )
    with op.batch_alter_table("classification_reviews", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_classification_reviews_segment_id"), ["segment_id"], unique=False
        )

    op.create_table(
        "classifications",
        sa.Column("classification_id", sa.String(length=40), nullable=False),
        sa.Column("stage_key", sa.String(length=70), nullable=False),
        sa.Column("segment_id", sa.String(length=40), nullable=False),
        sa.Column("conversation_id", sa.String(length=40), nullable=False),
        sa.Column("taxonomy_version", sa.String(length=40), nullable=False),
        sa.Column("method", sa.String(length=20), nullable=False),
        sa.Column("state", sa.String(length=20), nullable=False),
        sa.Column("answer_json", sa.Text(), nullable=True),
        sa.Column("problems_json", sa.Text(), nullable=False),
        sa.Column("provider_id", sa.String(length=40), nullable=True),
        sa.Column("served_model", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "state IN ('done','pending','review_required')",
            name=op.f("ck_classifications_state_valid"),
        ),
        sa.PrimaryKeyConstraint("classification_id", name=op.f("pk_classifications")),
        sa.UniqueConstraint("stage_key", name=op.f("uq_classifications_stage_key")),
    )
    with op.batch_alter_table("classifications", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_classifications_conversation_id"), ["conversation_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_classifications_segment_id"), ["segment_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_classifications_taxonomy_version"), ["taxonomy_version"], unique=False
        )

    op.create_table(
        "classification_labels",
        sa.Column("label_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("classification_id", sa.String(length=40), nullable=False),
        sa.Column("field", sa.String(length=20), nullable=False),
        sa.Column("target_id", sa.String(length=40), nullable=False),
        sa.Column("rank", sa.String(length=10), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("evidence_json", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["classification_id"],
            ["classifications.classification_id"],
            name=op.f("fk_classification_labels_classification_id_classifications"),
        ),
        sa.PrimaryKeyConstraint("label_id", name=op.f("pk_classification_labels")),
    )
    with op.batch_alter_table("classification_labels", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_classification_labels_classification_id"),
            ["classification_id"],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f("ix_classification_labels_target_id"), ["target_id"], unique=False
        )


def downgrade() -> None:
    """Drop the three tables."""
    with op.batch_alter_table("classification_labels", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_classification_labels_target_id"))
        batch_op.drop_index(batch_op.f("ix_classification_labels_classification_id"))
    op.drop_table("classification_labels")
    with op.batch_alter_table("classifications", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_classifications_taxonomy_version"))
        batch_op.drop_index(batch_op.f("ix_classifications_segment_id"))
        batch_op.drop_index(batch_op.f("ix_classifications_conversation_id"))
    op.drop_table("classifications")
    with op.batch_alter_table("classification_reviews", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_classification_reviews_segment_id"))
    op.drop_table("classification_reviews")
