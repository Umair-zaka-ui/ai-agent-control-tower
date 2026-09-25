# ACT VALIDATION GATE — V9 REPORT

**Phase:** V9 — Recovery / Performance / Scale. **Date:** 2026-09-25. **Branch:** `validation/v9-scale` off `224aea8`.
**Companions:** [`FIXTURE_GENERATION.md`](FIXTURE_GENERATION.md) · [`SCALE_MEASUREMENTS.md`](SCALE_MEASUREMENTS.md) ·
[`PROJECTION_DECISION.md`](PROJECTION_DECISION.md) · [`RECOVERY_RESULTS.md`](RECOVERY_RESULTS.md) ·
[`RESULTS_LEDGER.md`](RESULTS_LEDGER.md) · [`REGISTER_UPDATED.csv`](REGISTER_UPDATED.csv) ·
[`O11_CONFIRMATION.md`](O11_CONFIRMATION.md) · [`evidence/`](evidence/).

---

## A. Executive verdict

ACT's queries, reconciliation, graph and read models stay **correct and bounded at 100,000 agents and 1.09 M edges
under an honest worst case** (one tenant owning 80 % of everything, 40k-degree hubs, 31-hop chains) — with **one
measured cliff**: the trust/delegation reachability CTE enumerates simple paths and is exponential in branching ×
depth; the API's default depth aborts on every worst-case rung, and before the lab capped temp files a single
call filled a disk. The cliff is **algorithmic, not relational** — a frontier-dedup form of the same CTE returns
identical answers and the complete closure in 8 s at the depth cap — so ADR-0017 stands, no graph database and
no projection are needed, and the fix is a query-shape change for the architecture gate. **Recovery passes
completely**: M4.11 continuity holds through a real dump/restore, every degraded key configuration fails loud
with no silent identity reset, M5 durable state restores byte-for-byte, and a 100k-inventory restore takes 18.8 s.
**O-11 still stands** and must close before V10. The product diff is **empty**. The verdict is conditional because
V9-1 is a P1-class availability defect that needs an architecture-gate decision before scale is relied on, and
because of a lab side effect that must be reported (§M).

**Premise correction.** The brief assumed V8 passed and merged. V8 was stopped at pre-flight on 2026-09-25 (no
authorized read-only cloud sandbox), and nothing since V7 is merged (`main` = `9667707`). V9 does not depend on
V8; it branched from the last phase tip `224aea8` (V7.5). The cloud adapter is present and, as §2.3 requires, was
not exercised at scale; no cloud was contacted.

## B. Baseline + pre-flight

Live: `HEAD 224aea8` (`validation/v7.5-cloud-adapter`), clean; `alembic 0061_assurance_evidence (head)`; 152 tables;
routes 676; collection 2,681 + 1 deselected; frontend 384. **Dedicated lab DB (§2.2):** a host-native PostgreSQL
17.10 instance from the installed binaries (`lab/run/pg17/data`, port 55433, loopback trust, 512 MB shared buffers,
`temp_file_limit=3GB`) — the shared dev database was never touched; the app role has no `CREATEDB` and no host
superuser exists, so a separate instance was the only dedicated option. (It began as a `postgres:17-alpine`
container; see §M for why it moved.) **Ledger active** (V3 chain, 25 entries, every fixture anchored before
measurement). **Fixtures committed and deterministic** (`lab/scale/fixtures.py`, seeded; `FIXTURE_GENERATION.md`).
**No external calls**: the harness runs in-process on loopback; no cloud spend.

## C. Scale results — bounded vs cliff (full tables in `SCALE_MEASUREMENTS.md`)

Worst-case 100k rung (tenant 80,000 agents / 891,051 edges; DB 1,093,009 edges), p50 / p95 ms, no hot-table
sequential scan unless marked:

