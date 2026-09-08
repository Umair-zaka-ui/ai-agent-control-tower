# ADR-0017 — The control graph is relational: typed edges + recursive CTEs, no graph database

- **Status:** Accepted
- **Date:** 2026-09-08
- **Deciders:** Phase 5.3 / M5.3 (Milestone 5 — Universal Agent Control & Security Fabric)
- **Supersedes:** —
- **Relates to:** ADR-0002 (PostgreSQL as the sole datastore — this ADR is
  its first real test on graph-shaped data), ADR-0008 (telemetry as a
  derived plane — the assemble-from-rows discipline this ADR reuses for the
  authority chain), ADR-0015 (the universal agent asset model — the canonical
  nodes), ADR-0016 (discovery evidence vs. canonical truth — a
  discovery-produced edge is evidence, weighed not trusted).

## Context

Milestone 5.3 builds the relational control-graph substrate: typed edges
connecting the node rows that already exist (humans, agents, identities,
tools, credentials, resources, organizations), plus **authority-chain
reconstruction** — a first-class recursive query answering *who authorized
this action, under whose delegated authority, through which identity, down to
which resource*. Phases 5.4 (MCP / dependency graph), 5.6 (containment
attribution) and 5.7 (external identity) all build on this substrate, so the
substrate decision outweighs any single query.

Two temptations were live going in:

1. **Reach for a graph database.** "It's a graph, so use Neo4j" is the
   reflexive move on the first real graph phase. It would add a second
   datastore (against ADR-0002), a second consistency model, a second backup
   and failover story, and a synchronisation problem between it and the
   authoritative Postgres rows.
2. **Materialise a projection immediately.** A denormalised
   adjacency/closure table is fast to read but is a second copy of a fact —
   two things to keep in step, and the copy is the one that goes stale (the
   exact problem ADR-0008 identified for trace spans).

3. **Invent agent→agent delegation to make the graph "complete."** The
   runtime deliberately has no agent→agent invocation
   (`request_execution_as_agent` is self-only; multi-agent orchestration is
   explicitly deferred). Fabricating delegation edges the runtime never
   recorded would make the graph *look* complete while lying about what
   happened.

## Decision

**The control graph is relational. One typed edge table, recursive CTEs, no
projection unless a measurement proves one is needed. The graph represents
relationships that already exist; it never creates authority.**

1. **One table: `control_graph_edges`.** A typed, directed, tenant-scoped
   edge between two existing node rows, addressed by `(type, id)` and
   resolved against the node's own table at read time — **no node state is
   copied** (the `(resource_type, resource_id)` discipline `resources`
   already uses). Soft-revoked (`revoked_at`), optionally time-bounded
   (`valid_until`). A partial unique index (`uq_control_graph_edges_active`)
   makes `create` idempotent and a concurrent double-create resolve to
   exactly one live edge.

2. **No graph database.** The authority chain and every reachability query
   are `WITH RECURSIVE` CTEs over `control_graph_edges` (and, for the replay
   prefix, over `agent_executions.parent_execution_id`). 1M edges is small
   for Postgres with the two bidirectional composite indexes
   (`(organization_id, source_type, source_id)` and the target mirror);
   M4 already runs bounded recursive/aggregate queries at ~109k+ rows
   sub-millisecond.

3. **No materialised projection.** `test_ac03` records a measurement that
   assembling reachability from edges is well within budget, so "no
   projection" keeps being the right call. A projection is added *only* if a
   future measurement proves assembly too slow — and then as its own ADR.
   The graph-at-scale (1M-edge) adversarial benchmark is deferred to
   Phase 5.4 / 5.10.

4. **Per-hop tenant-bounded traversal.** Every recursion step re-applies
   `organization_id = :tenant` on the joined edge. Because
   `ControlGraphService` validates that *both* endpoints of an edge resolve
   inside the caller's tenant before writing it, that single predicate is a
   complete bound for service-created edges. For a hostile row inserted
   directly into the table, a second guarantee applies: any node that does
   not resolve *within the tenant* is dropped, and everything reachable only
   through it is dropped too — the walk truncates at the first out-of-tenant
   node, i.e. it stops at the tenant edge. Proven adversarially
   (`test_ac06_*`).

