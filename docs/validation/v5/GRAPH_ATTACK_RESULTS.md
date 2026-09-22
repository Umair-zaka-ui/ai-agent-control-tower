# GRAPH_ATTACK_RESULTS — V5 (T20): attacking the control graph directly

Raw: [`evidence/v5_graph_results.json`](evidence/v5_graph_results.json). Fired 2026-09-23.
**9 / 9 pass. Per-hop tenant bounding 100 %. Blast-radius under-estimation 0. No blocker.**

## Results

| # | scenario | attack | observed | verdict |
|---|---|---|---|---|
| V5-G1 | **blast-radius accuracy** | query the true dangerous path | reported **exactly** the one agent that truly reaches payroll; 0 under-estimated, 0 over-estimated, `incomplete=false` | **PASS (matches ground truth)** |
| V5-G2 | **false dependency injection** | assert a dependency the agent has no basis for | edge created `201` **by an authorized operator** and stamped `{"mode":"DECLARED","source":"operator","created_by":…}`; blast radius then reflects that recorded, attributed evidence | **PASS (evidence-based, operator-authored)** |
| V5-G3 | **missing dependency (unknown ≠ safe)** | query a resource whose dependencies were never recorded | empty answer carrying `incomplete=false` / `incomplete_reason=null` — a true "no recorded path", explicitly distinguished from a truncated walk | **PASS (truthful incompleteness)** |
| V5-G4 | **cross-tenant traversal** | plant a cross-tenant edge, then traverse in **both** directions | edge **`404 GRAPH_CROSS_TENANT_ENDPOINT`**; tenant A querying B's resource `404`; tenant B querying A's resource `404`; neither saw the other's agents | **PASS (tenant bound held at every hop)** |
| V5-G5 | **cycle attack** | close a tool→tool cycle, then traverse at max depth | the cycle-closing edge was **rejected `422`** (see below); the traversal still completed in **11.9 ms** | **PASS (bounded, terminated)** |
| V5-G6 | **unbounded traversal** | request `max_depth=9999` | `422 GRAPH_TRAVERSAL_DEPTH_EXCEEDED` | **PASS (bounded)** |
| V5-G7 | **high-degree node (graph DoS)** | a hub tool with 60 resource edges, queried through | `200` in **13.8 ms** | **PASS (bounded)** |
| V5-G8 | **poisoned edge granting authority** | give an agent a graph path, then use an ungranted capability | gateway still **`403`** — the path conferred nothing | **PASS (graph grants nothing)** |
| V5-G9 | **authority-chain forgery via edges** | forge an edge from a fabricated delegation; author an edge over another tenant's nodes | `422` and **`404 GRAPH_CROSS_TENANT_ENDPOINT`** | **PASS (rejected)** |

## Cross-tenant traversal — the mandatory blocker, answered

**No traversal crossed a tenant boundary.** The attack tried to *plant* the crossing edge first, which
is the only way a mid-chain crossing could arise, and edge creation re-resolves **both** endpoints in
the caller's organization: an out-of-tenant node is simply not found, returning a 404-shaped
`GRAPH_CROSS_TENANT_ENDPOINT` so the caller learns nothing about the other tenant's existence. With the
edge refused, both directions of blast radius returned 404 as well. The traversal itself re-applies
`organization_id` at **every recursive step** and truncates at the first out-of-tenant node, so the
bound does not depend on the edge refusal alone.

## The cycle result, stated accurately

ACT enforces a **typed edge schema**: `_EDGE_SHAPE` gives each dependency edge type exactly one
permitted `(source_type, target_type)` pair, so `DEPENDS_ON_TOOL` connects `AGENT → TOOL` and nothing
else. My tool→tool cycle-closing edge was therefore rejected as an invalid shape (`422
GRAPH_DEPENDENCY_INVALID`), not by a cycle detector. The honest reading: **a cycle of this shape cannot
be expressed at all**, because the permitted node-type pairs form a directed, acyclic set of shapes —
which is a stronger guarantee than surviving a cycle. The traversal's path-array guard remains an
independent second defence, and V4 already exercised a **real** A→B→A cycle through trust edges, which
terminated in 7.6 ms. I did not form a real data cycle here, and do not claim to have.

## False dependency — the honest trust boundary

A dependency edge *can* be asserted, and asserting one *does* change the blast-radius picture. That is
correct behaviour: blast radius reflects recorded evidence. The containment is threefold and worth
stating rather than glossing:

- creation requires an **authorized internal principal** (an external agent has no route to it);
- both endpoints must resolve **in the caller's tenant**;
- the edge is stamped with its **evidence and author** (`mode: DECLARED`, `source: operator`,
  `created_by`), so a declared assertion is distinguishable from an observed fact and is attributable.

So ACT's picture is only as true as its recorded edges — but every edge names who declared it, and no
unauthenticated party can add one.

## The graph represents, it never grants

G8 is the V4 F-1 lineage made explicit: after giving an agent a full graph path to the payroll
resource, that agent still could not invoke a capability outside its grant — the gateway returned
`403`. Reachability is a derived, read-only plane; authority is decided by `AuthorizationGateway`.
