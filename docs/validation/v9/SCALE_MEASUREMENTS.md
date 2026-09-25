# SCALE_MEASUREMENTS — every rung, both distributions, p50 / p95, plan evidence

**Scale ≠ interoperability.** These numbers say how ACT's queries, reconciliation, graph and read models behave
at volume on synthetic rows. They make **no** claim about governing real, independent agents — that was V7.

## Method

- Rungs **100 → 1,000 → 10,000 → 100,000 agents**; edges ≈ 10 per agent + hubs → **8,874 → 87,718 → 872,549
  (realistic) and 11,529 → 112,001 → 1,093,009 (worst)**. Two distributions per rung (`FIXTURE_GENERATION.md`).
- Dedicated PostgreSQL 17.10 instance (host-native, `shared_buffers=512MB`, `work_mem=32MB`, `temp_file_limit=3GB`,
  `statement_timeout=60s` on the reachability probes only), 12-CPU / 16 GB host, harness in-process on loopback.
  Tables `ANALYZE`d after every load.
- Every operation is the product's own service or route, called as the API calls it, against the measured tenant
  (the largest / the busy one). Warm-up, then **n** timed iterations on fresh sessions (n = 10; 3–5 for the heavy
  ones; 40 for gateway calls). p50/p95/p99 are in the JSON; p50 / p95 are tabled.
- The last iteration of every operation captured its SQL; each read statement was `EXPLAIN`ed and scanned for a
  `Seq Scan` on a hot table with > 5,000 live rows (⚠ *n* seq in the tables); the recursive CTEs additionally
  carry `EXPLAIN (ANALYZE, BUFFERS)` text in the JSON. Heavy operations ran under a 300 s budget and report
  progress and a projection when they exceed it.
- Raw: `evidence/v9_measure_<dist>_<rung>.json` (eight files), fixtures `evidence/v9_fixture_*.json`, the CTE
  variant probe `evidence/v9_reach_variant_worst_100000.json`, all hash-anchored (`RESULTS_LEDGER.md`).

## Baselines the brief asked to hold or beat

| baseline | V9 comparable number | held? |
|---|---|---|
| authority chain / blast radius, 5.4: ~274 ms at 128k edges | worst/10k (112k edges): chain typical **113 / 268 ms**, hub blast radius **164 / 299 ms**; at **1.09 M edges**: chain typical **1.01 / 1.33 s**, hub blast radius (40,148 dependents) **2.44 s**, typical resource **18.6 ms** | held at the baseline's scale; linear beyond it |
| 5.10: 98.9–119.9 ms at 4.4k edges | rung 1k (9–11k edges): chain typical 15–24 ms, blast radius 12–29 ms | beaten |
| posture full-population guard, V0.2: ~71 ms at 116k rows | **37.4 ms** at 100k rows (single sequential scan by design) | held |
| cost aggregation, 4.4: 0.80 ms at 109k executions | **34 ms p50 / 137 ms p95** at 121,550 executions in **one** tenant, with a `created_at`-range sequential scan | **not held** — the 4.4 figure came from fragmented dev data where the tenant index was selective; the busy-tenant number is the honest one (finding V9-6) |
| reconciliation, V5: clean | precision exact at every rung incl. **80,000 observations** (36,000 created / 40,000 linked / 4,000 flagged, 0 duplicate identifiers); 3-session races → 300 agents, 0 duplicates | held |

## Bounded or cliff — the one-paragraph answer

Everything is **bounded** — flat or linear in the honest answer size — except **one measured cliff**: the
trust/delegation **reachability CTE**, which enumerates simple paths and is exponential in branching × depth
(aborts at the API's default depth 16 on every worst-case rung; filled a disk at depth 32 before the lab
capped temp files). The decision and the evidence that the cliff is algorithmic, not relational, are in
`PROJECTION_DECISION.md`. Two linear-but-large ceilings are recorded beside it: N+1 label hydration in the
traversal (14,866 statements for an 8k-node answer) and the posture sweep at ~30–40 ms per agent (~53 min for
an 80k tenant).

## Results
### `realistic` distribution — p50 / p95 ms (n per op in the JSON)

