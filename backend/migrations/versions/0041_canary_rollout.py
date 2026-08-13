"""Phase 3.5 - Canary Deployment Engine.

Three new tables plus two genuinely necessary indexes on the pre-existing
``agent_executions``. No existing column is altered, widened or dropped, and
the pre-existing ``deployment_health`` table is left completely untouched
(ruling #3 -- see below).

- ``rollout_plans`` -- one governed canary promotion of a candidate version
  within an (agent, environment). Carries the rollout state machine
  (PENDING/IN_PROGRESS/PAUSED/SUCCEEDED/ABORTED/ROLLBACK_REQUESTED/FAILED),
  the current stage pointer, and a ``revision`` optimistic-concurrency guard
  (a SQLAlchemy ``version_id_col``, the same mechanism ``agent_deployments``
  already uses) so two actors advancing one rollout cannot both win.
- ``rollout_stages`` -- the ordered stages and their three gates
  (``min_duration_seconds``, ``min_samples``, ``health_requirement``), plus
  ``target_weight`` and ``advance_mode``. ``entered_at`` is null until the
  stage becomes current.
- ``deployment_health_evaluations`` -- the AI-aware release-health verdicts
  (ruling #3), computed by aggregating ``agent_executions`` over a window.

**Why a new health table rather than widening ``deployment_health``**
(ruling #3, stated here because a future reader will reasonably wonder why
this database has two health tables): they answer different questions.
``deployment_health`` is a liveness heartbeat -- a worker reported in, the
process is up -- written from an external signal by
``HealthMonitoringService.heartbeat``. ``deployment_health_evaluations`` is a
*release* judgement: is this version behaving well enough to earn more
traffic, computed from what actually happened. A heartbeat cannot answer that,
and widening the heartbeat table would have meant one row type carrying two
unrelated meanings. Neither the old table nor any of its rows is modified by
this migration in either direction.

**The two new ``agent_executions`` indexes are load-bearing, not decoration.**
Health evaluation aggregates executions per version over a time window, and
runs on every stage-gate check -- potentially every few seconds for an active
canary. Before this migration that table had *no* index covering such a query:
``agent_version_id`` alone existed (``ix_agent_executions_version``), nothing
touched ``created_at``, and ``deployment_id`` was not indexed at all. Each
evaluation would therefore have scanned a growing share of the platform's
entire execution history.

- ``ix_agent_executions_version_created`` on ``(agent_version_id, created_at)``
  -- the exact shape of the health-aggregation predicate, and the one the
  candidate/baseline queries use.
- ``ix_agent_executions_deployment_created`` on ``(deployment_id, created_at)``
  -- the per-deployment equivalent, and the first index this column has ever
  had.

Reversible: ``downgrade()`` drops the three tables and the two indexes,
restoring the exact pre-3.5 schema. No data backfill in either direction --
rollouts and health evaluations are forward-looking records with nothing
historical to reconstruct (unlike 3.1's lifecycle seed or 3.4's allocation
backfill, both of which had to preserve existing behaviour; nothing here
changes how anything already deployed behaves).

Revision ID: 0041_canary_rollout
Revises: 0040_traffic_allocation
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0041_canary_rollout"
down_revision: str | None = "0040_traffic_allocation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "rollout_plans",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("organization_id", sa.UUID(), sa.ForeignKey("organizations.id", ondelete="CASCADE"),
                 nullable=False),
        sa.Column("agent_id", sa.UUID(), sa.ForeignKey("agents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("environment_id", sa.UUID(), sa.ForeignKey("environments.id", ondelete="CASCADE"),
                 nullable=False),
        sa.Column("candidate_version_id", sa.UUID(),
                 sa.ForeignKey("agent_versions.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("stable_version_id", sa.UUID(),
                 sa.ForeignKey("agent_versions.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("state", sa.String(length=24), nullable=False, server_default="PENDING"),
        sa.Column("current_stage_index", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("state_reason", sa.Text(), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("created_by", sa.UUID(), nullable=True),
    )
    op.create_index("ix_rollout_plans_organization_id", "rollout_plans", ["organization_id"])
    op.create_index("ix_rollout_plans_agent_id", "rollout_plans", ["agent_id"])
    op.create_index("ix_rollout_plans_environment_id", "rollout_plans", ["environment_id"])
    op.create_index("ix_rollout_plans_agent_environment", "rollout_plans",
                   ["agent_id", "environment_id"])
    op.create_index("ix_rollout_plans_state", "rollout_plans", ["state"])

    op.create_table(
        "rollout_stages",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("rollout_plan_id", sa.UUID(),
                 sa.ForeignKey("rollout_plans.id", ondelete="CASCADE"), nullable=False),
        sa.Column("stage_index", sa.Integer(), nullable=False),
        sa.Column("target_weight", sa.Integer(), nullable=False),
        sa.Column("min_duration_seconds", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("min_samples", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("health_requirement", sa.String(length=16), nullable=False, server_default="HEALTHY"),
        sa.Column("advance_mode", sa.String(length=8), nullable=False, server_default="MANUAL"),
        sa.Column("entered_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("target_weight >= 0 AND target_weight <= 100",
                          name="ck_rollout_stages_target_weight_range"),
        sa.UniqueConstraint("rollout_plan_id", "stage_index", name="uq_rollout_stages_plan_index"),
    )
    op.create_index("ix_rollout_stages_plan_index", "rollout_stages",
                   ["rollout_plan_id", "stage_index"])

    op.create_table(
        "deployment_health_evaluations",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("organization_id", sa.UUID(), sa.ForeignKey("organizations.id", ondelete="CASCADE"),
                 nullable=False),
        sa.Column("deployment_id", sa.UUID(),
                 sa.ForeignKey("agent_deployments.id", ondelete="SET NULL"), nullable=True),
        sa.Column("agent_version_id", sa.UUID(),
                 sa.ForeignKey("agent_versions.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("rollout_plan_id", sa.UUID(),
                 sa.ForeignKey("rollout_plans.id", ondelete="CASCADE"), nullable=True),
        sa.Column("health_state", sa.String(length=20), nullable=False),
        sa.Column("sample_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("metrics", JSONB(), nullable=False, server_default="{}"),
        sa.Column("baseline_ref", JSONB(), nullable=True),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False,
                 server_default=sa.func.now()),
        sa.Column("evaluated_by", sa.UUID(), nullable=True),
    )
    op.create_index("ix_deployment_health_evaluations_organization_id",
                   "deployment_health_evaluations", ["organization_id"])
    op.create_index("ix_deployment_health_evaluations_agent_version_id",
                   "deployment_health_evaluations", ["agent_version_id"])
    op.create_index("ix_health_evaluations_deployment_evaluated",
                   "deployment_health_evaluations", ["deployment_id", "evaluated_at"])
    op.create_index("ix_health_evaluations_plan_evaluated",
                   "deployment_health_evaluations", ["rollout_plan_id", "evaluated_at"])

    # See this module's docstring: without these, every stage-gate check
    # scans the platform's execution history.
    op.create_index("ix_agent_executions_version_created", "agent_executions",
                   ["agent_version_id", "created_at"])
    op.create_index("ix_agent_executions_deployment_created", "agent_executions",
                   ["deployment_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_agent_executions_deployment_created", table_name="agent_executions")
    op.drop_index("ix_agent_executions_version_created", table_name="agent_executions")

    op.drop_index("ix_health_evaluations_plan_evaluated", table_name="deployment_health_evaluations")
    op.drop_index("ix_health_evaluations_deployment_evaluated",
                 table_name="deployment_health_evaluations")
    op.drop_index("ix_deployment_health_evaluations_agent_version_id",
                 table_name="deployment_health_evaluations")
    op.drop_index("ix_deployment_health_evaluations_organization_id",
                 table_name="deployment_health_evaluations")
    op.drop_table("deployment_health_evaluations")

    op.drop_index("ix_rollout_stages_plan_index", table_name="rollout_stages")
    op.drop_table("rollout_stages")

    op.drop_index("ix_rollout_plans_state", table_name="rollout_plans")
    op.drop_index("ix_rollout_plans_agent_environment", table_name="rollout_plans")
    op.drop_index("ix_rollout_plans_environment_id", table_name="rollout_plans")
    op.drop_index("ix_rollout_plans_agent_id", table_name="rollout_plans")
    op.drop_index("ix_rollout_plans_organization_id", table_name="rollout_plans")
    op.drop_table("rollout_plans")
