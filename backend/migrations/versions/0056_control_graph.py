"""Phase 5.3 (M5.3) - Identity, Delegation & Trust Graph.

One new table, additive, reversible, tenant-scoped, no existing table
changed, no data backfill. It does not duplicate any node's state -- an
endpoint is ``(type, id)`` resolved against its own table at read time, the
same ``(resource_type, resource_id)`` discipline ``resources`` already uses.

  * ``control_graph_edges`` - a typed, directed, tenant-scoped relationship
                              between two existing node rows. Soft-revoked,
                              never hard-deleted; optionally time-bounded
                              (``valid_until``). The partial unique index
                              makes ``create`` idempotent and a concurrent
                              double-create resolve to exactly one live edge.

There is NO graph database and NO materialized projection (ADR-0017): the
authority chain and reachability are recursive CTEs over this table plus the
existing execution/identity rows.

Revision ID: 0056_control_graph
Revises: 0055_agent_discovery
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0056_control_graph"
down_revision = "0055_agent_discovery"
branch_labels = None
depends_on = None

_NODE_TYPES = (
    "HUMAN", "AGENT", "AGENT_IDENTITY", "SERVICE_ACCOUNT", "FEDERATED_IDENTITY",
    "EXTERNAL_CLIENT", "TOOL", "CREDENTIAL", "RESOURCE", "ORGANIZATION",
)
_EDGE_TYPES = ("DELEGATES_TO", "AGENT_DELEGATES_TO", "TRUSTS", "ACTS_AS")
_PROVENANCE = ("EXPLICIT", "DERIVED", "DISCOVERED")


def upgrade() -> None:
    op.create_table(
        "control_graph_edges",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_type", sa.String(length=32), nullable=False),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("edge_type", sa.String(length=40), nullable=False),
        sa.Column("target_type", sa.String(length=32), nullable=False),
        sa.Column("target_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("evidence", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("confidence", sa.Numeric(3, 2), nullable=False, server_default="1.00"),
        sa.Column("provenance", sa.String(length=24), nullable=False, server_default="EXPLICIT"),
        sa.Column("valid_from", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "source_type IN " + str(_NODE_TYPES), name="ck_control_graph_edges_source_type"),
        sa.CheckConstraint(
            "target_type IN " + str(_NODE_TYPES), name="ck_control_graph_edges_target_type"),
        sa.CheckConstraint(
            "edge_type IN " + str(_EDGE_TYPES), name="ck_control_graph_edges_edge_type"),
        sa.CheckConstraint(
            "provenance IN " + str(_PROVENANCE), name="ck_control_graph_edges_provenance"),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1", name="ck_control_graph_edges_confidence"),
        sa.CheckConstraint(
            "NOT (source_type = target_type AND source_id = target_id)",
            name="ck_control_graph_edges_no_self_loop"),
    )
    op.create_index("ix_control_graph_edges_organization_id", "control_graph_edges",
                    ["organization_id"])
    # The two bidirectional traversal keys (SRS §M) -- a recursive CTE walks
    # forward on (org, source) and backward on (org, target), and every hop
    # re-applies the organization_id predicate (SRS §T, per-hop tenant bound).
    op.create_index("ix_control_graph_edges_source", "control_graph_edges",
                    ["organization_id", "source_type", "source_id"])
    op.create_index("ix_control_graph_edges_target", "control_graph_edges",
                    ["organization_id", "target_type", "target_id"])
    # One live edge per (org, source, edge_type, target) -- create is
    # idempotent and a concurrent double-create resolves to exactly one row
    # (the "one condition = one row" precedent migration 0050 set for
    # runtime_alerts and 0055 set for open staleness findings).
    op.execute(
        "CREATE UNIQUE INDEX uq_control_graph_edges_active "
        "ON control_graph_edges "
        "(organization_id, source_type, source_id, edge_type, target_type, target_id) "
        "WHERE revoked_at IS NULL"
    )


def downgrade() -> None:
    op.drop_index("uq_control_graph_edges_active", table_name="control_graph_edges")
    op.drop_index("ix_control_graph_edges_target", table_name="control_graph_edges")
    op.drop_index("ix_control_graph_edges_source", table_name="control_graph_edges")
    op.drop_index("ix_control_graph_edges_organization_id", table_name="control_graph_edges")
    op.drop_table("control_graph_edges")
