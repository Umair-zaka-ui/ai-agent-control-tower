"""Phase 2.1.1 - Connector Abstraction & Lifecycle.

Additive only, three new tables (``ACT-INT-FR-001..010``):

1. **``connectors``** — registered connector *types* (the implementation
   and its declared contract: capabilities, config schema, auth
   requirements, tool contracts). Platform-wide, versioned. Unique on
   ``(connector_type, version)``.

2. **``connector_instances``** — a tenant's configured *use* of one type.
   Org-scoped (``organization_id`` FK, CASCADE), carries ``configuration``
   and ``lifecycle_state``. Unique on ``(organization_id, name)``. No
   credential column — that is Phase 2.1.2.

3. **``connector_lifecycle_events``** — append-only audit trail of every
   instance's lifecycle transitions.

No existing table is touched.

Revision ID: 0033_connector_core
Revises: 0032_tool_loop
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0033_connector_core"
down_revision: str | None = "0032_tool_loop"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "connectors",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("connector_type", sa.String(length=64), nullable=False),
        sa.Column("version", sa.String(length=32), nullable=False),
        sa.Column("capabilities", JSONB(), nullable=False),
        sa.Column("config_schema", JSONB(), nullable=False),
        sa.Column("auth_requirements", JSONB(), nullable=False),
        sa.Column("tool_contracts", JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("connector_type", "version", name="uq_connectors_type_version"),
    )
    op.create_index("ix_connectors_connector_type", "connectors", ["connector_type"])

    op.create_table(
        "connector_instances",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("connector_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("configuration", JSONB(), nullable=False, server_default="{}"),
        sa.Column("lifecycle_state", sa.String(length=20), nullable=False, server_default="registered"),
        sa.Column("state_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["connector_id"], ["connectors.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("organization_id", "name", name="uq_connector_instances_org_name"),
    )
    op.create_index("ix_connector_instances_organization_id", "connector_instances", ["organization_id"])
    op.create_index("ix_connector_instances_connector_id", "connector_instances", ["connector_id"])
    op.create_index("ix_connector_instances_lifecycle_state", "connector_instances", ["lifecycle_state"])

    op.create_table(
        "connector_lifecycle_events",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("connector_instance_id", sa.UUID(), nullable=False),
        sa.Column("from_state", sa.String(length=20), nullable=True),
        sa.Column("to_state", sa.String(length=20), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("actor_id", sa.UUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["connector_instance_id"], ["connector_instances.id"], ondelete="CASCADE"),
    )
    op.create_index(
        "ix_connector_lifecycle_events_connector_instance_id",
        "connector_lifecycle_events", ["connector_instance_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_connector_lifecycle_events_connector_instance_id", table_name="connector_lifecycle_events")
    op.drop_table("connector_lifecycle_events")

    op.drop_index("ix_connector_instances_lifecycle_state", table_name="connector_instances")
    op.drop_index("ix_connector_instances_connector_id", table_name="connector_instances")
    op.drop_index("ix_connector_instances_organization_id", table_name="connector_instances")
    op.drop_table("connector_instances")

    op.drop_index("ix_connectors_connector_type", table_name="connectors")
    op.drop_table("connectors")
