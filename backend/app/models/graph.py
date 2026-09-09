"""Phase 5.3 (M5.3) — Identity, Delegation & Trust Graph: the relational
control-graph substrate.

**One table.** ``control_graph_edges`` is a typed, directed, tenant-scoped
edge between two existing node rows. It never copies node state — a node is
addressed by ``(type, id)`` and resolved against its own table at read time
(SRS §13, the same discipline ``resources`` uses for ``(resource_type,
resource_id)``). There is **no node table**, **no graph database**, and **no
materialized projection** (ADR-0017): the authority chain and every
reachability query are assembled from this table plus the existing
execution/identity rows with recursive CTEs — Postgres, nothing else.

**The graph represents; it never creates.** An edge is *evidence that a
relationship exists*, carrying a pointer back to the row that authorized it
(``evidence``). Reading an edge or a chain grants nothing — authority stays
with ``AuthorizationGateway``. Delegation edges mirror the existing
``delegations`` rows that ``DelegationService`` owns; trust edges mirror the
existing agent↔identity / agent↔tool bindings. ``AGENT_DELEGATES_TO`` is a
declared edge type with **no producer in this phase** — the runtime
deliberately has no agent→agent invocation (``request_execution_as_agent`` is
self-only), so 5.3 leaves the type in the vocabulary the way M5.1 left
discovery columns for M5.2, and does not invent the missing link.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin

# Node types an edge endpoint may address. Each maps to exactly one existing
# table (see app/graph/nodes.py) — the edge stores no node state of its own.
# Phase 5.4 adds MCP_SERVER (mcp_servers) and CONNECTOR (connector_instances)
# for the dependency graph. An "external system" (SRS §N) is represented as a
# RESOURCE node (resource_type = 'external_system'), matching the existing
# (resource_type, resource_id) discipline — no separate node type for it.
NODE_TYPES = (
    "HUMAN",              # users
    "AGENT",              # agents (native + external + discovered)
    "AGENT_IDENTITY",     # agent_identities
    "SERVICE_ACCOUNT",    # service_accounts
    "FEDERATED_IDENTITY",  # federated_identities
    "EXTERNAL_CLIENT",    # external_clients
    "TOOL",               # tools
    "CREDENTIAL",         # agent_api_keys / tool_credentials / provider_credentials / connector_credentials
    "RESOURCE",           # resources
    "ORGANIZATION",       # organizations
    "MCP_SERVER",         # mcp_servers (Phase 5.4)
    "CONNECTOR",          # connector_instances (Phase 5.4)
)

# Edge types. DELEGATES_TO / TRUSTS / ACTS_AS have real producers in Phase 5.3
# (they mirror existing rows). AGENT_DELEGATES_TO is the declared, producerless
# gap — see the module docstring.
#
# Phase 5.4 (M5.4) adds the dependency edge-type vocabulary. Every dependency
# edge references two existing rows and grants no authority; each carries an
# ``evidence.mode`` of OBSERVED (from tool_calls / egress) or DECLARED (from
# agent_tools / tool_credentials / http_config bindings). There is deliberately
# NO agent→model edge: no models registry row exists to reference (models are
# {provider, model} strings on agent_versions.model_configuration), so — the
# AGENT_DELEGATES_TO precedent — the type is left out rather than pointed at a
# non-governed row. The model-provider dependency surfaces as DEPENDS_ON_CREDENTIAL
# against the provider_credentials row, with the model id in evidence.
EDGE_TYPES = (
    "DELEGATES_TO",        # a human delegating administrative authority (delegations)
    "AGENT_DELEGATES_TO",  # agent→agent — declared, no producer
    "TRUSTS",              # an established, approved trust relationship
    "ACTS_AS",             # an agent acts through a machine identity (agent_identities)
    # --- Phase 5.4 dependency edges --------------------------------------- #
    "DEPENDS_ON_TOOL",             # AGENT → TOOL
    "DEPENDS_ON_MCP_SERVER",       # AGENT → MCP_SERVER
    "DEPENDS_ON_CREDENTIAL",       # AGENT → CREDENTIAL
    "DEPENDS_ON_CONNECTOR",        # AGENT → CONNECTOR
    "DEPENDS_ON_RESOURCE",         # AGENT → RESOURCE
    "MCP_EXPOSES_TOOL",            # MCP_SERVER → TOOL
    "TOOL_USES_CREDENTIAL",        # TOOL → CREDENTIAL
    "TOOL_ACCESSES_RESOURCE",      # TOOL → RESOURCE  (incl. external systems as RESOURCE)
    "CREDENTIAL_ACCESSES_RESOURCE",  # CREDENTIAL → RESOURCE (credential → system)
)

# The dependency edge types only (a strict subset of EDGE_TYPES) — used by the
# blast-radius traversals and the "no dependency edge grants authority" tests.
DEPENDENCY_EDGE_TYPES = (
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

# How an edge came to exist. EXPLICIT: created through the graph management
# API. DERIVED: mirrors a row another service owns (a delegations row, an
# agent_identities binding, a tool_calls observation, an agent_tools binding).
# DISCOVERED: produced by Phase 5.2 reconciliation for an external agent.
EDGE_PROVENANCE = ("EXPLICIT", "DERIVED", "DISCOVERED")

# An MCP server's review state. Anything other than APPROVED is "unapproved":
# a dependency on it is evidence for a Phase 5.5 posture finding (unknown ≠ safe).
MCP_TRUST_STATUSES = ("APPROVED", "PENDING", "REJECTED", "UNKNOWN")
MCP_PROVENANCE = ("EXPLICIT", "DERIVED", "DISCOVERED")


class ControlGraphEdge(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A typed, directed relationship between two existing node rows.

    Tenant-scoped by a denormalized ``organization_id`` — the management
    service validates that *both* endpoints resolve to that organization
    before an edge is written, so a single column is the complete tenant key
    and ``WHERE organization_id = :org`` is a correct per-hop bound for a
    recursive traversal (SRS §T).

    An edge is soft-revoked (``revoked_at``), never hard-deleted, and may
    carry an expiry (``valid_until``); a traversal only follows edges that
    are currently live. The partial unique index keeps ``create`` idempotent
    and a concurrent double-create race resolving to exactly one live edge.
    """

    __tablename__ = "control_graph_edges"
    __table_args__ = (
        CheckConstraint(
            f"source_type IN {NODE_TYPES}", name="ck_control_graph_edges_source_type"
        ),
        CheckConstraint(
            f"target_type IN {NODE_TYPES}", name="ck_control_graph_edges_target_type"
        ),
        CheckConstraint(
            f"edge_type IN {EDGE_TYPES}", name="ck_control_graph_edges_edge_type"
        ),
        CheckConstraint(
            f"provenance IN {EDGE_PROVENANCE}", name="ck_control_graph_edges_provenance"
        ),
        CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="ck_control_graph_edges_confidence",
        ),
        CheckConstraint(
            "NOT (source_type = target_type AND source_id = target_id)",
            name="ck_control_graph_edges_no_self_loop",
        ),
        Index(
            "ix_control_graph_edges_source",
            "organization_id",
            "source_type",
            "source_id",
        ),
        Index(
            "ix_control_graph_edges_target",
            "organization_id",
            "target_type",
            "target_id",
        ),
        Index(
            "uq_control_graph_edges_active",
            "organization_id",
            "source_type",
            "source_id",
            "edge_type",
            "target_type",
            "target_id",
            unique=True,
            postgresql_where=text("revoked_at IS NULL"),
        ),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    edge_type: Mapped[str] = mapped_column(String(40), nullable=False)
    target_type: Mapped[str] = mapped_column(String(32), nullable=False)
    target_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)

    # Each edge names its evidence: {"kind": ..., "ref_table": ..., "ref_id":
    # ..., "note": ...}. A DERIVED edge points at the row it mirrors; an
    # EXPLICIT edge points at the delegation/approval that authorized it.
    evidence: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    confidence: Mapped[Decimal] = mapped_column(
        Numeric(3, 2), nullable=False, default=Decimal("1.00")
    )
    provenance: Mapped[str] = mapped_column(String(24), nullable=False, default="EXPLICIT")

    valid_from: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    valid_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    revoked_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)


