"""Pydantic schemas for the Phase 5.3 (M5.3) control-graph API.

Deliberately minimal, read-and-represent only. The one write surface
(``POST``/``DELETE`` a trust or delegation edge) never accepts an
``organization_id`` -- the endpoint stamps the actor's tenant and validates
both endpoints resolve inside it. A client cannot set ``provenance``,
``confidence`` or ``evidence`` on an EXPLICIT edge beyond a free-text note;
those are server-derived.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.models.graph import (
    DEPENDENCY_EDGE_TYPES,
    MCP_PROVENANCE,
    MCP_TRUST_STATUSES,
    NODE_TYPES,
)

_NODE_PATTERN = "^(" + "|".join(NODE_TYPES) + ")$"
_DEP_EDGE_PATTERN = "^(" + "|".join(DEPENDENCY_EDGE_TYPES) + ")$"
_MCP_TRUST_PATTERN = "^(" + "|".join(MCP_TRUST_STATUSES) + ")$"
_MCP_PROV_PATTERN = "^(" + "|".join(MCP_PROVENANCE) + ")$"


class NodeRef(BaseModel):
    type: str = Field(pattern=_NODE_PATTERN)
    id: uuid.UUID


class TrustEdgeCreate(BaseModel):
    """An established, approved trust relationship between two existing nodes.
    Direction is source -> target. The endpoint validates both resolve inside
    the caller's tenant (a cross-tenant endpoint is 404, not 422 -- no
    existence leak)."""

    source: NodeRef
    target: NodeRef
    note: str | None = Field(default=None, max_length=500)
    valid_until: datetime | None = None


class DelegationEdgeCreate(BaseModel):
    """Represent an existing ``delegations`` row (that ``DelegationService``
    owns) as a graph edge. ``delegation_id`` must name a live delegation in
    the caller's tenant; the edge mirrors it and points its ``evidence`` back
    at it. 5.3 creates no delegation of its own and no agent->agent
    delegation (the runtime has no agent->agent invocation)."""

    delegation_id: uuid.UUID


class EdgeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    source_type: str
    source_id: uuid.UUID
    edge_type: str
    target_type: str
    target_id: uuid.UUID
    evidence: dict
    confidence: Decimal
    provenance: str
    valid_from: datetime
    valid_until: datetime | None
    revoked_at: datetime | None
    created_at: datetime


class ReachableNodeRead(BaseModel):
    node_type: str
    node_id: uuid.UUID
    depth: int
    label: str


class ReachabilityRead(BaseModel):
    start: NodeRef
    direction: str
    max_depth: int
    edge_types: list[str]
    reachable: list[ReachableNodeRead]


# --------------------------------------------------------------------------- #
# Phase 5.4 (M5.4) - MCP servers + dependency edges
# --------------------------------------------------------------------------- #
class McpServerCreate(BaseModel):
    """Register an MCP server. It is represented via the existing ``Tool``
    domain -- this creates no tool and no second registry. ``trust_status``
    defaults to PENDING (un-reviewed); pass UNKNOWN for a server whose
    provenance cannot be established. Anything other than APPROVED is surfaced
    as evidence for a Phase 5.5 finding."""

    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    provenance: str = Field(default="EXPLICIT", pattern=_MCP_PROV_PATTERN)
    trust_status: str = Field(default="PENDING", pattern=_MCP_TRUST_PATTERN)
    version: str | None = Field(default=None, max_length=64)
    endpoint_reference: str | None = Field(default=None, max_length=500)
    declared_capabilities: dict = Field(default_factory=dict)
    owner_id: uuid.UUID | None = None
    owner_type: str | None = Field(default=None, max_length=30)


class McpTrustUpdate(BaseModel):
    trust_status: str = Field(pattern=_MCP_TRUST_PATTERN)
    note: str | None = Field(default=None, max_length=500)


class McpToolLink(BaseModel):
    tool_id: uuid.UUID


class McpServerRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    name: str
    description: str | None
    provenance: str
    trust_status: str
    version: str | None
    endpoint_reference: str | None
    declared_capabilities: dict
    owner_id: uuid.UUID | None
    owner_type: str | None
    last_probed_at: datetime | None
    probe_status: str | None
    created_at: datetime


class DependencyEdgeCreate(BaseModel):
    """An operator's explicit declaration that a dependency exists. Both
    endpoints must resolve inside the caller's tenant; the edge grants no
    authority and is audited. ``evidence.mode`` is DECLARED."""

    source: NodeRef
    edge_type: str = Field(pattern=_DEP_EDGE_PATTERN)
    target: NodeRef
    note: str | None = Field(default=None, max_length=500)


class DependencyRebuildRead(BaseModel):
    agent_id: str
    edges_created: int
    by_type: dict
    note: str


class ChainHopRead(BaseModel):
    from_: dict = Field(alias="from")
    edge: str
    to: dict
    evidence: dict

    model_config = ConfigDict(populate_by_name=True)


class AuthorityChainRead(BaseModel):
    execution_id: uuid.UUID
    organization_id: uuid.UUID
    complete: bool
    notes: list[str]
    hops: list[dict]


__all__ = [
    "NodeRef",
    "TrustEdgeCreate",
    "DelegationEdgeCreate",
    "EdgeRead",
    "ReachableNodeRead",
    "ReachabilityRead",
    "ChainHopRead",
    "AuthorityChainRead",
    "McpServerCreate",
    "McpTrustUpdate",
    "McpToolLink",
    "McpServerRead",
    "DependencyEdgeCreate",
    "DependencyRebuildRead",
]
