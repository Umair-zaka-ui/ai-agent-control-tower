"""Phase 3.8 - Distributed Scheduler.

Two new tables, deliberately the minimum coherent model (SRS section 14 warns
against a table per noun). The build prompt offered ``JobLease`` and
``JobAttempt`` as possible separate tables; both are columns on ``job_runs``
here instead, and the reason is not brevity:

- A **lease** has no life of its own. It exists only while a run is being
  attempted, it is owned by exactly one run, and it dies with that run. A
  separate table would add a join to the hottest query in the system (the
  stale-lease scan) to model a strict one-to-one.
- An **attempt** does not need independent history here because a retry
  deliberately *reuses the same run row* rather than creating a new one. That
  is what makes exactly-once-per-occurrence structural rather than
  best-effort: there is one row per scheduled occurrence, it carries an
  ``attempt`` counter, and it ends in exactly one terminal state no matter how
  many instances touched it.

- ``job_definitions`` -- what to run, when, and under which policies. A
  ``handler_key`` referencing the code registry rather than an import path or
  a callable name: the scheduler dispatches only handlers that were
  deliberately registered, so a row in this table can never make it execute
  arbitrary code (``JOB_HANDLER_UNKNOWN``). ``organization_id`` is nullable --
  null means a platform-level job, which is why it is not simply
  ``NOT NULL`` like almost every other tenant-scoped table here.
  ``next_run_at`` is stored rather than recomputed on every poll so the
  due-job scan is a single indexed range query instead of a table scan plus
  per-row schedule arithmetic.

- ``job_runs`` -- one row per *scheduled occurrence*, carrying its own lease.
  ``uq_job_runs_occurrence`` on ``(job_definition_id, occurrence_key)`` is the
  exactly-once guard (M3-3.8-FR-014): two instances that both compute the same
  due occurrence cannot both create a run for it, because the second INSERT
  loses to the unique index. The database decides, not application timing --
  the same primitive Phase 3.4 used for ``uq_traffic_allocations_current`` and
  3.7 for ``uq_rollback_events_dedup``.

**Why the claim uses the definition row and not the run row.** A run row does
not exist yet at claim time, and you cannot ``SELECT ... FOR UPDATE SKIP
LOCKED`` a row that has not been inserted. The claim therefore locks the
*definition* with SKIP LOCKED -- so a second instance skips that job entirely
rather than blocking on it -- inserts the run, advances ``next_run_at``, and
commits. The unique index remains as the second line of defence for the case
the lock cannot cover: the same occurrence being computed again later, after
the lock has been released.

``ix_job_definitions_due`` is the due-scan index and is partial on
``enabled``: a disabled job should cost nothing to skip, and on a system with
many one-time jobs already fired, most rows are exactly that.

``ix_job_runs_stale`` serves the recovery scan (expired lease, still
non-terminal). Both are load-bearing rather than decorative -- the scheduler
polls both queries on every tick of every instance, so an unindexed variant
would put a sequential scan in the hot loop of a distributed system.

Reversible: ``downgrade()`` drops both tables, restoring the exact pre-3.8
schema. No data backfill in either direction -- job definitions are created
explicitly, and inventing them for existing tenants would silently start
running work nobody scheduled. The connector-health sweep that the interim
in-process scheduler used to run is registered as a definition by the
application's own seeding path, not by this migration, so that a downgrade
cannot leave orphaned rows behind and an upgrade cannot start automation
during a migration.

Revision ID: 0043_distributed_scheduler
Revises: 0042_automated_rollback
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "0043_distributed_scheduler"
down_revision: str | None = "0042_automated_rollback"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "job_definitions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        # Null = a platform-level job (the connector-health sweep, retention
        # cleanup). Tenant jobs carry their organization.
        sa.Column("organization_id", UUID(as_uuid=True),
                  sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("handler_key", sa.String(64), nullable=False),
        sa.Column("schedule_kind", sa.String(16), nullable=False, server_default="INTERVAL"),
        sa.Column("schedule_spec", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("params", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("timeout_seconds", sa.Integer, nullable=False, server_default="300"),
        sa.Column("retry_policy", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("concurrency_policy", sa.String(16), nullable=False,
                  server_default="NO_OVERLAP"),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("created_by", UUID(as_uuid=True), nullable=True),
        sa.CheckConstraint("schedule_kind IN ('INTERVAL', 'ONE_TIME')",
                           name="ck_job_definitions_schedule_kind"),
        sa.CheckConstraint("concurrency_policy IN ('NO_OVERLAP', 'ALLOW')",
                           name="ck_job_definitions_concurrency"),
        sa.CheckConstraint("timeout_seconds > 0", name="ck_job_definitions_timeout"),
        sa.UniqueConstraint("organization_id", "name", name="uq_job_definitions_org_name"),
    )
    op.create_index("ix_job_definitions_org", "job_definitions", ["organization_id"])
    op.create_index("ix_job_definitions_due", "job_definitions", ["next_run_at"],
                    postgresql_where=sa.text("enabled"))

    op.create_table(
        "job_runs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("job_definition_id", UUID(as_uuid=True),
                  sa.ForeignKey("job_definitions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("organization_id", UUID(as_uuid=True),
                  sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=True),
        sa.Column("occurrence_key", sa.String(128), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="CLAIMED"),
        sa.Column("attempt", sa.Integer, nullable=False, server_default="1"),
        sa.Column("lease_owner", sa.String(100), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("result", JSONB, nullable=True),
        sa.Column("error", sa.Text, nullable=True),
        sa.Column("recovered_from", sa.String(100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.CheckConstraint(
            "status IN ('CLAIMED', 'RUNNING', 'SUCCEEDED', 'FAILED', 'TIMED_OUT', 'ABANDONED')",
            name="ck_job_runs_status"),
        # The exactly-once guard.
        sa.UniqueConstraint("job_definition_id", "occurrence_key",
                            name="uq_job_runs_occurrence"),
    )
    op.create_index("ix_job_runs_definition_created", "job_runs",
                    ["job_definition_id", "created_at"])
    # The stale-lease recovery scan: non-terminal runs whose lease has lapsed.
    op.create_index("ix_job_runs_stale", "job_runs", ["lease_expires_at"],
                    postgresql_where=sa.text("status IN ('CLAIMED', 'RUNNING')"))


def downgrade() -> None:
    op.drop_index("ix_job_runs_stale", table_name="job_runs")
    op.drop_index("ix_job_runs_definition_created", table_name="job_runs")
    op.drop_table("job_runs")
    op.drop_index("ix_job_definitions_due", table_name="job_definitions")
    op.drop_index("ix_job_definitions_org", table_name="job_definitions")
    op.drop_table("job_definitions")
