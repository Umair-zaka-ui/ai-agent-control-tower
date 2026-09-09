"""Phase 5.4 (M5.4) - ``McpServerService``: an MCP server as a first-class,
security-relevant dependency, represented **via the existing ``Tool``
domain** (ADR-0018).

**No second tool registry.** This service owns the ``mcp_servers`` row -- an
MCP server's identity, provenance, ownership, trust/approval state, version
and endpoint reference. It never creates a ``tools`` row and never a second
tool table. The tools an MCP server exposes are ordinary ``tools`` rows
(created through the existing runtime tool API) whose ``mcp_server_id`` points
back at the server; ``link_tool`` only sets that column and records the
``MCP_EXPOSES_TOOL`` edge.

**The graph represents; it never creates.** Registering a server and linking
its tools grants nothing. MCP tool I/O stays contained by the existing
egress/SSRF guard and tool-schema validation (M1); ``AuthorizationGateway``
stays the sole decider.

**Unknown != safe.** A server registered with unknown provenance lands at
``trust_status='UNKNOWN'``; an un-reviewed one at ``'PENDING'``. Anything
other than ``'APPROVED'`` is surfaced (by ``BlastRadiusService`` and the
dependency read API) as *evidence* that an agent depends on an unapproved
MCP server -- the posture *finding* is Phase 5.5's job.

**No DB lock across an MCP probe.** 5.4 does not connect to arbitrary real
MCP servers in prod ([DEFERRED] -- a reference/local representation only). If
a probe is ever run, ``record_probe`` is a fetch-then-write: it takes no lock
while the network call is outstanding and only marks freshness afterwards,
never deleting the row on failure (SRS §11).
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.authorization.enums import AuthorizationAuditEvent
from app.graph.nodes import resolve_node
from app.identity.errors import ErrorCode, IdentityError
from app.models.graph import MCP_PROVENANCE, MCP_TRUST_STATUSES, ControlGraphEdge, McpServer
from app.models.runtime import Tool
from app.models.user import User
from app.runtime.services import _now, _record_event

_MAX_NAME = 255
_MAX_DESC = 2000


class McpServerService:
    def __init__(self, db: Session) -> None:
        self.db = db

    # ------------------------------------------------------------------ #
    # reads
    # ------------------------------------------------------------------ #
    def get_or_404(self, actor: User, server_id: uuid.UUID) -> McpServer:
        server = self.db.get(McpServer, server_id)
        if server is None or server.organization_id != actor.organization_id:
            # cross-tenant and missing are indistinguishable (no existence leak)
            raise IdentityError(
                ErrorCode.GRAPH_MCP_SERVER_NOT_FOUND, "MCP server not found."
            )
        return server

    def list_servers(
        self, actor: User, *, trust_status: str | None = None
    ) -> list[McpServer]:
        stmt = select(McpServer).where(
            McpServer.organization_id == actor.organization_id
        )
        if trust_status:
            stmt = stmt.where(McpServer.trust_status == trust_status)
        return list(
            self.db.execute(stmt.order_by(McpServer.created_at.desc())).scalars()
        )

    def exposed_tools(self, actor: User, server_id: uuid.UUID) -> list[Tool]:
        self.get_or_404(actor, server_id)
        return list(
            self.db.execute(
                select(Tool).where(Tool.mcp_server_id == server_id).order_by(Tool.name)
            ).scalars()
        )

    # ------------------------------------------------------------------ #
    # writes -- represent, never create authority
    # ------------------------------------------------------------------ #
    def register(
        self,
        actor: User,
        *,
        name: str,
        description: str | None = None,
        provenance: str = "EXPLICIT",
        trust_status: str = "PENDING",
        version: str | None = None,
        endpoint_reference: str | None = None,
        declared_capabilities: dict | None = None,
        owner_id: uuid.UUID | None = None,
        owner_type: str | None = None,
    ) -> McpServer:
        if provenance not in MCP_PROVENANCE:
            raise IdentityError(
                ErrorCode.GRAPH_MCP_TRUST_INVALID, f"provenance must be one of {MCP_PROVENANCE}."
            )
        if trust_status not in MCP_TRUST_STATUSES:
            raise IdentityError(
                ErrorCode.GRAPH_MCP_TRUST_INVALID,
                f"trust_status must be one of {MCP_TRUST_STATUSES}.",
            )
        name = (name or "").strip()[:_MAX_NAME]
        if not name:
            raise IdentityError(
                ErrorCode.GRAPH_MCP_TRUST_INVALID, "An MCP server needs a name."
            )
        if owner_id is not None and resolve_node(
            self.db, actor.organization_id, "HUMAN", owner_id
        ) is None:
            raise IdentityError(
                ErrorCode.GRAPH_CROSS_TENANT_ENDPOINT,
                "The named owner was not found in this organization.",
            )

        # idempotent on (org, name) via uq_mcp_servers_org_name
        existing = self.db.execute(
            select(McpServer).where(
                McpServer.organization_id == actor.organization_id,
                McpServer.name == name,
            )
        ).scalars().first()
        if existing is not None:
            return existing

        server = McpServer(
            organization_id=actor.organization_id,
            name=name,
            description=description[:_MAX_DESC] if description else None,
            provenance=provenance,
            trust_status=trust_status,
            version=(version or None),
            endpoint_reference=(endpoint_reference or None),
            declared_capabilities=declared_capabilities or {},
            owner_id=owner_id,
            owner_type=owner_type,
            created_by=actor.id,
        )
        self.db.add(server)
        try:
            self.db.commit()
        except IntegrityError:
            self.db.rollback()
            return self.db.execute(
                select(McpServer).where(
                    McpServer.organization_id == actor.organization_id,
                    McpServer.name == name,
                )
            ).scalars().one()
        self.db.refresh(server)
        _record_event(
            self.db,
            AuthorizationAuditEvent.GRAPH_MCP_SERVER_REGISTERED,
            actor,
            organization_id=actor.organization_id,
            meta={
                "mcp_server_id": str(server.id),
                "name": server.name,
                "provenance": server.provenance,
                "trust_status": server.trust_status,
            },
        )
        self.db.commit()
        self.db.refresh(server)
        return server

    def set_trust(
        self, actor: User, server_id: uuid.UUID, *, trust_status: str, note: str | None = None
    ) -> McpServer:
        if trust_status not in MCP_TRUST_STATUSES:
            raise IdentityError(
                ErrorCode.GRAPH_MCP_TRUST_INVALID,
                f"trust_status must be one of {MCP_TRUST_STATUSES}.",
            )
        # lock the row so two reviewers serialize on a single outcome
        stale = self.db.get(McpServer, server_id)
        if stale is not None:
            self.db.expunge(stale)
        server = self.db.get(McpServer, server_id, with_for_update=True)
        if server is None or server.organization_id != actor.organization_id:
            raise IdentityError(
                ErrorCode.GRAPH_MCP_SERVER_NOT_FOUND, "MCP server not found."
            )
        previous = server.trust_status
        server.trust_status = trust_status
        server.updated_at = _now()
        _record_event(
            self.db,
            AuthorizationAuditEvent.GRAPH_MCP_TRUST_CHANGED,
            actor,
            organization_id=actor.organization_id,
            meta={
                "mcp_server_id": str(server.id),
                "previous": previous,
                "new": trust_status,
                "note": (note or "")[:500] or None,
            },
        )
        self.db.commit()
        self.db.refresh(server)
        return server

    def link_tool(
        self, actor: User, server_id: uuid.UUID, tool_id: uuid.UUID
    ) -> ControlGraphEdge:
        """Mark an existing ``tools`` row as exposed by this MCP server and
        record the ``MCP_EXPOSES_TOOL`` edge. Never creates a tool."""
        server = self.get_or_404(actor, server_id)
        tool = self.db.get(Tool, tool_id)
        if tool is None or (
            tool.organization_id is not None
            and tool.organization_id != actor.organization_id
        ):
            raise IdentityError(
                ErrorCode.GRAPH_CROSS_TENANT_ENDPOINT,
                "That tool was not found in this organization.",
            )
        tool.mcp_server_id = server.id
        from app.graph.dependencies import DependencyGraphService

        edge = DependencyGraphService(self.db)._upsert_dependency_edge(
            actor,
            source_type="MCP_SERVER",
            source_id=server.id,
            edge_type="MCP_EXPOSES_TOOL",
            target_type="TOOL",
            target_id=tool.id,
            evidence={"mode": "DECLARED", "source": "tools.mcp_server_id"},
        )
        _record_event(
            self.db,
            AuthorizationAuditEvent.GRAPH_DEPENDENCY_EDGE_CREATED,
            actor,
            organization_id=actor.organization_id,
            meta={
                "edge_id": str(edge.id),
                "edge_type": "MCP_EXPOSES_TOOL",
                "mcp_server_id": str(server.id),
                "tool_id": str(tool.id),
            },
        )
        self.db.commit()
        self.db.refresh(edge)
        return edge

    def record_probe(
        self, actor: User, server_id: uuid.UUID, *, status: str, capabilities: dict | None = None
    ) -> McpServer:
        """Fetch-then-write: the caller does the (network) probe with NO DB
        lock held, then calls this to mark freshness. A failed probe marks
        ``probe_status`` and never deletes the row (SRS §11)."""
        server = self.get_or_404(actor, server_id)
        server.last_probed_at = _now()
        server.probe_status = (status or "")[:24] or None
        if capabilities is not None:
            server.declared_capabilities = capabilities
        self.db.commit()
        self.db.refresh(server)
        return server


__all__ = ["McpServerService"]