| operation | 100 | 1,000 | 10,000 | 100,000 |
|---|---|---|---|---|
| *measured tenant: agents / edges* | 42 / 408 | 256 / 2,433 | 1,004 / 9,513 | 4,719 / 44,102 |
| *whole DB: agents / edges* | 100 / 924 | 1,000 / 8,874 | 10,000 / 87,718 | 100,000 / 872,549 |
| Blast radius, reverse, RESOURCE hub (in-degree 50 % of tenant), depth 16 | 7.8 / 13.9 | 12.4 / 20.2 | 14.1 / 21.0 | 6.7 / 7.8 |
| Blast radius, reverse, typical resource, depth 16 | 6.0 / 6.9 | 10.3 / 13.1 | 8.0 / 9.9 | 8.7 / 10.7 |
| What-breaks, TOOL hub (40 %), depth 16 | 7.1 / 8.0 | 8.1 / 8.8 | 5.2 / 5.3 | 7.9 / 8.3 |
| Agents reaching resource kind `payroll` (3 resources, one the hub) | 14.4 / 21.0 | 24.7 / 29.2 | 26.3 / 27.0 | 30.4 / 32.6 |
| Reachability, AGENT super-node TRUSTS fan-out (10 %), depth 2 | 1.5 / 1.9 | 1.9 / 2.1 | 1.6 / 1.7 | 2.4 / 2.6 |
| Authority chain: replay depth 31 + 10 delegation hops | 6.0 / 14.3 | 6.2 / 17.9 | 6.0 / 17.6 | 5.6 / 6.2 |
| Authority chain: typical execution | 12.4 / 16.0 | 14.8 / 19.2 | 19.1 / 24.9 | 47.5 / 178.2 |
| Estate overview (5.10 read model) | 11.7 / 32.9 | 14.3 / 27.6 | 14.8 / 27.1 | 29.0 / 35.5 ⚠2 seq |
| Inventory list, page 1 (50) | 11.5 / 14.3 | 12.9 / 14.9 | 11.8 / 17.1 | 18.9 / 148.6 |
| Inventory list, last page (50) | 10.4 / 11.6 | 11.4 / 12.7 | 13.5 / 14.7 | 17.2 / 20.6 |
| Inventory list, filtered + text search | 8.4 / 12.5 | 9.3 / 10.6 | 9.9 / 11.6 | 14.4 / 16.4 |
| Cost summary, tenant total (4.4) | 1.2 / 1.7 | 1.3 / 1.5 | 1.5 / 2.5 | 4.1 / 10.5 ⚠1 seq |
| Cost summary by agent (4.4) | 3.2 / 3.6 | 5.3 / 5.8 | 10.4 / 11.8 ⚠1 seq | 16.7 / 19.8 ⚠2 seq |
| Posture/asset full-population invariant guard (all tenants) | 1.0 / 1.3 | 1.3 / 1.8 | 4.7 / 4.9 ⚠1 seq | 35.2 / 38.2 ⚠1 seq |
| Gateway authz-only (denied outside scope, 403) | 15.2 / 17.1 | 13.6 / 20.3 | 11.8 / 14.4 | 12.1 / 13.6 |
| Gateway allowed + loopback dispatch (200) | 219.0 / 242.9 | 228.8 / 256.3 | 207.1 / 229.7 | 205.9 / 229.1 |
| Small tenant list beside the busy tenant | 9.9 / 12.4 | 11.2 / 12.2 | 11.3 / 145.2 | 24.6 / 39.0 |
| Posture `evaluate_tenant` (full sweep, 16 rules) | 1.2 s (42 agents, 28.94 ms/agent) | 7.9 s (256 agents, 30.7 ms/agent) | 28.1 s (1,004 agents, 28.01 ms/agent) | 139.6 s (4,719 agents, 29.59 ms/agent) |

**Trust/delegation reachability depth ladder (`realistic`)** — ms per depth from the chain head; ✖ = aborted by the 60 s statement timeout or the 3 GB temp-file cap

