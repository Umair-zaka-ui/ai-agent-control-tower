"""Phase 5.4 (M5.4) - ``DependencyGraphService``: dependency edges on the
5.3 substrate, derived from evidence or declared through the API.

**More edge types, same table.** A dependency edge is a row on
``control_graph_edges`` with a Phase 5.4 ``edge_type``. It references two
existing rows and grants no authority (the 5.3 rule, extended). It carries
``evidence.mode``:

  * ``OBSERVED``  - the platform actually recorded this dependency happening
                    (a ``tool_calls`` row: this agent invoked this tool).
  * ``DECLARED``  - a binding/config says the dependency exists (an
                    ``agent_tools`` assignment, a ``tool_credentials`` row, a
                    ``tools.mcp_server_id`` link, the version's model provider).

An *observed* dependency and a *declared* one are different evidence and are
never conflated (SRS §N). ``build_for_agent`` derives both from existing rows
(``provenance='DERIVED'``); ``create_declared_edge`` records an operator's
explicit assertion (``provenance='EXPLICIT'``, authorized + audited).

**Missing evidence is explicit.** "No observed/declared dependency recorded"
is not "no dependency exists" -- ``build_for_agent`` returns what it found and
the read API says so; it never renders an empty result as proof of no
dependency (unknown != safe).
"""

from __future__ import annotations

import uuid

from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.authorization.enums import AuthorizationAuditEvent
from app.graph.nodes import resolve_node
from app.identity.errors import ErrorCode, IdentityError
from app.models.graph import DEPENDENCY_EDGE_TYPES, ControlGraphEdge
from app.models.user import User
from app.runtime.services import _now, _record_event

# The permitted (source_type, target_type) for each dependency edge type. A
# declared edge that does not match its shape is rejected before any row is
# touched.
_EDGE_SHAPE: dict[str, tuple[str, str]] = {
    "DEPENDS_ON_TOOL": ("AGENT", "TOOL"),
    "DEPENDS_ON_MCP_SERVER": ("AGENT", "MCP_SERVER"),
    "DEPENDS_ON_CREDENTIAL": ("AGENT", "CREDENTIAL"),
    "DEPENDS_ON_CONNECTOR": ("AGENT", "CONNECTOR"),
    "DEPENDS_ON_RESOURCE": ("AGENT", "RESOURCE"),
    "MCP_EXPOSES_TOOL": ("MCP_SERVER", "TOOL"),
    "TOOL_USES_CREDENTIAL": ("TOOL", "CREDENTIAL"),
    "TOOL_ACCESSES_RESOURCE": ("TOOL", "RESOURCE"),
    "CREDENTIAL_ACCESSES_RESOURCE": ("CREDENTIAL", "RESOURCE"),
}