class McpServer(Base, UUIDPrimaryKeyMixin):
    """Phase 5.4 (M5.4) — an MCP server as a first-class, security-relevant
    dependency, represented **via the existing ``Tool`` domain** (ADR-0018).

    This row carries an MCP server's *identity, provenance, ownership,
    trust/approval state, version and endpoint reference* — nothing about the
    tools it exposes. The tools an MCP server exposes are ordinary ``tools``
    rows whose ``mcp_server_id`` points back here: one tool registry, one
    schema-validation path, one gateway. There is **no second tool table**.

    An agent's dependency on an MCP server is a ``DEPENDS_ON_MCP_SERVER`` edge
    on ``control_graph_edges``; the server's exposed tools are
    ``MCP_EXPOSES_TOOL`` edges. Neither edge, nor this row, grants any
    authority — MCP tool I/O is contained by the existing egress/SSRF guard
    and tool-schema validation (M1), and ``AuthorizationGateway`` stays the
    sole decider.

    ``trust_status`` other than ``APPROVED`` is surfaced as evidence for a
    Phase 5.5 posture finding — 5.4 represents and surfaces; it does not raise
    the finding (unknown ≠ safe).
    """

    __tablename__ = "mcp_servers"
    __table_args__ = (
        CheckConstraint(
            f"provenance IN {MCP_PROVENANCE}", name="ck_mcp_servers_provenance"
        ),
        CheckConstraint(
            f"trust_status IN {MCP_TRUST_STATUSES}", name="ck_mcp_servers_trust_status"
        ),
        Index("uq_mcp_servers_org_name", "organization_id", "name", unique=True),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    provenance: Mapped[str] = mapped_column(String(24), nullable=False, default="EXPLICIT")
    trust_status: Mapped[str] = mapped_column(String(24), nullable=False, default="PENDING")
    version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    endpoint_reference: Mapped[str | None] = mapped_column(String(500), nullable=True)
    declared_capabilities: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    owner_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    owner_type: Mapped[str | None] = mapped_column(String(30), nullable=True)
    # Freshness only — a probe failure marks this, it never deletes the row
    # (SRS §11). 5.4 does not probe real MCP servers in prod ([DEFERRED]); the
    # columns exist so a reference/local probe can record its outcome.
    last_probed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    probe_status: Mapped[str | None] = mapped_column(String(24), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


__all__ = [
    "NODE_TYPES",
    "EDGE_TYPES",
    "DEPENDENCY_EDGE_TYPES",
    "EDGE_PROVENANCE",
    "MCP_TRUST_STATUSES",
    "MCP_PROVENANCE",
    "ControlGraphEdge",
    "McpServer",
]
