"""Phase 3.2 - Environment & Promotion Model.

Two new, additive tables and one additive column on the existing,
untouched ``agent_deployments`` table (its pre-existing ``environment``
string column is left entirely in place -- every legacy read of it,
including the M1 execution-path check in ``RuntimePolicyService.evaluate``,
is unchanged; see docs/deployment/environments.md):

- ``environments`` -- governed, tenant-scoped deployment targets
  (DEVELOPMENT/TEST/STAGING/PRODUCTION/SANDBOX, or an org-defined custom
  name), each carrying a ``policy`` JSONB document
  (``app.runtime.environment.policy``).
- ``promotion_paths`` -- the org-configured, directed graph of which
  environment a version's deployment eligibility may legally move to next.
- ``agent_deployments.environment_id`` -- nullable FK to ``environments``,
  backfilled below for every existing row.

The §15 seeding + backfill, applied once, live, for every organization
that has at least one row in ``agent_deployments`` (an org with zero
deployments gets its environments lazily, on first touch, via
``EnvironmentService.ensure_seeded`` -- see that module):

1. Seed the standard five ``environments`` rows for each such organization.
2. Backfill ``agent_deployments.environment_id`` by matching the existing
   ``environment`` string to the newly seeded row of the same name (any
   deployment whose legacy string doesn't match one of the five standard
   names -- none are expected in this codebase's history, mirroring 0037's
   own note about its eleven ``status`` values -- simply keeps
   ``environment_id`` null rather than the migration crashing on an
   unrecognized value).
3. Seed the default linear promotion graph
   DEVELOPMENT -> TEST -> STAGING -> PRODUCTION for each such organization
   (``STAGING -> PRODUCTION`` defaults ``requires_approval = true``,
   mirroring the pre-existing mission-critical-production precedent).
   SANDBOX is deliberately left out of the chain -- an isolated environment,
   not a promotion rung. This is a choice, not the only valid one (the build
   prompt explicitly allows starting with an empty, org-configured graph
   instead) -- made so the promotion API has something to promote along
   immediately for every organization with existing deployments, rather
   than requiring an undocumented extra setup step first.

No allocation/traffic backfill here (out of this phase's scope -- Phase
3.4's own job). No ``deployment_events``/audit row is synthesized for this
one-time seed -- it is schema/reference-data setup, not a lifecycle
transition.

Reversible: ``downgrade()`` drops the two new tables and the one new
``agent_deployments`` column, restoring the exact pre-3.2 schema; no
existing column, row, or value on any pre-existing table is altered by the
downgrade.

Revision ID: 0038_environments_promotion
Revises: 0037_deployment_lifecycle
"""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0038_environments_promotion"
down_revision: str | None = "0037_deployment_lifecycle"
branch_labels = None
depends_on = None

_STANDARD_ENVIRONMENTS: tuple[tuple[str, str, bool], ...] = (
    ("DEVELOPMENT", "Development", False),
    ("TEST", "Test", False),
    ("STAGING", "Staging", False),
    ("PRODUCTION", "Production", True),
    ("SANDBOX", "Sandbox", False),
)

_DEFAULT_PATHS: tuple[tuple[str, str, bool], ...] = (
    ("DEVELOPMENT", "TEST", False),
    ("TEST", "STAGING", False),
    ("STAGING", "PRODUCTION", True),
)


def upgrade() -> None:
    op.create_table(
        "environments",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("display_name", sa.String(length=128), nullable=False),
        sa.Column("is_production", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("policy", JSONB(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_environments_organization_id", "environments", ["organization_id"])
    op.create_unique_constraint("uq_environments_org_name", "environments", ["organization_id", "name"])

    op.create_table(
        "promotion_paths",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("from_environment_id", sa.UUID(), nullable=False),
        sa.Column("to_environment_id", sa.UUID(), nullable=False),
        sa.Column("requires_approval", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["from_environment_id"], ["environments.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["to_environment_id"], ["environments.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_promotion_paths_organization_id", "promotion_paths", ["organization_id"])
    op.create_index("ix_promotion_paths_from_environment_id", "promotion_paths", ["from_environment_id"])
    op.create_index("ix_promotion_paths_to_environment_id", "promotion_paths", ["to_environment_id"])
    op.create_unique_constraint(
        "uq_promotion_paths_org_edge", "promotion_paths",
        ["organization_id", "from_environment_id", "to_environment_id"],
    )

    op.add_column("agent_deployments", sa.Column("environment_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        "fk_agent_deployments_environment", "agent_deployments", "environments",
        ["environment_id"], ["id"], ondelete="SET NULL",
    )
    op.create_index("ix_agent_deployments_environment_id", "agent_deployments", ["environment_id"])

    connection = op.get_bind()
    organization_ids = [row[0] for row in connection.execute(
        sa.text("SELECT DISTINCT organization_id FROM agent_deployments")
    ).fetchall()]

    for organization_id in organization_ids:
        name_to_id: dict[str, uuid.UUID] = {}
        for name, display_name, is_production in _STANDARD_ENVIRONMENTS:
            environment_id = uuid.uuid4()
            connection.execute(
                sa.text(
                    "INSERT INTO environments "
                    "(id, organization_id, name, display_name, is_production, policy) "
                    "VALUES (:id, :organization_id, :name, :display_name, :is_production, '{}')"
                ),
                {"id": environment_id, "organization_id": organization_id, "name": name,
                 "display_name": display_name, "is_production": is_production},
            )
            name_to_id[name] = environment_id

        connection.execute(
            sa.text(
                "UPDATE agent_deployments SET environment_id = :environment_id "
                "WHERE organization_id = :organization_id AND environment = :name AND environment_id IS NULL"
            ),
            [
                {"environment_id": env_id, "organization_id": organization_id, "name": name}
                for name, env_id in name_to_id.items()
            ],
        )

        for from_name, to_name, requires_approval in _DEFAULT_PATHS:
            connection.execute(
                sa.text(
                    "INSERT INTO promotion_paths "
                    "(id, organization_id, from_environment_id, to_environment_id, requires_approval) "
                    "VALUES (:id, :organization_id, :from_environment_id, :to_environment_id, :requires_approval)"
                ),
                {"id": uuid.uuid4(), "organization_id": organization_id,
                 "from_environment_id": name_to_id[from_name], "to_environment_id": name_to_id[to_name],
                 "requires_approval": requires_approval},
            )


def downgrade() -> None:
    op.drop_index("ix_agent_deployments_environment_id", "agent_deployments")
    op.drop_constraint("fk_agent_deployments_environment", "agent_deployments", type_="foreignkey")
    op.drop_column("agent_deployments", "environment_id")

    op.drop_constraint("uq_promotion_paths_org_edge", "promotion_paths", type_="unique")
    op.drop_index("ix_promotion_paths_to_environment_id", "promotion_paths")
    op.drop_index("ix_promotion_paths_from_environment_id", "promotion_paths")
    op.drop_index("ix_promotion_paths_organization_id", "promotion_paths")
    op.drop_table("promotion_paths")

    op.drop_constraint("uq_environments_org_name", "environments", type_="unique")
    op.drop_index("ix_environments_organization_id", "environments")
    op.drop_table("environments")
