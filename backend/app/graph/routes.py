"""Phase 5.3 (M5.3) - the control-graph HTTP surface, under ``/api/v1/graph``.

Read-and-represent only. **No route grants authority** -- reading an edge or a
chain confers nothing; the two write routes create/revoke an edge that
*represents* a relationship (a trust relationship between existing nodes, or
an existing ``delegations`` row), never one that *is* authority. Enforcement
stays with ``AuthorizationGateway``.

No speculative dependency-graph / posture / containment endpoints -- those are
5.4+.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_permission
from app.graph.blast_radius import BlastRadiusService
from app.graph.dependencies import DependencyGraphService
from app.graph.mcp import McpServerService
from app.graph.schemas import (
    AuthorityChainRead,
    DelegationEdgeCreate,
    DependencyEdgeCreate,
    DependencyRebuildRead,
    EdgeRead,
    McpServerCreate,
    McpServerRead,
    McpToolLink,
    McpTrustUpdate,
    ReachabilityRead,
    ReachableNodeRead,
    TrustEdgeCreate,
)
from app.graph.service import AuthorityChainService, ControlGraphService
from app.models.graph import DEPENDENCY_EDGE_TYPES, EDGE_TYPES, NODE_TYPES
from app.models.user import User

router = APIRouter(prefix="/api/v1/graph", tags=["graph"])

_VIEW = "graph.view"
_MANAGE = "graph.manage"


@router.get("/node-types")
def list_node_types(actor: User = Depends(require_permission(_VIEW))) -> dict:
    """The node vocabulary, exhaustive by construction -- the same honesty
    ``GET /discovery/adapters`` gives for adapters."""
    return {
        "node_types": list(NODE_TYPES),
        "edge_types": list(EDGE_TYPES),
        "dependency_edge_types": list(DEPENDENCY_EDGE_TYPES),
    }


@router.get("/edges", response_model=list[EdgeRead])
def list_edges(
    node_type: str | None = Query(default=None),
    node_id: uuid.UUID | None = Query(default=None),
    edge_type: str | None = Query(default=None),
    include_revoked: bool = Query(default=False),
    actor: User = Depends(require_permission(_VIEW)),
    db: Session = Depends(get_db),
):
    return ControlGraphService(db).list_edges(
        actor,
        node_type=node_type,
        node_id=node_id,
        edge_type=edge_type,
        include_revoked=include_revoked,
    )


@router.get("/edges/{edge_id}", response_model=EdgeRead)
def get_edge(
    edge_id: uuid.UUID,
    actor: User = Depends(require_permission(_VIEW)),
    db: Session = Depends(get_db),
):
    return ControlGraphService(db).get_or_404(actor, edge_id)


@router.post("/trust-edges", response_model=EdgeRead, status_code=201)
def create_trust_edge(
    payload: TrustEdgeCreate,
    actor: User = Depends(require_permission(_MANAGE)),
    db: Session = Depends(get_db),
):
    return ControlGraphService(db).create_trust_edge(
        actor,
        source_type=payload.source.type,
        source_id=payload.source.id,
        target_type=payload.target.type,
        target_id=payload.target.id,
        note=payload.note,
        valid_until=payload.valid_until,
    )


@router.post("/delegation-edges", response_model=EdgeRead, status_code=201)
def create_delegation_edge(
    payload: DelegationEdgeCreate,
    actor: User = Depends(require_permission(_MANAGE)),
    db: Session = Depends(get_db),
):
    return ControlGraphService(db).create_delegation_edge(
        actor, delegation_id=payload.delegation_id
    )


@router.delete("/edges/{edge_id}", response_model=EdgeRead)
def revoke_edge(
    edge_id: uuid.UUID,
    actor: User = Depends(require_permission(_MANAGE)),
    db: Session = Depends(get_db),
):
    return ControlGraphService(db).revoke_edge(actor, edge_id)


@router.get(
    "/authority-chain/executions/{execution_id}", response_model=AuthorityChainRead
)
def reconstruct_authority_chain(
    execution_id: uuid.UUID,
    max_depth: int | None = Query(default=None, ge=1),
    actor: User = Depends(require_permission(_VIEW)),
    db: Session = Depends(get_db),
):
    """Who authorized this action, under whose delegated authority, through
    which identity, down to which resource -- assembled from existing
    execution/identity rows + edges, per-hop tenant-bounded, each hop naming
    its evidence. A cross-tenant execution is 404 (no existence leak)."""
    chain = AuthorityChainService(db).reconstruct(actor, execution_id, max_depth=max_depth)
    return AuthorityChainRead(**chain.as_dict())


@router.get("/reachability", response_model=ReachabilityRead)
def reachability(
    node_type: str = Query(...),
    node_id: uuid.UUID = Query(...),
    direction: str = Query(default="out", pattern="^(out|in)$"),
    max_depth: int | None = Query(default=None, ge=1),
    edge_type: list[str] | None = Query(default=None),
    actor: User = Depends(require_permission(_VIEW)),
    db: Session = Depends(get_db),
):
    """The bounded, cycle-safe, per-hop tenant-bounded reachability primitive
    that Phase 5.4 extends to dependencies."""
    reachable = AuthorityChainService(db).reachability(
        actor,
        node_type=node_type,
        node_id=node_id,
        edge_types=edge_type,
        direction=direction,
        max_depth=max_depth,
    )
    from app.graph.traversal import _clamp_depth

    return ReachabilityRead(
        start={"type": node_type, "id": node_id},
        direction=direction,
        max_depth=_clamp_depth(max_depth),
        edge_types=list(edge_type or []),
        reachable=[
            ReachableNodeRead(
                node_type=n.node_type, node_id=n.node_id, depth=n.depth, label=n.label
            )
            for n in reachable
        ],
    )


# =========================================================================== #
# Phase 5.4 (M5.4) - MCP servers (represented via the Tool domain), dependency
# edges, and blast-radius queries. No route grants authority; MCP tool I/O is
# contained by the existing egress/schema-validation authorities.
# =========================================================================== #
@router.get("/mcp-servers", response_model=list[McpServerRead])
def list_mcp_servers(
    trust_status: str | None = Query(default=None),
    actor: User = Depends(require_permission(_VIEW)),
    db: Session = Depends(get_db),
):
    return McpServerService(db).list_servers(actor, trust_status=trust_status)


@router.post("/mcp-servers", response_model=McpServerRead, status_code=201)
def register_mcp_server(
    payload: McpServerCreate,
    actor: User = Depends(require_permission(_MANAGE)),
    db: Session = Depends(get_db),
):
    return McpServerService(db).register(
        actor,
        name=payload.name,
        description=payload.description,
        provenance=payload.provenance,
        trust_status=payload.trust_status,
        version=payload.version,
        endpoint_reference=payload.endpoint_reference,
        declared_capabilities=payload.declared_capabilities,
        owner_id=payload.owner_id,
        owner_type=payload.owner_type,
    )


@router.get("/mcp-servers/{server_id}", response_model=McpServerRead)
def get_mcp_server(
    server_id: uuid.UUID,
    actor: User = Depends(require_permission(_VIEW)),
    db: Session = Depends(get_db),
):
    return McpServerService(db).get_or_404(actor, server_id)


@router.get("/mcp-servers/{server_id}/tools")
def list_mcp_server_tools(
    server_id: uuid.UUID,
    actor: User = Depends(require_permission(_VIEW)),
    db: Session = Depends(get_db),
) -> dict:
    tools = McpServerService(db).exposed_tools(actor, server_id)
    return {
        "mcp_server_id": str(server_id),
        "tools": [
            {"id": str(t.id), "name": t.name, "tool_type": t.tool_type,
             "mcp_server_id": str(t.mcp_server_id) if t.mcp_server_id else None}
            for t in tools
        ],
    }


@router.post("/mcp-servers/{server_id}/trust", response_model=McpServerRead)
def set_mcp_server_trust(
    server_id: uuid.UUID,
    payload: McpTrustUpdate,
    actor: User = Depends(require_permission(_MANAGE)),
    db: Session = Depends(get_db),
):
    return McpServerService(db).set_trust(
        actor, server_id, trust_status=payload.trust_status, note=payload.note
    )


@router.post("/mcp-servers/{server_id}/tools", response_model=EdgeRead, status_code=201)
def link_mcp_server_tool(
    server_id: uuid.UUID,
    payload: McpToolLink,
    actor: User = Depends(require_permission(_MANAGE)),
    db: Session = Depends(get_db),
):
    """Mark an existing tool as exposed by this MCP server (sets
    ``tools.mcp_server_id`` and records the MCP_EXPOSES_TOOL edge). Never
    creates a tool -- MCP-via-Tool, no second registry."""
    return McpServerService(db).link_tool(actor, server_id, payload.tool_id)


@router.get("/agents/{agent_id}/dependencies", response_model=list[EdgeRead])
def list_agent_dependencies(
    agent_id: uuid.UUID,
    actor: User = Depends(require_permission(_VIEW)),
    db: Session = Depends(get_db),
):
    return DependencyGraphService(db).list_for_agent(actor, agent_id)


@router.post(
    "/agents/{agent_id}/dependencies/rebuild", response_model=DependencyRebuildRead
)
def rebuild_agent_dependencies(
    agent_id: uuid.UUID,
    actor: User = Depends(require_permission(_MANAGE)),
    db: Session = Depends(get_db),
):
    """Derive this agent's dependency edges from recorded evidence
    (tool_calls = OBSERVED, agent_tools / tool_credentials / mcp_server_id /
    the version's model provider = DECLARED). Idempotent."""
    return DependencyRebuildRead(**DependencyGraphService(db).build_for_agent(actor, agent_id))


@router.post("/dependency-edges", response_model=EdgeRead, status_code=201)
def create_dependency_edge(
    payload: DependencyEdgeCreate,
    actor: User = Depends(require_permission(_MANAGE)),
    db: Session = Depends(get_db),
):
    return DependencyGraphService(db).create_declared_edge(
        actor,
        source_type=payload.source.type,
        source_id=payload.source.id,
        edge_type=payload.edge_type,
        target_type=payload.target.type,
        target_id=payload.target.id,
        note=payload.note,
    )


@router.delete("/dependency-edges/{edge_id}", response_model=EdgeRead)
def revoke_dependency_edge(
    edge_id: uuid.UUID,
    actor: User = Depends(require_permission(_MANAGE)),
    db: Session = Depends(get_db),
):
    return DependencyGraphService(db).revoke_edge(actor, edge_id)


@router.get("/blast-radius/agents-reaching")
def blast_radius_agents_reaching(
    node_type: str = Query(...),
    node_id: uuid.UUID = Query(...),
    max_depth: int | None = Query(default=None, ge=1),
    actor: User = Depends(require_permission(_VIEW)),
    db: Session = Depends(get_db),
) -> dict:
    """"Which agents can reach node X" -- reverse reachability over the
    dependency edges, per-hop tenant-bounded, each answer naming its path."""
    return BlastRadiusService(db).agents_reaching(
        actor, node_type=node_type, node_id=node_id, max_depth=max_depth
    )


@router.get("/blast-radius/what-breaks")
def blast_radius_what_breaks(
    node_type: str = Query(...),
    node_id: uuid.UUID = Query(...),
    max_depth: int | None = Query(default=None, ge=1),
    actor: User = Depends(require_permission(_VIEW)),
    db: Session = Depends(get_db),
) -> dict:
    """"What breaks if credential / MCP server / tool Y is revoked or removed"
    -- the exact dependent set."""
    return BlastRadiusService(db).what_breaks(
        actor, node_type=node_type, node_id=node_id, max_depth=max_depth
    )


@router.get("/blast-radius/mcp-dependents/{server_id}")
def blast_radius_mcp_dependents(
    server_id: uuid.UUID,
    max_depth: int | None = Query(default=None, ge=1),
    actor: User = Depends(require_permission(_VIEW)),
    db: Session = Depends(get_db),
) -> dict:
    """"Which agents depend on MCP server Z" -- direct + transitive; an
    unapproved / unknown-provenance server is surfaced as evidence."""
    return BlastRadiusService(db).agents_depending_on_mcp(
        actor, server_id, max_depth=max_depth
    )


@router.get("/blast-radius/resource-kind")
def blast_radius_resource_kind(
    kind: str = Query(..., min_length=1),
    max_depth: int | None = Query(default=None, ge=1),
    actor: User = Depends(require_permission(_VIEW)),
    db: Session = Depends(get_db),
) -> dict:
    """"Which agents can reach a resource of kind K" (e.g. payroll, customer
    financial records) -- reachability filtered by ``resources.resource_type``."""
    return BlastRadiusService(db).agents_reaching_resource_kind(
        actor, kind, max_depth=max_depth
    )


@router.get("/blast-radius/unapproved-mcp")
def blast_radius_unapproved_mcp(
    actor: User = Depends(require_permission(_VIEW)),
    db: Session = Depends(get_db),
) -> dict:
    """Agents depending on an MCP server whose trust status is not APPROVED --
    the evidence Phase 5.5 turns into a posture finding (5.4 does not raise it)."""
    return BlastRadiusService(db).unapproved_mcp_dependencies(actor)