| path | 100 | 1k | 10k | **100k** | shape |
|---|---|---|---|---|---|
| blast radius, typical resource, depth 16 | 8.0 / 9.7 | 16.8 / 28.1 | 6.9 / 9.2 | **18.6 / 30.7** | flat |
| blast radius, RESOURCE hub (in-degree 50 %) | 10.4 / 15.5 | 28.6 / 32.9 | 164 / 299 | **2,443 / 2,462** (40,148 agents) | linear in answer |
| what-breaks, TOOL hub (40 %) | 5.7 / 5.9 | 19.9 / 32.9 | 118 / 280 | **1,887 / 1,895** | linear in answer |
| authority chain, replay depth 31 + 10 delegation hops | 5.3 / 13.3 | 6.3 / 21.1 | 6.2 / 20.6 | **7.0 / 15.0** | flat |
| authority chain, typical execution | 11.4 / 13.9 | 23.9 / 27.4 | 113 / 268 | **1,011 / 1,330** ⚠ edge scan | linear in tenant edges |
| estate overview (5.10) | 12.1 / 25.9 | 16.2 / 30.9 | 43.9 / 62.0 | **333 / 486** ⚠ 7 scans | linear in tenant rows |
| inventory list p1 / last page / filtered | 10 / 10 / 8 | 11 / 11 / 11 | 12 / 14 / 16 | **16.8 / 47.1 / 54.1** | flat, index-backed |
| cost summary total / by agent (4.4) | 1.3 / 3.5 | 1.9 / 9.4 | 5.6 / 21.0 | **34.4 / 113** ⚠ `created_at` scan | linear in executions |
| posture full-population guard (all tenants) | 1.1 | 1.2 | 5.1 | **37.4** | one scan by design |
| gateway authz-only 403 / allowed + dispatch 200 | 12.1 / 218 | 13.9 / 218 | 13.1 / 214 | **12.8 / 214** | flat |
| small tenant beside the busy tenant | 8.4 | 8.9 | 11.8 | **23.6** | flat |
| reachability, super-node fan-out depth 2 | 6.9 | 44.4 | 378 | **3,976** (14,866 statements) | linear, N+1 |
| **reachability, chain head, depth ladder** | d12 1.9 s; **d16 aborts** | d12 5.3 s; **d16 aborts** | d12 9.7 s; **d16 aborts** | d16 22.5 s (63,322 nodes); **d20 aborts** | **exponential — cliff** |
| posture `evaluate_tenant` (16 rules) | 2.0 s | 25.5 s | **> 300 s** (7,771 / 8,000) | **> 300 s** (7,595 / 80,000 → 53 min projected) | linear, ~30–40 ms/agent |

Realistic distribution (largest tenant 4,719 agents / 44k edges at 100k): every path 1–50 ms except the estate
(29 ms), cost by agent (17 ms), authority chain typical (47 / 178 ms) and the reachability ladder (depth 16 in
1.1 s, aborts at depth 24). The cliff is present in both distributions; the honest worst case reaches it by
depth 16.

**Bounded:** everything in the table except the reachability ladder. **Cliff:** the reachability ladder.
**Linear ceilings worth naming:** hub blast radius and super-node fan-out (N+1 hydration, §J V9-2), authority
chain typical and estate (edge/gateway-call scans, V9-6), posture sweep (V9-3).

## D. The projection decision

**Restraint with numbers on every path but one; on that one, no projection and no graph database.** The variant
probe on the loaded 100k database (`evidence/v9_reach_variant_worst_100000.json`): product shape vs frontier-dedup
(`UNION`) shape return **identical node sets** at depths 4 and 8; the frontier form computes 16,724 nodes at
depth 12 in 229 ms, 63,323 at depth 16 in 1.35 s, and the **complete 66,996-node closure at depth 32 in 8.0 s**,
where the product shape cannot finish depth 20 (with a parent pointer for explainable paths: 24 s at 32). Same
table, same engine, same indexes — the cost is the enumeration strategy (paths vs nodes), not the relational
choice. A materialised closure would be computed by the same traversal and refreshed on every edge change — the
wrong tool for a depth-parameterised on-demand query. **Recommended to the architecture gate, not applied:**
frontier deduplication in `traverse`/`traverse_with_edges` plus batched label/edge hydration; interim operational
guard: `statement_timeout` + `temp_file_limit` on the application role. Details: `PROJECTION_DECISION.md`.

