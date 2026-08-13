"""Phase 3.4 - Traffic Allocation, Version Resolver & Execution Gate.

Two new, additive tables plus the second half of the §15 mapping Phase 3.1
began. No existing column is altered, widened or dropped.

- ``deployment_traffic_allocations`` -- one revision of an agent's weighted
  traffic split in one environment. Revisions are append-only: a weight
  change writes a new row and clears the previous row's ``is_current``, so
  the table doubles as the audit lineage (M3-3.4-FR-004).
- ``deployment_traffic_weights`` -- the (version, deployment, weight) entries
  of one allocation. ``weight`` carries a CHECK for its 0-100 range; the
  set-sums-to-100 invariant is a *transaction-level* guarantee rather than a
  table constraint (see below).

**How sum-to-100 is guaranteed (M3-3.4-FR-001/003).** A SQL CHECK cannot span
sibling rows, and a deferred constraint trigger would add a second place that
understands the invariant. Instead ``TrafficAllocationService.set_weights``
(``app.runtime.deployment.traffic``) validates the complete set *before* any
row is written and inserts the allocation and every one of its weights inside
a single transaction, committing once. A partial or non-100 set therefore
never commits, and never becomes visible to another connection -- the
invariant holds for every *observable* state, which is what FR-003 asks. The
resolver additionally ignores zero-weight and unservable entries at read
time, so it never depends on the stored set being currently routable.

**Concurrency.** ``uq_traffic_allocations_current`` is a *partial* unique
index on ``(agent_id, environment_id) WHERE is_current`` -- the concurrency
primitive for AC-13. Two admins racing to change one agent's weights both try
to insert a current allocation; Postgres admits exactly one, and the loser's
IntegrityError becomes ``TRAFFIC_ALLOCATION_CONFLICT``. No advisory lock is
taken anywhere in this domain, so nothing here can deadlock against the
execution path's own locks (§9). ``uq_traffic_allocations_revision`` keeps
revision numbers unique per (agent, environment) so the lineage cannot fork.

**The §15 step-2 backfill.** Every deployment that is *servable* at upgrade
time and has a governed ``environment_id`` gets a current allocation with a
single 100%% entry: its own current version. "Servable" here is exactly the
union-with-veto predicate the resolver uses (see
``app.runtime.deployment.traffic``) -- ``status='ACTIVE' OR
lifecycle_state='ACTIVE'``, minus the non-serving states of either machine --
because backfilling anything else would either strand a legacy-deployed
agent (status ACTIVE / lifecycle_state DRAFT) or hand traffic to a paused
one.

Where several servable deployments share one (agent, environment), the newest
by ``deployed_at`` wins the 100%% -- the same deployment the pre-3.4 execution
path would have chosen, so no agent's behaviour changes at upgrade. This is
what makes AC-11 true: every agent that could execute before this migration
still executes after it. Deployments with a NULL ``environment_id`` (the
legacy string-only create path) are deliberately skipped -- an allocation is
keyed by a real environment row, and the resolver serves those deployments
through its implicit-100%% rule instead, unchanged.

Reversible: ``downgrade()`` drops both tables and their indexes, restoring
the exact pre-3.4 schema. The backfilled rows live entirely inside the
dropped tables, so the downgrade leaves no residue on any pre-existing table.

Revision ID: 0040_traffic_allocation
Revises: 0039_deployment_preflight
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0040_traffic_allocation"
down_revision: str | None = "0039_deployment_preflight"
branch_labels = None
depends_on = None

# The union-with-veto servability predicate, in SQL. Mirrors
# ``app.runtime.deployment.traffic.servable_clause()`` exactly; kept literal
# here because a migration must not import application code that will keep
# evolving after this revision is pinned in history.
_SERVABLE = """
    (d.status = 'ACTIVE' OR d.lifecycle_state = 'ACTIVE')
    AND d.status NOT IN ('SUSPENDED', 'RETIRED', 'FAILED', 'ROLLING_BACK')
    AND d.lifecycle_state NOT IN ('PAUSED', 'SUPERSEDED', 'RETIRED', 'FAILED',
                                  'ROLLING_BACK', 'REJECTED', 'VALIDATION_FAILED')
