# PROJECTION_DECISION — restraint with numbers everywhere except one measured cliff, and that cliff is algorithmic

The ADR-0008 discipline: add a derived read model only for a **measured** need, never speculatively; reopen
ADR-0017 (relational graph, no graph database) only for a cliff a projection also cannot solve. V9 measured
eight fixture sets (`SCALE_MEASUREMENTS.md`). The decision, per hot path:

## 1. Restraint — no projection (the 5.4 outcome, now at 100k / 1 M edges)

| path | worst-case 100k number | shape | decision |
|---|---|---|---|
| blast radius, typical resource | 18.6 / 30.7 ms | flat | **none** |
| authority chain, replay depth 31 + 10 delegation hops | 7.0 / 15.0 ms | flat | **none** |
| inventory list p1 / last page / filtered | 16.8 / 47.1 / 54.1 ms | flat, index-backed | **none** |
| gateway authz-only / allowed+dispatch | 12.8 / 214 ms | flat across all rungs | **none** |
| posture full-population invariant guard | 37.4 ms over 100k rows | single sequential scan **by design** (V0.2: 71 ms / 116k) | **none** |
| reconciliation | 185 obs/s, precision exact, 0 duplicates at 80k | linear (one short transaction per observation, by design) | **none** |
| tenant isolation | 404-class refusal and hostile-edge truncation at every rung | invariant | **none** |
| blast radius on a **hub** (40k dependents) / what-breaks tool hub / resource-kind | 2.44 s / 1.89 s / 2.44 s | linear in dependents (answer size), hydration N+1 | **none yet** — bounded, but see §3 (the same N+1 as the reachability finding) |
| authority chain, typical execution | 1.01 / 1.33 s | linear in the tenant's edges: a sequential scan over 1.09 M edges filtered by org + edge_type | **none** — an index-shape question for the architecture gate, not a projection |
| estate overview (5.10) | 333 / 486 ms | seven sequential scans over the busy tenant's rows; `external_gateway_calls` filtered by `(organization_id, created_at)` has no index on `created_at` | **none** — a 30-day-window read model is a candidate *if* the estate page is polled; today it is a request-time aggregate at 0.3–0.5 s |
| cost summary (4.4) total / by agent | 34 / 113 ms (p95 137 / 231) | `agent_executions` sequential scan on a `created_at` range, no index | **none** — bounded; index candidate |

Restraint holds because every one of these is either flat or linear in the honest answer size, and the
largest linear one (a 40k-dependent hub) answers in 2.4 s.

## 2. The measured cliff — trust/delegation reachability (5.3 `reachability`, and any caller of `traverse`)

`app/graph/traversal.py` walks `control_graph_edges` with a `WITH RECURSIVE` whose cycle guard is a
**path array** (`NOT (next = ANY(r.path))`). That guard makes every row a distinct *simple path*, so the
recursion enumerates paths, not nodes:

| tenant | out-degree on trust/delegation edges | paths materialised per depth | outcome |
|---|---|---|---|
| worst, 80 agents | 2 | 84 @4 → 4,127 @8 → 170,711 @12 → **1,010,293 @14** (×2.5 per level) while distinct nodes saturate at **75 by depth 7** | depth 12 = 1.9–3.1 s; **depth 16 aborts** (3 GB temp cap); unbounded (depth 32 filled a 12 GB disk before the cap existed) |
| worst, 800 / 8,000 agents | 2 | growth probe itself exceeded 60 s at depth 14 | depth 12 = 5.3 s / 9.7 s; **depth 16 aborts** |
| worst, 80,000 agents | 2 | 55,695 paths @14 for 34,464 nodes (sparser relative to size) | depth 16 = 22.5 s (63,322 nodes); **depth 20 aborts** |
| realistic, 256 / 1,004 / 4,719 agents | ≈ 0.6 | ×1.7–1.95 per level | depth 16 = 0.4 / 1.3 / 1.1 s; **depth 20–24 aborts** |

