"""The node ``(type, id)`` <-> table mapping and tenant-scoped resolution.

An edge endpoint never stores node state. This module is the one place that
knows which table a node type lives in and how that table's tenant is
established -- directly (``organization_id`` on the row) or transitively (an
``agent_identities`` / ``agent_api_keys`` row inherits its agent's tenant).

Every resolver here is **tenant-scoped**: a node id that does not resolve
*within the given organization* comes back ``None``. That is what lets a
recursive traversal treat "the next node is not in my tenant" identically to
"the next node does not exist" -- the walk simply stops (SRS §T).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.graph import NODE_TYPES

# node type -> a SELECT that yields (id, organization_id, label) for every row
# of that type, with tenant resolved (directly or via a join). Used both to
# hydrate a traversal result and to check a single node's tenant. ``label`` is
# a best-effort human-readable name; never a secret.
_NODE_SOURCES: dict[str, str] = {
    "HUMAN": "SELECT id, organization_id, COALESCE(email, '') AS label FROM users",
    "AGENT": "SELECT id, organization_id, COALESCE(name, '') AS label FROM agents",
    "AGENT_IDENTITY": (
        "SELECT ai.id, a.organization_id, COALESCE(ai.client_id, '') AS label "
        "FROM agent_identities ai JOIN agents a ON a.id = ai.agent_id"
    ),
    "SERVICE_ACCOUNT": (
        "SELECT id, organization_id, COALESCE(name, '') AS label FROM service_accounts"
    ),
    "FEDERATED_IDENTITY": (
        "SELECT id, organization_id, COALESCE(external_subject_id, '') AS label "
        "FROM federated_identities"
    ),
    "EXTERNAL_CLIENT": (
        "SELECT id, organization_id, COALESCE(client_name, '') AS label FROM external_clients"
    ),
    "TOOL": "SELECT id, organization_id, COALESCE(name, '') AS label FROM tools",
    "CREDENTIAL": (
        "SELECT ak.id, a.organization_id, COALESCE(ak.key_prefix, '') AS label "
        "FROM agent_api_keys ak JOIN agents a ON a.id = ak.agent_id"
    ),
    "RESOURCE": (
        "SELECT id, organization_id, COALESCE(name, resource_type) AS label FROM resources"
    ),
    "ORGANIZATION": "SELECT id, id AS organization_id, COALESCE(name, '') AS label FROM organizations",
}

assert set(_NODE_SOURCES) == set(NODE_TYPES), "node source map drifted from NODE_TYPES"


@dataclass(frozen=True)
class ResolvedNode:
    node_type: str
    node_id: uuid.UUID
    label: str


def node_source_sql(node_type: str) -> str:
    """The ``(id, organization_id, label)`` SELECT for one node type."""
    try:
        return _NODE_SOURCES[node_type]
    except KeyError as exc:  # pragma: no cover - guarded by the schema CHECK too
        raise ValueError(f"unknown graph node type: {node_type!r}") from exc


def resolve_node(
    db: Session, organization_id: uuid.UUID, node_type: str, node_id: uuid.UUID
) -> ResolvedNode | None:
    """Return the node iff it exists **and belongs to this organization**.

    Cross-tenant or missing -> ``None`` (the caller renders both as "the walk
    stopped here", never as an existence oracle)."""
    if node_type not in _NODE_SOURCES:
        return None
    row = db.execute(
        text(
            f"SELECT label FROM ({_NODE_SOURCES[node_type]}) AS n "
            "WHERE n.id = :nid AND n.organization_id = :org"
        ),
        {"nid": str(node_id), "org": str(organization_id)},
    ).first()
    if row is None:
        return None
    return ResolvedNode(node_type=node_type, node_id=node_id, label=row[0] or "")


def node_exists_in_tenant(
    db: Session, organization_id: uuid.UUID, node_type: str, node_id: uuid.UUID
) -> bool:
    return resolve_node(db, organization_id, node_type, node_id) is not None


__all__ = [
    "ResolvedNode",
    "node_source_sql",
    "resolve_node",
    "node_exists_in_tenant",
]
