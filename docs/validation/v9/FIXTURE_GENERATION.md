# FIXTURE_GENERATION — committed, deterministic, reproducible; honest-worst-case first

Scripts (all under [`lab/scale/`](../../../lab/scale/), lab-only, importing the **unchanged** product code):

| file | role |
|---|---|
| `labenv.py` | binds every V9 process to the **dedicated lab database** (`127.0.0.1:55433/act_v9`) and lab-only key material (`lab/.keys/v9*`, gitignored); refuses to start against anything else |
| `fixtures.py` | the generator: `python lab/scale/fixtures.py --rung <N> --dist realistic|worst [--seed 9]` |
| `measure.py` | the §4 measurements (p50/p95/p99 + captured-statement EXPLAIN) |
| `recovery.py` + `recovery_step.py` | the §6 recovery scenarios, one interpreter per scenario |
| `v9_run.py` | the orchestrator: ladder → recovery → O-11, ledger-anchoring every artifact |
| `o11_check.py` | the §9 structural confirmation |

## Determinism

`random.Random(f"v9-{rung}-{dist}-{seed}")` seeds everything — UUIDs (`uuid.UUID(int=rng.getrandbits(128))`),
names, edge targets, statuses, costs. Same rung/dist/seed → byte-identical fixture set (modulo the four
tenants created through the product's own `register_organization`, whose ids are minted by the app; their
*contents* are deterministic). Every fixture manifest is written to `lab/run/results/v9_fixture_<dist>_<rung>.json`
and **hash-anchored in the lab ledger before any measurement reads it**.

Rows are loaded with `COPY ... FROM STDIN` per table (50k-row batches), then the hot tables are `ANALYZE`d
before any measurement — the stale-planner-statistics trap the 5.4 benchmark recorded (cold: 20 s; analyzed:
90 ms).

## The two distributions (the §1 mandate)

| | `realistic` | `worst` (honest worst case) |
|---|---|---|
| tenants | `clamp(rung/100, 4, 1000)`; Zipf-like sizes ∝ 1/rank^0.7 (largest ≈ 4 % at 100k) | **one busy tenant with 80 % of the agents**; the rest spread over ≤ 20 small tenants |
| measured tenant | the largest | the busy one |
| agents | 30 % NATIVE/GOVERNED · 60 % EXTERNAL (half REGISTERED + GATEWAY_ENFORCED, half DISCOVERED) · 10 % UNKNOWN/DISCOVERED; 30 % unowned; every row legal under ADR-0023 | same mix |
| dependency edges | per agent: 5 × DEPENDS_ON_TOOL, 3 × DEPENDS_ON_RESOURCE; per tool: 1 × TOOL_ACCESSES_RESOURCE (pools: tools = n/10, resources = n/20, three of them `payroll`) | same |
| inter-agent authority edges | 30 % of agents carry one TRUSTS and/or one AGENT_DELEGATES_TO to a random peer (expected out-degree ≈ 0.6) | **every agent** carries one TRUSTS **and** one AGENT_DELEGATES_TO to random peers (out-degree 2 — a branching digraph) |
| high-degree nodes | — | RESOURCE hub: in-degree = 50 % of the tenant's agents · TOOL hub: 40 % · AGENT super-node: TRUSTS fan-out to 10 % |
| deep chains | 100 chains × 31 `AGENT_DELEGATES_TO` hops (cap is 32) on the measured tenant | same |
| authority-chain replay | 50 execution chains of depth 31 (`parent_execution_id`, REPLAY) whose root is triggered by the admin, behind a 10-hop HUMAN `DELEGATES_TO` prefix (real `delegations` rows + edges) | same |
| executions (cost, 4.4) | 1,000 versions on the measured tenant; executions = 1.2 × tenant agents (≥ 100), `cost_amount` populated | 1.2 × rung, capped at 120,000 |
| gateway history (5.7) | 3 × executions `external_gateway_calls` rows (70 % ALLOWED/DISPATCHED, 30 % DENIED/NOT_DISPATCHED), capped at 300,000 | same |
| dense reconciliation (5.2) | one source + one run with **N = tenant agents observations**: 50 % LINK contention (identifiers of existing EXTERNAL agents), 5 % NATIVE collisions (must FLAG), 45 % new; plus a 300-observation race set reconciled by 3 concurrent sessions | same |
| durable state for recovery | 1 org budget + 100 agent budgets, 100 OPEN `runtime_alerts` | same |

Edge volume: ≈ 10 dependency/authority edges per agent + hubs → **~1.0–1.2 M edges at the 100k rung**
(exact per-set counts are in each manifest and in `SCALE_MEASUREMENTS.md`).

## What the fixtures are not

A synthetic agent is **not** an independent agent. These rows exercise ACT's queries, reconciliation and graph
at volume; they say nothing about governing real frameworks. That claim belongs to V7 and is not repeated here.

## The lab database (§2.2)

Not the shared dev database. A dedicated PostgreSQL 17.10 instance (`initdb` from the installed 17 binaries,
data directory `lab/run/pg17/data`, gitignored, ephemeral; `port=55433`, `listen_addresses=127.0.0.1`,
trust auth on loopback only, `shared_buffers=512MB`, `work_mem=32MB`, `maintenance_work_mem=256MB`,
`temp_file_limit=3GB`). It started in a `postgres:17-alpine` container on `127.0.0.1:55432`; that container was
lost when the first (unbounded) reachability probe filled the Docker VM's disk — see `PROJECTION_DECISION.md`
and the report's findings — and the lab moved to the host-native instance, which is also the fairer comparison
with the 5.4 / 5.10 / V0.2 baselines (all measured on the host engine).
