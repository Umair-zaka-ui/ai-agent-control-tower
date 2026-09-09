"""Phase 5.4 (M5.4) - MCP / Tool / Credential / Resource Dependency Graph.

Additive, reversible, tenant-scoped. It extends the Phase 5.3 relational
control-graph substrate (``control_graph_edges`` + the recursive-CTE
traversal) with **dependency edges** and makes an **MCP server a
first-class, security-relevant dependency represented via the existing
``Tool`` domain** (ADR-0018) -- *not* a second tool registry.

  * ``mcp_servers`` - NEW. An MCP server's identity, provenance,
                      ownership, trust/approval state, version and endpoint
                      reference. It does NOT hold tools -- the tools an MCP
                      server exposes are ordinary ``tools`` rows that point
                      back at it through the one additive column below.

  * ``tools.mcp_server_id`` - the one additive column on an existing table
                              (AC-15's "additive MCP-via-Tool link,
                              justified"). Nullable FK to ``mcp_servers``;
                              a native tool leaves it NULL, an MCP-exposed
                              tool sets it. One registry, one schema-
                              validation path, one gateway.

  * ``control_graph_edges`` CHECK constraints are widened (drop + recreate,
    same table, no column change) to admit the new node types
    (``MCP_SERVER``, ``CONNECTOR``) and the new dependency edge-type
    vocabulary. No new edge table -- dependency edges are more ``edge_type``
    values on the 5.3 table (ADR-0017 point 3 / "revisit when 5.4").

There is still NO graph database and NO materialized projection: the §V
blast-radius benchmark (see ``docs/graph/blast-radius.md`` and ADR-0018)
measured assembly from edges well inside budget, so "no projection" remains
the right call.

Revision ID: 0057_dependency_graph
Revises: 0056_control_graph
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0057_dependency_graph"
down_revision = "0056_control_graph"
branch_labels = None
depends_on = None

# --- the widened vocabularies (kept in lockstep with app/models/graph.py) --- #
_NODE_TYPES_OLD = (
    "HUMAN", "AGENT", "AGENT_IDENTITY", "SERVICE_ACCOUNT", "FEDERATED_IDENTITY",
    "EXTERNAL_CLIENT", "TOOL", "CREDENTIAL", "RESOURCE", "ORGANIZATION",
)
_NODE_TYPES_NEW = _NODE_TYPES_OLD + ("MCP_SERVER", "CONNECTOR")

_EDGE_TYPES_OLD = ("DELEGATES_TO", "AGENT_DELEGATES_TO", "TRUSTS", "ACTS_AS")
_EDGE_TYPES_NEW = _EDGE_TYPES_OLD + (
    "DEPENDS_ON_TOOL",
    "DEPENDS_ON_MCP_SERVER",
    "DEPENDS_ON_CREDENTIAL",
    "DEPENDS_ON_CONNECTOR",
    "DEPENDS_ON_RESOURCE",
    "MCP_EXPOSES_TOOL",
    "TOOL_USES_CREDENTIAL",
    "TOOL_ACCESSES_RESOURCE",
    "CREDENTIAL_ACCESSES_RESOURCE",
)

_MCP_PROVENANCE = ("EXPLICIT", "DERIVED", "DISCOVERED")
# APPROVED = reviewed and trusted. PENDING = registered, not yet reviewed.
# REJECTED = reviewed and explicitly disallowed. UNKNOWN = provenance/identity
# could not be established. Anything other than APPROVED is "unapproved" -- a
# dependency on it is evidence for a 5.5 finding (unknown != safe).
_MCP_TRUST = ("APPROVED", "PENDING", "REJECTED", "UNKNOWN")


def _recreate_check(name: str, column: str, allowed: tuple[str, ...]) -> None:
    op.drop_constraint(name, "control_graph_edges", type_="check")
    op.create_check_constraint(
        name, "control_graph_edges", f"{column} IN {allowed}"
    )


def upgrade() -> None:
    op.create_table(
        "mcp_servers",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("provenance", sa.String(length=24), nullable=False, server_default="EXPLICIT"),
        sa.Column("trust_status", sa.String(length=24), nullable=False, server_default="PENDING"),
        sa.Column("version", sa.String(length=64), nullable=True),
        sa.Column("endpoint_reference", sa.String(length=500), nullable=True),
        sa.Column("declared_capabilities", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("owner_type", sa.String(length=30), nullable=True),
        sa.Column("last_probed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("probe_status", sa.String(length=24), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("provenance IN " + str(_MCP_PROVENANCE), name="ck_mcp_servers_provenance"),
        sa.CheckConstraint("trust_status IN " + str(_MCP_TRUST), name="ck_mcp_servers_trust_status"),
    )
    op.create_index("ix_mcp_servers_organization_id", "mcp_servers", ["organization_id"])
    # One MCP server per (org, name) -- registration is idempotent and a
    # concurrent double-register resolves to one row (the "one condition = one
    # row" precedent 0050/0055/0056 set).
    op.create_index(
        "uq_mcp_servers_org_name", "mcp_servers", ["organization_id", "name"], unique=True
    )

    # The one additive MCP-via-Tool link (AC-15). Nullable; SET NULL on server
    # delete so a tool row survives its server being removed (the tool is still
    # a governed Tool; only its provider link is gone).
    op.add_column(
        "tools",
        sa.Column("mcp_server_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("mcp_servers.id", ondelete="SET NULL"), nullable=True),
    )
    op.create_index("ix_tools_mcp_server_id", "tools", ["mcp_server_id"])

    # Widen the 5.3 CHECK constraints in place -- same table, no column added or
    # altered, just a larger allowed-values set for the typed vocabulary
    # columns (ADR-0017 anticipated exactly this for 5.4).
    _recreate_check("ck_control_graph_edges_source_type", "source_type", _NODE_TYPES_NEW)
    _recreate_check("ck_control_graph_edges_target_type", "target_type", _NODE_TYPES_NEW)
    _recreate_check("ck_control_graph_edges_edge_type", "edge_type", _EDGE_TYPES_NEW)


def downgrade() -> None:
    # No dependency edge / new-node-type row can exist after a clean downgrade
    # of a system that only ever wrote through the services, but a defensive
    # delete keeps the narrower CHECK creatable even if one was planted.
    op.execute(
        "DELETE FROM control_graph_edges WHERE edge_type NOT IN " + str(_EDGE_TYPES_OLD)
        + " OR source_type NOT IN " + str(_NODE_TYPES_OLD)
        + " OR target_type NOT IN " + str(_NODE_TYPES_OLD)
    )
    _recreate_check("ck_control_graph_edges_edge_type", "edge_type", _EDGE_TYPES_OLD)
    _recreate_check("ck_control_graph_edges_target_type", "target_type", _NODE_TYPES_OLD)
    _recreate_check("ck_control_graph_edges_source_type", "source_type", _NODE_TYPES_OLD)

    op.drop_index("ix_tools_mcp_server_id", table_name="tools")
    op.drop_column("tools", "mcp_server_id")

    op.drop_index("uq_mcp_servers_org_name", table_name="mcp_servers")
    op.drop_index("ix_mcp_servers_organization_id", table_name="mcp_servers")
    op.drop_table("mcp_servers")
