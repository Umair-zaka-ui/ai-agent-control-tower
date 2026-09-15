"""Phase 5.7 (M5.7) - External Agent Governance Bridge.

Additive, reversible, tenant-scoped. Three new tables and **one new nullable
column** on ``agents``; no existing column changed, no data backfill needed.

  * ``agents.external_enforcement_mode`` - the storable half of the
    enforcement mode. Its CHECK constraint admits only
    OBSERVED/ADVISORY/GATEWAY_ENFORCED: **``NATIVE_ENFORCED`` cannot be
    written into this database at all.** Full enforcement is derived from
    ``control_state = 'GOVERNED'`` (the same signal Phase 5.6's
    truthful-containment gate reads), so a row cannot claim control ACT does
    not have. NULL means "not classified", which
    ``app.bridge.modes.effective_mode`` reads as OBSERVED - the weakest
    truthful claim - so every pre-existing row gets an honest mode with no
    backfill: native rows are GOVERNED and therefore NATIVE_ENFORCED;
    discovered/claimed/registered rows are OBSERVED.

  * ``external_capability_grants`` - a scoped, expiring, revocable,
    rate-limited signing credential for an agent outside ACT. Not an internal
    principal: no ``users`` row, no role, no session.

  * ``external_request_nonces`` - the replay ledger. The unique constraint on
    ``(grant_id, nonce)`` *is* the anti-replay primitive.

  * ``external_gateway_calls`` - one row per boundary decision, including the
    real ``AuthorizationGateway`` verdict it reused. Note
    ``ck_ext_calls_denied_never_dispatched``: the database itself refuses to
    hold a denied call that carries a dispatch.

Revision ID: 0060_external_gov_bridge
Revises: 0059_threat_containment
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0060_external_gov_bridge"
down_revision = "0059_threat_containment"
branch_labels = None
depends_on = None

_STORABLE_MODES = ("OBSERVED", "ADVISORY", "GATEWAY_ENFORCED")
_OUTCOMES = ("ALLOWED", "DENIED")
_DISPATCH = ("NOT_DISPATCHED", "DISPATCHED", "DISPATCH_FAILED")
_FAIL_MODES = ("FAIL_CLOSED", "FAIL_OPEN")
_POLICY = ("NOT_APPLICABLE", "SATISFIED", "APPROVAL_REQUIRED", "UNEVALUABLE")
_COST = ("NOT_MEASURABLE", "WITHIN_BUDGET", "EXCEEDED", "UNEVALUABLE")


def upgrade() -> None:
    op.add_column("agents", sa.Column("external_enforcement_mode",
                                      sa.String(length=20), nullable=True))
    op.create_check_constraint(
        "ck_agents_external_enforcement_mode", "agents",
        f"external_enforcement_mode IS NULL OR external_enforcement_mode IN {_STORABLE_MODES}",
    )

    op.create_table(
        "external_capability_grants",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("agents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("label", sa.String(length=100), nullable=False),
        sa.Column("key_id", sa.String(length=64), nullable=False),
        sa.Column("secret_ciphertext", sa.Text(), nullable=False),
        sa.Column("secret_hint", sa.String(length=32), nullable=False),
        sa.Column("scope", postgresql.JSONB(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("revocation_reason", sa.Text(), nullable=True),
        sa.Column("rate_limit_per_minute", sa.Integer(), nullable=False, server_default="60"),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.UniqueConstraint("key_id", name="uq_ext_grants_key_id"),
        sa.UniqueConstraint("organization_id", "agent_id", "label",
                            name="uq_ext_grants_org_agent_label"),
        sa.CheckConstraint("rate_limit_per_minute > 0", name="ck_ext_grants_rate_limit"),
    )
    op.create_index("ix_external_capability_grants_organization_id",
                    "external_capability_grants", ["organization_id"])
    op.create_index("ix_external_capability_grants_agent_id",
                    "external_capability_grants", ["agent_id"])
    op.create_index("ix_ext_grants_org_agent", "external_capability_grants",
                    ["organization_id", "agent_id"])

    op.create_table(
        "external_request_nonces",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("grant_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("external_capability_grants.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("nonce", sa.String(length=128), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.UniqueConstraint("grant_id", "nonce", name="uq_ext_nonce_grant_nonce"),
    )
    op.create_index("ix_external_request_nonces_organization_id",
                    "external_request_nonces", ["organization_id"])
    op.create_index("ix_ext_nonce_expires", "external_request_nonces", ["expires_at"])

    op.create_table(
        "external_gateway_calls",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("agents.id", ondelete="CASCADE"), nullable=False),
        # SET NULL: deleting a grant must not erase the record of what it did.
        sa.Column("grant_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("external_capability_grants.id", ondelete="SET NULL"),
                  nullable=True),
        sa.Column("capability_key", sa.String(length=64), nullable=False),
        sa.Column("target_ref", sa.String(length=255), nullable=True),
        sa.Column("enforcement_mode_at_time", sa.String(length=20), nullable=False),
        sa.Column("authz_decision", sa.String(length=32), nullable=False),
        sa.Column("authz_permission", sa.String(length=128), nullable=False),
        sa.Column("authz_reason", sa.Text(), nullable=True),
        sa.Column("authz_request_id", sa.String(length=128), nullable=True),
        sa.Column("policy_outcome", sa.String(length=24), nullable=False),
        sa.Column("policy_detail", postgresql.JSONB(), nullable=True),
        sa.Column("cost_outcome", sa.String(length=24), nullable=False),
        sa.Column("cost_detail", postgresql.JSONB(), nullable=True),
        sa.Column("outcome", sa.String(length=16), nullable=False),
        sa.Column("denial_reason", sa.Text(), nullable=True),
        sa.Column("fail_mode", sa.String(length=16), nullable=False),
        sa.Column("dispatch_status", sa.String(length=24), nullable=False,
                  server_default="NOT_DISPATCHED"),
        sa.Column("dispatch_detail", postgresql.JSONB(), nullable=True),
        sa.Column("idempotency_key", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.CheckConstraint(f"outcome IN {_OUTCOMES}", name="ck_ext_calls_outcome"),
        sa.CheckConstraint(f"dispatch_status IN {_DISPATCH}", name="ck_ext_calls_dispatch"),
        sa.CheckConstraint(f"fail_mode IN {_FAIL_MODES}", name="ck_ext_calls_fail_mode"),
        sa.CheckConstraint(f"policy_outcome IN {_POLICY}", name="ck_ext_calls_policy"),
        sa.CheckConstraint(f"cost_outcome IN {_COST}", name="ck_ext_calls_cost"),
        sa.CheckConstraint("outcome = 'ALLOWED' OR dispatch_status = 'NOT_DISPATCHED'",
                           name="ck_ext_calls_denied_never_dispatched"),
    )
    op.create_index("ix_external_gateway_calls_organization_id",
                    "external_gateway_calls", ["organization_id"])
    op.create_index("ix_external_gateway_calls_agent_id",
                    "external_gateway_calls", ["agent_id"])
    op.create_index("ix_external_gateway_calls_grant_id",
                    "external_gateway_calls", ["grant_id"])
    op.create_index("ix_external_gateway_calls_capability_key",
                    "external_gateway_calls", ["capability_key"])
    op.create_index("ix_external_gateway_calls_outcome",
                    "external_gateway_calls", ["outcome"])
    op.create_index("ix_ext_calls_org_agent_created", "external_gateway_calls",
                    ["organization_id", "agent_id", "created_at"])


def downgrade() -> None:
    op.drop_table("external_gateway_calls")
    op.drop_table("external_request_nonces")
    op.drop_table("external_capability_grants")
    op.drop_constraint("ck_agents_external_enforcement_mode", "agents", type_="check")
    op.drop_column("agents", "external_enforcement_mode")
