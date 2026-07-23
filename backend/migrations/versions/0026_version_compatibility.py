"""Phase 5.2.6 - Compatibility & Breaking-Change Detection.

Additive, same philosophy as 0025: ``agent_versions`` gains two more
release-management columns (which baseline a compatibility verdict was
computed against, and when) rather than a second version table, and one new
satellite table holds the many-per-version compatibility findings a run of
the analyzer produces.

- ``agent_version_compatibility_findings``  one row per detected change
  (input/output contract, tool/capability binding, model configuration,
  resource limit, policy, prompt, metadata) between a version and its
  resolved baseline (see ``app/runtime/versioning/compatibility.py``).

The existing ``agent_versions.compatibility_level`` column (added by 0025,
default ``'UNKNOWN'``) is left untouched — it already has the right type and
default; this migration only adds the two columns that record *how* that
level was computed.

Revision ID: 0026_version_compatibility
Revises: 0025_agent_versioning
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0026_version_compatibility"
down_revision: str | None = "0025_agent_versioning"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- agent_versions: which baseline + when (§5) -------------------------
    op.add_column("agent_versions", sa.Column("compatibility_baseline_id", sa.UUID(), nullable=True))
    op.add_column("agent_versions", sa.Column("compatibility_analyzed_at", sa.DateTime(timezone=True),
                                               nullable=True))
    op.create_foreign_key("fk_agent_versions_compatibility_baseline", "agent_versions", "agent_versions",
                          ["compatibility_baseline_id"], ["id"], ondelete="SET NULL")
    op.create_index("ix_agent_versions_compatibility_baseline", "agent_versions", ["compatibility_baseline_id"])

    # --- agent_version_compatibility_findings (§5) ---------------------------
    op.create_table(
        "agent_version_compatibility_findings",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("agent_version_id", sa.UUID(), nullable=False),
        sa.Column("baseline_version_id", sa.UUID(), nullable=True),
        sa.Column("category", sa.String(length=40), nullable=False),
        sa.Column("path", sa.String(length=255), nullable=False),
        sa.Column("change_type", sa.String(length=20), nullable=False),
        sa.Column("materiality", sa.String(length=20), nullable=False),
        sa.Column("baseline_value", sa.Text(), nullable=True),
        sa.Column("candidate_value", sa.Text(), nullable=True),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["agent_version_id"], ["agent_versions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["baseline_version_id"], ["agent_versions.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_version_compat_findings_version", "agent_version_compatibility_findings",
                    ["agent_version_id"])


def downgrade() -> None:
    op.drop_index("ix_version_compat_findings_version", table_name="agent_version_compatibility_findings")
    op.drop_table("agent_version_compatibility_findings")

    op.drop_index("ix_agent_versions_compatibility_baseline", table_name="agent_versions")
    op.drop_constraint("fk_agent_versions_compatibility_baseline", "agent_versions", type_="foreignkey")
    op.drop_column("agent_versions", "compatibility_analyzed_at")
    op.drop_column("agent_versions", "compatibility_baseline_id")