5. **Bounded and cycle-safe.** `depth < :max_depth` (hard ceiling
   `MAX_TRAVERSAL_DEPTH = 32`) caps traversal length; a `'type:id'` path
   array carried on each row makes a revisit impossible, so a cycle in the
   data cannot make the query run away.

6. **The graph represents; it never creates.** A **trust edge** is created
   explicitly but only between two nodes that already exist in the caller's
   tenant, and it grants nothing — `AuthorizationGateway` stays the sole
   decider. A **delegation edge** mirrors a `delegations` row that
   `DelegationService` already owns, with `evidence` pointing back at that
   row; the graph never writes `delegations`. **`AGENT_DELEGATES_TO` is a
   declared edge type with no producer in this phase** — the runtime has no
   agent→agent invocation, so 5.3 leaves the type in the vocabulary the way
   M5.1 left discovery columns for M5.2, and does not invent the missing
   link.

7. **The authority chain is assembled from existing rows.** It generalises
   the Phase 4.2 `correlation_id` human→agent→model→tool reconstruction into
   a recursive query: a recursive delegation prefix over
   `control_graph_edges`, a recursive replay prefix over
   `parent_execution_id`, and a bounded FK spine
   (execution → agent → identity → tool calls → targets). Each hop names its
   evidence (the row or edge it came from). Deterministic: same data ⇒ same
   chain.

8. **Missing evidence is explicit, and the plane fails open.** A hop with no
   recoverable evidence is reported as "chain incomplete" with a note —
   never rendered as "no delegation occurred" (missing evidence ≠ evidence of
   absence). The graph is a derived read plane, off every execution and
   governance path (structurally: nothing under `app/runtime/` imports
   `app/graph/`), so a graph-query failure returns an error to its caller
   and cannot block an execution or mutate authority.

## Consequences

### Positive
- No second datastore, no second consistency/backup/failover story; ADR-0002
  holds, and is shown to hold for graph-shaped data.
- The authority chain is never a stale copy — it is the current truth of the
  execution/identity/delegation rows plus the current edges, every time.
- Tenant isolation is a single predicate re-applied per hop, easy to audit
  and adversarially proven, rather than an emergent property of a traversal
  engine's configuration.
- 5.4 extends the substrate by adding `edge_type` values and dependency-edge
  producers — no new table, no migration to a graph store.

### Negative / accepted cost
- A recursive CTE over a wide edge set is more expensive than a single
  indexed lookup in a purpose-built graph engine. Accepted at this
  milestone's scale; re-measured every phase, and the projection door is
  left open (point 3).
- Assembly cannot carry an attribute that is not derivable from a row or an
  edge. If a later phase needs one, it adds a column to the table that owns
  the fact — which is where it belonged.
- The authority chain's agent→agent segment is empty until the runtime gains
  agent→agent invocation. This is a deliberate, documented gap, not a bug —
  the chain reports what the runtime actually recorded.

### Residual risk
- `MAX_TRAVERSAL_DEPTH = 32` is a fixed ceiling. A genuinely deeper legitimate
  chain would be truncated with a note; revisit if a real deployment shows
  chains that long.
- The per-hop bound relies on `ControlGraphService` being the only writer of
  edges in normal operation. A component that bypassed it to insert edges
  directly would not get the both-endpoints-in-tenant validation — the
  traversal's truncation-at-first-out-of-tenant-node is the backstop, and is
  what the adversarial test exercises.

## Revisit when

- **A measurement shows assembly is too slow** — add a projection, as its own
  ADR, with the deterministic-and-reconstructable standard ADR-0008 sets.
- **Phase 5.4 adds the dependency graph** — confirm the one-table +
  recursive-CTE design still holds with dependency edges and the "what breaks
  if X" queries, and run the graph-at-scale benchmark deferred here.
- **The runtime gains agent→agent invocation** — wire a producer for
  `AGENT_DELEGATES_TO` and confirm the authority chain's recursive delegation
  prefix already covers it (it does — the edge type is in the walk today).
- **Phase 5.7 attaches enforcement** — confirm nothing here assumed a graph
  edge would stay purely descriptive if a later phase wants to gate on one
  (it must not: an edge grants nothing, and that is the spine of this ADR).
