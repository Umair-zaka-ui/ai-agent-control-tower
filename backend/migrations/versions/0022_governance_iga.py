"""Phase 4.3.8 - Identity Governance & Administration (IGA).

New tables (§17):

- ``sod_rules``                  Separation-of-Duties AND toxic-permission rules.
  Both are "these two permission sets must not co-occur on one identity" checks
  that differ only in intent (business-process conflict vs. raw over-privilege),
  so they share one engine/table distinguished by ``rule_type``.
- ``governance_findings``        detected SoD/toxic/orphaned/privileged issues.
- ``remediation_actions``        remediation work items raised against a finding.
- ``governance_risk_scores``     latest computed risk score per identity.
- ``compliance_reports``         generated compliance evidence snapshots.
- ``privileged_account_reviews`` periodic review record for a privileged grant.

Additive: ``access_review_campaigns`` gains ``campaign_type`` (§5); no column
dropped or retyped.

Revision ID: 0022_governance_iga
Revises: 0021_access_reviews
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0022_governance_iga"
down_revision: str | None = "0021_access_reviews"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "access_review_campaigns",
        sa.Column("campaign_type", sa.String(length=30), nullable=False,
                   server_default="QUARTERLY"),
    )

    op.create_table(
        "sod_rules",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("rule_type", sa.String(length=20), nullable=False, server_default="SOD"),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("risk_level", sa.String(length=20), nullable=False, server_default="MEDIUM"),
        sa.Column("permissions_a", JSONB(), nullable=False),
        sa.Column("permissions_b", JSONB(), nullable=False),
        sa.Column("scope", JSONB(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="DRAFT"),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column("approved_by", sa.UUID(), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_sod_rules_org", "sod_rules", ["organization_id"])
    op.create_index("ix_sod_rules_type", "sod_rules", ["rule_type"])
    op.create_index("ix_sod_rules_status", "sod_rules", ["status"])

    op.create_table(
        "governance_findings",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("finding_type", sa.String(length=30), nullable=False),
        sa.Column("severity", sa.String(length=20), nullable=False, server_default="MEDIUM"),
        sa.Column("identity_id", sa.UUID(), nullable=True),
        sa.Column("identity_label", sa.String(length=255), nullable=True),
        sa.Column("resource_id", sa.UUID(), nullable=True),
        sa.Column("rule_id", sa.UUID(), nullable=True),
        sa.Column("details", JSONB(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="OPEN"),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_by", sa.UUID(), nullable=True),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["rule_id"], ["sod_rules.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_governance_findings_org", "governance_findings", ["organization_id"])
    op.create_index("ix_governance_findings_type", "governance_findings", ["finding_type"])
    op.create_index("ix_governance_findings_status", "governance_findings", ["status"])
    op.create_index("ix_governance_findings_identity", "governance_findings", ["identity_id"])

    op.create_table(
        "remediation_actions",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("finding_id", sa.UUID(), nullable=False),
        sa.Column("action_type", sa.String(length=30), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="PENDING"),
        sa.Column("mode", sa.String(length=20), nullable=False, server_default="MANUAL"),
        sa.Column("payload", JSONB(), nullable=True),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column("approved_by", sa.UUID(), nullable=True),
        sa.Column("executed_by", sa.UUID(), nullable=True),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["finding_id"], ["governance_findings.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_remediation_actions_org", "remediation_actions", ["organization_id"])
    op.create_index("ix_remediation_actions_finding", "remediation_actions", ["finding_id"])
    op.create_index("ix_remediation_actions_status", "remediation_actions", ["status"])

    op.create_table(
        "governance_risk_scores",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("identity_id", sa.UUID(), nullable=False),
        sa.Column("identity_label", sa.String(length=255), nullable=False),
        sa.Column("score", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("band", sa.String(length=20), nullable=False, server_default="LOW"),
        sa.Column("factors", JSONB(), nullable=True),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("organization_id", "identity_id", name="uq_governance_risk_identity"),
    )
    op.create_index("ix_governance_risk_scores_org", "governance_risk_scores", ["organization_id"])
    op.create_index("ix_governance_risk_scores_band", "governance_risk_scores", ["band"])

    op.create_table(
        "compliance_reports",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("framework", sa.String(length=30), nullable=False),
        sa.Column("report_type", sa.String(length=50), nullable=False),
        sa.Column("scope", JSONB(), nullable=True),
        sa.Column("payload", JSONB(), nullable=False),
        sa.Column("version", sa.String(length=20), nullable=False, server_default="v1"),
        sa.Column("generated_by", sa.UUID(), nullable=True),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_compliance_reports_org", "compliance_reports", ["organization_id"])
    op.create_index("ix_compliance_reports_framework", "compliance_reports", ["framework"])

    op.create_table(
        "privileged_account_reviews",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("identity_id", sa.UUID(), nullable=False),
        sa.Column("identity_label", sa.String(length=255), nullable=False),
        sa.Column("role_name", sa.String(length=255), nullable=False),
        sa.Column("risk_score", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="PENDING"),
        sa.Column("reviewed_by", sa.UUID(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_privileged_account_reviews_org", "privileged_account_reviews", ["organization_id"])
    op.create_index("ix_privileged_account_reviews_identity", "privileged_account_reviews", ["identity_id"])
    op.create_index("ix_privileged_account_reviews_status", "privileged_account_reviews", ["status"])


def downgrade() -> None:
    op.drop_table("privileged_account_reviews")
    op.drop_table("compliance_reports")
    op.drop_table("governance_risk_scores")
    op.drop_table("remediation_actions")
    op.drop_table("governance_findings")
    op.drop_table("sod_rules")
    op.drop_column("access_review_campaigns", "campaign_type")
