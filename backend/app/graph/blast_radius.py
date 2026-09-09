"""Phase 5.4 (M5.4) - ``BlastRadiusService``: the security payoff.

Deterministic, explainable, per-hop tenant-bounded reachability over the
Phase 5.4 dependency edges, reusing the 5.3 recursive-CTE machinery
(``traverse_with_edges`` - per-hop ``organization_id = :org``, path-array
cycle guard, ``MAX_TRAVERSAL_DEPTH`` cap, out-of-tenant truncation). **No new
traversal engine.**

The four questions the milestone points at:

  * ``agents_reaching(node)``            - "which agents can reach resource X"
  * ``what_breaks(node)``                - "what breaks if credential / MCP /
                                           tool Y is revoked or removed"
  * ``agents_depending_on_mcp(server)``  - "which agents depend on MCP server Z"
  * ``agents_reaching_resource_kind(k)`` - "which agents can reach a resource
                                           of kind / classification K"
                                           (e.g. payroll, customer financials)

Each answer:
  * names its path (the exact edge chain + each edge's evidence) - SRS §7.4;
  * is **per-hop tenant-bounded** - a blast radius never crosses a tenant
    boundary, even via a shared-looking node (re-proven for dependency edges);
  * carries ``incomplete`` - ``True`` when the walk was cut at the depth cap,
    so an answer is never falsely "empty" when it might be partial (SRS §11);
  * is a **read**: it changes nothing, mutates no authority. It is recorded
    (``GRAPH_BLAST_RADIUS_QUERIED``) because it exposes the shape of the
    tenant's dependency surface.

A query failure fails **open** - it returns an error to its caller and can
never block an execution or corrupt an edge (the graph is a derived plane).
"""

from __future__ import annotations

import uuid

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.authorization.enums import AuthorizationAuditEvent
from app.graph.nodes import resolve_node
from app.graph.traversal import MAX_TRAVERSAL_DEPTH, DependencyPath, traverse_with_edges
from app.identity.errors import ErrorCode, IdentityError
from app.models.graph import DEPENDENCY_EDGE_TYPES
from app.models.user import User
from app.runtime.services import _record_event


def _path_as_dict(p: DependencyPath) -> dict:
    return {
        "node": {"type": p.node_type, "id": str(p.node_id), "label": p.label},
        "depth": p.depth,
        "node_path": p.node_path,
        "edges": [
            {
                "edge_id": h.edge_id,
                "edge_type": h.edge_type,
                "from": {"type": h.source_type, "id": h.source_id},
                "to": {"type": h.target_type, "id": h.target_id},
                "evidence": h.evidence,
            }
            for h in p.edges
        ],
    }