| depth | 100 | 1,000 | 10,000 | 100,000 |
|---|---|---|---|---|
| 4 | 108 (5 nodes) | 118 (52 nodes) | 127 (45 nodes) | 217 (22 nodes) |
| 8 | 7 (14 nodes) | 48 (178 nodes) | 99 (356 nodes) | 73 (287 nodes) |
| 12 | 9 (24 nodes) | 77 (180 nodes) | 240 (694 nodes) | 520 (1883 nodes) |
| 16 | 11 (30 nodes) | 426 (180 nodes) | 1,250 (714 nodes) | 1,141 (2930 nodes) |
| 20 | 12 (34 nodes) | 4,820 (180 nodes) | ✖ 17.8 s (temp cap) | 16,169 (3011 nodes) |
| 24 | 12 (34 nodes) | ✖ 18.8 s (temp cap) | (not reached) | ✖ 17.1 s (temp cap) |
| 32 | 13 (34 nodes) | (not reached) | (not reached) | (not reached) |

**Path rows materialised per depth (`realistic`, chain head, bounded probe)**

| rung | tenant agents | paths @d4 | @d8 | @d10 | @d12 | @d14 | distinct nodes @d14 | growth/level (d8→d14) |
|---|---|---|---|---|---|---|---|---|
| 100 | 42 | 2 | 8 | 10 | 4 | 10 | 5 | ×1.04 |
| 1,000 | 256 | 30 | 337 | 974 | 2,779 | 7,862 | 180 | ×1.69 |
| 10,000 | 1,004 | 24 | 311 | 1,193 | 4,532 | 17,185 | 706 | ×1.95 |
| 100,000 | 4,719 | 10 | 147 | 533 | 1,941 | 7,394 | 2285 | ×1.92 |

**Reconciliation, sweep, isolation (`realistic`)**

| item | 100 | 1,000 | 10,000 | 100,000 |
|---|---|---|---|---|
| dense reconciliation: observations / throughput | 42 obs, 175/s (5.71 ms/obs) | 256 obs, 170/s (5.87 ms/obs) | 1,004 obs, 198/s (5.04 ms/obs) | 4,719 obs, 195/s (5.14 ms/obs) |
| precision vs ground truth (created/linked/flagged match; Δagents = created; duplicate refs) | **all match**, 0 dups | **all match**, 0 dups | **all match**, 0 dups | **all match**, 0 dups |
| staleness check (10 % missing) | 40 linked, 4 raised, 0.04 s | 244 linked, 25 raised, 0.2 s | 954 linked, 96 raised, 0.69 s | 4,484 linked, 449 raised, 3.28 s |
| 3-session race over 300 new ids | 300 agents, 0 dups, 5.28 s | 300 agents, 0 dups, 4.93 s | 300 agents, 0 dups, 4.78 s | 300 agents, 0 dups, 4.82 s |
| sweep (HTTP reference adapter): run1 create / run2 link / idempotent | 42 in 0.61 s / 42 in 0.43 s / yes | 256 in 2.62 s / 256 in 1.76 s / yes | 1,004 in 10.19 s / 1,004 in 5.85 s / yes | 4,719 in 46.96 s / 4,719 in 31.2 s / yes |
| sweep of a 100k-item source, single run | — | — | — | PARTIAL, 20,000 obs, checkpoint {'offset': 19800}, 209.6 s |
| cross-tenant blast radius (busy actor, foreign resource) | GRAPH_NODE_NOT_FOUND | GRAPH_NODE_NOT_FOUND | GRAPH_NODE_NOT_FOUND | GRAPH_NODE_NOT_FOUND |
| hostile cross-tenant edge truncated at tenant edge | True | True | True | True |
| estate total == live count | True | True | True | True |
| grants issued for the gateway probe | 14 | 81 | 200 | 200 |
| ops with a Seq Scan on a hot table (>5k rows) | none | none | cost.summary_by_agent; posture.full_population_origin_state_guard(all_tenants) | estate.command_center_overview; cost.summary_total; cost.summary_by_agent; posture.full_population_origin_state_guard(all_tenants) |

### `worst` distribution — p50 / p95 ms (n per op in the JSON)

