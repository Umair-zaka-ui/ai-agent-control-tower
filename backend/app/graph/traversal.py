"""The recursive CTEs: bounded, cycle-safe, per-hop tenant-bounded.

Two capabilities, both **relational** -- ``WITH RECURSIVE`` over
``control_graph_edges`` (and, for the replay prefix, over
``agent_executions``). No graph database, no projection (ADR-0017).

**Per-hop tenant bound (SRS §T -- the sharpest isolation rule).** Every
recursive step re-applies ``organization_id = :org`` on the joined edge.
Because every edge is validated same-tenant on *both* endpoints when it is
created (``ControlGraphService``), that single predicate is a correct bound
for service-created edges. For a hostile row inserted directly into the
table (the adversarial test), a second guarantee applies: any result node
that does not resolve *within the tenant* is dropped, and every node reached
*through* it is dropped too -- the walk is truncated at the first
out-of-tenant node, i.e. it stops at the tenant edge.

**Bounded / cycle-safe.** ``depth < :max_depth`` caps traversal length; a
path array carried on each row (``'type:id'`` strings) makes a revisit
impossible, so a cycle in the data cannot make the query run away.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.graph.nodes import node_source_sql, resolve_node

# A hard ceiling no caller can exceed -- defence in depth against a
# pathological request even if a caller passes a huge max_depth.
MAX_TRAVERSAL_DEPTH = 32
DEFAULT_TRAVERSAL_DEPTH = 16

_DELEGATION_EDGE_TYPES = ("DELEGATES_TO", "AGENT_DELEGATES_TO")


def _clamp_depth(requested: int | None) -> int:
    if requested is None:
        return DEFAULT_TRAVERSAL_DEPTH
    return max(1, min(int(requested), MAX_TRAVERSAL_DEPTH))


def _key(node_type: str, node_id) -> str:
    return f"{node_type}:{node_id}"


@dataclass(frozen=True)
class ReachableNode:
    node_type: str
    node_id: uuid.UUID
    depth: int
    label: str
    path: list[str]


def traverse(
    db: Session,
    organization_id: uuid.UUID,
    *,
    start_type: str,
    start_id: uuid.UUID,
    edge_types: list[str] | None = None,
    direction: str = "out",
    max_depth: int | None = None,
) -> list[ReachableNode]:
    """Reachability from one node over ``control_graph_edges``.

    ``direction``: ``"out"`` follows source->target, ``"in"`` follows
    target->source. Returns every node reachable within ``max_depth`` at its
    shortest depth, **excluding** any node that does not resolve inside
    ``organization_id`` and anything only reachable through such a node.
    """
    depth = _clamp_depth(max_depth)
    if direction not in ("out", "in"):
        raise ValueError("direction must be 'out' or 'in'")

    if direction == "out":
        match_type, match_id = "e.source_type", "e.source_id"
        step_type, step_id = "e.target_type", "e.target_id"
    else:
        match_type, match_id = "e.target_type", "e.target_id"
        step_type, step_id = "e.source_type", "e.source_id"

    all_types = not edge_types
    sql = text(
        f"""
        WITH RECURSIVE reach(node_type, node_id, depth, path) AS (
            SELECT CAST(:start_type AS varchar), CAST(:start_id AS uuid), 0,
                   ARRAY[CAST(:start_key AS text)]
          UNION ALL
            SELECT {step_type}, {step_id}, r.depth + 1,
                   r.path || ({step_type} || ':' || {step_id})
            FROM reach r
            JOIN control_graph_edges e
              ON {match_type} = r.node_type
             AND {match_id} = r.node_id
             AND e.organization_id = :org
             AND e.revoked_at IS NULL
             AND (e.valid_until IS NULL OR e.valid_until > now())
             AND (:all_types OR e.edge_type = ANY(:edge_types))
            WHERE r.depth < :max_depth
              AND NOT (({step_type} || ':' || {step_id}) = ANY(r.path))
        )
        SELECT DISTINCT ON (node_type, node_id) node_type, node_id, depth, path
        FROM reach
        WHERE depth > 0
        ORDER BY node_type, node_id, depth
        """
    )
    rows = db.execute(
        sql,
        {
            "start_type": start_type,
            "start_id": str(start_id),
            "start_key": _key(start_type, start_id),
            "org": str(organization_id),
            "all_types": all_types,
            "edge_types": list(edge_types or []),
            "max_depth": depth,
        },
    ).all()

    resolved: dict[str, str | None] = {}

    def _label(k: str) -> str | None:
        if k not in resolved:
            ntype, _, nid = k.partition(":")
            try:
                node = resolve_node(db, organization_id, ntype, uuid.UUID(nid))
            except ValueError:
                node = None
            resolved[k] = node.label if node else None
        return resolved[k]

    out: list[ReachableNode] = []
    for node_type, node_id, node_depth, path in rows:
        # every hop after the start must resolve in-tenant for this node to
        # be reported -- truncate the walk at the first out-of-tenant node.
        if any(_label(k) is None for k in list(path)[1:]):
            continue
        nid = node_id if isinstance(node_id, uuid.UUID) else uuid.UUID(str(node_id))
        out.append(
            ReachableNode(
                node_type=node_type,
                node_id=nid,
                depth=int(node_depth),
                label=_label(_key(node_type, nid)) or "",
                path=list(path),
            )
        )
    out.sort(key=lambda n: n.depth)
    return out


# --------------------------------------------------------------------------- #
# Phase 5.4 -- explainable blast-radius traversal
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class EdgeHop:
    edge_id: str
    edge_type: str
    source_type: str
    source_id: str
    target_type: str
    target_id: str
    evidence: dict


@dataclass(frozen=True)
class DependencyPath:
    """One reachable node plus the exact edge chain that reached it -- the
    "deterministic + explainable" blast-radius answer (SRS §7.4). ``depth`` is
    the shortest depth at which the node is reachable; ``edges`` is that
    shortest path's edge chain, each hop naming the edge and its evidence."""

    node_type: str
    node_id: uuid.UUID
    depth: int
    label: str
    node_path: list[str]
    edges: list[EdgeHop]


