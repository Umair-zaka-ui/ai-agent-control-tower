# The Control Graph (Phase 5.3 / M5.3)

The **relational control-graph substrate**: typed, directed edges connecting
the node rows that already exist in the platform, plus the recursive-CTE
machinery that walks them. This is the spine of the Universal Control Graph —
Phases 5.4 (MCP / dependency graph), 5.6 (containment attribution) and 5.7
(external identity) all build on it.

## No graph database

The graph is **PostgreSQL**. One table (`control_graph_edges`), two
bidirectional composite indexes, and `WITH RECURSIVE` queries. No Neo4j, no
second datastore, no materialised projection. See
[ADR-0017](../architecture/adr/0017-relational-control-graph-no-graph-database.md)
for the full reasoning and the measurement that keeps "no projection" honest.

## Nodes are existing rows

An edge endpoint is `(type, id)` — never a copy of node state. The node is
resolved against its own table at read time. `app/graph/nodes.py` is the one
place that knows the mapping:

| Node type | Table | Tenant |
| --- | --- | --- |
| `HUMAN` | `users` | `organization_id` |
| `AGENT` | `agents` | `organization_id` |
| `AGENT_IDENTITY` | `agent_identities` | via `agent_id → agents` |
| `SERVICE_ACCOUNT` | `service_accounts` | `organization_id` |
| `FEDERATED_IDENTITY` | `federated_identities` | `organization_id` |
| `EXTERNAL_CLIENT` | `external_clients` | `organization_id` |
| `TOOL` | `tools` | `organization_id` |
| `CREDENTIAL` | `agent_api_keys` | via `agent_id → agents` |
| `RESOURCE` | `resources` | `organization_id` |
| `ORGANIZATION` | `organizations` | the row *is* the tenant |

## Edge types

| Edge type | Producer this phase | Meaning |
| --- | --- | --- |
| `DELEGATES_TO` | mirrors a `delegations` row | a human acting under another human's delegated administrative authority |
| `TRUSTS` | explicit, via `POST /graph/trust-edges` | an established, approved trust relationship between two existing nodes |
| `ACTS_AS` | derived from `agent_identities` (or an explicit edge) | an agent acting through a machine identity |
| `AGENT_DELEGATES_TO` | **none** | agent→agent — a declared type with no producer: the runtime has no agent→agent invocation (`request_execution_as_agent` is self-only), so 5.3 does not invent it. Left in the vocabulary the way M5.1 left discovery columns for M5.2. |

Every edge carries `evidence` (a pointer back to the row that authorised it),
`confidence`, `provenance` (`EXPLICIT` / `DERIVED` / `DISCOVERED`), an optional
`valid_until`, and `revoked_at`. Edges are **soft-revoked, never
hard-deleted**. A traversal follows only edges that are currently live
(`revoked_at IS NULL AND (valid_until IS NULL OR valid_until > now())`).

## The graph represents; it never creates

Reading an edge or a chain grants **nothing** — `AuthorizationGateway` stays
the sole decider. A `TRUSTS` edge between a user and an agent does not let that
user do anything the gateway would deny. A `DELEGATES_TO` edge **mirrors** a
`delegations` row that `DelegationService` owns; the graph never writes
`delegations`, and `create_delegation_edge` refuses a revoked or non-existent
delegation. `graph.view` / `graph.manage` gate the API; neither grants
authority over anything the edges point at.

## Per-hop tenant-bounded traversal

The single most important security property. Every recursion step re-applies
`organization_id = :tenant` on the joined edge:

```sql
WITH RECURSIVE reach(node_type, node_id, depth, path) AS (
    SELECT :start_type, :start_id, 0, ARRAY[:start_key]
  UNION ALL
    SELECT e.target_type, e.target_id, r.depth + 1, r.path || (e.target_type||':'||e.target_id)
    FROM reach r
    JOIN control_graph_edges e
      ON e.source_type = r.node_type AND e.source_id = r.node_id
     AND e.organization_id = :tenant          -- ← per-hop tenant bound
     AND e.revoked_at IS NULL
     AND (e.valid_until IS NULL OR e.valid_until > now())
    WHERE r.depth < :max_depth
      AND NOT ((e.target_type||':'||e.target_id) = ANY(r.path))   -- ← cycle guard
)
```

Because `ControlGraphService` validates that **both** endpoints of an edge
resolve inside the caller's tenant before writing it, that predicate is a
complete bound for service-created edges. For a hostile row inserted directly
into the table, the traversal additionally **truncates at the first node that
does not resolve in-tenant** — it stops at the tenant edge, and the foreign
node is never surfaced. Proven adversarially in `test_ac06_*`.

## Bounded and cycle-safe

`depth < :max_depth` caps traversal length (hard ceiling
`MAX_TRAVERSAL_DEPTH = 32`; a request above it is `422
GRAPH_TRAVERSAL_DEPTH_EXCEEDED`). The `'type:id'` path array carried on each
row makes a revisit impossible, so a cycle in the data cannot make the query
run away.

## API

All under `/api/v1/graph`, gated by `graph.view` (reads) or `graph.manage`
(edge create/revoke). Nothing here writes `agents` or `delegations`.

| Method + path | Permission | Purpose |
| --- | --- | --- |
| `GET /node-types` | `graph.view` | the node + edge vocabulary, exhaustive by construction |
| `GET /edges` | `graph.view` | list edges (filter by node, edge type, include-revoked) |
| `GET /edges/{id}` | `graph.view` | one edge (cross-tenant → 404) |
| `POST /trust-edges` | `graph.manage` | create a `TRUSTS` edge between two in-tenant nodes |
| `POST /delegation-edges` | `graph.manage` | represent an existing `delegations` row as a `DELEGATES_TO` edge |
| `DELETE /edges/{id}` | `graph.manage` | soft-revoke an edge |
| `GET /authority-chain/executions/{id}` | `graph.view` | reconstruct the authority chain (see [authority-chain.md](authority-chain.md)) |
| `GET /reachability` | `graph.view` | bounded, per-hop-tenant reachability from a node |

## Concurrency

`uq_control_graph_edges_active` (a partial unique index over
`(organization_id, source_type, source_id, edge_type, target_type,
target_id) WHERE revoked_at IS NULL`) makes `create` idempotent: a concurrent
double-create (real separate Postgres sessions) resolves to exactly one live
edge, the loser catching the `IntegrityError` and re-reading it. A revoke
locks the row `FOR UPDATE`, so two concurrent revokers serialise —
one returns `200`, the other `409 GRAPH_EDGE_ALREADY_REVOKED`.

## Failure semantics

The graph is a derived read plane, off every execution and governance path
(structurally: nothing under `app/runtime/` imports `app/graph/`). A
graph-query failure returns an error to its caller and **cannot** block an
execution or mutate authority. See [authority-chain.md](authority-chain.md)
for how missing evidence is surfaced.