| operation | 100 | 1,000 | 10,000 | 100,000 |
|---|---|---|---|---|
| *measured tenant: agents / edges* | 80 / 915 | 800 / 9,466 | 8,000 / 91,848 | 80,000 / 891,051 |
| *whole DB: agents / edges* | 100 / 1,175 | 1,000 / 11,529 | 10,000 / 112,001 | 100,000 / 1,093,009 |
| Blast radius, reverse, RESOURCE hub (in-degree 50 % of tenant), depth 16 | 10.4 / 15.5 | 28.6 / 32.9 | 163.9 / 299.0 ⚠1 seq | 2,442.6 / 2,461.5 ⚠1 seq |
| Blast radius, reverse, typical resource, depth 16 | 8.0 / 9.7 | 16.8 / 28.1 | 6.9 / 9.2 | 18.6 / 30.7 |
| What-breaks, TOOL hub (40 %), depth 16 | 5.7 / 5.9 | 19.9 / 32.9 | 118.4 / 279.7 | 1,887.3 / 1,894.5 |
| Agents reaching resource kind `payroll` (3 resources, one the hub) | 18.7 / 19.8 | 45.5 / 58.6 | 171.9 / 336.5 ⚠1 seq | 2,440.4 / 2,450.0 ⚠1 seq |
| Reachability, AGENT super-node TRUSTS fan-out (10 %), depth 2 | 6.9 / 7.5 | 44.4 / 53.3 | 377.5 / 392.8 | 3,975.7 / 4,206.8 |
| Authority chain: replay depth 31 + 10 delegation hops | 5.3 / 13.3 | 6.3 / 21.1 | 6.2 / 20.6 | 7.0 / 15.0 |
| Authority chain: typical execution | 11.4 / 13.9 | 23.9 / 27.4 ⚠1 seq | 113.2 / 267.6 ⚠1 seq | 1,011.5 / 1,330.3 ⚠1 seq |
| Estate overview (5.10 read model) | 12.1 / 25.9 | 16.2 / 30.9 ⚠1 seq | 43.9 / 62.0 ⚠7 seq | 333.2 / 485.5 ⚠7 seq |
| Inventory list, page 1 (50) | 10.3 / 14.4 | 11.1 / 15.0 | 11.7 / 15.1 | 16.8 / 23.0 |
| Inventory list, last page (50) | 9.9 / 10.2 | 11.2 / 13.8 | 13.9 / 15.0 | 47.1 / 47.9 |
| Inventory list, filtered + text search | 7.7 / 8.7 | 11.1 / 14.7 | 15.5 / 17.1 | 54.0 / 59.7 |
| Cost summary, tenant total (4.4) | 1.3 / 1.7 | 1.9 / 2.6 | 5.6 / 7.4 ⚠1 seq | 34.4 / 137.1 ⚠1 seq |
| Cost summary by agent (4.4) | 3.5 / 3.6 | 9.4 / 10.1 | 21.0 / 22.3 ⚠3 seq | 113.3 / 231.1 ⚠2 seq |
| Posture/asset full-population invariant guard (all tenants) | 1.1 / 1.4 | 1.2 / 1.5 | 5.1 / 6.5 ⚠1 seq | 37.4 / 138.7 ⚠1 seq |
| Gateway authz-only (denied outside scope, 403) | 12.1 / 15.0 | 13.9 / 15.2 | 13.1 / 15.2 | 12.8 / 20.2 |
| Gateway allowed + loopback dispatch (200) | 218.2 / 244.4 | 217.5 / 237.5 | 214.2 / 229.8 | 214.2 / 236.5 |
| Small tenant list beside the busy tenant | 8.4 / 9.4 | 8.9 / 10.3 | 11.8 / 19.4 | 23.6 / 34.5 |
| Posture `evaluate_tenant` (full sweep, 16 rules) | 2.0 s (80 agents, 24.79 ms/agent) | 25.5 s (800 agents, 31.86 ms/agent) | **>300 s budget** (7,771 of 8,000 agents; 38.61 ms/agent; projected 5 min) | **>300 s budget** (7,595 of 80,000 agents; 39.51 ms/agent; projected 53 min) |

**Trust/delegation reachability depth ladder (`worst`)** — ms per depth from the chain head; ✖ = aborted by the 60 s statement timeout or the 3 GB temp-file cap

| depth | 100 | 1,000 | 10,000 | 100,000 |
|---|---|---|---|---|
| 4 | 134 (61 nodes) | 142 (92 nodes) | 134 (87 nodes) | 142 (56 nodes) |
| 8 | 45 (75 nodes) | 246 (747 nodes) | 1,164 (4267 nodes) | 322 (1116 nodes) |
| 12 | 1,912 (75 nodes) | 5,333 (768 nodes) | 9,743 (7195 nodes) | 5,031 (16724 nodes) |
| 16 | ✖ 25.8 s (temp cap) | ✖ 17.8 s (temp cap) | ✖ 11.5 s (temp cap) | 22,477 (63322 nodes) |
| 20 | (not reached) | (not reached) | (not reached) | ✖ 22.6 s (temp cap) |
| 24 | (not reached) | (not reached) | (not reached) | (not reached) |
| 32 | (not reached) | (not reached) | (not reached) | (not reached) |