def traverse_with_edges(
    db: Session,
    organization_id: uuid.UUID,
    *,
    start_type: str,
    start_id: uuid.UUID,
    edge_types: list[str] | None = None,
    direction: str = "out",
    max_depth: int | None = None,
) -> tuple[list[DependencyPath], bool]:
    """Reachability that also returns the edge chain to each node.

    Same machinery as :func:`traverse` -- one ``WITH RECURSIVE`` over
    ``control_graph_edges``, per-hop ``organization_id = :org``, a path array
    cycle guard, ``depth < :max_depth``. In addition to the node path it
    carries the array of edge ids traversed, hydrated afterwards into
    :class:`EdgeHop`s (with each edge's evidence) for the explanation.

    Returns ``(paths, depth_capped)`` -- ``depth_capped`` is ``True`` if any
    branch was cut at ``max_depth`` (so the caller can say the blast radius
    "may be incomplete", never falsely "empty" -- SRS §11).

    A node that does not resolve *within the tenant*, and everything reachable
    only through it, is dropped (the 5.3 adversarial backstop, unchanged for
    dependency edges).
    """
    depth = _clamp_depth(max_depth)
    if direction not in ("out", "in"):
        raise ValueError("direction must be 'out' or 'in'")

    if direction == "out":
        match_type, match_id = "e.source_type", "e.source_id"
        step_type, step_id = "e.target_type", "e.target_id"
    else:
        match_type, match_id = "e.target_type", "e.target_id"
        step_type, step_id = "e.source_type", "e.source_id"

    all_types = not edge_types
    # One recursive CTE. ``any_capped`` (a single scalar sub-select over the
    # same CTE) tells the caller whether any branch was cut at ``:max_depth`` --
    # so a blast radius is never falsely "empty" when it might be partial
    # (SRS §11) -- without a second traversal.
    sql = text(
        f"""
        WITH RECURSIVE reach(node_type, node_id, depth, node_path, edge_path, capped) AS (
            SELECT CAST(:start_type AS varchar), CAST(:start_id AS uuid), 0,
                   ARRAY[CAST(:start_key AS text)], ARRAY[]::uuid[], false
          UNION ALL
            SELECT {step_type}, {step_id}, r.depth + 1,
                   r.node_path || ({step_type} || ':' || {step_id}),
                   r.edge_path || e.id,
                   (r.depth + 1 >= :max_depth)
            FROM reach r
            JOIN control_graph_edges e
              ON {match_type} = r.node_type
             AND {match_id} = r.node_id
             AND e.organization_id = :org
             AND e.revoked_at IS NULL
             AND (e.valid_until IS NULL OR e.valid_until > now())
             AND (:all_types OR e.edge_type = ANY(:edge_types))
            WHERE r.depth < :max_depth
              AND NOT (({step_type} || ':' || {step_id}) = ANY(r.node_path))
        )
        SELECT DISTINCT ON (node_type, node_id)
               node_type, node_id, depth, node_path, edge_path,
               (SELECT bool_or(capped) FROM reach) AS any_capped
        FROM reach
        WHERE depth > 0
        ORDER BY node_type, node_id, depth
        """
    )
    params = {
        "start_type": start_type,
        "start_id": str(start_id),
        "start_key": _key(start_type, start_id),
        "org": str(organization_id),
        "all_types": all_types,
        "edge_types": list(edge_types or []),
        "max_depth": depth,
    }
    rows = db.execute(sql, params).all()
    depth_capped = any(bool(r[5]) for r in rows)

    # hydrate every traversed edge in one query
    edge_ids: set[str] = set()
    for r in rows:
        edge_ids.update(str(e) for e in (r[4] or []))
    edge_map: dict[str, EdgeHop] = {}
    if edge_ids:
        for er in db.execute(
            text(
                """
                SELECT id, edge_type, source_type, source_id, target_type, target_id, evidence
                FROM control_graph_edges
                WHERE organization_id = :org AND id = ANY(CAST(:ids AS uuid[]))
                """
            ),
            {"org": str(organization_id), "ids": list(edge_ids)},
        ).all():
            edge_map[str(er[0])] = EdgeHop(
                edge_id=str(er[0]),
                edge_type=er[1],
                source_type=er[2],
                source_id=str(er[3]),
                target_type=er[4],
                target_id=str(er[5]),
                evidence=er[6] or {},
            )

    # resolve every node that appears in any path IN-TENANT, batched by type
    # (one query per node type, not one per node) -- the 5.3 adversarial
    # backstop: a node that does not resolve inside the tenant, and everything
    # reachable only through it, is dropped.
    by_type: dict[str, set[str]] = {}
    for r in rows:
        for k in list(r[3])[1:]:
            nt, _, ni = k.partition(":")
            by_type.setdefault(nt, set()).add(ni)
    in_tenant: dict[str, str] = {}
    for nt, ids in by_type.items():
        try:
            src = node_source_sql(nt)
        except ValueError:
            continue
        for rid, lbl in db.execute(
            text(
                f"SELECT n.id, n.label FROM ({src}) AS n "
                "WHERE n.organization_id = :org AND n.id = ANY(CAST(:ids AS uuid[]))"
            ),
            {"org": str(organization_id), "ids": list(ids)},
        ).all():
            in_tenant[f"{nt}:{rid}"] = lbl or ""

    out: list[DependencyPath] = []
    for node_type, node_id, node_depth, node_path, edge_path, _capped in rows:
        tail = list(node_path)[1:]
        if any(k not in in_tenant for k in tail):
            continue  # truncate at the first out-of-tenant node
        nid = node_id if isinstance(node_id, uuid.UUID) else uuid.UUID(str(node_id))
        hops = [edge_map[str(e)] for e in (edge_path or []) if str(e) in edge_map]
        out.append(
            DependencyPath(
                node_type=node_type,
                node_id=nid,
                depth=int(node_depth),
                label=in_tenant.get(_key(node_type, nid), ""),
                node_path=list(node_path),
                edges=hops,
            )
        )
    out.sort(key=lambda p: (p.depth, p.node_type, str(p.node_id)))
    return out, depth_capped