## E. Recovery (`RECOVERY_RESULTS.md`)

M4.11 continuity: after a real `pg_dump`/`pg_restore` with the key restored from `create_key_material_archive`,
`verify_key_material` → `OK / CANARY_MATCH`, install `EXISTING`, **all three ciphertexts decrypt** (provider
credential, tool credential, discovery-source secret), the **historical version signature verifies**, and a **new
version publishes and signs** after restore. Fail-loud: restore without the key → `ENCRYPTION_KEY_MISSING_ESTABLISHED_INSTALL`
(also with `allow_bootstrap`), bootstrap refused `BOOTSTRAP_REFUSED_MARKER_PRESENT`, decrypt refused, **no key file
written, marker and canary byte-identical → no silent identity reset**; wrong key `ENCRYPTION_KEY_CANNOT_DECRYPT`;
malformed `ENCRYPTION_KEY_MALFORMED`; key path a directory `ENCRYPTION_KEY_PROVIDER_UNAVAILABLE`; unknown provider
`ENCRYPTION_KEY_PROVIDER_UNKNOWN`. **Zero-ciphertext established install** (marker only) → `EXISTING_INSTALL`,
and the key cannot be silently adopted (`ENCRYPTION_KEY_UNVERIFIED_ESTABLISHED_INSTALL`). **M5 durable state:** 31
tables byte-identical (count + md5) after restoring the worst-case 100k database — 1,093,009 edges, 176,300
agents, findings, policies, grants, assurance evidence, discovery-source config, budgets (sum preserved), 100
OPEN alerts; hub blast radius 40,148 before and after. **No phantom live workers** (3 RUNNING registrations →
stale → reaped → none live); expired locks cleared. **100k restore:** dump 11.8 s (139.6 MB), restore 18.8 s,
consistent. No P0.

## F. Reconciliation / posture / cost / tenant queries at 100k

Reconciliation of **80,000 contending observations** (50 % LINK contention, 5 % NATIVE collisions, 45 % new) in
431 s (**185 obs/s**, ~5.4 ms/observation — one short transaction each, by design): 36,000 created / 40,000 linked
/ 4,000 flagged, **exactly the ground truth, 0 duplicate identifiers**; staleness over 76,000 linked agents with
10 % missing → 7,600 findings in 58 s; three concurrent sessions over 300 new identifiers → 300 agents, 0
duplicates (M5.2-AC-10 holds at every rung). Posture guard 37 ms; posture sweep linear (§C). Cost 34 ms / 113 ms.
**Isolation intact at every rung**: cross-tenant blast radius → `GRAPH_NODE_NOT_FOUND`; a hostile cross-tenant
edge inserted directly is truncated at the tenant edge; the small tenant's list and the estate totals match the
fixture; a small tenant beside the busy one answers in 24 ms.

## G. Explicit separation

**V9 makes scale claims only**: correctness and latency of ACT's own queries at 100k records / 1.09 M edges. It
makes **no interoperability claim** — a synthetic agent is not an independent agent; V7's seven real agents on
five stacks are the interoperability evidence, and V9 adds nothing to it. The two claims live in separate artifacts.

## H. Measurements + baseline comparison

Headlines: worst-case authority chain at 1.09 M edges **7 ms (replay chain) / 1.01 s p50, 1.33 s p95 (typical,
edge scan)**; blast radius **18.6 ms typical / 2.44 s on a 40k-degree hub**; reconciliation precision at 80k
**exact, 0 duplicates**; posture full-population **37 ms at 100k**; the cliff and its decision (§D); recovery all
green; 100k restore **18.8 s, consistent**. Baselines: 5.4's 274 ms/128k held at the same scale (113–164 ms at
112k edges); 5.10's ~100 ms/4.4k beaten (6–45 ms); V0.2's 71 ms/116k held (37 ms/100k); 4.4's 0.80 ms/109k **not
held** — 34 ms in one busy tenant with a `created_at` scan (the fragmented-data lesson, made concrete). **No scale
claim beyond what was measured; no interoperability claim.**

## I. Register rows filled

