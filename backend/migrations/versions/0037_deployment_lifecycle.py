"""Phase 3.1 - Enterprise Deployment Core.

Extends the existing, verified ``agent_deployments`` table (no
``deployments_v2``, no parallel domain) and adds two new, additive tables:

- ``lifecycle_state``/``revision``/``state_reason``/``superseded_by_deployment_id``
  on ``agent_deployments`` -- the new 15-state governed lifecycle
  (``app.runtime.deployment.lifecycle``) and its optimistic-concurrency
  guard (``revision`` is a SQLAlchemy ``version_id_col``). The pre-existing
  ``status`` column (narrower, Phase 5.0) is left entirely in place and
  untouched -- every legacy ``DeploymentService`` method keeps reading and
  writing it exactly as before; so do ``desired_replicas``/``active_replicas``
  (vestigial, per REPO_STATE's own §27 analysis -- neither is read or
  written anywhere in the new lifecycle).
- ``deployment_events`` -- append-only lifecycle lineage (one row per
  transition), distinct from the platform-wide audit trail and the
  pre-existing ``runtime_events`` Operations Center feed (both still
  written, unchanged, alongside this).
- ``idempotency_keys`` -- the reusable, platform-wide ``Idempotency-Key``
  contract (ACT-SRS-M3 §3.1 FR-010..013), scoped to ``(organization,
  operation)`` -- deliberately not the same table as the pre-existing,
  narrower ``idempotency_records`` (Phase 5.0 §33, execution-specific, and
  on the M1 execution path this phase must not touch).

The deterministic §15 mapping applied to every existing ``agent_deployments``
row (the eleven legacy ``status`` values -> the new ``lifecycle_state``)::

    CREATED          -> DRAFT             (hasn't gone through the new
                                            validation/approval pipeline yet)
    PENDING_APPROVAL  -> PENDING_APPROVAL  (direct match)
    SCHEDULED         -> DEPLOYING         (closest equivalent: about to
                                            deploy, not yet serving)
    DEPLOYING         -> DEPLOYING         (direct match)
    HEALTH_CHECKING   -> DEPLOYING         (closest equivalent: mid-activation,
                                            not yet confirmed serving)
    ACTIVE            -> ACTIVE            (direct match -- a currently-serving
                                            deployment lands ACTIVE, per spec)
    DEGRADED          -> DEGRADED          (direct match)
    FAILED            -> FAILED            (direct match)
    SUSPENDED         -> PAUSED            (direct semantic match: was active,
                                            not serving, still intact)
    ROLLING_BACK      -> ROLLING_BACK      (direct match)
    RETIRED           -> RETIRED           (direct match)

No allocation backfill here -- that is Phase 3.4's own half of this same §15
mapping, per this phase's explicit scope boundary (this phase seeds
lifecycle, 3.4 backfills traffic allocation). No ``deployment_events`` row is
synthesized for historical transitions that predate this table -- lineage
starts from this migration forward, not retroactively invented.

Reversible: ``downgrade()`` drops the two new tables and the four new
``agent_deployments`` columns, restoring the exact pre-3.1 schema; no
existing column, row, or value is altered by the downgrade.

Revision ID: 0037_deployment_lifecycle
Revises: 0036_identity_federation
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0037_deployment_lifecycle"
down_revision: str | None = "0036_identity_federation"
branch_labels = None
depends_on = None

_STATUS_TO_LIFECYCLE_STATE: dict[str, str] = {
    "CREATED": "DRAFT",
    "PENDING_APPROVAL": "PENDING_APPROVAL",
    "SCHEDULED": "DEPLOYING",
    "DEPLOYING": "DEPLOYING",
    "HEALTH_CHECKING": "DEPLOYING",
    "ACTIVE": "ACTIVE",
    "DEGRADED": "DEGRADED",
    "FAILED": "FAILED",
    "SUSPENDED": "PAUSED",
    "ROLLING_BACK": "ROLLING_BACK",
    "RETIRED": "RETIRED",
}


def upgrade() -> None:
    op.add_column("agent_deployments", sa.Column(
        "lifecycle_state", sa.String(length=24), nullable=False, server_default="DRAFT"))
    op.add_column("agent_deployments", sa.Column(
        "revision", sa.Integer(), nullable=False, server_default="1"))
    op.add_column("agent_deployments", sa.Column("state_reason", sa.Text(), nullable=True))
    op.add_column("agent_deployments", sa.Column("superseded_by_deployment_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        "fk_agent_deployments_superseded_by", "agent_deployments", "agent_deployments",
        ["superseded_by_deployment_id"], ["id"], ondelete="SET NULL",
    )
    op.create_index("ix_agent_deployments_lifecycle_state", "agent_deployments", ["lifecycle_state"])

    connection = op.get_bind()
    for status, lifecycle_state in _STATUS_TO_LIFECYCLE_STATE.items():
        connection.execute(
            sa.text(
                "UPDATE agent_deployments SET lifecycle_state = :lifecycle_state, "
                "state_reason = :reason WHERE status = :status"
            ),
            {"lifecycle_state": lifecycle_state, "status": status,
             "reason": f"migrated from legacy status={status} (Phase 3.1 §15 mapping)"},
        )
    # Any row whose legacy status is not one of the eleven known values
    # (none are expected in this codebase's history) simply keeps the column
    # default, DRAFT, rather than the migration crashing on an unknown value.

    op.create_table(
        "deployment_events",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("deployment_id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("from_state", sa.String(length=24), nullable=True),
        sa.Column("to_state", sa.String(length=24), nullable=False),
        sa.Column("event_type", sa.String(length=48), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("actor_id", sa.UUID(), nullable=True),
        sa.Column("idempotency_key", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["deployment_id"], ["agent_deployments.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_deployment_events_deployment_id", "deployment_events", ["deployment_id"])
    op.create_index("ix_deployment_events_organization_id", "deployment_events", ["organization_id"])
    op.create_index("ix_deployment_events_event_type", "deployment_events", ["event_type"])
    op.create_index(
        "ix_deployment_events_deployment_created", "deployment_events", ["deployment_id", "created_at"])

    op.create_table(
        "idempotency_keys",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("operation", sa.String(length=64), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("result_ref", JSONB(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_idempotency_keys_organization_id", "idempotency_keys", ["organization_id"])
    op.create_unique_constraint(
        "uq_idempotency_keys_scope", "idempotency_keys",
        ["organization_id", "operation", "idempotency_key"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_idempotency_keys_scope", "idempotency_keys", type_="unique")
    op.drop_index("ix_idempotency_keys_organization_id", "idempotency_keys")
    op.drop_table("idempotency_keys")

    op.drop_index("ix_deployment_events_deployment_created", "deployment_events")
    op.drop_index("ix_deployment_events_event_type", "deployment_events")
    op.drop_index("ix_deployment_events_organization_id", "deployment_events")
    op.drop_index("ix_deployment_events_deployment_id", "deployment_events")
    op.drop_table("deployment_events")

    op.drop_index("ix_agent_deployments_lifecycle_state", "agent_deployments")
    op.drop_constraint("fk_agent_deployments_superseded_by", "agent_deployments", type_="foreignkey")
    op.drop_column("agent_deployments", "superseded_by_deployment_id")
    op.drop_column("agent_deployments", "state_reason")
    op.drop_column("agent_deployments", "revision")
    op.drop_column("agent_deployments", "lifecycle_state")
