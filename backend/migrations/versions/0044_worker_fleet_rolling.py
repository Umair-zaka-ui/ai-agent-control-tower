"""Phase 3.9 - Distributed Execution Worker Fleet & Rolling Deployment.

One new table and two new columns. The restraint is deliberate and worth
explaining, because the obvious design for this phase is much larger.

**Why there is no new execution-lease table.** The build prompt allowed one,
but M1 already built the lease: ``execution_locks`` carries ``worker_id``,
``acquired_at``, ``expires_at`` and ``heartbeat_at``, with ``execution_id``
UNIQUE (``uq_execution_locks_execution``, migration 0023). That unique
constraint *is* the no-duplicate-execution guarantee -- two workers cannot
both hold a claim on one execution because the database will not let them,
and no amount of application timing can talk it out of that. Adding a second
lease table beside it would create two sources of truth for one fact, which is
exactly how a distributed system starts lying about who owns what. This phase
therefore extends the M1 claim rather than paralleling it, as §5 instructed.

**Why there is no rolling-plan table.** Rolling is a progressive, gated,
pausable, abortable weight transition that must integrate with rollback. Phase
3.5 already built precisely that machine -- ``rollout_plans`` +
``rollout_stages``, with a seven-state transition graph, per-stage health
gates, optimistic concurrency and idempotency. A ``rolling_deployments`` table
would have been a second copy of it, differing only in where the stage weights
come from. So rolling reuses the machine and this migration adds the one thing
that genuinely differs:

- ``rollout_plans.kind`` -- ``CANARY`` or ``ROLLING``. Defaulted to
  ``CANARY`` server-side so every existing row and every existing 3.5 code
  path keeps its exact current meaning. The two share an engine but are not
  the same operation, and an operator reading a plan must be told which one
  they are looking at.

- ``rollout_plans.cohort_plan`` -- the fleet snapshot the stage weights were
  derived from. This is evidence, not state. A rolling deployment's steps are
  computed from the *real* registered fleet at creation time (a fleet of two
  cohorts holding 8 and 2 slots of capacity produces steps of 80% and 100%,
  not an invented 25/50/75/100), and the fleet changes constantly. Without
  this column, a rollout's own step sizes become unexplainable minutes after
  it starts -- "why 80?" would have no answer anywhere in the system. Nullable
  because a canary plan has no cohort derivation and must not pretend to.

**``worker_registrations`` is deliberately ephemeral-recoverable.** It records
which worker processes exist, what capacity they declare, and when they were
last alive. None of it is authoritative after a restart or a restore: a
registration whose ``heartbeat_at`` has lapsed describes a process that is
gone, and the recovery path treats it as gone (SRS §16, RECOVERY.md's
durable/ephemeral split). Nothing here is backed up for its content's sake --
it is rebuilt in seconds by the workers themselves re-registering. What must
*not* be lost is the executions those workers were running, and those live in
``agent_executions``, which is durable and untouched by this migration.

``worker_id`` is UNIQUE: a worker process re-registering after a restart
updates its own row rather than accumulating a new one per restart, so the
fleet view shows processes rather than process history.

Two indexes, both load-bearing rather than decorative:

- ``ix_worker_registrations_stale`` on ``heartbeat_at``, partial on the
  non-STOPPED statuses -- the staleness sweep runs on every reaper pass and a
  STOPPED worker is already accounted for, so it should cost nothing to skip.
- ``ix_worker_registrations_cohort`` on ``(cohort, status)`` -- rolling reads
  live capacity per cohort every time it derives or re-validates a step.

**The vestigial replica columns on ``agent_deployments`` are not touched, not
read, and not named by any code this phase adds.** Rolling is defined over
real registered worker capacity. That was the whole point of deferring it in
3.6, and implementing it against those columns now would be the pretence SRS
§3.6 forbids, just a phase later.

Reversible: ``downgrade()`` drops the table and both columns, restoring the
exact pre-3.9 schema. No backfill in either direction -- worker rows are
created by workers starting up, and inventing them would put phantom capacity
in the fleet view that rolling would then derive real step sizes from.

Revision ID: 0044_worker_fleet_rolling
Revises: 0043_distributed_scheduler
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "0044_worker_fleet_rolling"
down_revision: str | None = "0043_distributed_scheduler"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "worker_registrations",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        # The process identity. Unique so a restart updates rather than
        # accumulates -- the fleet view lists processes, not process history.
        sa.Column("worker_id", sa.String(100), nullable=False),
        # The rolling unit. A plain declared label: workers that share one are
        # one cohort, and rolling converts the fleet a cohort at a time.
        sa.Column("cohort", sa.String(64), nullable=False, server_default="default"),
        sa.Column("status", sa.String(16), nullable=False, server_default="RUNNING"),
        # Declared capacity: how many executions this process runs at once.
        sa.Column("concurrency", sa.Integer, nullable=False, server_default="1"),
        # In-flight count, reported by the worker on each heartbeat. Advisory
        # (the authoritative in-flight set is execution_locks), but it is what
        # makes backpressure and queue depth answerable without a join.
        sa.Column("active_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("hostname", sa.String(255), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("registered_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("stopped_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("status IN ('RUNNING', 'DRAINING', 'STOPPED')",
                           name="ck_worker_registrations_status"),
        sa.CheckConstraint("concurrency > 0", name="ck_worker_registrations_concurrency"),
        sa.CheckConstraint("active_count >= 0", name="ck_worker_registrations_active_count"),
        sa.UniqueConstraint("worker_id", name="uq_worker_registrations_worker_id"),
    )
    # The staleness sweep. A STOPPED worker has already been accounted for,
    # so it is excluded rather than scanned and skipped.
    op.create_index("ix_worker_registrations_stale", "worker_registrations", ["heartbeat_at"],
                    postgresql_where=sa.text("status <> 'STOPPED'"))
    # Rolling's capacity read: live slots per cohort.
    op.create_index("ix_worker_registrations_cohort", "worker_registrations",
                    ["cohort", "status"])

    # Rolling reuses Phase 3.5's rollout engine. These two columns are the
    # entire schema difference between a canary and a rolling deployment.
    op.add_column("rollout_plans",
                  sa.Column("kind", sa.String(16), nullable=False, server_default="CANARY"))
    op.add_column("rollout_plans", sa.Column("cohort_plan", JSONB, nullable=True))
    op.create_check_constraint(
        "ck_rollout_plans_kind", "rollout_plans", "kind IN ('CANARY', 'ROLLING')")


def downgrade() -> None:
    op.drop_constraint("ck_rollout_plans_kind", "rollout_plans", type_="check")
    op.drop_column("rollout_plans", "cohort_plan")
    op.drop_column("rollout_plans", "kind")
    op.drop_index("ix_worker_registrations_cohort", table_name="worker_registrations")
    op.drop_index("ix_worker_registrations_stale", table_name="worker_registrations")
    op.drop_table("worker_registrations")