class DependencyGraphService:
    def __init__(self, db: Session) -> None:
        self.db = db

    # ------------------------------------------------------------------ #
    # the idempotent, concurrency-safe upsert (mirrors ControlGraphService)
    # ------------------------------------------------------------------ #
    def _upsert_dependency_edge(
        self,
        actor: User,
        *,
        source_type: str,
        source_id: uuid.UUID,
        edge_type: str,
        target_type: str,
        target_id: uuid.UUID,
        evidence: dict,
        provenance: str = "DERIVED",
    ) -> ControlGraphEdge:
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
            # keep the evidence current, but never downgrade OBSERVED->DECLARED
            merged = dict(existing.evidence or {})
            if merged.get("mode") == "OBSERVED" and evidence.get("mode") == "DECLARED":
                evidence = {**evidence, "mode": "OBSERVED", "also_declared": True}
            merged.update(evidence)
            existing.evidence = merged
            self.db.add(existing)
            self.db.commit()
            self.db.refresh(existing)
            return existing

        edge = ControlGraphEdge(
            organization_id=actor.organization_id,
            source_type=source_type,
            source_id=source_id,
            edge_type=edge_type,
            target_type=target_type,
            target_id=target_id,
            provenance=provenance,
            evidence=evidence,
            created_by=actor.id,
        )
        self.db.add(edge)
        try:
            self.db.commit()
        except IntegrityError:
            # concurrent create of the same edge -> exactly one row, re-read it
            self.db.rollback()
            return self.db.execute(
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
        self.db.refresh(edge)
        return edge

    # ------------------------------------------------------------------ #
    # reads
    # ------------------------------------------------------------------ #
    def list_for_agent(self, actor: User, agent_id: uuid.UUID) -> list[ControlGraphEdge]:
        if resolve_node(self.db, actor.organization_id, "AGENT", agent_id) is None:
            raise IdentityError(ErrorCode.GRAPH_NODE_NOT_FOUND, "No such agent in this organization.")
        return list(
            self.db.execute(
                select(ControlGraphEdge)
                .where(
                    ControlGraphEdge.organization_id == actor.organization_id,
                    ControlGraphEdge.revoked_at.is_(None),
                    ControlGraphEdge.edge_type.in_(DEPENDENCY_EDGE_TYPES),
                    ControlGraphEdge.source_type == "AGENT",
                    ControlGraphEdge.source_id == agent_id,
                )
                .order_by(ControlGraphEdge.edge_type, ControlGraphEdge.created_at)
            ).scalars()
        )

    # ------------------------------------------------------------------ #
    # derive dependency edges from evidence
    # ------------------------------------------------------------------ #
    def build_for_agent(self, actor: User, agent_id: uuid.UUID) -> dict:
        """Derive this agent's dependency edges from existing rows. Idempotent:
        re-running refreshes evidence and adds nothing new if nothing changed.

        Sources:
          * OBSERVED  - ``tool_calls`` for this agent's executions -> agent->tool
          * DECLARED  - ``agent_tools`` assignments               -> agent->tool
          * DECLARED  - each depended tool's ``tool_credentials``  -> tool->credential
          * DECLARED  - each depended tool's ``mcp_server_id``     -> agent->mcp, mcp->tool
          * DECLARED  - the published version's model provider ->
                        ``provider_credentials`` row                -> agent->credential
        """
        if resolve_node(self.db, actor.organization_id, "AGENT", agent_id) is None:
            raise IdentityError(ErrorCode.GRAPH_NODE_NOT_FOUND, "No such agent in this organization.")
        org = actor.organization_id
        created = 0
        touched: dict[str, int] = {}
        tool_ids: set[uuid.UUID] = set()

        def _bump(edge_type: str, before_new: bool) -> None:
            nonlocal created
            touched[edge_type] = touched.get(edge_type, 0) + 1
            if before_new:
                created += 1

        # --- OBSERVED: tool_calls -------------------------------------- #
        observed = self.db.execute(
            text(
                """
                SELECT tc.tool_id, count(*) AS n, min(tc.id::text) AS sample,
                       max(tc.started_at) AS last_seen
                FROM tool_calls tc
                JOIN agent_executions ae ON ae.id = tc.execution_id
                WHERE ae.organization_id = :org AND tc.agent_id = :aid
                GROUP BY tc.tool_id
                """
            ),
            {"org": str(org), "aid": str(agent_id)},
        ).all()
        for tool_id, n, sample, last_seen in observed:
            tid = tool_id if isinstance(tool_id, uuid.UUID) else uuid.UUID(str(tool_id))
            if resolve_node(self.db, org, "TOOL", tid) is None:
                continue
            tool_ids.add(tid)
            pre = self._is_new(actor, "AGENT", agent_id, "DEPENDS_ON_TOOL", "TOOL", tid)
            self._upsert_dependency_edge(
                actor, source_type="AGENT", source_id=agent_id, edge_type="DEPENDS_ON_TOOL",
                target_type="TOOL", target_id=tid,
                evidence={
                    "mode": "OBSERVED", "source": "tool_calls", "call_count": int(n),
                    "sample_tool_call_id": sample,
                    "last_seen": last_seen.isoformat() if last_seen else None,
                },
            )
            _bump("DEPENDS_ON_TOOL", pre)

        # --- DECLARED: agent_tools ----------------------------------- #
        declared_tools = self.db.execute(
            text(
                """
                SELECT at.tool_id, at.status FROM agent_tools at
                JOIN tools t ON t.id = at.tool_id
                WHERE at.agent_id = :aid
                  AND (t.organization_id IS NULL OR t.organization_id = :org)
                """
            ),
            {"org": str(org), "aid": str(agent_id)},
        ).all()
        for tool_id, at_status in declared_tools:
            tid = tool_id if isinstance(tool_id, uuid.UUID) else uuid.UUID(str(tool_id))
            if resolve_node(self.db, org, "TOOL", tid) is None:
                continue
            tool_ids.add(tid)
            pre = self._is_new(actor, "AGENT", agent_id, "DEPENDS_ON_TOOL", "TOOL", tid)
            self._upsert_dependency_edge(
                actor, source_type="AGENT", source_id=agent_id, edge_type="DEPENDS_ON_TOOL",
                target_type="TOOL", target_id=tid,
                evidence={"mode": "DECLARED", "source": "agent_tools", "assignment_status": at_status},
            )
            _bump("DEPENDS_ON_TOOL", pre)

        # --- per depended tool: credentials + MCP provider ---------- #
        for tid in tool_ids:
            for cred_id, hint in self.db.execute(
                text(
                    "SELECT id, secret_hint FROM tool_credentials "
                    "WHERE organization_id = :org AND tool_id = :tid AND status = 'ACTIVE'"
                ),
                {"org": str(org), "tid": str(tid)},
            ).all():
                cid = cred_id if isinstance(cred_id, uuid.UUID) else uuid.UUID(str(cred_id))
                pre = self._is_new(actor, "TOOL", tid, "TOOL_USES_CREDENTIAL", "CREDENTIAL", cid)
                self._upsert_dependency_edge(
                    actor, source_type="TOOL", source_id=tid, edge_type="TOOL_USES_CREDENTIAL",
                    target_type="CREDENTIAL", target_id=cid,
                    evidence={"mode": "DECLARED", "source": "tool_credentials", "hint": hint},
                )
                _bump("TOOL_USES_CREDENTIAL", pre)

            mcp_row = self.db.execute(
                text("SELECT mcp_server_id FROM tools WHERE id = :tid"), {"tid": str(tid)}
            ).first()
            if mcp_row and mcp_row[0]:
                mcp_id = mcp_row[0] if isinstance(mcp_row[0], uuid.UUID) else uuid.UUID(str(mcp_row[0]))
                if resolve_node(self.db, org, "MCP_SERVER", mcp_id) is not None:
                    pre = self._is_new(actor, "AGENT", agent_id, "DEPENDS_ON_MCP_SERVER", "MCP_SERVER", mcp_id)
                    self._upsert_dependency_edge(
                        actor, source_type="AGENT", source_id=agent_id,
                        edge_type="DEPENDS_ON_MCP_SERVER", target_type="MCP_SERVER", target_id=mcp_id,
                        evidence={"mode": "DECLARED", "source": "tools.mcp_server_id", "via_tool": str(tid)},
                    )
                    _bump("DEPENDS_ON_MCP_SERVER", pre)
                    pre = self._is_new(actor, "MCP_SERVER", mcp_id, "MCP_EXPOSES_TOOL", "TOOL", tid)
                    self._upsert_dependency_edge(
                        actor, source_type="MCP_SERVER", source_id=mcp_id,
                        edge_type="MCP_EXPOSES_TOOL", target_type="TOOL", target_id=tid,
                        evidence={"mode": "DECLARED", "source": "tools.mcp_server_id"},
                    )
                    _bump("MCP_EXPOSES_TOOL", pre)

        # --- DECLARED: the published version's model provider -------- #
        prov = self.db.execute(
            text(
                """
                SELECT av.model_configuration
                FROM agent_versions av
                WHERE av.agent_id = :aid AND av.status = 'PUBLISHED'
                ORDER BY av.version DESC LIMIT 1
                """
            ),
            {"aid": str(agent_id)},
        ).first()
        if prov and isinstance(prov[0], dict):
            provider = str(prov[0].get("provider") or "").strip()
            model = str(prov[0].get("model") or "").strip()
            if provider:
                pc = self.db.execute(
                    text(
                        "SELECT id FROM provider_credentials "
                        "WHERE organization_id = :org AND lower(provider) = lower(:p)"
                    ),
                    {"org": str(org), "p": provider},
                ).first()
                if pc:
                    cid = pc[0] if isinstance(pc[0], uuid.UUID) else uuid.UUID(str(pc[0]))
                    pre = self._is_new(actor, "AGENT", agent_id, "DEPENDS_ON_CREDENTIAL", "CREDENTIAL", cid)
                    self._upsert_dependency_edge(
                        actor, source_type="AGENT", source_id=agent_id,
                        edge_type="DEPENDS_ON_CREDENTIAL", target_type="CREDENTIAL", target_id=cid,
                        evidence={
                            "mode": "DECLARED", "source": "provider_credentials",
                            "provider": provider, "model": model or None,
                        },
                    )
                    _bump("DEPENDS_ON_CREDENTIAL", pre)

        self.db.commit()
        _record_event(
            self.db,
            AuthorizationAuditEvent.GRAPH_DEPENDENCIES_REBUILT,
            actor,
            organization_id=org,
            agent_id=agent_id,
            meta={"agent_id": str(agent_id), "edges_created": created, "by_type": touched},
        )
        self.db.commit()
        return {
            "agent_id": str(agent_id),
            "edges_created": created,
            "by_type": touched,
            "note": (
                "Derived from recorded evidence only. Absence of an edge is not "
                "proof of no dependency (unknown != safe)."
            ),
        }

    def _is_new(
        self, actor: User, s_type: str, s_id: uuid.UUID, e_type: str, t_type: str, t_id: uuid.UUID
    ) -> bool:
        return (
            self.db.execute(
                select(ControlGraphEdge.id).where(
                    ControlGraphEdge.organization_id == actor.organization_id,
                    ControlGraphEdge.source_type == s_type,
                    ControlGraphEdge.source_id == s_id,
                    ControlGraphEdge.edge_type == e_type,
                    ControlGraphEdge.target_type == t_type,
                    ControlGraphEdge.target_id == t_id,
                    ControlGraphEdge.revoked_at.is_(None),
                )
            ).first()
            is None
        )

    # ------------------------------------------------------------------ #
    # an operator's explicit declared edge
    # ------------------------------------------------------------------ #
    def create_declared_edge(
        self,
        actor: User,
        *,
        source_type: str,
        source_id: uuid.UUID,
        edge_type: str,
        target_type: str,
        target_id: uuid.UUID,
        note: str | None = None,
    ) -> ControlGraphEdge:
        if edge_type not in _EDGE_SHAPE:
            raise IdentityError(
                ErrorCode.GRAPH_DEPENDENCY_INVALID,
                f"{edge_type} is not a dependency edge type.",
            )
        want_src, want_tgt = _EDGE_SHAPE[edge_type]
        if (source_type, target_type) != (want_src, want_tgt):
            raise IdentityError(
                ErrorCode.GRAPH_DEPENDENCY_INVALID,
                f"{edge_type} connects {want_src} -> {want_tgt}, not {source_type} -> {target_type}.",
            )
        if source_type == target_type and source_id == target_id:
            raise IdentityError(ErrorCode.GRAPH_DEPENDENCY_INVALID, "An edge cannot loop on one node.")
        if resolve_node(self.db, actor.organization_id, source_type, source_id) is None:
            raise IdentityError(
                ErrorCode.GRAPH_CROSS_TENANT_ENDPOINT,
                "The edge source was not found in this organization.",
            )
        if resolve_node(self.db, actor.organization_id, target_type, target_id) is None:
            raise IdentityError(
                ErrorCode.GRAPH_CROSS_TENANT_ENDPOINT,
                "The edge target was not found in this organization.",
            )
        evidence = {"mode": "DECLARED", "source": "operator", "created_by": str(actor.id)}
        if note:
            evidence["note"] = note[:500]
        edge = self._upsert_dependency_edge(
            actor,
            source_type=source_type,
            source_id=source_id,
            edge_type=edge_type,
            target_type=target_type,
            target_id=target_id,
            evidence=evidence,
            provenance="EXPLICIT",
        )
        self.db.flush()
        _record_event(
            self.db,
            AuthorizationAuditEvent.GRAPH_DEPENDENCY_EDGE_CREATED,
            actor,
            organization_id=actor.organization_id,
            meta={
                "edge_id": str(edge.id),
                "edge_type": edge_type,
                "source": f"{source_type}:{source_id}",
                "target": f"{target_type}:{target_id}",
            },
        )
        self.db.commit()
        self.db.refresh(edge)
        return edge

    def revoke_edge(self, actor: User, edge_id: uuid.UUID) -> ControlGraphEdge:
        stale = self.db.get(ControlGraphEdge, edge_id)
        if stale is not None:
            self.db.expunge(stale)
        edge = self.db.get(ControlGraphEdge, edge_id, with_for_update=True)
        if edge is None or edge.organization_id != actor.organization_id:
            raise IdentityError(ErrorCode.GRAPH_EDGE_NOT_FOUND, "Edge not found.")
        if edge.edge_type not in DEPENDENCY_EDGE_TYPES:
            raise IdentityError(
                ErrorCode.GRAPH_DEPENDENCY_INVALID,
                "That edge is not a dependency edge; revoke it through the graph edge API.",
            )
        if edge.revoked_at is not None:
            raise IdentityError(ErrorCode.GRAPH_EDGE_ALREADY_REVOKED, "Edge is already revoked.")
        edge.revoked_at = _now()
        edge.revoked_by = actor.id
        _record_event(
            self.db,
            AuthorizationAuditEvent.GRAPH_DEPENDENCY_EDGE_REVOKED,
            actor,
            organization_id=actor.organization_id,
            meta={"edge_id": str(edge.id), "edge_type": edge.edge_type},
        )
        self.db.commit()
        self.db.refresh(edge)
        return edge


__all__ = ["DependencyGraphService"]