R-045 (scale — measured, not interop), R-066 (enterprise deployment — recovery confirmed, O-11 open), R-072 (known
gaps — V9-1…V9-6 added). The register is threat-intel oriented and has no dedicated performance row; V9 added none.

## J. Findings (`DEFECT · SEVERITY · ROOT CAUSE · IMPACT · FIX/DEFER · EVIDENCE`)

| id | defect | severity | root cause | impact | fix/defer | evidence |
|---|---|---|---|---|---|---|
| **V9-1** | Trust/delegation reachability enumerates simple paths — exponential in branching × depth; default depth 16 aborts on every worst-case rung; unbounded temp files fill the disk | **HIGH (P1: availability)** — one authenticated `GET /graph/reachability` at depth ≥ 16 on a tenant whose agents trust/delegate to ~2 peers can exhaust the DB server's disk (it did, twice, in the lab) | path-array cycle guard in `traverse` / `traverse_with_edges` (`app/graph/traversal.py`): rows are paths, not nodes | reachability and blast radius over cyclic authority graphs unavailable at depth ≥ 16; DoS vector | **DEFER → architecture gate**: frontier-dedup (`UNION`) CTE (variant B/C proven identical) + batched hydration; interim `statement_timeout`/`temp_file_limit` on the app role | `SCALE_MEASUREMENTS.md` ladders + growth tables; `evidence/v9_reach_variant_worst_100000.json` |
| **V9-2** | N+1 label/edge hydration in traversal | MEDIUM | one `resolve_node` per reached node / one edge fetch per hop | 14,866 statements → 4.0 s for an 8k-node fan-out; ~18 s of the 22.5 s at 63k nodes; 2.4 s hub blast radius | DEFER (same file, same gate): batch by node type | measure JSONs (`statements` counts) |
| **V9-3** | Posture sweep cost linear at 25–40 ms/agent → ~53 min per 80k tenant | MEDIUM (operational) | 16 rules × per-agent queries in `evaluate_tenant` | the scheduled `posture.evaluate` job walls on busy tenants | DEFER (M6/gate): set-based per-rule evaluation | budgeted runs at 10k and 100k |
| **V9-4** | O-11 stands; `backend/.keys/` also holds 92,694 test-residue private keys (~126 MB) | **HIGH (pilot blocker, pre-existing)** | `.dockerignore` lacks `.keys/`, `COPY . .`; suite writes signing keys into the dev key dir | image embeds live + residue key material; archive tooling copies every `*.pem` | DEFER: bounded fix before V10 (`O11_CONFIRMATION.md`) | `evidence/v9_o11.json` |
| **V9-5** | Resumed bounded sweep raises spurious staleness: checkpoint points at the *start* of the page that hit the 20k bound (offset 19,800), so the resume re-observes 200 items and `check_staleness` flags the other **19,800** agents; a source of exactly 20,000 items is reported `PARTIAL` (`>=` bound) | MEDIUM | `HttpAgentRegistryAdapter.fetch` bound return + `run_source` running staleness when `complete=False` (V7.5's F7.5-1, now measured) | finding floods (non-destructive, auto-resolve on the next full sweep) on any source > 20k items | DEFER (5.2): checkpoint = next offset; skip staleness on partial runs; bound check after the page | worst/100k `discovery.sweep_volume_two_runs` (`findings: 19800`) |
| **V9-6** | Busy-tenant sequential scans on hot paths: `agent_executions` `created_at` range (cost), `external_gateway_calls (organization_id, created_at)` (estate), delegation-edge scan without a node predicate (authority chain) | LOW–MEDIUM (bounded: 34 ms–1.0 s at 100k) | no `created_at`-inclusive indexes; org filters matching 80 % of a table are planner-correct | latency grows linearly with the tenant | DEFER: index review at the gate | captured plans in `SCALE_MEASUREMENTS.md` |
| V9-7 (lab) | The first, unbounded reachability probe filled the Docker VM's disk and wedged Docker Desktop (`com.docker.backend`); the host drive sat at 96–97 % | not ACT | same query as V9-1, before the lab had a temp-file cap | the user's unrelated `scp-mongo-dev` container went down with the engine; Docker Desktop needs a restart | recorded; lab moved to a host-native instance with `temp_file_limit` | §M |

Harness defects fixed during the phase (none changed ACT): model registration (`import app.main`), a
`runtime_alerts.source` CHECK, relative manifest paths after `chdir` (twice), API envelope unwrapping, the estate
check's timing, COPY flush ordering at the 100k rung (executions before versions), and the unbounded first probe
(replaced by the timeout/temp-capped depth ladder).

## K. Product-change findings → O-1…O-11 (re-weighted by V9)

1. **New, highest after F6-1: V9-1 + V9-2** (traversal query shape + hydration) — a P1 availability defect with a
   proven small fix; belongs beside F6-1 at the top of the M6 list.
2. **O-11 (V9-4)** — unchanged priority: mandatory before V10.
3. **V9-5** — a bounded 5.2 fix (checkpoint/staleness on partial runs); low effort, removes a finding flood.
4. **V9-3** — posture sweep shape; needed before scheduled sweeps on large tenants.
5. **V9-6** — index review; cheap.
F6-1 (detection blind to gateway-enforced agents) keeps its V7 weight; V9 did not exercise detection.

## L. P0 / STOP

None triggered: no silent cryptographic identity reset, no fail-loud regression, no durable state lost, no
cross-tenant leakage at any rung, no cliff requiring a graph database, no T12.

## M. What happened to the lab, honestly

The first measurement smoke test ran the product's reachability query at depth 32 without a bound. Inside the
`postgres:17-alpine` container it filled the Docker VM's disk; the Docker engine wedged (every CLI call timed out,
`com.docker.backend` still holding the published port), and the user's unrelated `scp-mongo-dev` container went
down with it. Repeated on the host instance, the same query consumed the host's remaining free space (~12 GB of
temp files) before erroring; the temp files were released, and the lab instance was then capped
(`temp_file_limit=3GB`) and probes bounded (`statement_timeout=60s`). **Docker Desktop needs a restart by the
user**, after which `docker rm actlab-v9-db` and a prune will reclaim the VM disk growth. The host drive was at
96–97 % throughout; the lab instance, its data (4.7 GB with WAL), dumps and lab keys were removed at the end.

