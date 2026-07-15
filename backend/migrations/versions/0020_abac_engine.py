"""Phase 4.3.5 - Attribute-Based Access Control engine.

New tables (§21):

- ``abac_policies``           versioned, lifecycle-managed context policies.
- ``abac_policy_versions``    immutable published snapshots.
- ``attribute_definitions``   the attribute registry (only registered
                              attributes may appear in policies).
- ``abac_evaluations``        one row per evaluation with the explanation.
- ``abac_policy_exceptions``  time-boxed, approved per-subject exemptions.

Additive: no column dropped or retyped.

Revision ID: 0020_abac_engine
Revises: 0019_resource_authorization
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0020_abac_engine"
down_revision: str | None = "0019_resource_authorization"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "abac_policies",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("policy_family_id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="DRAFT"),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("combining_algorithm", sa.String(length=30), nullable=False,
                  server_default="DENY_OVERRIDES"),
        sa.Column("scope_type", sa.String(length=20), nullable=False,
                  server_default="ORGANIZATION"),
        sa.Column("scope_id", sa.UUID(), nullable=True),
        sa.Column("target", JSONB(), nullable=True),
        sa.Column("conditions", JSONB(), nullable=True),
        sa.Column("effect", sa.String(length=30), nullable=False, server_default="DENY"),
        sa.Column("obligations", JSONB(), nullable=True),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column("updated_by", sa.UUID(), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_abac_policies_family", "abac_policies", ["policy_family_id"])
    op.create_index("ix_abac_policies_org", "abac_policies", ["organization_id"])
    op.create_index("ix_abac_policies_status", "abac_policies", ["status"])

    op.create_table(
        "abac_policy_versions",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("policy_family_id", sa.UUID(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("snapshot", JSONB(), nullable=False),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_abac_policy_versions_family", "abac_policy_versions", ["policy_family_id"])

    op.create_table(
        "attribute_definitions",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("category", sa.String(length=20), nullable=False),
        sa.Column("data_type", sa.String(length=20), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("sensitivity", sa.String(length=20), nullable=False, server_default="INTERNAL"),
        sa.Column("supported_operators", JSONB(), nullable=True),
        sa.Column("source", sa.String(length=50), nullable=True),
        sa.Column("is_system", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("name", name="uq_attribute_definitions_name"),
    )

    op.create_table(
        "abac_evaluations",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("organization_id", sa.UUID(), nullable=True),
        sa.Column("identity_id", sa.UUID(), nullable=True),
        sa.Column("resource_type", sa.String(length=50), nullable=True),
        sa.Column("resource_id", sa.UUID(), nullable=True),
        sa.Column("action", sa.String(length=100), nullable=False),
        sa.Column("decision", sa.String(length=30), nullable=False),
        sa.Column("matched_policy_ids", JSONB(), nullable=True),
        sa.Column("obligations", JSONB(), nullable=True),
        sa.Column("explanation", JSONB(), nullable=True),
        sa.Column("evaluation_time_ms", sa.Float(), nullable=True),
        sa.Column("request_id", sa.String(length=100), nullable=True),
        sa.Column("correlation_id", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_abac_evaluations_org", "abac_evaluations", ["organization_id"])
    op.create_index("ix_abac_evaluations_decision", "abac_evaluations", ["decision"])

    op.create_table(
        "abac_policy_exceptions",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("policy_id", sa.UUID(), nullable=False),
        sa.Column("subject_type", sa.String(length=30), nullable=False, server_default="USER"),
        sa.Column("subject_id", sa.UUID(), nullable=False),
        sa.Column("resource_type", sa.String(length=50), nullable=True),
        sa.Column("resource_id", sa.UUID(), nullable=True),
        sa.Column("reason", sa.String(length=500), nullable=True),
        sa.Column("approved_by", sa.UUID(), nullable=True),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="ACTIVE"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["policy_id"], ["abac_policies.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_abac_policy_exceptions_policy", "abac_policy_exceptions", ["policy_id"])
    op.create_index("ix_abac_policy_exceptions_subject", "abac_policy_exceptions", ["subject_id"])


def downgrade() -> None:
    op.drop_table("abac_policy_exceptions")
    op.drop_table("abac_evaluations")
    op.drop_table("attribute_definitions")
    op.drop_table("abac_policy_versions")
    op.drop_table("abac_policies")