# --------------------------------------------------------------------------- #
# Authority-chain reconstruction
# --------------------------------------------------------------------------- #
@dataclass
class ChainHop:
    from_type: str
    from_id: str
    edge: str
    to_type: str
    to_id: str
    to_label: str
    evidence: dict


@dataclass
class AuthorityChain:
    execution_id: str
    organization_id: str
    hops: list[ChainHop] = field(default_factory=list)
    complete: bool = True
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "execution_id": self.execution_id,
            "organization_id": self.organization_id,
            "complete": self.complete,
            "notes": self.notes,
            "hops": [
                {
                    "from": {"type": h.from_type, "id": h.from_id},
                    "edge": h.edge,
                    "to": {"type": h.to_type, "id": h.to_id, "label": h.to_label},
                    "evidence": h.evidence,
                }
                for h in self.hops
            ],
        }


def _replay_ancestors(
    db: Session, organization_id: uuid.UUID, execution_id: uuid.UUID, max_depth: int
) -> list[uuid.UUID]:
    """The chain of ``parent_execution_id`` links (a human REPLAY of a prior
    execution), oldest first, tenant-bounded at every hop."""
    sql = text(
        """
        WITH RECURSIVE chain(id, parent_execution_id, depth, path) AS (
            SELECT id, parent_execution_id, 0, ARRAY[id]
            FROM agent_executions
            WHERE id = :eid AND organization_id = :org
          UNION ALL
            SELECT p.id, p.parent_execution_id, c.depth + 1, c.path || p.id
            FROM chain c
            JOIN agent_executions p
              ON p.id = c.parent_execution_id
             AND p.organization_id = :org
            WHERE c.depth < :max_depth
              AND NOT (p.id = ANY(c.path))
        )
        SELECT id FROM chain WHERE depth > 0 ORDER BY depth DESC
        """
    )
    return [
        r[0] if isinstance(r[0], uuid.UUID) else uuid.UUID(str(r[0]))
        for r in db.execute(
            sql,
            {"eid": str(execution_id), "org": str(organization_id), "max_depth": max_depth},
        ).all()
    ]


