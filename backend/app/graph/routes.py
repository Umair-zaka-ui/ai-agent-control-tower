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
from app.graph.schemas import (
    AuthorityChainRead,
    DelegationEdgeCreate,
    EdgeRead,
    ReachabilityRead,
    ReachableNodeRead,
    TrustEdgeCreate,
)
from app.graph.service import AuthorityChainService, ControlGraphService
from app.models.graph import EDGE_TYPES, NODE_TYPES
from app.models.user import User

router = APIRouter(prefix="/api/v1/graph", tags=["graph"])

_VIEW = "graph.view"
_MANAGE = "graph.manage"


@router.get("/node-types")
def list_node_types(actor: User = Depends(require_permission(_VIEW))) -> dict:
    """The node vocabulary, exhaustive by construction -- the same honesty
    ``GET /discovery/adapters`` gives for adapters."""
    return {"node_types": list(NODE_TYPES), "edge_types": list(EDGE_TYPES)}


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
