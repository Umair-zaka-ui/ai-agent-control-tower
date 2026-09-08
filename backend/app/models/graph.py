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
NODE_TYPES = (
    "HUMAN",              # users
    "AGENT",              # agents (native + external + discovered)
    "AGENT_IDENTITY",     # agent_identities
    "SERVICE_ACCOUNT",    # service_accounts
    "FEDERATED_IDENTITY",  # federated_identities
    "EXTERNAL_CLIENT",    # external_clients
    "TOOL",               # tools
    "CREDENTIAL",         # agent_api_keys
    "RESOURCE",           # resources
    "ORGANIZATION",       # organizations
)

# Edge types. DELEGATES_TO / TRUSTS / ACTS_AS have real producers in this
# phase (they mirror existing rows). AGENT_DELEGATES_TO is the declared,
# producerless gap — see the module docstring.
EDGE_TYPES = (
    "DELEGATES_TO",        # a human delegating administrative authority (delegations)
    "AGENT_DELEGATES_TO",  # agent→agent — declared, no producer this phase
    "TRUSTS",              # an established, approved trust relationship
    "ACTS_AS",             # an agent acts through a machine identity (agent_identities)
)

# How an edge came to exist. EXPLICIT: created through the graph management
# API. DERIVED: mirrors a row another service owns (a delegations row, an
# agent_identities binding). DISCOVERED: produced by Phase 5.2 reconciliation
# for an external agent.
EDGE_PROVENANCE = ("EXPLICIT", "DERIVED", "DISCOVERED")


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


__all__ = [
    "NODE_TYPES",
    "EDGE_TYPES",
    "EDGE_PROVENANCE",
    "ControlGraphEdge",
]
