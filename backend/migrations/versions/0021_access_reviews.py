"""Phase 4.3.7 - Enterprise authorization administration portal.

New tables (§14):

- ``access_review_campaigns``  periodic access certification campaigns.
- ``access_review_items``      one role assignment under review per row.

Additive: no column dropped or retyped.

Revision ID: 0021_access_reviews
Revises: 0020_abac_engine
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0021_access_reviews"
down_revision: str | None = "0020_abac_engine"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "access_review_campaigns",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="DRAFT"),
        sa.Column("scope", JSONB(), nullable=True),
        sa.Column("reviewer_id", sa.UUID(), nullable=True),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_access_review_campaigns_org", "access_review_campaigns", ["organization_id"])
    op.create_index("ix_access_review_campaigns_status", "access_review_campaigns", ["status"])

    op.create_table(
        "access_review_items",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("campaign_id", sa.UUID(), nullable=False),
        sa.Column("subject_id", sa.UUID(), nullable=False),
        sa.Column("subject_label", sa.String(length=255), nullable=False),
        sa.Column("assignment_id", sa.UUID(), nullable=True),
        sa.Column("role_id", sa.UUID(), nullable=True),
        sa.Column("role_name", sa.String(length=255), nullable=False),
        sa.Column("scope_label", sa.String(length=255), nullable=True),
        sa.Column("decision", sa.String(length=20), nullable=False, server_default="PENDING"),
        sa.Column("decided_by", sa.UUID(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("comment", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["campaign_id"], ["access_review_campaigns.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_access_review_items_campaign", "access_review_items", ["campaign_id"])
    op.create_index("ix_access_review_items_subject", "access_review_items", ["subject_id"])
    op.create_index("ix_access_review_items_decision", "access_review_items", ["decision"])


def downgrade() -> None:
    op.drop_table("access_review_items")
    op.drop_table("access_review_campaigns")
