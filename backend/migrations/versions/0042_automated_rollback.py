"""Phase 3.7 - Automated Rollback & Release Safety.

Two new tables. No existing column is altered, widened or dropped, and
``agent_versions.rollback_target_id`` -- the field this phase finally makes
*authoritative* -- is not touched by this migration at all. That is deliberate
and worth stating, because the build prompt anticipated a schema change here
and none is needed: the column has existed since ``0025_agent_versioning``
with the right shape (a self-referential FK to ``agent_versions`` with
``ON DELETE SET NULL``), it was already being written as lineage, and Phase
3.6 already reads it to perform a blue-green rollback. What was missing was
never storage -- it was a policy that designates it and a unified operation
that honours it. Both are code, not columns.

- ``rollback_trigger_policies`` -- the per-tenant, optionally per-environment
  and per-agent threshold rules that decide when an automatic rollback fires.
  ``thresholds`` is JSONB rather than a column per rule so a new signal can be
  added without a migration, matching how ``environments.policy`` already
  carries this platform's other governed threshold sets. ``mode`` is
  ``AUTO_EXECUTE`` or ``NOTIFY_ONLY``: an organization may reasonably want
  alerting before it wants automation, and that choice is theirs rather than
  ours. ``min_samples`` is the INSUFFICIENT_DATA floor -- below it no trigger
  may fire, mirroring Phase 3.5's own discipline (a thin sample is not
  evidence of failure any more than it is evidence of health).

- ``rollback_events`` -- append-only, one row per rollback that actually
  happened, whatever fired it (``MANUAL``/``REQUESTED``/``AUTOMATIC``/
  ``FORCED``). Carries ``from_version_id``/``to_version_id`` so the record
  survives independently of any later lineage change, and ``evidence_ref``
  JSONB holding the candidate's metrics *at the moment of rollback*
  (M3-3.7-FR-012). Evidence preservation is the point: a rolled-back
  candidate is the thing an engineer most needs to diagnose, and rolling back
  must not be the act that destroys the reason.

**Why ``rollback_events`` is not merely an audit event.** The platform's
audit trail already records rollbacks and continues to. This table exists
because the trigger engine must *read* rollback history to enforce anti-flap
(a cooldown keyed on the most recent rollback for an agent+environment) and
to deduplicate one threshold crossing into exactly one rollback. Querying an
append-only, indexed, purpose-shaped table for that is honest; scraping the
generic audit log for control-flow decisions would not be, and would couple
safety behaviour to an observability surface that is free to change.

The ``uq_rollback_events_dedup`` partial unique index is the deduplication
primitive, in the same spirit as Phase 3.4's
``uq_traffic_allocations_current``: the database, not application timing,
decides who wins when two evaluations fire for one crossing. It covers
automatic rollbacks only -- a human is allowed to roll back the same
deployment twice, and being told "no" by a uniqueness constraint would be
absurd; automation is not.

Reversible: ``downgrade()`` drops both tables, restoring the exact pre-3.7
schema. No data backfill in either direction -- there is no historical
rollback intent to reconstruct, and inventing trigger policies for existing
tenants would silently arm automation nobody asked for. Policies are created
explicitly or not at all; absent a policy, nothing fires.

Revision ID: 0042_automated_rollback
Revises: 0041_canary_rollout
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "0042_automated_rollback"
down_revision: str | None = "0041_canary_rollout"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "rollback_trigger_policies",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", UUID(as_uuid=True),
                  sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        # Null environment_id means "the organization default"; a row naming an
        # environment overrides it, and a row naming an agent overrides that.
        sa.Column("environment_id", UUID(as_uuid=True),
                  sa.ForeignKey("environments.id", ondelete="CASCADE"), nullable=True),
        sa.Column("agent_id", UUID(as_uuid=True),
                  sa.ForeignKey("agents.id", ondelete="CASCADE"), nullable=True),
        sa.Column("thresholds", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("mode", sa.String(16), nullable=False, server_default="AUTO_EXECUTE"),
        sa.Column("min_samples", sa.Integer, nullable=False, server_default="20"),
        sa.Column("cooldown_seconds", sa.Integer, nullable=False, server_default="900"),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("created_by", UUID(as_uuid=True), nullable=True),
        sa.CheckConstraint("mode IN ('AUTO_EXECUTE', 'NOTIFY_ONLY')",
                           name="ck_rollback_trigger_policies_mode"),
        sa.CheckConstraint("min_samples >= 1", name="ck_rollback_trigger_policies_min_samples"),
        sa.CheckConstraint("cooldown_seconds >= 0",
                           name="ck_rollback_trigger_policies_cooldown"),
    )
    op.create_index("ix_rollback_trigger_policies_org", "rollback_trigger_policies",
                    ["organization_id"])
    op.create_index("ix_rollback_trigger_policies_scope", "rollback_trigger_policies",
                    ["organization_id", "environment_id", "agent_id"])
    # One policy per exact scope. ``NULLS NOT DISTINCT`` is deliberately *not*
    # used (it needs PostgreSQL 15+ and this codebase does not otherwise
    # require it); instead the service resolves most-specific-wins and the
    # index below simply keeps identical fully-specified scopes from
    # multiplying.
    op.create_index("uq_rollback_trigger_policies_agent_scope", "rollback_trigger_policies",
                    ["organization_id", "environment_id", "agent_id"], unique=True,
                    postgresql_where=sa.text("environment_id IS NOT NULL AND agent_id IS NOT NULL"))

    op.create_table(
        "rollback_events",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", UUID(as_uuid=True),
                  sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("deployment_id", UUID(as_uuid=True),
                  sa.ForeignKey("agent_deployments.id", ondelete="CASCADE"), nullable=False),
        sa.Column("agent_id", UUID(as_uuid=True),
                  sa.ForeignKey("agents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("environment_id", UUID(as_uuid=True),
                  sa.ForeignKey("environments.id", ondelete="SET NULL"), nullable=True),
        sa.Column("rollout_plan_id", UUID(as_uuid=True),
                  sa.ForeignKey("rollout_plans.id", ondelete="SET NULL"), nullable=True),
        sa.Column("from_version_id", UUID(as_uuid=True),
                  sa.ForeignKey("agent_versions.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("to_version_id", UUID(as_uuid=True),
                  sa.ForeignKey("agent_versions.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("trigger", sa.String(24), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="COMPLETED"),
        sa.Column("reason", sa.Text, nullable=True),
        sa.Column("justification", sa.Text, nullable=True),
        sa.Column("evidence_ref", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("policy_id", UUID(as_uuid=True),
                  sa.ForeignKey("rollback_trigger_policies.id", ondelete="SET NULL"), nullable=True),
        # Null for an automatic rollback: no human initiated it, and writing a
        # system user id here would make the audit trail claim a person acted.
        sa.Column("initiated_by", UUID(as_uuid=True), nullable=True),
        sa.Column("dedup_key", sa.String(200), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("trigger IN ('MANUAL', 'REQUESTED', 'AUTOMATIC', 'FORCED')",
                           name="ck_rollback_events_trigger"),
        sa.CheckConstraint("status IN ('IN_PROGRESS', 'COMPLETED', 'FAILED')",
                           name="ck_rollback_events_status"),
    )
    op.create_index("ix_rollback_events_deployment_created", "rollback_events",
                    ["deployment_id", "created_at"])
    op.create_index("ix_rollback_events_org", "rollback_events", ["organization_id"])
    # Anti-flap and resume both read this shape: the most recent rollback for
    # an (agent, environment).
    op.create_index("ix_rollback_events_agent_env_created", "rollback_events",
                    ["agent_id", "environment_id", "created_at"])
    # The deduplication primitive (M3-3.7-FR-022 / AC-07). One automatic
    # rollback per threshold crossing, decided by the database rather than by
    # application timing. Manual and forced rollbacks are deliberately outside
    # it -- see the module docstring.
    op.create_index("uq_rollback_events_dedup", "rollback_events", ["dedup_key"], unique=True,
                    postgresql_where=sa.text("dedup_key IS NOT NULL"))


def downgrade() -> None:
    op.drop_index("uq_rollback_events_dedup", table_name="rollback_events")
    op.drop_index("ix_rollback_events_agent_env_created", table_name="rollback_events")
    op.drop_index("ix_rollback_events_org", table_name="rollback_events")
    op.drop_index("ix_rollback_events_deployment_created", table_name="rollback_events")
    op.drop_table("rollback_events")
    op.drop_index("uq_rollback_trigger_policies_agent_scope",
                  table_name="rollback_trigger_policies")
    op.drop_index("ix_rollback_trigger_policies_scope", table_name="rollback_trigger_policies")
    op.drop_index("ix_rollback_trigger_policies_org", table_name="rollback_trigger_policies")
    op.drop_table("rollback_trigger_policies")
