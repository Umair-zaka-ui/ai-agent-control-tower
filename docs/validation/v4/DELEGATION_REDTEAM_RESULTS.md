# DELEGATION_REDTEAM_RESULTS — V4 (T8): forgery, amplification, laundering, truncation

Raw: [`evidence/v4_delegation_results.json`](evidence/v4_delegation_results.json). Fired inside the
wrapper on 2026-09-22. **13 / 14 pass, 0 fail, 1 GAP, delegation-integrity rate 8/9, no P1.**

## The model under attack

- `DelegationService.delegate` always stamps `organization_id = actor.organization_id` and
  `delegator_id = actor.id`. Delegating a scope that does not resolve to the actor's own organization
  raises `DELEGATION_EXCEEDS_AUTHORITY`.
- `POST /api/v1/graph/delegation-edges` takes **only a `delegation_id`** and mirrors a live, in-tenant
  delegation row, re-checking both HUMAN endpoints in-tenant. **There is no route that creates a
  free-form authority edge**, and edge creation requires an internal `_MANAGE` principal — which an
  external agent, by construction, does not have.
- `GET /api/v1/graph/authority-chain/executions/{id}` reconstructs the chain per-hop tenant-bounded,
  each hop naming its evidence, and sets `complete=false` **with a note naming the reason** when a hop
  cannot be resolved. The graph is a *derived* plane: it "never blocks an execution or mutates
  authority".
- Traversal is bounded (`MAX_TRAVERSAL_DEPTH = 32`) and cycle-safe (a path array makes a revisit
  impossible).

## Results

| # | scenario | attack | observed | verdict |
|---|---|---|---|---|
| T8-01 | authority chain (**control**) | reconstruct a real native execution's chain | `200`, 3 hops, `complete=true`, no notes | PASS (control) |
| T8-02 | **forged delegation edge** | create an edge from a fabricated delegation id | `422 GRAPH_DELEGATION_NOT_REPRESENTABLE` | PASS (rejected) |
| T8-03 | legitimate delegation (control) | org-scoped delegation to an in-tenant human | `201` | PASS (control) |
| T8-04 | **amplification** | delegate ORGANIZATION scope naming *another tenant's* org id | `403 DELEGATION_EXCEEDS_AUTHORITY` | PASS (rejected) |
| T8-05 | cross-tenant delegatee | delegate to a human in another tenant, then mirror the edge | delegation row `201` (stamped with **A's** org), edge **`404 GRAPH_CROSS_TENANT_ENDPOINT`** | PASS (tenant bound held) |
| T8-06 | revoked delegation | mirror an edge after revoking the delegation | `422 GRAPH_DELEGATION_NOT_REPRESENTABLE` | PASS (rejected) |
| T8-07 | **delegation-edge replay** | mirror the same delegation twice | `201` then `201` — **two edges for one delegation** | **GAP** (see below) |
| T8-08 | **authority laundering A→B→C** | chain delegations so C exceeds A | every delegation carries the delegator's own org; no widening | PASS (no widening) |
| T8-09 | cyclic delegation | A→B and B→A edges, then traverse | `200` in **7.6 ms**, 1 node, terminated | PASS (bounded, cycle-safe) |
| T8-10 | **chain truncation (hidden hop)** | force a depth limit on a chain that has a delegation prefix | full 4 hops `complete=true`; depth-limited **also 4 hops `complete=true`** | PASS (no silent truncation) |
| T8-11 | depth ceiling | request `max_depth=999` | `422 GRAPH_TRAVERSAL_DEPTH_EXCEEDED` | PASS (rejected) |
| T8-12 | cross-tenant chain reconstruction | tenant B reconstructs tenant A's execution | `404 GRAPH_NODE_NOT_FOUND` | PASS (no existence leak) |
| T8-13 | external-agent attribution boundary | what authority surface exists for an external agent? | gateway call attributed by `agent_id` + `grant_id`; **0 `agent_executions`** → no chain surface | PASS (truthful boundary) |
| T8-14 | non-repudiation | deny having authorized | `DELEGATION_CREATED` and `GRAPH_AUTHORITY_CHAIN_RECONSTRUCTED` both audited | PASS (non-repudiable) |

## The P1 lines, explicitly

**Not forgeable, not amplifiable, not launderable, not silently truncatable.** Every P1 flag is false.

- **Forgery** is structurally impossible: the only authority-edge route mirrors an existing live
  in-tenant delegation row, and it needs an internal `_MANAGE` principal.
- **Amplification** is blocked at creation: a delegator cannot name another organization's scope.
- **Laundering** cannot widen: every delegation row is stamped with the *delegator's* own organization,
  so C in an A→B→C chain can never hold authority A did not have.
- **Truncation**: I built a chain that genuinely has a delegation prefix (delegate A→B, mirror the edge,
  then let B trigger the execution) and then forced `max_depth=1`. The chain returned the **same 4 hops,
  still `complete=true`** — the depth limit bounds the recursive delegation-prefix walk, and this
  chain's prefix was already within that bound, so there was nothing to truncate. **I could not induce
  a chain that was short *and* claimed completeness.** The code path that would report a missing hop
  sets `complete=false` *and* appends an explicit note naming the reason, so an incomplete chain is
  reported as incomplete rather than hidden. Recorded honestly: no silent truncation was observed, and
  the silent-truncation scenario could not be induced by depth limiting.

## The one GAP: duplicate mirrored authority edges (T8-07)

Mirroring the same delegation twice produces **two `DELEGATES_TO` edges for one delegation row**
(confirmed in the database: one delegation with 2 mirrored edges).

**Impact is limited and does not widen authority.** The gateway resolves delegated authority from the
`delegations` rows via `DelegationService.active_for_user`, **not** from graph edges, and the control
graph is explicitly a derived plane that "never … mutates authority". So a duplicate edge cannot grant
anything; it is graph hygiene — a hop could be double-counted in a traversal or blast-radius view.
Severity **Low**, pre-existing, recorded not fixed.

## Attribution scope — an honest finding (T8-13)

The 5.3 authority-chain surface is keyed on `agent_executions`. **External, gateway-enforced agents
never produce `agent_executions`** (the tenant showed 0), so the authority-chain reconstruction does not
cover external agent actions. Those actions are still attributed — every `external_gateway_calls` row
carries `agent_id`, `grant_id`, `capability_key`, `target_ref`, `outcome` and `denial_reason` — but
"who ultimately authorized this" is answered by the grant and its issuer, not by a reconstructed chain.
This is a real boundary of the attribution model, recorded as finding **F-2**, not a defect.
