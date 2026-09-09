# Blast-radius queries (Phase 5.4 / M5.4)

The security payoff of the [dependency graph](./dependency-graph.md):
deterministic, explainable, per-hop tenant-bounded reachability over the
dependency edges, answering the enterprise's hardest AI-dependency questions.

All four reuse the Phase 5.3 recursive-CTE machinery
(`app/graph/traversal.py::traverse_with_edges`) — the same per-hop
`organization_id = :org` bound, the same `'type:id'` path-array cycle guard,
the same `MAX_TRAVERSAL_DEPTH = 32` cap, the same out-of-tenant truncation.
**No new traversal engine.** `traverse_with_edges` is `traverse` plus an
accumulated edge-id array, hydrated into an explainable path (each hop names
the edge and its `evidence`).

## The queries

| Endpoint | Question | Direction |
| --- | --- | --- |
| `GET /graph/blast-radius/agents-reaching?node_type=&node_id=` | which agents can reach node X | reverse (target → source) |
| `GET /graph/blast-radius/what-breaks?node_type=&node_id=` | what breaks if node Y is revoked / removed | reverse |
| `GET /graph/blast-radius/mcp-dependents/{server_id}` | which agents depend on MCP server Z (direct + transitive) | reverse |
| `GET /graph/blast-radius/resource-kind?kind=` | which agents can reach a resource of kind K (e.g. `payroll`) | reverse, per matching resource |
| `GET /graph/blast-radius/unapproved-mcp` | agents depending on an unapproved MCP server (evidence for 5.5) | direct edge scan |

All are `graph.view`; all are reads that change nothing; all are recorded
(`GRAPH_BLAST_RADIUS_QUERIED`) because they expose the shape of the tenant's
dependency surface.

## Properties

- **Explainable** — every answer names its path: the exact edge chain, each
  edge's type and `evidence` (`{mode, source, …}`). SRS §7.4.
- **Per-hop tenant-bounded** — a blast radius never crosses a tenant
  boundary, even via a shared-looking node. Re-proven adversarially for
  dependency edges (`test_ac06_planted_cross_tenant_dependency_edge_does_not_extend_a_blast_radius`):
  a hostile edge whose endpoint is another tenant's row is truncated at the
  tenant edge.
- **Bounded / cycle-safe** — depth cap + path-array revisit guard; a
  `max_depth` over the ceiling is `422 GRAPH_TRAVERSAL_DEPTH_EXCEEDED`.
- **`incomplete` is explicit** — when the walk is cut at the depth cap the
  answer carries `incomplete: true` + `incomplete_reason`, so a truncated
  result is never presented as the whole blast radius (SRS §11). A
  `resource-kind` query with no matching resources says
  `"no resource of this kind is recorded"` — never a bare empty result.
- **Fails open** — a query failure returns an error to its caller and can
  never block an execution or corrupt an edge (the graph is a derived plane;
  nothing under `app/runtime/` imports `app/graph/`).

## The §V graph-at-scale benchmark — no materialised projection

ADR-0017 deferred the 1M-edge adversarial benchmark to Phase 5.4 and left the
projection door open: materialise a reachability projection **only if a
measurement proves assembly from edges too slow.**

`test_ac08_v_blast_radius_benchmark_at_scale` builds a single-busy-tenant
fixture — ≈12,000 agents each depending on ≈10 tools, tools → resources,
tools → credentials — `ANALYZE`s it (a bulk load leaves stale planner
statistics that autovacuum maintains in production), ≈128,000 dependency
edges, and times the four blast-radius queries:

| Query | Latency |
| --- | --- |
| which agents can reach the payroll resource | ~270 ms |
| what breaks if a busy credential is revoked | ~110 ms |
| which agents reach a resource of kind `payroll` | ~130 ms |
| agents depending on an unapproved MCP server | ~40 ms |

The recursive term is an index scan on `ix_control_graph_edges_target`
(`Index Cond: organization_id = … AND target_type = … AND target_id = …`);
cost scales with the *reachable set* for the start node, not total edge
count. ADR-0017 already recorded M4 running bounded recursive queries at
~109k rows sub-millisecond. Extrapolated to the 1M-edge target the traversal
stays index-bound and depth-capped.

One artefact worth naming: a **cold bulk load** (stale planner statistics,
table planned as if tiny) produces a ~20 s plan. That is a statistics
artefact, not an algorithmic one — it does not occur under
autovacuum-maintained statistics, and single-edge inserts through the
services never move the statistics far.

**Decision: no materialised projection.** Assembly from edges is well inside
budget; ADR-0017's "no projection" call holds, now backed by a real
measurement at scale. A projection is added only if a future measurement
proves otherwise, and then as its own ADR (assembly stays the fallback and
the source of truth). See
[ADR-0018](../architecture/adr/0018-mcp-representation-via-tool-domain.md).