**Path rows materialised per depth (`worst`, chain head, bounded probe)**

| rung | tenant agents | paths @d4 | @d8 | @d10 | @d12 | @d14 | distinct nodes @d14 | growth/level (d8→d14) |
|---|---|---|---|---|---|---|---|---|
| 100 | 80 | 84 | 4,127 | 27,212 | 170,711 | 1,010,293 | 75 | ×2.50 |
| 1,000 | 800 | probe aborted |||||||
| 10,000 | 8,000 | probe aborted |||||||
| 100,000 | 80,000 | 31 | 596 | 2,562 | 11,043 | 55,695 | 34464 | ×2.13 |

**Reconciliation, sweep, isolation (`worst`)**

| item | 100 | 1,000 | 10,000 | 100,000 |
|---|---|---|---|---|
| dense reconciliation: observations / throughput | 80 obs, 156/s (6.4 ms/obs) | 800 obs, 147/s (6.8 ms/obs) | 8,000 obs, 162/s (6.17 ms/obs) | 80,000 obs, 186/s (5.39 ms/obs) |
| precision vs ground truth (created/linked/flagged match; Δagents = created; duplicate refs) | **all match**, 0 dups | **all match**, 0 dups | **all match**, 0 dups | **all match**, 0 dups |
| staleness check (10 % missing) | 76 linked, 8 raised, 0.07 s | 760 linked, 76 raised, 0.82 s | 7,600 linked, 760 raised, 7.87 s | 76,000 linked, 7600 raised, 58.38 s |
| 3-session race over 300 new ids | 300 agents, 0 dups, 5.6 s | 300 agents, 0 dups, 5.38 s | 300 agents, 0 dups, 5.65 s | 300 agents, 0 dups, 4.99 s |
| sweep (HTTP reference adapter): run1 create / run2 link / idempotent | 80 in 0.97 s / 80 in 0.62 s / yes | 800 in 8.56 s / 800 in 5.0 s / yes | 8,000 in 84.72 s / 8,000 in 49.68 s / yes | 20,000 in 203.3 s / 200 in 84.47 s / NO |
| sweep of a 100k-item source, single run | — | — | — | PARTIAL, 20,000 obs, checkpoint {'offset': 19800}, 197.77 s |
| cross-tenant blast radius (busy actor, foreign resource) | GRAPH_NODE_NOT_FOUND | GRAPH_NODE_NOT_FOUND | GRAPH_NODE_NOT_FOUND | GRAPH_NODE_NOT_FOUND |
| hostile cross-tenant edge truncated at tenant edge | True | True | True | True |
| estate total == live count | True | True | True | True |
| grants issued for the gateway probe | 24 | 200 | 200 | 200 |
| ops with a Seq Scan on a hot table (>5k rows) | none | authority_chain.reconstruct_typical; estate.command_center_overview | blast_radius.reverse_hub_resource_depth16; blast_radius.agents_reaching_resource_kind_payroll; authority_chain.reconstruct_typical; estate.command_center_overview; cost.summary_total; cost.summary_by_agent; posture.full_population_origin_state_guard(all_tenants) | blast_radius.reverse_hub_resource_depth16; blast_radius.agents_reaching_resource_kind_payroll; authority_chain.reconstruct_typical; estate.command_center_overview; cost.summary_total; cost.summary_by_agent; posture.full_population_origin_state_guard(all_tenants) |

## Sequential scans on hot tables (captured plans)

The planner's choice is correct where the busy tenant is 80 % of a table (an index cannot help a filter that matches most rows); the entries that name a `created_at` range or an `edge_type` filter without a node predicate are the ones that would benefit from an index (finding V9-6).