## N. Empty-diff confirmation

`git diff 224aea8 --stat -- backend/ frontend/` is **empty**. No projection was built. The commit adds only
`lab/scale/` (lab tooling), `docs/validation/v9/`, and one tracking paragraph each in `ROADMAP.md` and
`REPO_STATE.md`.

## O. Artifacts

`docs/validation/v9/{FIXTURE_GENERATION, SCALE_MEASUREMENTS, PROJECTION_DECISION, RECOVERY_RESULTS, RESULTS_LEDGER,
O11_CONFIRMATION, V9_REPORT}.md`, `REGISTER_UPDATED.csv`, `evidence/` (8 fixture manifests, 8 measurement JSONs
with p50/p95/p99, captured statements and `EXPLAIN ANALYZE` text, the variant probe, both recovery JSONs, the O-11
JSON, the run summary, the run log, generated tables, `ledger.jsonl`); `lab/scale/*.py`. No secrets (synthetic lab
credentials only; the recovery plaintexts were never written to any artifact).

## P. Git

`validation/v9-scale` off `224aea8`; one commit; pushed; **not merged**; `main` untouched at `9667707`.

## Q. V10 readiness

- **O-11 first** — mandatory before any organization environment, even OBSERVE_ONLY (§K.2), with the residue
  clean-up.
- **V9-1/V9-2 decision at the architecture gate** before ACT is placed on any tenant whose agents trust/delegate
  to more than one peer; until then, `statement_timeout` + `temp_file_limit` on the app role in every deployment.
- Reuse: the deterministic fixture generator and the ladder harness give V10 a way to rehearse an organization's
  expected shape before touching it.
- Still out of scope: interoperability claims (V7), cloud (V8, unstarted), T12.

**VERDICT: V9 CONDITIONAL — REVIEW REQUIRED**