def _delegation_prefix(
    db: Session,
    organization_id: uuid.UUID,
    identity_type: str,
    identity_id: uuid.UUID,
    max_depth: int,
) -> tuple[list[ChainHop], list[str]]:
    """Recursive walk *backwards* over DELEGATES_TO / AGENT_DELEGATES_TO edges
    into the triggering identity -- "under whose delegated authority".
    Per-hop tenant-bounded; a delegator that does not resolve in-tenant
    truncates the chain and adds a note."""
    edge_rows = db.execute(
        text(
            """
            SELECT id, source_type, source_id, edge_type, target_type, target_id, evidence
            FROM control_graph_edges
            WHERE organization_id = :org
              AND edge_type IN ('DELEGATES_TO', 'AGENT_DELEGATES_TO')
              AND revoked_at IS NULL
              AND (valid_until IS NULL OR valid_until > now())
            """
        ),
        {"org": str(organization_id)},
    ).all()
    incoming: dict[str, list] = {}
    for row in edge_rows:
        incoming.setdefault(_key(row[4], row[5]), []).append(row)

    hops: list[ChainHop] = []
    notes: list[str] = []
    frontier = [(identity_type, str(identity_id))]
    seen = {_key(identity_type, identity_id)}
    steps = 0
    while frontier and steps < max_depth:
        nxt: list[tuple[str, str]] = []
        for ntype, nid in frontier:
            for (eid, s_type, s_id, e_type, t_type, t_id, evidence) in incoming.get(
                _key(ntype, nid), []
            ):
                src = resolve_node(db, organization_id, s_type, uuid.UUID(str(s_id)))
                if src is None:
                    notes.append(
                        "delegation chain truncated: a delegator does not resolve in this tenant"
                    )
                    continue
                tgt = resolve_node(db, organization_id, t_type, uuid.UUID(str(t_id)))
                hops.append(
                    ChainHop(
                        from_type=s_type,
                        from_id=str(s_id),
                        edge=e_type,
                        to_type=t_type,
                        to_id=str(t_id),
                        to_label=tgt.label if tgt else "",
                        evidence={
                            "kind": "control_graph_edge",
                            "id": str(eid),
                            **(evidence or {}),
                        },
                    )
                )
                k = _key(s_type, s_id)
                if k not in seen:
                    seen.add(k)
                    nxt.append((s_type, str(s_id)))
        frontier = nxt
        steps += 1
    # deepest delegator first, so the chain reads origin -> ... -> identity
    hops.reverse()
    return hops, notes