```
realistic/10000 cost.summary_by_agent: agents rows=10000 filter=
realistic/10000 posture.full_population_origin_state_guard(all_tenants): agents rows=10000 filter=(((control_state)::text <> ALL ('{DISCOVERED,CLAIMED,REGISTERED,GOVERNED}'::text[])) OR ((origin_category)::text <> ALL 
realistic/100000 estate.command_center_overview: external_gateway_calls rows=16986 filter=((created_at >= '2026-09-24 22:14:35.427659+05'::timestamp with time zone) AND (organization_id = 'be12e914-3fe6-4173-92
realistic/100000 estate.command_center_overview: external_gateway_calls rows=16986 filter=((created_at >= '2026-09-24 22:14:35.437383+05'::timestamp with time zone) AND (organization_id = 'be12e914-3fe6-4173-92
realistic/100000 cost.summary_total: agent_executions rows=7212 filter=((created_at >= '2026-08-26 22:14:36.36877+05'::timestamp with time zone) AND (created_at <= '2026-09-25 22:14:36.36877+
realistic/100000 cost.summary_by_agent: agent_executions rows=7212 filter=((created_at >= '2026-08-26 22:14:36.465226+05'::timestamp with time zone) AND (created_at <= '2026-09-25 22:14:36.46522
realistic/100000 cost.summary_by_agent: agent_executions rows=7212 filter=((created_at >= '2026-08-26 22:14:36.465226+05'::timestamp with time zone) AND (created_at <= '2026-09-25 22:14:36.46522
realistic/100000 posture.full_population_origin_state_guard(all_tenants): agents rows=100000 filter=(((control_state)::text <> ALL ('{DISCOVERED,CLAIMED,REGISTERED,GOVERNED}'::text[])) OR ((origin_category)::text <> ALL 
worst/1000 authority_chain.reconstruct_typical: control_graph_edges rows=11529 filter=((revoked_at IS NULL) AND ((edge_type)::text = ANY ('{DELEGATES_TO,AGENT_DELEGATES_TO}'::text[])) AND (organization_id =
worst/1000 estate.command_center_overview: control_graph_edges rows=11529 filter=((revoked_at IS NULL) AND (organization_id = 'bd73c5f2-bae6-44a4-8e10-c2421491538c'::uuid))
worst/10000 blast_radius.reverse_hub_resource_depth16: agents rows=10000 filter=((organization_id = 'bb16f40d-9465-40e4-84c4-de4a0386dfb8'::uuid) AND (id = ANY ('{0f6587d4-0e80-485c-9423-6823d70cf239,
worst/10000 blast_radius.agents_reaching_resource_kind_payroll: agents rows=10000 filter=((organization_id = 'bb16f40d-9465-40e4-84c4-de4a0386dfb8'::uuid) AND (id = ANY ('{0f6587d4-0e80-485c-9423-6823d70cf239,
worst/10000 authority_chain.reconstruct_typical: control_graph_edges rows=112001 filter=((revoked_at IS NULL) AND ((edge_type)::text = ANY ('{DELEGATES_TO,AGENT_DELEGATES_TO}'::text[])) AND (organization_id =
worst/10000 estate.command_center_overview: agents rows=10000 filter=(organization_id = 'bb16f40d-9465-40e4-84c4-de4a0386dfb8'::uuid)
worst/10000 estate.command_center_overview: agents rows=10000 filter=(organization_id = 'bb16f40d-9465-40e4-84c4-de4a0386dfb8'::uuid)
worst/10000 estate.command_center_overview: agents rows=10000 filter=(organization_id = 'bb16f40d-9465-40e4-84c4-de4a0386dfb8'::uuid)
worst/10000 estate.command_center_overview: agents rows=10000 filter=(((last_observed_at IS NULL) OR (last_observed_at < '2026-08-26 22:27:23.678815+05'::timestamp with time zone)) AND ((co
worst/10000 estate.command_center_overview: external_gateway_calls rows=36000 filter=((created_at >= '2026-09-24 22:27:23.687316+05'::timestamp with time zone) AND (organization_id = 'bb16f40d-9465-40e4-84
worst/10000 estate.command_center_overview: control_graph_edges rows=112001 filter=((revoked_at IS NULL) AND (organization_id = 'bb16f40d-9465-40e4-84c4-de4a0386dfb8'::uuid))
worst/10000 estate.command_center_overview: external_gateway_calls rows=36000 filter=((created_at >= '2026-09-24 22:27:23.704861+05'::timestamp with time zone) AND (organization_id = 'bb16f40d-9465-40e4-84
worst/10000 cost.summary_total: agent_executions rows=13550 filter=((created_at >= '2026-08-26 22:27:24.362433+05'::timestamp with time zone) AND (created_at <= '2026-09-25 22:27:24.36243
worst/10000 cost.summary_by_agent: agent_executions rows=13550 filter=((created_at >= '2026-08-26 22:27:24.482058+05'::timestamp with time zone) AND (created_at <= '2026-09-25 22:27:24.48205
worst/10000 cost.summary_by_agent: agent_executions rows=13550 filter=((created_at >= '2026-08-26 22:27:24.482058+05'::timestamp with time zone) AND (created_at <= '2026-09-25 22:27:24.48205
worst/10000 cost.summary_by_agent: agents rows=10000 filter=
worst/10000 posture.full_population_origin_state_guard(all_tenants): agents rows=10000 filter=(((control_state)::text <> ALL ('{DISCOVERED,CLAIMED,REGISTERED,GOVERNED}'::text[])) OR ((origin_category)::text <> ALL 
worst/100000 blast_radius.reverse_hub_resource_depth16: agents rows=100000 filter=((organization_id = '9e3d2bc5-642a-48d2-a3c4-4bbe0915a74e'::uuid) AND (id = ANY ('{d97c8e0d-421f-475c-b3b4-50ba5e7d025f,
worst/100000 blast_radius.agents_reaching_resource_kind_payroll: agents rows=100000 filter=((organization_id = '9e3d2bc5-642a-48d2-a3c4-4bbe0915a74e'::uuid) AND (id = ANY ('{d97c8e0d-421f-475c-b3b4-50ba5e7d025f,
worst/100000 authority_chain.reconstruct_typical: control_graph_edges rows=1092996 filter=((revoked_at IS NULL) AND ((edge_type)::text = ANY ('{DELEGATES_TO,AGENT_DELEGATES_TO}'::text[])) AND (organization_id =
worst/100000 estate.command_center_overview: agents rows=100000 filter=(organization_id = '9e3d2bc5-642a-48d2-a3c4-4bbe0915a74e'::uuid)
worst/100000 estate.command_center_overview: agents rows=100000 filter=(organization_id = '9e3d2bc5-642a-48d2-a3c4-4bbe0915a74e'::uuid)
worst/100000 estate.command_center_overview: agents rows=100000 filter=(organization_id = '9e3d2bc5-642a-48d2-a3c4-4bbe0915a74e'::uuid)
worst/100000 estate.command_center_overview: agents rows=100000 filter=(((last_observed_at IS NULL) OR (last_observed_at < '2026-08-26 22:44:38.550639+05'::timestamp with time zone)) AND ((co
worst/100000 estate.command_center_overview: external_gateway_calls rows=300000 filter=((created_at >= '2026-09-24 22:44:38.684179+05'::timestamp with time zone) AND (organization_id = '9e3d2bc5-642a-48d2-a3
worst/100000 estate.command_center_overview: control_graph_edges rows=1092996 filter=((revoked_at IS NULL) AND (organization_id = '9e3d2bc5-642a-48d2-a3c4-4bbe0915a74e'::uuid))
worst/100000 estate.command_center_overview: external_gateway_calls rows=300000 filter=((created_at >= '2026-09-24 22:44:38.803552+05'::timestamp with time zone) AND (organization_id = '9e3d2bc5-642a-48d2-a3
worst/100000 cost.summary_total: agent_executions rows=121550 filter=((created_at >= '2026-08-26 22:44:40.993362+05'::timestamp with time zone) AND (created_at <= '2026-09-25 22:44:40.99336
worst/100000 cost.summary_by_agent: agent_executions rows=121550 filter=((created_at >= '2026-08-26 22:44:41.635438+05'::timestamp with time zone) AND (created_at <= '2026-09-25 22:44:41.63543
worst/100000 cost.summary_by_agent: agent_executions rows=121550 filter=((created_at >= '2026-08-26 22:44:41.635438+05'::timestamp with time zone) AND (created_at <= '2026-09-25 22:44:41.63543
worst/100000 posture.full_population_origin_state_guard(all_tenants): agents rows=100000 filter=(((control_state)::text <> ALL ('{DISCOVERED,CLAIMED,REGISTERED,GOVERNED}'::text[])) OR ((origin_category)::text <> ALL 
```