"""


def upgrade() -> None:
    op.create_table(
        "deployment_traffic_allocations",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("organization_id", sa.UUID(), sa.ForeignKey("organizations.id", ondelete="CASCADE"),
                 nullable=False),
        sa.Column("agent_id", sa.UUID(), sa.ForeignKey("agents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("environment_id", sa.UUID(), sa.ForeignKey("environments.id", ondelete="CASCADE"),
                 nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("is_current", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("created_by", sa.UUID(), nullable=True),
    )
    op.create_index("ix_deployment_traffic_allocations_organization_id",
                   "deployment_traffic_allocations", ["organization_id"])
    op.create_index("ix_deployment_traffic_allocations_agent_id",
                   "deployment_traffic_allocations", ["agent_id"])
    op.create_index("ix_deployment_traffic_allocations_environment_id",
                   "deployment_traffic_allocations", ["environment_id"])
    # The resolver's hot-path lookup (AC-14): one indexed seek per gated
    # execution on exactly the tuple it queries by.
    op.create_index("ix_traffic_allocations_agent_environment_current",
                   "deployment_traffic_allocations", ["agent_id", "environment_id", "is_current"])
    # AC-13's concurrency primitive -- at most one current allocation per
    # (agent, environment), enforced by the database, not by application
    # timing.
    op.create_index("uq_traffic_allocations_current", "deployment_traffic_allocations",
                   ["agent_id", "environment_id"], unique=True,
                   postgresql_where=sa.text("is_current"))
    op.create_unique_constraint("uq_traffic_allocations_revision", "deployment_traffic_allocations",
                               ["agent_id", "environment_id", "revision"])

    op.create_table(
        "deployment_traffic_weights",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("allocation_id", sa.UUID(),
                 sa.ForeignKey("deployment_traffic_allocations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("agent_version_id", sa.UUID(),
                 sa.ForeignKey("agent_versions.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("deployment_id", sa.UUID(),
                 sa.ForeignKey("agent_deployments.id", ondelete="CASCADE"), nullable=False),
        sa.Column("weight", sa.Integer(), nullable=False),
        sa.CheckConstraint("weight >= 0 AND weight <= 100", name="ck_traffic_weights_range"),
        sa.UniqueConstraint("allocation_id", "agent_version_id",
                           name="uq_traffic_weights_allocation_version"),
    )
    op.create_index("ix_traffic_weights_allocation_id", "deployment_traffic_weights", ["allocation_id"])
    op.create_index("ix_deployment_traffic_weights_agent_version_id",
                   "deployment_traffic_weights", ["agent_version_id"])
    op.create_index("ix_deployment_traffic_weights_deployment_id",
                   "deployment_traffic_weights", ["deployment_id"])

    # ------------------------------------------------------------------ #
    # The §15 step-2 backfill (AC-11) -- see this module's docstring.
    # ------------------------------------------------------------------ #
    connection = op.get_bind()
    # One winning deployment per (agent, environment): the newest by
    # deployed_at, ties broken by id so the result is deterministic and this
    # migration is repeatable against the same data.
    connection.execute(sa.text(f"""
        INSERT INTO deployment_traffic_allocations
            (id, organization_id, agent_id, environment_id, revision, is_current, reason, created_at)
        SELECT gen_random_uuid(), winners.organization_id, winners.agent_id, winners.environment_id,
               1, TRUE,
               'Phase 3.4 §15 step-2 backfill: 100%% to the version this deployment was already serving.',
               now()
        FROM (
            SELECT DISTINCT ON (d.agent_id, d.environment_id)
                   d.organization_id, d.agent_id, d.environment_id
            FROM agent_deployments d
            WHERE d.environment_id IS NOT NULL AND {_SERVABLE}
            ORDER BY d.agent_id, d.environment_id, d.deployed_at DESC NULLS LAST, d.id
        ) AS winners
    """))
    connection.execute(sa.text(f"""
        INSERT INTO deployment_traffic_weights
            (id, allocation_id, agent_version_id, deployment_id, weight)
        SELECT gen_random_uuid(), a.id, winners.agent_version_id, winners.deployment_id, 100
        FROM deployment_traffic_allocations a
        JOIN (
            SELECT DISTINCT ON (d.agent_id, d.environment_id)
                   d.agent_id, d.environment_id, d.agent_version_id, d.id AS deployment_id
            FROM agent_deployments d
            WHERE d.environment_id IS NOT NULL AND {_SERVABLE}
            ORDER BY d.agent_id, d.environment_id, d.deployed_at DESC NULLS LAST, d.id
        ) AS winners
          ON winners.agent_id = a.agent_id AND winners.environment_id = a.environment_id
        WHERE a.revision = 1
    """))


def downgrade() -> None:
    op.drop_index("ix_deployment_traffic_weights_deployment_id", table_name="deployment_traffic_weights")
    op.drop_index("ix_deployment_traffic_weights_agent_version_id", table_name="deployment_traffic_weights")
    op.drop_index("ix_traffic_weights_allocation_id", table_name="deployment_traffic_weights")
    op.drop_table("deployment_traffic_weights")

    op.drop_constraint("uq_traffic_allocations_revision", "deployment_traffic_allocations", type_="unique")
    op.drop_index("uq_traffic_allocations_current", table_name="deployment_traffic_allocations")
    op.drop_index("ix_traffic_allocations_agent_environment_current",
                 table_name="deployment_traffic_allocations")
    op.drop_index("ix_deployment_traffic_allocations_environment_id",
                 table_name="deployment_traffic_allocations")
    op.drop_index("ix_deployment_traffic_allocations_agent_id", table_name="deployment_traffic_allocations")
    op.drop_index("ix_deployment_traffic_allocations_organization_id",
                 table_name="deployment_traffic_allocations")
    op.drop_table("deployment_traffic_allocations")
