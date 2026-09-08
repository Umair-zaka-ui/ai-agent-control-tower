"""Phase 5.3 (M5.3) - ``ControlGraphService`` (edge management) and
``AuthorityChainService`` (reconstruction + reachability).

**The graph represents; it never creates.**

  * A **trust edge** is created explicitly through this service, but only
    between two nodes that already exist *in the caller's tenant* -- the
    endpoint resolution is the whole check. It grants nothing.
  * A **delegation edge** mirrors a row ``DelegationService`` already owns
    (a ``delegations`` row). This service never writes ``delegations`` and
    never invents an agent->agent delegation -- ``AGENT_DELEGATES_TO`` has no
    producer here because the runtime has no agent->agent invocation.
  * **Reading a chain or an edge is not a mutation and grants no authority.**
    ``AuthorizationGateway`` stays the sole decider.

Concurrency: a create is idempotent via the ``uq_control_graph_edges_active``
partial unique index -- a concurrent double-create (real separate Postgres
sessions) resolves to exactly one live edge, the loser re-reads it. A revoke
locks the row ``FOR UPDATE`` so two revokers serialize.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.authorization.enums import AuthorizationAuditEvent
from app.graph.nodes import resolve_node
from app.graph.traversal import (
    MAX_TRAVERSAL_DEPTH,
    AuthorityChain,
    ReachableNode,
    reconstruct_authority_chain,
    traverse,
)
from app.identity.errors import ErrorCode, IdentityError
from app.models.graph import ControlGraphEdge
from app.models.organization_hierarchy import Delegation
from app.models.user import User
from app.runtime.services import _now, _record_event

_TRUST_EVENT = {
    True: AuthorizationAuditEvent.GRAPH_TRUST_EDGE_CREATED,
    False: AuthorizationAuditEvent.GRAPH_TRUST_EDGE_REVOKED,
}
_DELEGATION_EVENT = {
    True: AuthorizationAuditEvent.GRAPH_DELEGATION_EDGE_CREATED,
    False: AuthorizationAuditEvent.GRAPH_DELEGATION_EDGE_REVOKED,
}


class ControlGraphService:
    def __init__(self, db: Session) -> None:
        self.db = db

    # ------------------------------------------------------------------ #
    # reads
    # ------------------------------------------------------------------ #
    def get_or_404(self, actor: User, edge_id: uuid.UUID) -> ControlGraphEdge:
        edge = self.db.get(ControlGraphEdge, edge_id)
        if edge is None or edge.organization_id != actor.organization_id:
            # cross-tenant and missing are indistinguishable to the caller.
            raise IdentityError(ErrorCode.GRAPH_EDGE_NOT_FOUND, "Edge not found.")
        return edge

    def list_edges(
        self,
        actor: User,
        *,
        node_type: str | None = None,
        node_id: uuid.UUID | None = None,
        edge_type: str | None = None,
        include_revoked: bool = False,
    ) -> list[ControlGraphEdge]:
        stmt = select(ControlGraphEdge).where(
            ControlGraphEdge.organization_id == actor.organization_id
        )
        if not include_revoked:
            stmt = stmt.where(ControlGraphEdge.revoked_at.is_(None))
        if edge_type:
            stmt = stmt.where(ControlGraphEdge.edge_type == edge_type)
        if node_type and node_id:
            stmt = stmt.where(
                (
                    (ControlGraphEdge.source_type == node_type)
                    & (ControlGraphEdge.source_id == node_id)
                )
                | (
                    (ControlGraphEdge.target_type == node_type)
                    & (ControlGraphEdge.target_id == node_id)
                )
            )
        return list(self.db.execute(stmt.order_by(ControlGraphEdge.created_at.desc())).scalars())

    # ------------------------------------------------------------------ #
    # writes -- represent, never create
    # ------------------------------------------------------------------ #
    def _require_in_tenant(self, actor: User, node_type: str, node_id: uuid.UUID) -> None:
        if resolve_node(self.db, actor.organization_id, node_type, node_id) is None:
            # 404-shaped: a caller must not learn whether a node exists in
            # another tenant.
            raise IdentityError(
                ErrorCode.GRAPH_CROSS_TENANT_ENDPOINT,
                "An edge endpoint was not found in this organization.",
            )

    def _upsert_edge(
        self,
        actor: User,
        *,
        source_type: str,
        source_id: uuid.UUID,
        edge_type: str,
        target_type: str,
        target_id: uuid.UUID,
        provenance: str,
        evidence: dict,
        valid_until=None,
    ) -> tuple[ControlGraphEdge, bool]:
        """Insert the edge, or return the existing live one (idempotent /
        concurrency-safe via the partial unique index). Returns
        ``(edge, created)``."""
        existing = self.db.execute(
            select(ControlGraphEdge).where(
                ControlGraphEdge.organization_id == actor.organization_id,
                ControlGraphEdge.source_type == source_type,
                ControlGraphEdge.source_id == source_id,
                ControlGraphEdge.edge_type == edge_type,
                ControlGraphEdge.target_type == target_type,
                ControlGraphEdge.target_id == target_id,
                ControlGraphEdge.revoked_at.is_(None),
            )
        ).scalars().first()
        if existing is not None:
            return existing, False

        edge = ControlGraphEdge(
            organization_id=actor.organization_id,
            source_type=source_type,
            source_id=source_id,
            edge_type=edge_type,
            target_type=target_type,
            target_id=target_id,
            provenance=provenance,
            evidence=evidence,
            valid_until=valid_until,
            created_by=actor.id,
        )
        self.db.add(edge)
        try:
            self.db.commit()
        except IntegrityError:
            # A concurrent session created the same edge first -- the correct
            # outcome is one edge, so re-read theirs.
            self.db.rollback()
            edge = self.db.execute(
                select(ControlGraphEdge).where(
                    ControlGraphEdge.organization_id == actor.organization_id,
                    ControlGraphEdge.source_type == source_type,
                    ControlGraphEdge.source_id == source_id,
                    ControlGraphEdge.edge_type == edge_type,
                    ControlGraphEdge.target_type == target_type,
                    ControlGraphEdge.target_id == target_id,
                    ControlGraphEdge.revoked_at.is_(None),
                )
            ).scalars().one()
            return edge, False
        self.db.refresh(edge)
        return edge, True

    def create_trust_edge(
        self,
        actor: User,
        *,
        source_type: str,
        source_id: uuid.UUID,
        target_type: str,
        target_id: uuid.UUID,
        note: str | None = None,
        valid_until=None,
    ) -> ControlGraphEdge:
        if source_type == target_type and source_id == target_id:
            raise IdentityError(ErrorCode.GRAPH_EDGE_INVALID, "An edge cannot loop on one node.")
        self._require_in_tenant(actor, source_type, source_id)
        self._require_in_tenant(actor, target_type, target_id)

        evidence = {"kind": "trust", "created_by": str(actor.id)}
        if note:
            evidence["note"] = note[:500]
        edge, created = self._upsert_edge(
            actor,
            source_type=source_type,
            source_id=source_id,
            edge_type="TRUSTS",
            target_type=target_type,
            target_id=target_id,
            provenance="EXPLICIT",
            evidence=evidence,
            valid_until=valid_until,
        )
        if created:
            _record_event(
                self.db,
                _TRUST_EVENT[True],
                actor,
                organization_id=actor.organization_id,
                meta={
                    "edge_id": str(edge.id),
                    "source": f"{source_type}:{source_id}",
                    "target": f"{target_type}:{target_id}",
                },
            )
            self.db.commit()
        return edge

    def create_delegation_edge(self, actor: User, *, delegation_id: uuid.UUID) -> ControlGraphEdge:
        """Represent an existing ``delegations`` row as a DELEGATES_TO edge.

        The row must be a live delegation in the caller's tenant. This
        service never writes ``delegations`` -- ``DelegationService`` owns
        that lifecycle; the edge only mirrors it, with ``evidence`` pointing
        back at the row (SRS §14 -- delegation as edges over the existing
        service, not a parallel mechanism)."""
        deleg = self.db.get(Delegation, delegation_id)
        if deleg is None or deleg.organization_id != actor.organization_id:
            raise IdentityError(
                ErrorCode.GRAPH_DELEGATION_NOT_REPRESENTABLE,
                "No such delegation in this organization.",
            )
        if deleg.revoked_at is not None:
            raise IdentityError(
                ErrorCode.GRAPH_DELEGATION_NOT_REPRESENTABLE,
                "That delegation has been revoked and cannot be represented as a live edge.",
            )
        if deleg.delegator_id is None:
            raise IdentityError(
                ErrorCode.GRAPH_DELEGATION_NOT_REPRESENTABLE,
                "That delegation has no recorded delegator to anchor an edge.",
            )
        self._require_in_tenant(actor, "HUMAN", deleg.delegator_id)
        self._require_in_tenant(actor, "HUMAN", deleg.delegatee_id)

        evidence = {
            "kind": "delegation",
            "ref_table": "delegations",
            "ref_id": str(deleg.id),
            "scope_type": deleg.scope_type,
            "scope_id": str(deleg.scope_id) if deleg.scope_id else None,
            "permission": deleg.permission,
        }
        edge, created = self._upsert_edge(
            actor,
            source_type="HUMAN",
            source_id=deleg.delegator_id,
            edge_type="DELEGATES_TO",
            target_type="HUMAN",
            target_id=deleg.delegatee_id,
            provenance="DERIVED",
            evidence=evidence,
        )
        if created:
            _record_event(
                self.db,
                _DELEGATION_EVENT[True],
                actor,
                organization_id=actor.organization_id,
                meta={"edge_id": str(edge.id), "delegation_id": str(deleg.id)},
            )
            self.db.commit()
        return edge

    def revoke_edge(self, actor: User, edge_id: uuid.UUID) -> ControlGraphEdge:
        # lock the row so two revokers serialize on a single deterministic
        # outcome (the AgentControlStateService._lock precedent).
        stale = self.db.get(ControlGraphEdge, edge_id)
        if stale is not None:
            self.db.expunge(stale)
        edge = self.db.get(ControlGraphEdge, edge_id, with_for_update=True)
        if edge is None or edge.organization_id != actor.organization_id:
            raise IdentityError(ErrorCode.GRAPH_EDGE_NOT_FOUND, "Edge not found.")
        if edge.revoked_at is not None:
            raise IdentityError(ErrorCode.GRAPH_EDGE_ALREADY_REVOKED, "Edge is already revoked.")
        if edge.provenance == "DISCOVERED":
            raise IdentityError(
                ErrorCode.GRAPH_EDGE_INVALID,
                "A discovery-produced edge is resolved by reconciliation, not revoked here.",
            )
        edge.revoked_at = _now()
        edge.revoked_by = actor.id
        event = _DELEGATION_EVENT[False] if edge.edge_type == "DELEGATES_TO" else _TRUST_EVENT[False]
        _record_event(
            self.db,
            event,
            actor,
            organization_id=actor.organization_id,
            meta={"edge_id": str(edge.id), "edge_type": edge.edge_type},
        )
        self.db.commit()
        self.db.refresh(edge)
        return edge


class AuthorityChainService:
    """Reconstruction + reachability. Both are reads; both are off every
    execution and governance path. A failure here returns an error to the
    caller and never blocks an execution or mutates authority (SRS §10 --
    the graph is a derived plane, like telemetry). Missing evidence for a
    hop is explicit ("chain incomplete"), never rendered as "no delegation
    occurred"."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def reconstruct(
        self, actor: User, execution_id: uuid.UUID, *, max_depth: int | None = None
    ) -> AuthorityChain:
        if max_depth is not None and max_depth > MAX_TRAVERSAL_DEPTH:
            raise IdentityError(
                ErrorCode.GRAPH_TRAVERSAL_DEPTH_EXCEEDED,
                f"max_depth cannot exceed {MAX_TRAVERSAL_DEPTH}.",
            )
        chain = reconstruct_authority_chain(
            self.db, actor.organization_id, execution_id, max_depth=max_depth
        )
        if chain is None:
            raise IdentityError(
                ErrorCode.GRAPH_NODE_NOT_FOUND, "No such execution in this organization."
            )
        _record_event(
            self.db,
            AuthorizationAuditEvent.GRAPH_AUTHORITY_CHAIN_RECONSTRUCTED,
            actor,
            organization_id=actor.organization_id,
            execution_id=execution_id,
            meta={
                "execution_id": str(execution_id),
                "hop_count": len(chain.hops),
                "complete": chain.complete,
            },
        )
        self.db.commit()
        return chain

    def reachability(
        self,
        actor: User,
        *,
        node_type: str,
        node_id: uuid.UUID,
        edge_types: list[str] | None = None,
        direction: str = "out",
        max_depth: int | None = None,
    ) -> list[ReachableNode]:
        if max_depth is not None and max_depth > MAX_TRAVERSAL_DEPTH:
            raise IdentityError(
                ErrorCode.GRAPH_TRAVERSAL_DEPTH_EXCEEDED,
                f"max_depth cannot exceed {MAX_TRAVERSAL_DEPTH}.",
            )
        if resolve_node(self.db, actor.organization_id, node_type, node_id) is None:
            raise IdentityError(
                ErrorCode.GRAPH_NODE_NOT_FOUND, "No such node in this organization."
            )
        return traverse(
            self.db,
            actor.organization_id,
            start_type=node_type,
            start_id=node_id,
            edge_types=edge_types,
            direction=direction,
            max_depth=max_depth,
        )


__all__ = ["ControlGraphService", "AuthorityChainService"]
