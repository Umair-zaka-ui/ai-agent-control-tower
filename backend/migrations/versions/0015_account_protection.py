"""Phase 4 Part 4.2.2.3.4 - enterprise account protection & risk-based auth.

Adds:

- ``account_locks``               stateful, progressive, time-bounded locks (§8, §17).
- ``identity_risk_events``        scored login attempts with signals JSONB (§17, §26).
- ``blocked_ips``                 IPs denied at the door (§16); org-scoped or global.
- ``identity_protection_rules``   admin rules: conditions JSONB → decision (§16, §27).
- ``login_history`` risk columns  organization_id / device_fingerprint / risk_score /
                                  decision — extends the existing attempts table (§17)
                                  rather than forking a second one.
- ``security.protection`` permission, backfilled onto every SUPER_ADMIN / ADMIN role.

Additive: no column is dropped or retyped.

Revision ID: 0015_account_protection  (<=32 chars)
Revises: 0014_password_reset_recovery
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0015_account_protection"
down_revision: str | None = "0014_password_reset_recovery"
branch_labels = None
depends_on = None

_PERMISSIONS = (
    ("security.protection", "View and manage account protection: locks, blocked IPs, rules"),
)
_ROLES = ("SUPER_ADMIN", "ADMIN")


def upgrade() -> None:
    # ---- login_history risk columns ---------------------------------- #
    op.add_column("login_history", sa.Column("organization_id", sa.UUID(), nullable=True))
    op.add_column("login_history", sa.Column("device_fingerprint", sa.String(length=128), nullable=True))
    op.add_column("login_history", sa.Column("risk_score", sa.Integer(), nullable=True))
    op.add_column("login_history", sa.Column("decision", sa.String(length=30), nullable=True))
    op.create_foreign_key(
        "fk_login_history_organization_id", "login_history", "organizations",
        ["organization_id"], ["id"], ondelete="CASCADE",
    )
    op.create_index("ix_login_history_organization_id", "login_history", ["organization_id"])

    # ---- account_locks ---------------------------------------------- #
    op.create_table(
        "account_locks",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("reason", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="ACTIVE"),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("unlocked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("unlocked_by", sa.UUID(), nullable=True),
        sa.Column("meta", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["unlocked_by"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_account_locks_user_id", "account_locks", ["user_id"])
    op.create_index("ix_account_locks_organization_id", "account_locks", ["organization_id"])
    op.create_index("ix_account_locks_status", "account_locks", ["status"])
    op.create_index("ix_account_locks_user_status", "account_locks", ["user_id", "status"])

    # ---- identity_risk_events --------------------------------------- #
    op.create_table(
        "identity_risk_events",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("organization_id", sa.UUID(), nullable=True),
        sa.Column("user_id", sa.UUID(), nullable=True),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("risk_score", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("risk_level", sa.String(length=20), nullable=False),
        sa.Column("signals", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("decision", sa.String(length=30), nullable=False),
        sa.Column("ip_address", sa.String(length=64), nullable=True),
        sa.Column("user_agent", sa.String(length=512), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_identity_risk_events_organization_id", "identity_risk_events", ["organization_id"])
    op.create_index("ix_identity_risk_events_user_id", "identity_risk_events", ["user_id"])
    op.create_index("ix_identity_risk_events_event_type", "identity_risk_events", ["event_type"])
    op.create_index("ix_identity_risk_events_risk_level", "identity_risk_events", ["risk_level"])
    op.create_index("ix_identity_risk_events_created_at", "identity_risk_events", ["created_at"])
    op.create_index("ix_identity_risk_events_org_created", "identity_risk_events", ["organization_id", "created_at"])

    # ---- blocked_ips ------------------------------------------------ #
    op.create_table(
        "blocked_ips",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("organization_id", sa.UUID(), nullable=True),
        sa.Column("ip_address", sa.String(length=64), nullable=False),
        sa.Column("reason", sa.String(length=255), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_blocked_ips_organization_id", "blocked_ips", ["organization_id"])
    op.create_index("ix_blocked_ips_ip_address", "blocked_ips", ["ip_address"])
    op.create_index("ix_blocked_ips_org_ip", "blocked_ips", ["organization_id", "ip_address"])

    # ---- identity_protection_rules ---------------------------------- #
    op.create_table(
        "identity_protection_rules",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=150), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=True),
        sa.Column("conditions", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("decision", sa.String(length=30), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_identity_protection_rules_organization_id", "identity_protection_rules", ["organization_id"])

    # ---- RBAC: security.protection, backfilled onto admin roles ----- #
    conn = op.get_bind()
    insert_permission = sa.text(
        """
        INSERT INTO rbac_permissions (id, code, description)
        SELECT gen_random_uuid(), :code, :description
        WHERE NOT EXISTS (SELECT 1 FROM rbac_permissions WHERE code = :code)
        """
    )
    for code, description in _PERMISSIONS:
        conn.execute(insert_permission, {"code": code, "description": description})
    conn.execute(
        sa.text(
            """
            INSERT INTO role_permissions (id, role_id, permission_id)
            SELECT gen_random_uuid(), r.id, p.id
              FROM roles r CROSS JOIN rbac_permissions p
             WHERE r.name = ANY(:roles) AND p.code = ANY(:codes)
               AND NOT EXISTS (
                     SELECT 1 FROM role_permissions rp
                      WHERE rp.role_id = r.id AND rp.permission_id = p.id)
            """
        ),
        {"roles": list(_ROLES), "codes": [c for c, _ in _PERMISSIONS]},
    )


def downgrade() -> None:
    conn = op.get_bind()
    codes = [c for c, _ in _PERMISSIONS]
    conn.execute(
        sa.text(
            "DELETE FROM role_permissions WHERE permission_id IN "
            "(SELECT id FROM rbac_permissions WHERE code = ANY(:codes))"
        ),
        {"codes": codes},
    )
    conn.execute(sa.text("DELETE FROM rbac_permissions WHERE code = ANY(:codes)"), {"codes": codes})

    op.drop_table("identity_protection_rules")
    op.drop_table("blocked_ips")
    op.drop_table("identity_risk_events")
    op.drop_table("account_locks")
    op.drop_index("ix_login_history_organization_id", table_name="login_history")
    op.drop_constraint("fk_login_history_organization_id", "login_history", type_="foreignkey")
    op.drop_column("login_history", "decision")
    op.drop_column("login_history", "risk_score")
    op.drop_column("login_history", "device_fingerprint")
    op.drop_column("login_history", "organization_id")
