"""Phase 3.3 - Deployment Preflight & Release Gate Engine.

One new, additive table. Nothing else in the schema changes -- the release
gate (``app.runtime.deployment.gate``) reads existing columns across
``agents``, ``agent_versions``, ``agent_deployments``, ``environments``,
``tools``, ``agent_identities`` and ``deployment_health``; it writes only to
the new table below.

- ``deployment_preflight_results`` -- one row per ``ReleaseGateService.
  evaluate()`` call: the verdict (PASS/WARNING/BLOCK), the structured
  findings (JSONB list of {code, severity, source, explanation,
  remediation} -- a snapshot, not normalized into rows; see
  docs/deployment/release-gates.md), when it ran, and who ran it.

Reversible: ``downgrade()`` drops the one new table; no existing column,
row, or value on any pre-existing table is altered by either direction.

Revision ID: 0039_deployment_preflight
Revises: 0038_environments_promotion
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0039_deployment_preflight"
down_revision: str | None = "0038_environments_promotion"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "deployment_preflight_results",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("deployment_id", sa.UUID(), sa.ForeignKey("agent_deployments.id", ondelete="CASCADE"),
                 nullable=False),
        sa.Column("organization_id", sa.UUID(), sa.ForeignKey("organizations.id", ondelete="CASCADE"),
                 nullable=False),
        sa.Column("verdict", sa.String(length=12), nullable=False),
        sa.Column("findings", JSONB(), nullable=False, server_default="[]"),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("evaluated_by", sa.UUID(), nullable=True),
    )
    op.create_index("ix_deployment_preflight_results_deployment_id", "deployment_preflight_results",
                    ["deployment_id"])
    op.create_index("ix_deployment_preflight_results_organization_id", "deployment_preflight_results",
                    ["organization_id"])
    op.create_index("ix_deployment_preflight_results_deployment_evaluated", "deployment_preflight_results",
                    ["deployment_id", "evaluated_at"])


def downgrade() -> None:
    op.drop_index("ix_deployment_preflight_results_deployment_evaluated",
                  table_name="deployment_preflight_results")
    op.drop_index("ix_deployment_preflight_results_organization_id", table_name="deployment_preflight_results")
    op.drop_index("ix_deployment_preflight_results_deployment_id", table_name="deployment_preflight_results")
    op.drop_table("deployment_preflight_results")