def reconstruct_authority_chain(
    db: Session,
    organization_id: uuid.UUID,
    execution_id: uuid.UUID,
    *,
    max_depth: int | None = None,
) -> AuthorityChain | None:
    """Reconstruct origin -> agent -> (agent) -> tool/identity -> target for
    one execution, from existing rows + edges, per-hop tenant-bounded, each
    hop naming its evidence. ``None`` if the execution is not in this tenant
    (the route renders that as 404 -- no existence leak)."""
    depth = _clamp_depth(max_depth)
    exec_row = db.execute(
        text(
            """
            SELECT agent_id, trigger_type, triggered_by_identity_id
            FROM agent_executions
            WHERE id = :eid AND organization_id = :org
            """
        ),
        {"eid": str(execution_id), "org": str(organization_id)},
    ).first()
    if exec_row is None:
        return None

    agent_id, _trigger, _trig_by = exec_row
    agent_uuid = agent_id if isinstance(agent_id, uuid.UUID) else uuid.UUID(str(agent_id))
    chain = AuthorityChain(
        execution_id=str(execution_id), organization_id=str(organization_id)
    )
    hops: list[ChainHop] = []

    # --- root of the replay chain + its trigger identity ------------------ #
    ancestors = _replay_ancestors(db, organization_id, execution_id, depth)
    root_exec_id = ancestors[0] if ancestors else execution_id
    root = db.execute(
        text(
            "SELECT trigger_type, triggered_by_identity_id FROM agent_executions "
            "WHERE id = :rid AND organization_id = :org"
        ),
        {"rid": str(root_exec_id), "org": str(organization_id)},
    ).first()
    r_trigger, r_identity = root if root else (_trigger, _trig_by)

    identity_node: tuple[str, uuid.UUID] | None = None
    if r_identity is not None:
        rid = r_identity if isinstance(r_identity, uuid.UUID) else uuid.UUID(str(r_identity))
        as_human = resolve_node(db, organization_id, "HUMAN", rid)
        as_agent = resolve_node(db, organization_id, "AGENT", rid)
        if r_trigger == "AGENT" and as_agent is not None:
            identity_node = ("AGENT", rid)
        elif as_human is not None:
            identity_node = ("HUMAN", rid)
        elif as_agent is not None:
            identity_node = ("AGENT", rid)
        else:
            chain.complete = False
            chain.notes.append(
                "triggering identity is recorded but does not resolve in this tenant "
                "- chain begins at the execution"
            )
    else:
        chain.complete = False
        chain.notes.append(
            f"no triggering identity on the root execution (trigger_type={r_trigger}) "
            "- chain begins at the execution"
        )

    # --- delegation prefix (recursive over control_graph_edges) ----------- #
    if identity_node is not None:
        d_hops, d_notes = _delegation_prefix(
            db, organization_id, identity_node[0], identity_node[1], depth
        )
        hops.extend(d_hops)
        chain.notes.extend(d_notes)

        inode = resolve_node(db, organization_id, identity_node[0], identity_node[1])
        hops.append(
            ChainHop(
                from_type=identity_node[0],
                from_id=str(identity_node[1]),
                edge="TRIGGERED",
                to_type="AGENT_EXECUTION",
                to_id=str(root_exec_id),
                to_label=inode.label if inode else "",
                evidence={
                    "kind": "agent_executions.triggered_by_identity_id",
                    "id": str(root_exec_id),
                    "trigger_type": r_trigger,
                },
            )
        )

    # --- replay hops: root -> ... -> this execution ---------------------- #
    prev = root_exec_id
    replay_seq = ancestors[1:] + [execution_id] if ancestors else []
    for nxt_exec in replay_seq:
        hops.append(
            ChainHop(
                from_type="AGENT_EXECUTION",
                from_id=str(prev),
                edge="REPLAYED_AS",
                to_type="AGENT_EXECUTION",
                to_id=str(nxt_exec),
                to_label="",
                evidence={"kind": "agent_executions.parent_execution_id", "id": str(nxt_exec)},
            )
        )
        prev = nxt_exec

    # --- spine: execution -> agent -> identity -> tools -> targets -------- #
    agent_node = resolve_node(db, organization_id, "AGENT", agent_uuid)
    hops.append(
        ChainHop(
            from_type="AGENT_EXECUTION",
            from_id=str(execution_id),
            edge="EXECUTED_AS",
            to_type="AGENT",
            to_id=str(agent_uuid),
            to_label=agent_node.label if agent_node else "",
            evidence={"kind": "agent_executions.agent_id", "id": str(execution_id)},
        )
    )
    if agent_node is None:
        chain.complete = False
        chain.notes.append("the executing agent does not resolve in this tenant")

    acts_as = db.execute(
        text(
            """
            SELECT id, target_id, evidence FROM control_graph_edges
            WHERE organization_id = :org AND source_type = 'AGENT' AND source_id = :aid
              AND edge_type = 'ACTS_AS' AND revoked_at IS NULL
              AND (valid_until IS NULL OR valid_until > now())
            ORDER BY created_at LIMIT 1
            """
        ),
        {"org": str(organization_id), "aid": str(agent_uuid)},
    ).first()
    if acts_as is not None:
        ai_node = resolve_node(
            db, organization_id, "AGENT_IDENTITY", uuid.UUID(str(acts_as[1]))
        )
        hops.append(
            ChainHop(
                from_type="AGENT",
                from_id=str(agent_uuid),
                edge="ACTS_AS",
                to_type="AGENT_IDENTITY",
                to_id=str(acts_as[1]),
                to_label=ai_node.label if ai_node else "",
                evidence={
                    "kind": "control_graph_edge",
                    "id": str(acts_as[0]),
                    **(acts_as[2] or {}),
                },
            )
        )
    else:
        ai = db.execute(
            text(
                "SELECT ai.id, ai.client_id FROM agent_identities ai "
                "JOIN agents a ON a.id = ai.agent_id "
                "WHERE ai.agent_id = :aid AND a.organization_id = :org"
            ),
            {"aid": str(agent_uuid), "org": str(organization_id)},
        ).first()
        if ai is not None:
            hops.append(
                ChainHop(
                    from_type="AGENT",
                    from_id=str(agent_uuid),
                    edge="ACTS_AS",
                    to_type="AGENT_IDENTITY",
                    to_id=str(ai[0]),
                    to_label=ai[1] or "",
                    evidence={"kind": "agent_identities", "id": str(ai[0])},
                )
            )

    tool_calls = db.execute(
        text(
            """
            SELECT tc.id, tc.tool_id, t.name, tc.target_host
            FROM tool_calls tc
            JOIN agent_executions ae ON ae.id = tc.execution_id
            LEFT JOIN tools t ON t.id = tc.tool_id
            WHERE tc.execution_id = :eid AND ae.organization_id = :org
            ORDER BY tc.started_at NULLS LAST, tc.id
            """
        ),
        {"eid": str(execution_id), "org": str(organization_id)},
    ).all()
    for tc_id, tool_id, tool_name, target_host in tool_calls:
        hops.append(
            ChainHop(
                from_type="AGENT",
                from_id=str(agent_uuid),
                edge="INVOKED",
                to_type="TOOL",
                to_id=str(tool_id),
                to_label=tool_name or "",
                evidence={"kind": "tool_calls", "id": str(tc_id)},
            )
        )
        if target_host:
            hops.append(
                ChainHop(
                    from_type="TOOL",
                    from_id=str(tool_id),
                    edge="TARGETED",
                    to_type="EXTERNAL_HOST",
                    to_id=str(target_host),
                    to_label=str(target_host),
                    evidence={"kind": "tool_calls.target_host", "id": str(tc_id)},
                )
            )

    chain.hops = hops
    return chain


__all__ = [
    "MAX_TRAVERSAL_DEPTH",
    "DEFAULT_TRAVERSAL_DEPTH",
    "ReachableNode",
    "traverse",
    "EdgeHop",
    "DependencyPath",
    "traverse_with_edges",
    "ChainHop",
    "AuthorityChain",
    "reconstruct_authority_chain",
]
