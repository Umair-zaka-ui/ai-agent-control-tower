# Milestone 4 — the end-to-end proof

> **Phase 4.10 (ACT-SRS-M4 §33, §34, §35, §36, §31, §41).** The finish line for
> Milestone 4, and a **proof phase, not a feature phase.** It builds no product
> capability. It *demonstrates*, on one real governed execution, that runtime
> governance, cost truth, tracing, privacy and export operate together — and it
> re-proves the three enterprise properties (tenant privacy, budget race,
> telemetry failure) at the milestone level.
>
> All fifteen tests live in `backend/tests/runtime/test_milestone_4_proof.py`.
> **No proof was weakened to pass, and no product defect was found.** One
> documented behaviour was confirmed rather than fixed — see
> [The one finding](#the-one-finding).

## The §33 end-to-end proof

One `pytest` fixture (`governed_run`) configures a real execution and runs it;
five tests assert the stages. **Every assertion is a real effect of the run —
nothing is a pre-inserted row** (`test_ac05` proves this structurally: the
fixture only ever writes *configuration* — a budget, a capture policy, a
governance policy — never an outcome row).

### The configuration (real cause)

| Thing configured | Via |
|---|---|
| A deployed, published agent version | `_ready_agent` — register → validate → approve → publish → deploy |
| A real priced model | `PricingService.set_price` for a model name unique to the run (0.02/1k) |
| A function tool, assigned to the agent | `POST /tools` + `POST /agents/{id}/tools` |
| A governance cost policy | `{"max_execution_cost": 0.0025, "min_remaining_cost": 0.0015}` (the headroom rule) |
| A `HARD_LIMIT` budget | limit $1.00, reservation estimate $0.25 |
| A `REDACTED_CONTENT` capture policy | org-wide `telemetry_capture_policies` row |
| The input payload | `{"prompt": "Summarise the weather for the client", "headers": {"authorization": "Bearer sk-live-…"}}` — a sensitive-named field and a planted secret |

The mock model transport returns a **tool call on every turn**, so the loop runs
until governance stops it.

### The stages (real effect asserted)

| # | Stage | Real effect asserted (`test_ac0N`) |
|---|---|---|
| 1 | routed to the deployed version | `agent_executions.agent_version_id` / `deployment_id` match the deployed version (`ac01`) |
| 2 | a worker claimed it | an `execution_attempts` row exists; `started_at` is set (`ac01`) |
| 3 | first model call | the first `execution_messages` assistant turn has real `total_tokens > 0` and a real priced `cost_amount > 0` (`ac01`) |
| 4 | model requests a tool; **governance evaluates mid-loop**; tool permitted + executed | a `tool_calls` row exists — a denied tool never reaches `tool_calls`, so its presence *is* the proof the `BEFORE_TOOL_EXECUTION` checkpoint ran and allowed (`ac01`) |
| 5 | a second model call begins; spend approaches the bound; **governance STOPs the loop mid-flight with an explicit reason** | `status == FAILED`, `error_code == GOVERNANCE_EXECUTION_STOPPED`, exactly one `STOP` decision with `reason_code == MIN_REMAINING_COST` and a real templated sentence, at `BEFORE_TOOL_EXECUTION`; the mock model was called exactly **twice**; `loop_iterations == 2` (`ac02`) |
| 6 | **the budget stayed within its configured bound** | `sum(budget_reservations.reserved_amount) ≤ limit`; actual spend `== 0.002 ≤ 0.0025` — 4.4's documented reserve-vs-actual semantics (`ac03`) |
| 7 | **the complete trace reconstructs the execution** | `TraceAssembler.assemble(row)` produces spans of kind `execution`, `model_call`, `tool_call`; the root span's status is the real terminal `FAILED`, not an invented success (`ac04`) |
| 8 | **sensitive fields are redacted per the capture policy** | `TraceContentService.view` returns `mode == REDACTED_CONTENT`, `captured == True`; the planted secret is absent; the `prompt` field's value is masked; at least one item is flagged `redacted` / `secret_scrubbed` (`ac04`) |
| 9 | **metrics reflect the outcome** | `GET /metrics` contains `act_runtime_executions` with `status="FAILED"` (`ac04`) |
| 10 | **the governance decision is audited** | an `authorization_audit` row with `event_type == RUNTIME_EXECUTION_STOPPED` exists for the execution's org (`ac04`) |
| 11 | **the telemetry is OTLP-exportable** | `trace_to_export(trace)` → `_to_readable_spans` → `encode_spans` → `SerializeToString` → re-parse: every span carries a 16-byte trace id and an 8-byte span id, and the planted secret is **not** in the wire bytes (`ac04`) |

## The three enterprise proofs

### §34 — tenant privacy (`test_ac06`)

Two orgs, both with sensitive traces (org A on `FULL_CONTENT`). Adversarial
matrix over the **whole M4 read surface**, org B trying to reach org A:

- metadata — `GET /observability/executions/{a}/trace` → 403/404; `GET
  /observability/traces/{a}` → 404; the explorer never returns A's rows;
- content — `GET /observability/traces/{a}/content` → **404** (`TRACE_NOT_FOUND`),
  not 403 — cross-tenant existence is never confirmed;
- existence via 4.9 aggregation — `GET /runtime/overview` counts only B's own;
  `GET /runtime/governance/decisions` and `GET /cost/summary` never mention A's
  execution or agent;
- and org A still sees its own content in full.

Elevates the phase-level checks (4.2 `test_ac09_*`, 4.8
`test_ac10_privacy_set_cross_tenant_*`) into one milestone-level matrix.

### §35 — the budget race (`test_ac07`)

Twelve concurrent workers, **each on its own real `SessionLocal()` connection**,
race for a $1.00 budget that holds $0.25 per execution. Exactly four fit; the
sum of `reserved_amount` never exceeds $1.00 — decided by `SELECT … FOR UPDATE`
on the budget row in the database, not by application timing. A companion test
(`test_ac07_the_reservation_claim_serialises_…`) asserts `app/finops` imports no
`threading`/`multiprocessing` and uses `with_for_update`. Composes 4.4's
`test_ac06_concurrent_workers_cannot_collectively_exceed_a_budget`.

### §36 — both plane directions

- **Telemetry fails open** (`test_ac08`): a real execution runs to `SUCCEEDED`
  with a `Failing` export sink; five dispatch cycles later the exporter is
  `degraded` with a visible `last_error`, the bounded buffer's `span_count`
  never exceeds `capacity_spans`, and the execution row's `status`/`cost_amount`
  are byte-identical to before the failed cycles. Composes 4.6's
  `test_ac05_execution_completes_normally_with_the_collector_down`.
- **Governance fails closed** (`test_ac09`): a mandatory governance constraint
  that raises at `BEFORE_FIRST_MODEL_CALL` — the execution is STOPped with
  `error_code == GOVERNANCE_CHECKPOINT_UNEVALUABLE`, a `STOP` decision with
  `reason_code == CHECKPOINT_UNEVALUABLE`, and `loop_iterations == 0`: **the
  loop never ran past the unevaluable checkpoint.** Elevates 4.3's
  `test_ac06_a_mandatory_policy_that_cannot_be_evaluated_stops_the_execution`
  from the unit level to an end-to-end POST.

## Hardening (§31 / §10)

| Test | What it holds |
|---|---|
| `test_ac10_trace_explorer_stays_bounded_and_indexed_at_volume` | 400 executions for one tenant; the explorer caps the result set at `limit`, reports `has_more`, and `EXPLAIN` shows **no `Seq Scan on agent_executions`** — the tenant-leading, time-bounded plan the 4.2 index discipline established holds at volume. |
| `test_ac10_metrics_cardinality_stays_bounded_at_volume` | 200 executions across 40 distinct fake error codes; every label on every `/metrics` line is drawn from the 4.1/4.6 bounded dimension set — a raw per-execution error code never becomes a label. |
| `test_ac11_recovery_…_survive_a_restart` | after a simulated restart (a fresh `Session`), the governance policy, the budget, the capture policy and an `OPEN` alert are all still there and effective — nothing is reset, no phantom worker appears, `resolve_capture_mode` still returns `REDACTED_CONTENT`. |

## The §41 gate-closure audit

`test_ac12_every_gate_a_through_o_maps_to_a_named_passing_proof` asserts the
mapping below is complete (A–O, no gaps). **The A–O letter ↔ concern mapping is
reconstructed** from the per-phase `Gate X` references in the phase docs/tests
(`test_cost_governance` names D/E, `test_telemetry_privacy` names F,
`test_otel_interop` names H/I/N, `test_slos_and_alerts` names J/K,
`test_behavioral_signals` names L, `observability-center.md` names M) plus this
phase's build prompt — the SRS §41 consolidated table is not carried in the
repo (a reported SRS/repo observation).

| Gate | Concern | Owning phase | Proof |
|---|---|---|---|
| A | end-to-end governed execution | 4.10 | `test_milestone_4_proof::test_ac01..ac05` |
| B | trace context & assembly foundation | 4.1 | `test_telemetry_foundation` + `test_ac04` (the trace reconstructs) |
| C | trace explorer / metadata surface | 4.2 | `test_execution_tracing` |
| D | cost truth (actual vs estimated kept apart) | 4.4 | `test_cost_governance::test_ac01_*` |
| E | budget enforcement under concurrency (§35) | 4.4 | `test_cost_governance::test_ac06_*` + `test_ac07` |
| F | telemetry privacy / capture policy / retention | 4.8 | `test_telemetry_privacy` |
| G | runtime governance enforcement (one path, fail-closed) | 4.3 | `test_runtime_governance::test_ac02_*` + `test_ac02`/`test_ac09` |
| H | OTLP export — fail-open, off the hot path | 4.6 | `test_otel_interop::test_ac05_*` + `test_ac08` |
| I | metrics interoperability — bounded cardinality | 4.6 | `test_otel_interop::test_ac04_*` + `test_ac10` |
| J | SLOs — deterministic, explainable, `INSUFFICIENT_DATA` first-class | 4.7 | `test_slos_and_alerts` |
| K | alert lifecycle — signal, not notification | 4.7 | `test_slos_and_alerts` |
| L | behavioral signals — deterministic, explainable, no ML | 4.5 | `test_behavioral_signals` |
| M | observability center — read + trigger, content governance inherited | 4.9 | `test_observability_center` + `test_telemetry_privacy` content set |
| N | telemetry-failure resilience (§36) | 4.6 | `test_otel_interop::test_ac05_*` + `test_ac08` |
| O | regression — M1/M2/M3/4.1–4.9 unchanged | 4.10 | the full backend suite passes unchanged (2,265 → 2,280) |

## The one finding

**`GOVERNANCE_CHECKPOINT_UNEVALUABLE` is deliberately retryable — this is
documented behaviour, not a defect.** The first end-to-end run of the §36
governance-fail-closed proof left the execution `QUEUED` rather than terminally
`FAILED`. Reading `ExecutionWorkerService._fail_or_retry`
(`app/runtime/services.py`) confirms this is intentional: the code comment reads
*"GOVERNANCE_CHECKPOINT_UNEVALUABLE is deliberately not in [the non-retryable]
set. Fail-closed says an unevaluable mandatory checkpoint stops this attempt; it
does not say the condition is permanent, and a transient dependency failure is
exactly what the retry policy exists for."*

The fail-closed guarantee is about the **attempt**: the loop never ran past the
checkpoint (`loop_iterations == 0`), the execution never proceeded ungoverned,
and a `STOP` decision was recorded. The requeue is the retry policy doing its
job; after `max_attempts` the execution goes `DEAD_LETTERED`. `test_ac09`
asserts the honest property — `status in (FAILED, QUEUED, BLOCKED,
DEAD_LETTERED)`, never `SUCCEEDED` — rather than a weakened one.

**No product code was changed by this phase.**

## Milestone 4 is complete

One real execution proves the whole thesis: a governed production agent runs, is
traced, routed and metered in real cost; the runtime governance engine blocks an
expensive action mid-loop and terminates it with an explicit reason; the budget
holds; the trace reconstructs the journey; sensitive fields are redacted; the
decision is audited; and the telemetry exports through an open standard — with
tenant privacy, budget-race safety and telemetry-failure resilience each
independently proven, and all fifteen gates (A–O) closed.
