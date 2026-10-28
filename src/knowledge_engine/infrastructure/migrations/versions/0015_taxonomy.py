"""Add the taxonomy and project registry (TAX-001, TAX-002).

Revision ID: 0015_taxonomy
Revises: 0014_model_ledger
Create Date: 2026-10-28
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0015_taxonomy"
down_revision: str | None = "0014_model_ledger"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    """Create terms, aliases, versions, proposals, projects and project aliases."""
    op.create_table(
        "projects",
        sa.Column("project_id", sa.String(length=40), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=12), nullable=False),
        sa.Column("merged_into", sa.String(length=40), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "(status = 'merged') = (merged_into IS NOT NULL)",
            name=op.f("ck_projects_merged_has_target"),
        ),
        sa.CheckConstraint(
            "status IN ('proposed','approved','retired','merged')",
            name=op.f("ck_projects_status_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["merged_into"], ["projects.project_id"], name=op.f("fk_projects_merged_into_projects")
        ),
        sa.PrimaryKeyConstraint("project_id", name=op.f("pk_projects")),
    )
    op.create_table(
        "taxonomy_proposals",
        sa.Column("proposal_id", sa.String(length=40), nullable=False),
        sa.Column("operation", sa.String(length=12), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("evidence_json", sa.Text(), nullable=False),
        sa.Column("proposer", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=10), nullable=False),
        sa.Column("reviewer", sa.String(length=100), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "operation IN ('add','rename','alias','merge','retire','reparent')",
            name=op.f("ck_taxonomy_proposals_operation_valid"),
        ),
        sa.CheckConstraint(
            "status IN ('open','approved','rejected')",
            name=op.f("ck_taxonomy_proposals_status_valid"),
        ),
        sa.PrimaryKeyConstraint("proposal_id", name=op.f("pk_taxonomy_proposals")),
    )
    op.create_table(
        "taxonomy_terms",
        sa.Column("term_id", sa.String(length=40), nullable=False),
        sa.Column("dimension", sa.String(length=20), nullable=False),
        sa.Column("label", sa.String(length=200), nullable=False),
        sa.Column("definition", sa.Text(), nullable=True),
        sa.Column("parent_id", sa.String(length=40), nullable=True),
        sa.Column("status", sa.String(length=12), nullable=False),
        sa.Column("merged_into", sa.String(length=40), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "(status = 'merged') = (merged_into IS NOT NULL)",
            name=op.f("ck_taxonomy_terms_merged_has_target"),
        ),
        sa.CheckConstraint(
            "dimension IN ('domain','purpose','topic','knowledge_type','output')",
            name=op.f("ck_taxonomy_terms_dimension_valid"),
        ),
        sa.CheckConstraint(
            "status IN ('proposed','approved','retired','merged')",
            name=op.f("ck_taxonomy_terms_status_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["merged_into"],
            ["taxonomy_terms.term_id"],
            name=op.f("fk_taxonomy_terms_merged_into_taxonomy_terms"),
        ),
        sa.ForeignKeyConstraint(
            ["parent_id"],
            ["taxonomy_terms.term_id"],
            name=op.f("fk_taxonomy_terms_parent_id_taxonomy_terms"),
        ),
        sa.PrimaryKeyConstraint("term_id", name=op.f("pk_taxonomy_terms")),
    )
    with op.batch_alter_table("taxonomy_terms", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_taxonomy_terms_dimension"), ["dimension"], unique=False
        )

    op.create_table(
        "taxonomy_versions",
        sa.Column("version", sa.String(length=40), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("snapshot_json", sa.Text(), nullable=False),
        sa.Column("author", sa.String(length=100), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("version", name=op.f("pk_taxonomy_versions")),
    )
    op.create_table(
        "project_aliases",
        sa.Column("alias_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("project_id", sa.String(length=40), nullable=False),
        sa.Column("alias", sa.String(length=200), nullable=False),
        sa.Column("norm_form", sa.String(length=200), nullable=False),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.project_id"],
            name=op.f("fk_project_aliases_project_id_projects"),
        ),
        sa.PrimaryKeyConstraint("alias_id", name=op.f("pk_project_aliases")),
        sa.UniqueConstraint("norm_form", name=op.f("uq_project_aliases_norm_form")),
    )
    with op.batch_alter_table("project_aliases", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_project_aliases_project_id"), ["project_id"], unique=False
        )

    op.create_table(
        "taxonomy_aliases",
        sa.Column("alias_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("term_id", sa.String(length=40), nullable=False),
        sa.Column("dimension", sa.String(length=20), nullable=False),
        sa.Column("alias", sa.String(length=200), nullable=False),
        sa.Column("norm_form", sa.String(length=200), nullable=False),
        sa.ForeignKeyConstraint(
            ["term_id"],
            ["taxonomy_terms.term_id"],
            name=op.f("fk_taxonomy_aliases_term_id_taxonomy_terms"),
        ),
        sa.PrimaryKeyConstraint("alias_id", name=op.f("pk_taxonomy_aliases")),
        sa.UniqueConstraint(
            "dimension", "norm_form", name=op.f("uq_taxonomy_aliases_dimension_norm_form")
        ),
    )
    with op.batch_alter_table("taxonomy_aliases", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_taxonomy_aliases_term_id"), ["term_id"], unique=False)


def downgrade() -> None:
    """Drop the registry tables, children first."""
    for table in (
        "taxonomy_aliases",
        "project_aliases",
        "taxonomy_versions",
        "taxonomy_terms",
        "taxonomy_proposals",
        "projects",
    ):
        op.drop_table(table)
