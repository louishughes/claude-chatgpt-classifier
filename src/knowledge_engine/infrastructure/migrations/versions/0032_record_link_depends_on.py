"""Let record links say one action waits for another (EXT-010).

Revision ID: 0032_record_link_depends_on
Revises: 0031_model_request_run
Create Date: 2026-10-28
"""

from __future__ import annotations

from alembic import op

revision: str = "0032_record_link_depends_on"
down_revision: str | None = "0031_model_request_run"
branch_labels: str | None = None
depends_on: str | None = None

_BEFORE = "'creates','references','elaborates','same_project'"
_AFTER = _BEFORE + ",'depends_on'"


def _predicates(allowed: str) -> None:
    with op.batch_alter_table("record_links", schema=None) as batch_op:
        batch_op.drop_constraint(op.f("ck_record_links_predicate_valid"), type_="check")
        batch_op.create_check_constraint(
            op.f("ck_record_links_predicate_valid"), f"predicate IN ({allowed})"
        )


def upgrade() -> None:
    """Allow ``depends_on`` in record_links.predicate."""
    _predicates(_AFTER)


def downgrade() -> None:
    """Back to the four REC-002 predicates (fails while depends_on links exist)."""
    _predicates(_BEFORE)