**The API default is `DEFAULT_TRAVERSAL_DEPTH = 16`.** On every worst-case rung the default request either
aborts or takes tens of seconds; a caller can request 32. Before the lab instance had a `temp_file_limit`,
one such request consumed the free disk of the host (and, in the container run, the Docker VM's disk) — an
authenticated tenant admin can take the database server down with one `GET /graph/reachability`.

### Is it relational, or is it the query? — the variant probe

[`lab/scale/reach_variant_probe.py`](../../../lab/scale/reach_variant_probe.py), same 80k-agent tenant, same
chain head, same edge filter, read-only, product untouched (raw:
[`evidence/v9_reach_variant_worst_100000.json`](evidence/v9_reach_variant_worst_100000.json)):

| depth | **A** product shape (path array, `UNION ALL`) | **B** frontier-dedup (`UNION` on `(node, depth)`, no path) | **C** = B + parent pointer (explainable shortest path) |
|---|---|---|---|
| 4 | 6.8 ms · 56 nodes | 1.4 ms · 56 nodes · **identical set** | — |
| 8 | 22.6 ms · 1,116 nodes | 5.9 ms · 1,116 nodes · **identical set** | — |
| 12 | (5.0 s in the ladder) | 229 ms · 16,724 | 145 ms |
| 16 | 3.95 s SQL (+ ~18 s label hydration in the service) | **1.35 s · 63,323** | 1.88 s |
| 24 | aborts | 4.5 s · 66,996 (closure complete) | 10.8 s |
| 32 | aborts | **8.0 s · 66,996** | 24.3 s |

Same relational table, same PostgreSQL, same indexes: the frontier-dedup shape computes the **complete**
closure at the depth cap where the product shape cannot finish depth 20. Postgres's `UNION` recursion is the
standard BFS: each `(node, depth)` materialises once, cycles die by deduplication, cost is O(reachable × depth)
instead of O(simple paths). A parent pointer keeps the path explainable (C) at polynomial cost.

### Decision

- **Not a graph database.** ADR-0017 stands with *more* evidence than before: the relational engine computes
  the 67k-node closure of a 891k-edge tenant in 8 s at the depth cap. The cliff is the enumeration strategy.
- **Not a projection either.** A materialised reachability closure would have to be *computed* by some
  traversal (this one), would be O(N²) for a dense trust graph, and would have to be refreshed on every edge
  change — the wrong tool for an on-demand, depth-parameterised query.
- **A query-shape change** — frontier deduplication (B/C) plus **batched label hydration** (one `IN (...)`
  query per node type instead of one query per reached node; see §3) — is the first response the
  architecture gate should consider. It is smaller than a projection and removes the DoS. It is a product
  change to `traversal.py`, which V9 is not authorized to make; **recorded here for the architecture gate,
  not applied.**
- Until it lands, an operational guard is available without code: `statement_timeout` and `temp_file_limit`
  on the application role (the lab used 60 s / 3 GB), which turns the failure into a loud 5xx instead of a
  full disk.

**Bright line kept:** ACT was not tuned, no fixture was softened (the worst-case out-degree-2 graph stayed
in every rung), and the cliff is reported at its full measured size.

## 3. The second finding inside the same code — N+1 hydration (bounded, but it sets the ceiling)

`traverse()` resolves the label of every node on every returned path with a separate `resolve_node` query;
`traverse_with_edges` hydrates every edge id the same way. Measured: the super-node fan-out (depth 2, 8k
nodes) issues **14,866 SQL statements** and takes 4.0 s; the 63k-node reachability at depth 16 spends ~18 s of
its 22.5 s here; the hub blast radius (40k dependents) 2.4 s. This is linear in the answer and therefore
"bounded", but it is what turns a 1.4 s SQL answer into a 22 s API call. Same recommendation, same file,
same gate: batch the hydration.

## 4. Posture evaluation — linear, but a scheduled sweep of an 80k tenant takes ~53 minutes

`PostureEvaluator.evaluate_tenant` loads every agent, then runs 16 rules per agent with per-agent queries:
25–40 ms/agent at every rung (28.9 → 30.7 → 28.0 → 29.6 ms realistic; 24.8 → 31.9 → 38.6 → 39.5 ms worst).
At 8,000 agents the sweep exceeded the 300 s lab budget (7,771 done); at 80,000 the projection is
**3,160 s (53 min)** per `posture.evaluate` job run. Not a cliff — no super-linear term — but operationally a
wall for the scheduled sweep on a busy tenant. A set-based evaluation (one query per rule over the tenant) or a
per-rule materialised view would remove it; **not V9 work, recorded for M6/the gate.**

## 5. Summary

| outcome | paths |
|---|---|
| restraint, record the numbers, add nothing | blast radius (typical + hubs), authority chain, inventory, gateway, cost, posture guard, reconciliation, estate, isolation |
| **measured cliff — algorithmic, relational fix exists, no projection, no graph DB; product change deferred to the architecture gate** | trust/delegation reachability (`traverse` / `traverse_with_edges`) |
| bounded-linear ceilings recorded for the gate | N+1 hydration in traversal; posture sweep per-agent cost; `created_at` scans in cost/estate; delegation-edge scan in authority chain |

**No cliff requires a graph database → no STOP.** **No projection was built → the product diff is empty.**