class BlastRadiusService:
    def __init__(self, db: Session) -> None:
        self.db = db

    # ------------------------------------------------------------------ #
    @staticmethod
    def _check_depth(max_depth: int | None) -> None:
        if max_depth is not None and max_depth > MAX_TRAVERSAL_DEPTH:
            raise IdentityError(
                ErrorCode.GRAPH_TRAVERSAL_DEPTH_EXCEEDED,
                f"max_depth cannot exceed {MAX_TRAVERSAL_DEPTH}.",
            )

    def _require_node(self, actor: User, node_type: str, node_id: uuid.UUID) -> str:
        node = resolve_node(self.db, actor.organization_id, node_type, node_id)
        if node is None:
            raise IdentityError(
                ErrorCode.GRAPH_NODE_NOT_FOUND, "No such node in this organization."
            )
        return node.label

    def _reverse(
        self, actor: User, node_type: str, node_id: uuid.UUID, *, max_depth: int | None
    ) -> tuple[list[DependencyPath], bool]:
        """Everything that depends on this node: walk the dependency edges
        backwards (target -> source), per-hop tenant-bounded."""
        return traverse_with_edges(
            self.db,
            actor.organization_id,
            start_type=node_type,
            start_id=node_id,
            edge_types=list(DEPENDENCY_EDGE_TYPES),
            direction="in",
            max_depth=max_depth,
        )

    def _audit(self, actor: User, query: str, meta: dict) -> None:
        _record_event(
            self.db,
            AuthorizationAuditEvent.GRAPH_BLAST_RADIUS_QUERIED,
            actor,
            organization_id=actor.organization_id,
            meta={"query": query, **meta},
        )
        self.db.commit()

    # ------------------------------------------------------------------ #
    # 1. which agents can reach node X
    # ------------------------------------------------------------------ #
    def agents_reaching(
        self, actor: User, *, node_type: str, node_id: uuid.UUID, max_depth: int | None = None
    ) -> dict:
        self._check_depth(max_depth)
        label = self._require_node(actor, node_type, node_id)
        paths, capped = self._reverse(actor, node_type, node_id, max_depth=max_depth)
        agents = [p for p in paths if p.node_type == "AGENT"]
        self._audit(
            actor, "agents_reaching",
            {"target": f"{node_type}:{node_id}", "agent_count": len(agents), "incomplete": capped},
        )
        return {
            "target": {"type": node_type, "id": str(node_id), "label": label},
            "incomplete": capped,
            "incomplete_reason": "traversal hit the depth cap" if capped else None,
            "agents": [_path_as_dict(p) for p in agents],
            "all_dependents": [_path_as_dict(p) for p in paths],
        }

    # ------------------------------------------------------------------ #
    # 2. what breaks if node Y is revoked / removed
    # ------------------------------------------------------------------ #
    def what_breaks(
        self, actor: User, *, node_type: str, node_id: uuid.UUID, max_depth: int | None = None
    ) -> dict:
        self._check_depth(max_depth)
        label = self._require_node(actor, node_type, node_id)
        paths, capped = self._reverse(actor, node_type, node_id, max_depth=max_depth)
        agents = [p for p in paths if p.node_type == "AGENT"]
        self._audit(
            actor, "what_breaks",
            {"revoked": f"{node_type}:{node_id}", "affected": len(paths), "incomplete": capped},
        )
        return {
            "revoked": {"type": node_type, "id": str(node_id), "label": label},
            "incomplete": capped,
            "incomplete_reason": "traversal hit the depth cap" if capped else None,
            "affected_agents": [_path_as_dict(p) for p in agents],
            "affected_nodes": [_path_as_dict(p) for p in paths],
        }

    # ------------------------------------------------------------------ #
    # 3. which agents depend on MCP server Z
    # ------------------------------------------------------------------ #
    def agents_depending_on_mcp(
        self, actor: User, server_id: uuid.UUID, *, max_depth: int | None = None
    ) -> dict:
        self._check_depth(max_depth)
        server = self.db.execute(
            text(
                "SELECT name, trust_status, provenance FROM mcp_servers "
                "WHERE id = :id AND organization_id = :org"
            ),
            {"id": str(server_id), "org": str(actor.organization_id)},
        ).first()
        if server is None:
            raise IdentityError(
                ErrorCode.GRAPH_MCP_SERVER_NOT_FOUND, "MCP server not found."
            )
        name, trust_status, provenance = server
        paths, capped = self._reverse(actor, "MCP_SERVER", server_id, max_depth=max_depth)
        agents = [p for p in paths if p.node_type == "AGENT"]
        unapproved = trust_status != "APPROVED"
        self._audit(
            actor, "agents_depending_on_mcp",
            {"mcp_server_id": str(server_id), "agent_count": len(agents),
             "unapproved": unapproved, "incomplete": capped},
        )
        return {
            "mcp_server": {
                "id": str(server_id), "name": name,
                "trust_status": trust_status, "provenance": provenance,
                # 5.4 surfaces the evidence; the posture *finding* is 5.5's job.
                "is_unapproved_dependency": unapproved,
            },
            "incomplete": capped,
            "incomplete_reason": "traversal hit the depth cap" if capped else None,
            "direct_dependents": [
                _path_as_dict(p) for p in agents if p.depth == 1
            ],
            "transitive_dependents": [
                _path_as_dict(p) for p in agents if p.depth > 1
            ],
            "agents": [_path_as_dict(p) for p in agents],
        }

    # ------------------------------------------------------------------ #
    # 4. which agents can reach a resource of kind / classification K
    # ------------------------------------------------------------------ #
    def agents_reaching_resource_kind(
        self, actor: User, kind: str, *, max_depth: int | None = None
    ) -> dict:
        self._check_depth(max_depth)
        kind = (kind or "").strip()
        if not kind:
            raise IdentityError(
                ErrorCode.GRAPH_DEPENDENCY_INVALID, "A resource kind is required."
            )
        resources = self.db.execute(
            text(
                "SELECT id, COALESCE(name, resource_type) FROM resources "
                "WHERE organization_id = :org AND resource_type = :kind"
            ),
            {"org": str(actor.organization_id), "kind": kind},
        ).all()
        by_agent: dict[str, dict] = {}
        incomplete = False
        matched_resources = []
        for res_id, res_label in resources:
            rid = res_id if isinstance(res_id, uuid.UUID) else uuid.UUID(str(res_id))
            matched_resources.append({"id": str(rid), "label": res_label})
            paths, capped = self._reverse(actor, "RESOURCE", rid, max_depth=max_depth)
            incomplete = incomplete or capped
            for p in paths:
                if p.node_type != "AGENT":
                    continue
                key = str(p.node_id)
                entry = by_agent.setdefault(
                    key,
                    {"agent": {"id": key, "label": p.label}, "reaches": []},
                )
                entry["reaches"].append(
                    {"resource": {"id": str(rid), "label": res_label}, **_path_as_dict(p)}
                )
        self._audit(
            actor, "agents_reaching_resource_kind",
            {"kind": kind, "resource_count": len(resources),
             "agent_count": len(by_agent), "incomplete": incomplete},
        )
        return {
            "kind": kind,
            "matched_resources": matched_resources,
            "incomplete": incomplete,
            "incomplete_reason": "traversal hit the depth cap" if incomplete else (
                None if resources else "no resource of this kind is recorded"
            ),
            "agents": list(by_agent.values()),
        }

    # ------------------------------------------------------------------ #
    # evidence for 5.5: agents depending on an unapproved MCP server
    # ------------------------------------------------------------------ #
    def unapproved_mcp_dependencies(self, actor: User) -> dict:
        rows = self.db.execute(
            text(
                """
                SELECT e.id, e.source_id, e.evidence, m.id, m.name, m.trust_status, m.provenance
                FROM control_graph_edges e
                JOIN mcp_servers m ON m.id = e.target_id
                WHERE e.organization_id = :org
                  AND e.edge_type = 'DEPENDS_ON_MCP_SERVER'
                  AND e.revoked_at IS NULL
                  AND m.trust_status <> 'APPROVED'
                ORDER BY m.name
                """
            ),
            {"org": str(actor.organization_id)},
        ).all()
        findings = []
        for edge_id, agent_id, evidence, mcp_id, mcp_name, trust_status, provenance in rows:
            agent = resolve_node(self.db, actor.organization_id, "AGENT", uuid.UUID(str(agent_id)))
            if agent is None:
                continue  # not in tenant -> not our evidence
            findings.append({
                "edge_id": str(edge_id),
                "agent": {"id": str(agent_id), "label": agent.label},
                "mcp_server": {
                    "id": str(mcp_id), "name": mcp_name,
                    "trust_status": trust_status, "provenance": provenance,
                },
                "evidence": evidence or {},
                "why": (
                    f"agent depends on MCP server {mcp_name!r} whose trust status is "
                    f"{trust_status} (provenance {provenance}) - unknown != safe"
                ),
            })
        return {
            "count": len(findings),
            "note": "Evidence for a Phase 5.5 posture finding; 5.4 does not raise the finding.",
            "dependencies": findings,
        }


__all__ = ["BlastRadiusService"]
