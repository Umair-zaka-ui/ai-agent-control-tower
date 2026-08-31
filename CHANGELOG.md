# Changelog

All notable changes to the AI Agent Control Tower are documented here. The format is
based on [Keep a Changelog](https://keepachangelog.com/); the project is pre-1.0 and
versions track the roadmap phases rather than semver guarantees.

## [Unreleased] — Phase 4.6 · OpenTelemetry & Metrics Interoperability

**Milestone 4's sixth sub-phase: the platform now speaks OpenTelemetry at its boundary — and does so such that a collector outage is an observability event, never an execution event.** An enterprise streams execution traces and operational metrics to Datadog, Azure Monitor, Grafana, Splunk, Elastic, or any OTLP collector by pointing at an endpoint. No runtime change. No vendor lock-in.

- **The OTel SDK lives behind one adapter package and nowhere else.** `app/telemetry_export/sinks.py` is the only module in the codebase that imports `opentelemetry`, and it imports it at function scope. `test_ac02_*` walks the AST of every other package (`app/runtime`, `app/observability`, everything) and fails on a single stray `import opentelemetry` / `ddtrace` / `datadog` / `prometheus_client`. There is no vendor name anywhere in the code, so switching collectors is a config edit — recorded in [ADR-0011](docs/architecture/adr/0011-opentelemetry-export-as-a-fail-open-plane.md).
- **Export is fail-open, and it is not on the execution path at all.** A background `ExportDispatcher` reads executions that have *already reached a terminal state*, assembles their traces through 4.2's read model, converts them to neutral records, and hands them to a sink. The runtime is never instrumented — there is no code path from an execution to an export to fail along. Every dispatcher method catches `Exception` and returns; a runtime export failure is exporter-health state and a metric, never an exception and never an error code (the only export error that is an HTTP error is `EXPORT_CONFIG_INVALID`, a validation failure on a config write).
- **The §36 proof is the gate.** `test_ac05_execution_completes_normally_with_the_collector_down` runs a real execution, then drives five dispatch cycles with the collector down, and asserts the execution row is byte-for-byte unchanged, no telemetry event and no audit row were written by export, `exporter_health` reports `degraded` with a visible `last_error`, and the buffer never grew past its cap. A companion test does the same against a real `OTLPSpanExporter` pointed at a dead port — a genuine `ConnectionError`, contained.
- **Bounded buffering — never an unbounded queue.** `BoundedSpanBuffer` has a hard maximum measured in *spans* (the unit the "memory bounded" claim is about) and a declared policy when full (`drop_oldest` default / `drop_newest` / `block_bounded`). `BUFFER_FULL_POLICIES` contains no "grow" option and a test asserts that. The buffer lock is never held across the network export, so a hung collector blocks only the dispatcher thread. "Retry" means a failed batch re-queues to the front *under the same cap* — if producers moved on, the stale batch loses to newer data.
- **Metrics are scraped, not pushed.** `GET /metrics` returns Prometheus text exposition, **tenant-scoped** and **authenticated** (`runtime.telemetry.view`) — deliberately not the open-unauthenticated-scrape model, which on a multi-tenant platform is a cross-tenant disclosure. Spans push over OTLP (event-shaped); metrics scrape (state-shaped), avoiding a second export loop with its own backpressure problem.
- **Bounded metric cardinality reuses 4.1's denylist.** Every label goes through `metric_label_set()`: a name in `SENSITIVE_ATTRIBUTES` or `HIGH_CARDINALITY_ATTRIBUTES` (`execution_id`, `email`, `prompt`, raw `model`, …) raises. The allowed set is 4.1's `METRIC_DIMENSIONS` plus a small explicitly-declared 4.6 extension for two behavioral-finding enums (`signal_type`, `state`) — declared in 4.6, *not* added to the global allowlist. A structural test parses `metrics.py` and checks every `r.add()` call's keywords.
- **Config is two layers.** Platform default in `Settings` (env vars); per-environment override in `Environment.policy["telemetry_export"]` — the same JSONB document that already carries allowed models and budgets. `PUT /api/v1/observability/export/config` (`runtime.telemetry.export.manage`, audited, idempotent) sets `enabled`/`endpoint`/`protocol`/`headers`; buffer sizing stays platform-level. Header values are carried opaquely — never logged, audited, or echoed; the audit record for a change carries the endpoint **host only** (no path, no query, no credential).
- **Extends [ADR-0008](docs/architecture/adr/0008-telemetry-as-a-derived-plane.md):** the exported spans are also derived — produced by the same `TraceAssembler` from the same domain rows. A collector's span disagreeing with an `agent_executions` row is resolved in favour of the row. Export changes where a derived view can be *read*; it adds no plane.
- **Plane discipline preserved.** Export is fail-open telemetry; it is never a governance input and never gates execution. Governance still fails closed (4.3 unchanged) — asserted structurally (`app/runtime` never imports `telemetry_export` or reads `exporter_health`) and behaviourally (a degraded exporter does not change a governance decision).
- **No new table, no migration.** Export config lives in `Environment.policy`; exporter health is in-process and ephemeral (dropped on restart, never a phantom — see `RECOVERY.md`). A span/metric storage backend is explicitly *not* built — the customer's collector stores.
- **New dependency:** `opentelemetry-sdk==1.44.0` + `opentelemetry-exporter-otlp-proto-http==1.44.0` (pulls `requests`, `protobuf`, `googleapis-common-protos` transitively), imported only behind the adapter. **Added** `app/telemetry_export/` (10 modules); routes 562 → 566 (`GET`/`PUT /api/v1/observability/export/config`, `GET /api/v1/observability/export/health`, `GET /metrics`); one new permission (`runtime.telemetry.export.manage`), one new error code (`EXPORT_CONFIG_INVALID`, 422), one new audit event (`RUNTIME_TELEMETRY_EXPORT_CONFIGURED`). Head stays `0049` — no migration.
- 51 new backend tests (`tests/runtime/test_otel_interop.py`). Backend **2,180 passed**, 0 failed, 1 deselected (2,129 + 51); frontend **327** green, unchanged — the observability center UI is 4.9. Two existing 4.2 tests updated, both intent-preserving and neither touching production code: `test_ac13_the_observability_prefix_does_not_collide` (bare route count → membership assertions, for the two new routes under the shared prefix) and `test_ac06_the_explorer_query_uses_the_index_and_does_not_scan` (a query-plan assertion that named the 0046 composite index specifically — loosened to "an organization-leading index, and never a Seq Scan", its actual documented invariant, after shared-database growth made Postgres prefer the compact single-column org index for the bitmap path on a tiny tenant; the failure reproduces on unmodified `main` — 4.6 touches neither the query nor its indexes — and the 0046 composite's real value, sort elision at volume, stays guarded by the specific companion test). See [docs/observability/opentelemetry.md](docs/observability/opentelemetry.md) and [metrics.md](docs/observability/metrics.md).

## [Phase 4.5] — Behavioral Signals & Runtime Anomaly Detection

**Milestone 4's fifth sub-phase, and a discipline-of-restraint phase: the hardest part was what not to build.** The platform now detects how an agent's runtime behavior *changes* — deterministically, explainably, and strictly as a signal.

- **No machine learning, and the reason is stated rather than merely obeyed.** *"This agent is 0.87 anomalous"* is unauditable, unappealable and ungovernable — a regulated tenant cannot act on it, dispute it, or show a regulator why it fired. *"Tool `send_email` failed 34% of 118 calls this week against a 3% baseline"* is all three. Every rule here is arithmetic over a window; the thresholds are declared, not learned.
- **Determinism is structural, not promised.** The rules are pure functions of `(candidate, baseline, thresholds)` — no session, no clock, no globals. One test runs a full evaluation three times and compares every field of every signal; another asserts over the AST that no numerical or ML library (including `random`) is importable anywhere in `app/behavior`, and that no rule takes a session or reads a clock.
- **Reuses Phase 3.5's engine, does not fork it**: veto → sufficiency → threshold → baseline, `INSUFFICIENT_DATA` first-class. Three of the five state values are **byte-identical** to 3.5's, asserted against the live module so a rename on either side breaks the build. The terminal-status sets are asserted equal too.
- **A genuine prompt-vs-repo conflict, resolved and reported.** The build prompt asked for `NORMAL/…/ANOMALOUS` while saying "do not fork a parallel vocabulary" — but the existing set is `HEALTHY/…/UNHEALTHY`, so the proposed one differs in two of five positions and taking it literally would have been the fork it forbade. Resolved by keeping the shared middle exactly and letting the endpoints differ, because they are different claims: 3.5 judges **fitness** ("should this version get more traffic"), 4.5 judges **deviation** ("has this agent changed"). A p95 that drops 80% overnight is anomalous and in no sense unhealthy; a steady 30% failure rate is unhealthy and not anomalous at all.
- **Added** seven signals with stated rules: `error_rate_shift`, `policy_denial_surge`, `latency_drift`, `cost_drift`, `tool_failure_spike`, `tool_pattern_shift`, `loop_termination_anomaly`.
- **`latency_drift` reports speedups too** — a metric that halves overnight usually means the agent stopped doing something it used to do. This is the clearest place a behavioral signal differs from a health signal, which only cares about getting worse.
- **`tool_failure_spike` is per tool and names the worst offender**, because one broken integration among five healthy ones barely moves an aggregate.
- **`loop_termination_anomaly` is the signal invisible in the error rate**: a model that has started looping is stopped by Phase 5.6a.3's caps working exactly as designed, so nothing errors from the caller's view and only the termination mix shows it. A test asserts it fires while `error_rate_shift` stays NORMAL.
- **Every finding explains itself from its own row** — metric, both window bounds with sample counts, observed value, threshold and/or baseline, the crossing in words, and the evidence. A test walks every persisted finding and asserts the record is self-contained.
- **`INSUFFICIENT_DATA` is first-class, and a thin *baseline* is treated as no baseline** rather than a weak one — comparing against three executions would manufacture drift out of noise. Absolute thresholds still apply, so the signal is still evaluated.
- **The veto has a sharper reason than 3.5's**: a killed agent's runtime data describes the *kill*, not the agent. Reporting the resulting cancellation spike as ANOMALOUS would raise an alarm about the intervention at the moment an operator is already using it. A test asserts aggregation never runs when the veto fires.
- **Connector attribution deferred and named in every finding.** The runtime has no record of which external system a version depends on (ACT-INT-FR-006 — the boundary Phases 3.2, 3.3 and 3.5 each reported in turn), so findings carry `connector: null` **with a reason string** rather than omitting the key and letting a reader assume it was never considered. A test asserts the package imports nothing from `app.integration`.
- **Findings are signals; 4.3 remains the only enforcer.** Nothing in `app/behavior` writes an execution's status, raises the governance stop or reaches the kill switch — asserted over the AST against the execution-state vocabulary — and a behavioural test confirms evaluating a wildly anomalous agent leaves every execution row byte-identical. Emission is **non-gating**: a failed evaluation produces no finding, never a STOP.
- **The 4.4/4.5 cost boundary is demonstrated, not asserted**, in both directions: per-execution cost doubling while traffic halves leaves total spend flat (4.5 fires, 4.4 silent); traffic multiplying at unchanged per-execution cost is the reverse. Neither package imports the other, tested both ways.
- **Measured; no index added.** Agent-scoped window aggregate **0.57ms p50 / 1.42ms p95** at 115,381 executions. The plan is the point: no composite covers `(organization_id, agent_id, created_at)` and Postgres does not need one — it combines Phase 4.2's tenant+recency index with Milestone 1's `agent_id` index via `BitmapAnd`. One shape on `tool_calls` is **named rather than fixed on suspicion** (the time bound is a post-index Filter, the shape 4.2 found dangerous) because 5,210 tool calls platform-wide cannot demonstrate it; migration `0049` records the revisit trigger instead.
- **No scheduler was built** — that would be the fork this milestone has refused three times. The evaluate operation is idempotent at two levels (3.1's `Idempotency-Key`, plus a unique constraint on `(agent, signal, window)`) so Phase 3.8's scheduler can adopt it as a registration rather than a rewrite.
- Routes 559 → **562** (mounted on the existing runtime prefix rather than a second agents namespace); schema 128 → **129 tables**; **no new permission** (`runtime.telemetry.view` reused), no new error code, no new audit event — findings are telemetry-plane records and inventing an audit event for routine emission would misrepresent which plane they belong to. Head `0048` → **`0049_behavioral_signals`**, reversible.
- 46 new backend tests (`tests/runtime/test_behavioral_signals.py`). Backend **2,129 passed**, 0 failed, 1 deselected (2,083 + 46); frontend **327** green across 49 files, unchanged — the Behavior view is deferred to 4.9. See [docs/runtime/behavioral-signals.md](docs/runtime/behavioral-signals.md).

## [Phase 4.4] — Enterprise AI Cost Governance & FinOps

**Milestone 4's fourth sub-phase: cost truth, and budgets that hold under concurrency.** The platform now knows what it actually spent — per execution, aggregated every way an enterprise allocates it — and can enforce a ceiling that N concurrent workers cannot collectively blow through.

- **Added** the §35 budget race proof, which is the phase's gate. The failure prevented: twenty workers each read *"$9 remaining"* against a $10 budget, each conclude they may spend $9, and $180 is spent — every worker having read a true balance and acted on it correctly. The defect is the gap between the read and the act, and here that gap contains a model call. **Proven with twelve real Postgres sessions** racing a $1.00 budget at $0.25 a hold: exactly four are granted. §11 forbids an in-process lock and a structural test asserts none exists.
- **The mechanism**: `SELECT ... FROM budgets ... FOR UPDATE`, sum the period's holds, refuse-or-insert, **commit** — releasing the lock before the caller does anything slow. Two indexed statements under the lock, never across model or tool I/O. Commit-before-dispatch, applied to money.
- **What is guaranteed, and what is not — stated rather than glossed.** Guaranteed: total *reserved* never exceeds the limit. **Not** guaranteed: total *actual*, because a model call's cost is unknowable until it returns. An execution admitted with a $0.25 hold that costs $0.40 overshoots by $0.15; the total is bounded by the sum of (actual − reserved) in flight, and per-execution by 4.3's `min_remaining_cost`. **A test asserts the overshoot is real** so nobody meets it first in production. Recorded in [ADR-0010](docs/architecture/adr/0010-budget-reservation-semantics.md).
- **One enforcement path preserved.** A refused reservation is not a refused execution: 4.4 reports `budget_remaining <= 0` and Phase 4.3's engine turns it into a `STOP`/`BUDGET_EXCEEDED` before any model call. `app/finops` contains no code that writes an execution's status, raises the governance stop or calls the kill switch — asserted over the AST against the execution-state *vocabulary*, so `budget_reservations`' own `status` column does not force the test to be weakened. The budget constraint entered the engine as a **separate tier** rather than another built-in cap, precisely so 4.3's exact cap-ordering assertion did not have to be relaxed.
- **Added** `app/finops/` — `aggregation`, `budgets`, `reservations`, `guard`, `schemas`, `routes` — a sibling of `app/runtime` and `app/observability`, so the dependency direction is visible in the import graph.
- **Actual, estimated and unpriced are three numbers and are never added.** `cost_is_estimated` exists because the platform sometimes cannot meter a call; a NULL `cost_amount` counts in neither sum and is reported separately. Treating "we don't know" as zero is how a spend figure becomes a lie that gets repeated to a finance team.
- **Deprecated in place**, not rewired: the legacy `GET /analytics/cost` (un-prefixed — the Phase-3 analytics router mounts with an empty `API_PREFIX`) multiplies `agent_actions` row counts by flat constants like `_COST_PER_ACTION = 0.012`. Its response now carries a `deprecation` object naming `GET /api/v1/cost/summary`. **Not rewired** because the Phase-3 dashboard consuming it expects six synthetic categories — human review, policy evaluation, storage — that `agent_executions` knows nothing about; pointing it at real data would have silently redefined every number on a dashboard this phase does not own.
- **Immutable provenance (§10) is a property of what already existed**: `PricingService.set_price` closes the prior row and inserts a new one, and an execution records its `pricing_version`. A test 10×s a model's price and asserts both the single charge and the org-wide total are unchanged — it would fail loudly if either half ever became an in-place update.
- **Measured; no index added.** At 109,398 executions across 10,934 tenants: tenant summary **0.80ms p50**, breakdowns 1.99–5.69ms, timeseries 1.11ms, all through Phase 4.2's existing index with no sequential scan. The honest worst case (one tenant owning the table) is 20.46ms summing / 41.70ms grouped — and **no index fixes that**, because summing a tenant's spend means reading every row of it. The only sublinear answer is a materialized rollup, which is the parallel cost store this phase is forbidden to build.
- **Two accounting sources, deliberately.** Enforcing budgets use the reservation ledger (you cannot atomically claim a share of a number you compute by scanning); signalling budgets take no reservations and observe real spend directly. **The consequence is documented**: a budget switched from WARNING to HARD_LIMIT starts its ledger at that moment and its utilization drops.
- **Fixed — three defects the tests caught in this phase's own code.** (1) A budget `STOP` was retryable, so an exhausted budget would burn every remaining attempt taking and releasing holds against a budget with nothing left; `BUDGET_EXCEEDED` is now non-retryable. (2) Signalling budgets could never signal, reading utilization from a ledger they never write. (3) A stale `QUEUED` row from an unrelated suite starves the eager inline worker — `claim_next` takes the oldest queued row across *every* organization — surfacing as an execution stuck in QUEUED with no error at all; the suite now quiesces the queue per test, the discipline Phase 3.9 established.
- **Orphan release is a correctness requirement, not housekeeping**: a leaked hold permanently shrinks a tenant's budget every time a worker dies. Every terminal path settles; the sweeper beneath them is **not time-based**, because a long execution legitimately holds a reservation for its whole run and releasing on age would return live holds under exactly the load that made them slow.
- Routes 549 → **559**; schema 126 → **128 tables** (two new, plus a nullable `budget_id` on `runtime_governance_decisions`, and **no new index on `agent_executions`**); four new error codes (`BUDGET_EXCEEDED` is **402**, not 403 — the request was permitted, the money was not there); two new audit events; two new permissions (`runtime.cost.view` reused). Head `0047` → **`0048_cost_governance`**, reversible.
- 59 new backend tests (`tests/runtime/test_cost_governance.py`). Backend **2,083 passed**, 0 failed, 1 deselected (2,024 + 59); frontend **327** green across 49 files, unchanged — the Cost Center UI is deferred to 4.9. See [docs/runtime/cost-governance.md](docs/runtime/cost-governance.md) and [budgets.md](docs/runtime/budgets.md).

## [Phase 4.3] — Runtime Governance Enforcement Engine

**Milestone 4's third sub-phase, and the first since 3.9 to modify the execution path itself.** The platform can now govern an agent *while it runs*: at six checkpoints inside the model→tool→model loop, one engine decides ALLOW / DENY / CHALLENGE / STOP with an explicit reason and obligation.

- **Changed — the four termination caps are no longer enforced by the loop.** Since Phase 5.6a.3, `ToolLoopOrchestrator.run` compared against iteration count, wall-clock, token budget and repeated-identical-call inline. Those comparisons are **gone**: they are constraints inside `RuntimeGovernanceEngine`, reached through the same `evaluate()` call as every richer rule. **Nothing an existing reader observes changed** — same `termination_reason` values, same `TOOL_LOOP_LIMIT_EXCEEDED`, same `loop_iterations`, and the full pre-existing tool-loop suite passes unmodified.
- **Why generalize rather than add beside it.** Two enforcers can disagree about whether to stop an execution, and the winner would be whichever `if` statement the loop reached first — an implementation detail nobody wrote down. Generalizing cost this phase; a second path would have cost every phase after it. Recorded in [ADR-0009](docs/architecture/adr/0009-runtime-governance-as-a-fail-closed-plane.md).
- **The one subtlety worth knowing.** The wall-clock and token checks that used to sit at the *bottom* of the loop body now run at the top of the next iteration — the adjacent half of the same boundary, with no code between them. The order that decides which cap is reported when two breach on the same turn (wall-clock, tokens, iterations) was derived from the pre-4.3 statement order and is **asserted by a test**, because that is exactly the corner case a refactor silently inverts.
- **The one-path property is structural, not documentary.** The orchestrator no longer names `TOOL_LOOP_MAX_TOTAL_TOKENS`/`TOOL_LOOP_MAX_WALL_CLOCK_SECONDS` in any comparison and no longer raises the cap error code — asserted over the AST, so a check reintroduced in a helper, comprehension or nested function fails CI. A grep would only catch someone restoring the old lines verbatim.
- **Added** `app/runtime/governance/` — `contract` (the checkpoint vocabulary, imports no SQLAlchemy), `constraints` (the caps plus seventeen configurable rules), `engine`, `policies`, `schemas`, `routes`.
- **Governance fails CLOSED, the deliberate inverse of 4.1/4.2's telemetry plane** — and the two rules now live inches apart in the same loop. A **mandatory** policy that cannot be evaluated STOPs the execution; a non-mandatory one is logged and skipped, because an advisory rule that halted production the first time it misbehaved would be a worse control than no rule at all. Policy *resolution* failing fails closed regardless of any flag: then the platform does not merely not know what the rules say, it does not know whether a mandatory one applies.
- **Plane separation is tested in both directions**, including the dangerous one: a telemetry failure neither stops an execution nor changes a governance decision, **and** a broken telemetry plane cannot *suppress* a governance stop. It is also structural — the governance package does not import `app.observability`'s read models, and a `CheckpointContext` carries no telemetry handle a constraint could read.
- **Commit-before-dispatch holds at all six checkpoints.** Each does one plain non-locking `SELECT` (kill state, read fresh because an operator's kill arrives on a different connection) plus, for a *material* decision only, one `INSERT`. No statement takes `FOR UPDATE`. The only lock a checkpoint can cause is the FK `KEY SHARE` the transcript writer has taken every turn since 5.6a.3 — compatible with what a tool thread needs. Proven structurally and against a second real connection with `NOWAIT`.
- **The kill switch is triggered, never paralleled** (§19). New `KillSwitchService.activate_system` reuses the same `_cancel_executions`/`_suspend_deployments` and the same `RUNTIME_KILL_SWITCH_ACTIVATED` audit event as the operator path. Automation reaches **EXECUTION and AGENT scope only** — a rule misconfigured by one tenant must not be able to halt a project, an organization or the platform. The engine never *clears* a kill (asserted over the AST), and `KILL_SWITCH_ACTIVE` is non-retryable, because an automatic retry past a kill would be automation overruling an operator.
- **Added** `runtime_governance_policies` (organization → environment → agent, most-specific-first) and the append-only `runtime_governance_decisions` (`REVOKE UPDATE, DELETE ... FROM PUBLIC`). Resolution returns a **list, not a winner** — picking one would let a narrow per-agent policy silently switch off the organization-wide mandatory ceiling above it.
- **Absent any policy, nothing changes.** The built-in caps always apply; everything configurable is opt-in. A tenant that configures nothing gets exactly the execution behaviour 5.6a.3 gave them — which is what made shipping an engine on this path survivable.
- **One capability gap, stated rather than papered over.** A CHALLENGE at the first checkpoint parks the execution in `PENDING_APPROVAL` and the existing funnel resumes it. A challenge raised *later* cannot be resumed — this platform has no way to re-enter a partially-run loop, and re-queuing would repeat tool calls that already had side effects — so it raises its obligation and terminates in `BLOCKED`. Parking it where nothing could move it out again would have been worse. Two new state edges: `RUNNING → PENDING_APPROVAL`, `RUNNING → BLOCKED`.
- **Cost: the ceiling and the headroom rule are different things, and both are tested including the unflattering case.** A bare `max_execution_cost` can only notice an overshoot — a call's cost is unknowable until it returns (measured: a 0.0025 ceiling with 0.001 turns stops on the third at 0.003). `min_remaining_cost` is what keeps spend *within* a bound (same ceiling, stopped at 0.002). The engine reads existing cost and **reserves nothing** — budgets are 4.4's.
- **A misspelled constraint key is rejected, not stored.** A governance control that silently never fires is worse than one that is absent, because someone believes it works.
- **Measured overhead (§25):** one full checkpoint evaluation is **0.42ms p50 / 0.68ms p95**, ~1.7ms per loop iteration — recorded as an executable test, not a commit-message note.
- **Deviations reported, not silently taken**: (1) the decision-read route is mounted on the existing `/api/v1/runtime` prefix rather than the prompt's prefix-less `/api/v1/executions/...`, which would have created a second execution namespace; (2) only **one** permission was added (`runtime.governance.manage`) — decision reads reuse `runtime.execution.view`, because *why did this execution stop* is a fact about an execution, and a second code would leave operators holding execution-view unable to answer it.
- Routes 544 → **549**; schema 124 → **126 tables** (two new, **no new column on `agent_executions`**); four new error codes (`GOVERNANCE_POLICY_INVALID`, `GOVERNANCE_POLICY_NOT_FOUND`, `GOVERNANCE_CHECKPOINT_UNEVALUABLE` — deliberately *retryable*, `GOVERNANCE_EXECUTION_STOPPED` — not); two new audit events; head `0046` → **`0047_runtime_governance`**, reversible.
- 77 new backend tests (`tests/runtime/test_runtime_governance.py`). Backend **2,024 passed**, 0 failed, 1 deselected (1,947 + 77); frontend **327** green across 49 files, unchanged. See [docs/runtime/runtime-governance.md](docs/runtime/runtime-governance.md) and [runtime-policy-checkpoints.md](docs/runtime/runtime-policy-checkpoints.md).

## [Phase 4.2] — Unified AI Execution Trace (Trace Explorer & Timeline)

**Milestone 4's second sub-phase, and the one ADR-0008 named in advance as the point to revisit the derived-spans decision with real numbers.** An operator can now reconstruct any execution's full journey and search across executions to find the one they need.

- **The measurement decided the architecture, and it came first.** At **90,695 executions / 355,377 runtime_events**: trace assembly **0.74ms p50 / 1.08ms p95**; all six explorer filter dimensions **0.23–0.87ms p50**; no sequential scans. **No read projection and no span index were added** — a projection would have optimized a sub-millisecond query at the cost of a second copy to keep in sync, the exact §13 duplication ADR-0008 rejected. Recorded in ADR-0008's new "Measurement outcome" section *and* as an executable benchmark test, so the conclusion keeps being checked rather than having been true once.
- **The measurement also found what the fragmented dev data was hiding.** 90,695 executions across **62,126 organizations** means the busiest tenant owns 500 — every tenant query looked fast for a reason that would not survive a real customer. The honest worst case (one tenant owning the table) exposed a `Parallel Seq Scan` at **26.94ms p50 / 142.27ms p95**: `agent_executions` had **no `created_at` index at all**.
- **Added** migration `0046_trace_explorer_index` — one index, `(organization_id, created_at DESC)`, no table, no column. Before/after on the same query: `Bitmap Heap Scan -> rows=500 -> top-N heapsort` (18 buffers) became `Index Scan -> rows=50 -> no Sort node` (4 buffers). The vanished Sort is the point: bitmap-plus-sort is **O(rows the tenant owns)**, an ordered index scan stopped at the LIMIT is **O(limit)**. An index is not a §13 duplication — it stores no independent copy and is an access path to the authoritative table, not a second thing claiming to be the truth.
- **Added** `app/observability/explorer.py` and `routes.py`; **enriched** `assembly.py` with the missing §8-4.2 node categories — **authorization**, **runtime_policy**, **queue**, **approval**. Six of ten node kinds are row-backed and name their row (`source_table`/`source_id`); four are computed phases reporting `source_table: null`, so derived and row-backed nodes are distinguishable at a glance.
- **The queue node is a computed gap with no row anywhere**, and is worth having precisely because of that: in a slow trace it is frequently the largest interval, and "why did this take 40 seconds?" is usually answered by queue wait rather than model latency. Emitted only when both ends are known — an open-ended wait is not a measured duration.
- **Fixed** a real Phase 4.1 modelling bug surfaced by the new nodes: the root `execution` span started at `started_at`, so the gate and queue nodes rendered *before their own parent*. The root now spans `created_at`→`completed_at` and is a true envelope.
- **Metadata only, enforced upstream of the routes.** Neither read model reads a content column at all (asserted over the AST as attribute reads), so the boundary survives a route change. `runtime.trace.content.view` is named in code and **deliberately not registered** — naming it gives the boundary an owner; registering it would create a grantable permission guarding nothing.
- **Tenant isolation in §34's stronger form** — refusing to *confirm existence*, not merely to read. A cross-tenant trace id returns a response byte-identical to a nonexistent one, and a structural test asserts no explorer code path builds a statement without an `organization_id` filter.
- **Deviation reported, not silently taken**: §6 asked for a new `runtime.observability.view`; this reuses the pre-existing `runtime.telemetry.view`, whose description already reads "View runtime telemetry and execution traces". Two codes guarding one capability is how an authorization model drifts from what operators think they granted.
- **Deferred**: the frontend Trace Explorer and Trace Detail views, to Phase 4.9's observability center (the build prompt permits this). Building them now and rebuilding them into the unified center two phases later would be duplicated work against a moving design.
- Routes 541 → **544** (all GET, under `/api/v1/observability`, no collision with the legacy analytics dashboards); one new error code `TRACE_NOT_FOUND`; no new audit event; schema **unchanged at 124 tables**; head `0045` → **`0046_trace_explorer_index`**, reversible.
- 52 new backend tests (`tests/runtime/test_execution_tracing.py`). Backend **1,947** green (1,895 + 52), 0 failed, 1 deselected; frontend **327** green across 49 files, unchanged. See [docs/observability/tracing.md](docs/observability/tracing.md).

## [Phase 4.1] — Runtime Telemetry & Trace Context Foundation

**Milestone 4 opens.** The instrumentation contract every later M4 phase builds on: a trace/span context that follows an execution across every hop, stable bounded semantic attributes, a non-gating runtime-event shape, and an isolated secret scrubber with a METADATA_ONLY baseline — so that from the very first capture, no unscrubbed secret and no private reasoning can be persisted.

- **Two mandatory pre-steps ran first, and both found real staleness.** *(A)* REPO_STATE's §2/§3/§5 had each kept a **stale headline** while their per-phase narrative paragraphs were faithfully extended beneath — the worst combination, because the document looked maintained. §2 said "119 tables ... `0041_canary_rollout`" (live: **124**, head `0045_runtime_telemetry_context`); §3 said "42 revisions" (live: **45**); §5 said **518** routes, correct as of Phase 3.6 (live: **541**). All three re-derived from the live system. *(B)* The 4.x numbering is now disambiguated: this repository has **two unrelated families** — Book-07's `Part 4.1`/`Phase 4.3` identity-and-authorization work, and ACT-SRS-M4's `Phase 4.1–4.10` observability work with `M4-`-prefixed requirements. ROADMAP carries a comparison table at the top and both historical headings are labelled.
- **The gap was measured, not assumed.** `correlation_id` had existed on `agent_executions` (indexed) since Milestone 1, and `runtime_events` had carried `request_id`/`correlation_id` just as long. Nothing populated them: the service read `correlation_id` **only** from the request body, and `POST /executions` took no `Request` object, so no header could reach it. Live: **74,395 of 74,619** executions (99.7%) had no trace identity, and essentially all **296,941** `runtime_events` rows. The substrate was right; the propagation was absent.
- **Added** `app/observability/` — a **sibling** of `app/runtime` and `app/integration`, so the derived-plane dependency direction is visible in the import graph rather than only asserted. Six modules: `scrubbing`, `attributes`, `capture`, `trace`, `events`, `assembly`.
- **The scrubber is isolated exactly as `scope.py` was** — standard library only, zero platform imports, asserted over the AST. Nine §14 secret classes, matched **by key** (the name says what it is) *and* **by value shape** (a credential under an innocuous name), because either alone is insufficient. Scrubbed **before persistence**, not masked at display: a value that reached the database unscrubbed is already leaked. Not over-eager either — `password_changed_at`, `credential_id` and `prompt_tokens` all survive.
- **Spans are derived, never stored** — the §13 decision and the most consequential one in the phase. A span id is a deterministic `uuid5` over (trace, kind, row, ordinal); a trace assembles by walking foreign keys that already exist, because `execution_attempts`/`execution_messages`/`tool_calls` all carry `execution_id` and are already authoritative. A span table would have been a lossy second copy of them. **No `correlation_id` was denormalized onto any child table either** — that is the same duplication arriving as a column instead of a table.
- **Migration `0045_runtime_telemetry_context`: two nullable columns, no table, no backfill.** Only the two facts not derivable from existing data — `agent_executions.request_id` (lost forever if not captured at the request) and `runtime_events.span_id` (`execution_id` narrows to a trace, not to a step). `correlation_id` was deliberately **not** backfilled: `trace_id_for()` returns `correlation_id or str(id)`, so ~74,000 historical executions gained a stable trace identity from a pure function, with zero rows written and nothing a downgrade could fail to reverse. Reversible, verified live.
- **Telemetry is non-gating, enforced two ways because one is not enough** (§9 — the deliberate inverse of every other subsystem here, which all fail closed). `emit()` catches `Exception` **and** writes inside a `SAVEPOINT`. Without the savepoint a failed `INSERT` poisons the caller's transaction, so the swallowed exception resurfaces as a corrupted execution three frames up — a bug that looks correct in a unit test and fails in production. Proven by a real execution run with the emitter monkeypatched to raise, and by asserting the session is still usable afterwards.
- **`_record_event` was split along the plane boundary.** It had *dual-written* audit and telemetry from one call, with raw unfiltered `meta` as payload and a null correlation. The audit half is unchanged and still raises (a compliance record must not be lossy); the telemetry half now attaches the trace identity, scrubs, drops content and reasoning, and never raises. One choke point, 33 call sites, none changed.
- **METADATA_ONLY is the default; chain-of-thought is structurally excluded.** Content is not captured at all — a real execution carrying a distinctive marker leaves it nowhere in `runtime_events`. Private reasoning is `DataClass.NEVER`, absent from *every* mode's allowed set and tested over every member of `CaptureMode`, so a mode added later cannot acquire it — and it is **dropped rather than redacted**, because a `REDACTED` marker would still record that reasoning existed and how many turns had it.
- **Bounded metric cardinality is structural** (§12). `metric_labels()` is the only way to build a label dict; it raises — never silently drops — on every high-cardinality identity and every sensitive name, with tests parametrized over the declared sets so a name added later cannot escape the guard. The raw `model` is a trace attribute; only `model_category` is metric-eligible.
- **Execution behaviour is unchanged, including the subtle case.** Phase 3.4 uses `payload["correlation_id"]` as its sticky routing key, so writing an auto-minted correlation into the *payload* would have made every request sticky and quietly defeated percentage rollouts. The minted id reaches the **row** and never the payload; `_routing_key` is untouched and a test pins it.
- **The scheduler leg is wired, not merely available** (M4-4.1-FR-003). `SchedulerService._audit` already routed through `_record_event`, so each of a job occurrence's events was getting a freshly minted trace id — one run's STARTED and SUCCEEDED/FAILED events belonged to *different* traces, leaving the run unreconstructable. It now passes `TraceContext.for_job_run(run)`, so every event of an occurrence shares one trace, derived from the `job_runs` row id with no schema change. A structural test asserts the call site exists — an API nobody calls would satisfy the requirement on paper and leave scheduler events untraceable in fact.
- **Changed — six tests pinned to a moving target were rewritten, none weakened.** The full suite surfaced a defect family this codebase has now hit seven times: a guard that asserts a claim about *its own phase* but expresses it as a snapshot of the world ("the newest migration is `0044`", "the diff against `main` is empty"). Five Milestone 2 connector guards (2.1.4, 2.2.1–2.2.4) asserted the newest migration filename — each already carrying a *"Updated Phase 3.5 ... pointing at the new, correct head"* comment, the tell that they were being paid for rather than maintained, and each one careless bump away from asserting nothing. Phase 3.10's byte-identity guard diffed against `main` on the stated reasoning that *"3.10 is the last sub-phase of the milestone"* — true until the next milestone touched one of its files, at which point it reported a **4.1** change to `scheduler/service.py` as a 3.10 regression. Each now asserts the claim itself: *no migration belongs to Phase X* (stronger — it catches one inserted before the head too), and the diff guard pins **3.10's own commit range**, a fixed historical fact. Verified still-biting by planting a fake Phase 2.2.1 migration and watching the guard fail.
- **Changed** — Phase 3.10's `test_ac15_no_migration_was_added` asserted the repository's *newest* migration was `0044`, a moving target that says nothing about 3.10 (the same trap 3.7's byte-identity guard hit). It now asserts the claim itself — no migration belongs to Phase 3.10 — which stays true forever and additionally catches a 3.10 migration inserted *before* the head, which the original would have missed.
- **One route** (540 → **541**): `GET /runtime/executions/{execution_id}/trace`, reusing the **pre-existing** `runtime.telemetry.view` permission. No new permission, error code or audit event. The stronger `runtime.trace.content.view` is deferred to 4.8 — under METADATA_ONLY it would guard nothing, and a permission that guards nothing teaches operators it is safe to grant.
- **Explicitly out of scope**: the trace explorer/UI (4.2), governance engine (4.3), cost governance (4.4), behavioral signals (4.5), OTel export (4.6), SLOs/alerts (4.7), the full telemetry policy/retention/access system (4.8), the observability center (4.9), hardening (4.10).
- Schema **unchanged at 124 tables**; migration head `0044_worker_fleet_rolling` → **`0045_runtime_telemetry_context`**.
- 125 new backend tests (`tests/runtime/test_telemetry_foundation.py`). Backend **1,895** green (1,770 + 125), 0 failed, 1 deselected; frontend **327** green across 49 files, unchanged (backend-only phase). See [docs/observability/architecture.md](docs/observability/architecture.md), [semantic-conventions.md](docs/observability/semantic-conventions.md), [privacy.md](docs/observability/privacy.md) and [ADR-0008](docs/architecture/adr/0008-telemetry-as-a-derived-plane.md).

## [Phase 3.10] — AI Release Operations Center

**Milestone 3's final sub-phase. MILESTONE 3 IS COMPLETE (10/10).** An operator can now see every deployment across every environment, watch a canary advance stage by stage with live health, read a release gate's findings, promote through environments, roll back with one guarded click, watch the worker fleet and scheduler, and reconstruct any release from its timeline.

- **Added** `frontend/src/modules/operations/` — twelve operational views, a permission-gated nav, a two-tier confirmation dialog, and `useGuardedAction`: the single place every privileged action dispatches, which is what makes "dangerous actions are confirmation-gated" a property of the module rather than a habit twelve pages have to remember individually.
- **Read + trigger only, and enforced rather than promised.** `app/runtime/operations.py` contains no `add`/`commit`/`delete`/`flush` call and imports no mutating service — both asserted over the AST. All four new routes are GET. **No migration** — reading existing data is the whole job, and a new table would have meant this phase invented domain state. A git-diff test pins twelve deployment/worker/scheduler engine modules byte-identical to `main`.
- **Eight of the twelve views needed no new endpoint.** The four that did were reported before any code was written: an **overview** aggregation (a row needs the agent, version identity, environment, traffic weight, live rollout and health — five extra requests per deployment client-side, so forty deployments would be two hundred round trips to render one table); **release history** (previously exposed only *per deployment*, so reconstructing "what shipped last night" required knowing every deployment id in advance — which §13's reconstructability requirement cannot survive); the **detail composite** (§22 lists thirteen fields spread across eight endpoints); and the **rollout list**.
- **The rollout list was the sharpest gap.** Phase 3.5 shipped `GET /rollouts/{id}` and no way to *find* a rollout — so one was discoverable only if you had kept the id returned when you created it. A canary could be advancing through production traffic with no way to see it in the API at all.
- **Truthful state is this phase's real deliverable** (§10). The UI can only show what the read model tells it, so a read model that omitted a kill switch would *make* the UI present a killed release as deployable. Four facts are surfaced as first-class fields rather than left to be inferred: `kill_switch_active` (a boolean, not a lifecycle string the browser must parse), `gate_verdict` (BLOCK renders destructive and is never summarised away), `release_health.is_proving` (false for UNKNOWN/INSUFFICIENT_DATA — Phase 3.5's rule that the absence of evidence is never evidence of health, carried into the UI), and `servable` (Phase 3.4's own union-with-veto predicate, reported rather than re-derived, because two implementations of "is this actually serving?" would eventually disagree).
- **Blockers are shown all at once, most severe first**, above everything else on the detail view. An operator who clears a kill switch and finds a BLOCK verdict waiting has been told twice as much as one who clears it and has to look again.
- **Two confirmation tiers, deliberately unequal.** A single confirm for reversible operations (drain a worker, pause a rollout, disable a job); type-to-confirm for the irreversible or production-traffic-moving (promote to production, roll back, abort a rollout, change traffic weights, arm a scheduled job). Uniform friction is friction people learn to click through. A required reason is not decoration — it lands in the audit trail the server writes.
- **The dialog guards against the accidental, not the unauthorized.** The server decides whether an operator *may* roll back; the dialog exists so that one who may does not do it by reflex, in the wrong tab, at 3am. Treating it as a security control would be exactly the client-side-only gating §10 forbids.
- **Conflicts are explained, never retried.** An operator acting on stale state gets the server's conflict code. The UI never auto-retries — that would re-apply an intent formed against state that no longer exists — and never shows it as a generic failure, which reads as "the platform is broken" rather than "your colleague just paused this". Safety refusals (`KILL_SWITCH_ACTIVE`, `ROLLBACK_TARGET_UNAVAILABLE`, `ROLLING_COHORT_INVALID`, `ROLLOUT_STAGE_GATE_NOT_MET`) pass through **verbatim**, because the server's message names precisely which rule fired.
- **Five things the UI deliberately cannot do**, each closing a hole a convenience feature would have opened: **run a job** (Phase 3.8 built its API so no HTTP route dispatches — a "run now" button would execute a handler with no occurrence row and no lease, defeating exactly-once by never taking one); **register a worker** (phantom capacity, from which rolling derives *real* step weights); **choose an arbitrary rollback target** (3.7 fails closed rather than guessing, so the wizard displays the target and says so when there isn't one, instead of offering a picker that reintroduces the guess); **normalise traffic weights** (that would be making an allocation decision, and would hide that what was typed is not what shipped); **predict a stage gate** (a UI that predicted it would eventually predict it wrong, and a wrongly-disabled button is as damaging mid-incident as a wrongly-enabled one).
- **A path conflict was reported, not silently redesigned around.** The build prompt's §6 sketched `/api/v1/deployments/overview`; this repository's runtime API is uniformly `/api/v1/runtime/...` and `/deployments/{deployment_id}` would have swallowed "overview" as an id. The read models nest under `/runtime/operations/`; the rollout list sits at `/runtime/rollouts` beside `GET /rollouts/{id}`, because it is not an aggregation for a screen — it is the list endpoint 3.5's own resource was missing. Third consecutive phase to hit and report one (3.7's `/rollback`, 3.9's `/workers`, now this).
- **Explicitly out of scope**: any new deployment logic, any new authorization model, any new design system (the existing shadcn-style components and `PageHeader`/back-nav conventions are reused throughout).
- Route count 536 → **540** (+4, all GET); schema **unchanged at 124 tables**; migration head **unchanged at `0044_worker_fleet_rolling`**.
- 26 new backend tests (`tests/runtime/test_operations_center.py`), 30 new frontend tests (`src/modules/operations/tests/operations.test.tsx`). Backend **1,770** green (1,744 + 26), 0 failed, 1 deselected; frontend **327** green (297 + 30) across 49 files. See [docs/deployment/operations-center.md](docs/deployment/operations-center.md).

**MILESTONE 3 — Deployment, Release & Operations — IS COMPLETE (10/10).** The platform executes real governed AI (M1), integrates with the enterprise in both directions (M2), and deploys, releases, monitors, routes, rolls back and operates agent versions safely at production scale (M3).

## [Unreleased] — Phase 3.9 · Distributed Execution Worker Fleet & Rolling Deployment

**Milestone 3's riskiest sub-phase, and the one that resolves ruling #1.** Agent execution now runs on independently-operable worker processes, and ROLLING is finally implemented — over real worker cohorts rather than the vestigial counters Phase 3.6 refused to pretend with.

- **The claim commits before the execution runs.** `ExecutionWorkerService.claim_next` **committed** instead of flushing, and that single change is the phase. Until now the claim's `FOR UPDATE` was held for the *entire* attempt — every model call, every tool call, every byte of network I/O — released only by `run_once`'s `finally`. That was survivable with one inline caller and is not survivable with a fleet: it is the exact shape of the M1 deadlock, which `ToolLoopOrchestrator._execute_parallel` had been working around by hand with its own commit before spawning tool threads. A worker now holds **no** database lock across model or tool I/O.
- **Committing is safe because the lock had already done its one job.** It existed to stop a second worker claiming the same row, and the row is no longer `QUEUED` — the *committed* status change is what excludes peers now, permanently rather than for a transaction's duration.
- **One behavioural change, stated rather than buried.** A worker that dies mid-attempt used to have its claim rolled back straight back to `QUEUED`. Now the claim is committed, so the execution stays `RUNNING` until its lease expires and `reap_expired_locks` applies the retry policy. Recovery is slower by at most one lease and, in exchange, *observable* — there is a durable record of who held what and for how long.
- **Proven three ways, and the lock mode was corrected by a failing test.** Behaviourally (a second connection takes `FOR UPDATE NOWAIT` on the just-claimed row and succeeds), from *inside a running model call*, and structurally over the AST. The in-flight probe first asked for `FOR UPDATE NOWAIT` and **failed against correct code**: by mid-attempt the worker legitimately holds a *shared* lock on its own row, having inserted children of it. The right probe is `FOR KEY SHARE NOWAIT` — exactly the lock a tool thread's `INSERT INTO tool_calls` needs, and exactly the one the old exclusive claim blocked. **All five gate tests were verified to fail with the boundary reverted to `flush()`.**
- **No second lease table.** `execution_locks.execution_id` has been UNIQUE since migration 0023 and *is* the guarantee that no two workers successfully execute one claimed execution. A parallel table would have been two sources of truth for one fact, which is how a distributed system starts lying about who owns what. The build prompt allowed one; the M1 claim was extended instead.
- **Added** `app/workers/` — a sibling of `app/scheduler/`, for the same reason: a worker process is platform infrastructure that *drives* the runtime domain rather than a service inside it. `fleet.py` (registration, liveness, capacity, staleness), `worker.py` (claim loop, concurrency slots, drain, graceful shutdown), `runner.py` (`python -m app.workers.runner`), `routes.py` (observability and drain only).
- **M1 execution semantics are preserved exactly — the non-negotiable gate.** `worker.py` contains no provider call, tool loop, retry policy, cost arithmetic or authorization, asserted over the **AST's names-in-use** rather than source text (its docstring necessarily names the machinery it delegates to — the self-match trap this repository keeps rediscovering). The entire M1 execution suite passes unchanged.
- **The honest limit, stated as plainly as Phase 3.8 stated its own**: exactly-once *dispatch*, not exactly-once side effects. A worker that dies after a tool call committed but before its own result did will have that execution retried, and the tool will have been called twice. `ToolGatewayService` already knows which tools are idempotent; this phase does not weaken that answer and cannot promise more than the layer beneath it delivers.
- **Drain is a contract, not a mood.** `DRAINING` means *claim nothing new, finish what you hold*, which is why graceful shutdown needs no separate flag and the two can never disagree. An API drain writes the *request*; `ExecutionWorker.refresh()` turns it into behaviour within one poll. Reconciliation is one-directional — a worker picks up a drain but never promotes itself back to RUNNING, because undoing an operator's drain from inside the process being drained is never the right resolution of that disagreement.
- **Worker recovery and execution recovery are deliberately separate.** `reap_stale_workers` marks the *worker* dead and audits the affected tenants; M1's `reap_expired_locks` owns execution recovery with the real retry policy. Two components implementing that policy could disagree about whether an execution had attempts left, and that disagreement is how an execution gets run twice or dropped. Every worker sweeps on every tick rather than a leader doing it — a leader needs an election, and an election needs exactly the coordination this platform deliberately does not have.
- **ROLLING is implemented over real worker cohorts — ruling #1 is resolved.** A cohort is a declared partition of the registered fleet; its capacity is the summed declared concurrency of its live, heartbeating workers. Each step moves traffic to the fraction of **real** capacity converted: a fleet of 8 and 2 slots steps **80 → 100**, not an invented 25/50/75/100; four equal cohorts step 25/50/75/100 because the fleet *is* four equal quarters. **The shape of the rollout is dictated by the shape of the fleet** — the entire difference from a canary, and the entire reason it could not be written before.
- **The honest limit on rolling, stated up front.** **Workers are not version-pinned.** Phase 3.4 binds the version at *enqueue* and remains the sole allocator, so what rolls is the share of new work routed to the candidate, in units of real capacity. Pinning workers to versions would put version filtering in the hot claim path, make the worker second-guess the sole allocator, and starve any execution whose version had no converted worker. Instead the fleet **sizes** the rollout (a step can never describe capacity that does not exist) and **gates** it (a cohort that died mid-rollout fails the next step closed with `ROLLING_COHORT_INVALID`). Neither is expressible without a real fleet.
- **The vestigial replica columns remain untouched and unnamed.** Phase 3.1's AC-14 guard — which forbids even *naming* them anywhere in `app/runtime/deployment/`, prose included — still passes over the whole package.
- **No rolling state machine and no rolling table.** Phase 3.5 already built seven states, pause/resume/abort/rollback-request, per-stage health gates, optimistic concurrency, idempotency and audit; rolling needs exactly that and differs only in where stage weights come from. So a rolling deployment **is** a `RolloutPlan` with `kind='ROLLING'`, and every operation after the start is 3.5's, unmodified. Rollback integration is inherited rather than rebuilt. The whole schema difference is two columns.
- **The cohort gate was moved into the choke point.** It was first written on a rolling-specific wrapper — and that was wrong: a rolling plan *is* a `RolloutPlan`, so `POST /rollouts/{id}/advance` reaches it directly and the wrapper's check simply would not run. It now lives in `CanaryRolloutService._advance_one_stage`, the one place a stage is entered, and the wrapper was deleted.
- **A route collision was reported, not silently redesigned around.** `GET /api/v1/runtime/workers` and `POST .../workers/reap` have existed since M1. The build prompt's §6 sketched the fleet API at `/api/v1/workers`; this repository's runtime API is uniformly `/api/v1/runtime/...` and that prefix was taken. The fleet API mounts at **`/api/v1/runtime/fleet`** — the same discipline Phase 3.7 used when it nested under `/deployments/{id}/rollback/...` rather than seizing the Phase 5.0 endpoint.
- **No fleet route can run an execution, and none can create a registration.** If HTTP could dispatch, a caller could run agent work with no lease and no worker identity, defeating the unique constraint by never taking one. If HTTP could register, a caller could inject phantom capacity — and rolling derives *real step weights* from that capacity.
- **The PostgreSQL 16/17 mismatch is CLOSED** (a §26 production-readiness gate carried here from 3.8). `docker-compose.yml` declared `postgres:16-alpine` with database `agent_control_tower` while every backup comes from PostgreSQL 17.10 with `ai_agent_control_tower` — so the documented restore drill had no correct container target. Compose is now aligned to `postgres:17-alpine` + `ai_agent_control_tower`, asserted by tests against **both the file and the running server**. The one hazard alignment creates — `act_pgdata` is a major-version-specific data directory, so an existing checkout that ever started on 16 must drop that volume — is documented in `RECOVERY.md` and **deliberately not automated**: a script that silently dropped a database volume would be a worse failure than the mismatch it fixed.
- **Phase 3.7's byte-identity guard was narrowed and replaced, not weakened.** It compared six deployment modules against a *moving* `main`, so it asserted "no future phase ever touches these" — and two of the six had a future phase with an explicit mandate (3.6's own `RollingStrategy` docstring designated itself "the seam Phase 3.9 fills"). `canary.py` and `strategies.py` moved out of byte-equality, and a new test compares both modules' **declared surface** against `main`, asserting nothing was removed or renamed and the only additions are the two named rolling helpers. Four files byte-locked plus two structurally locked is a stronger total guarantee than six locked against a baseline that had to break.
- **Added** migration `0044_worker_fleet_rolling` (one table `worker_registrations`; two columns `rollout_plans.kind` and `.cohort_plan`; reversible, verified live), 6 routes, three error codes (`WORKER_NOT_FOUND`, `WORKER_INVALID_STATE`, `ROLLING_COHORT_INVALID`), three audit events and two permissions (`runtime.worker.view`/`.manage`).
- **`STRATEGY_ROLLING_DEFERRED` is now unreachable but deliberately kept.** It was returned to real API consumers with a documented 501 meaning; a consumer holding that string in a retry table should find it still explicable rather than vanished. A test asserts nothing constructs it any more.
- **Explicitly out of scope**: the Release Operations Center (3.10), version-pinned worker cohorts (see the honest limit above), and any change to the model→tool→model execution semantics or to execution authorization.
- Route count 530 → 536 (+6); schema 123 → 124 tables; migration head `0043_distributed_scheduler` → `0044_worker_fleet_rolling`.
- 60 new backend tests (`tests/runtime/test_worker_fleet_rolling.py`). Backend **1,744** green (1,684 + 60), 0 failed, 1 deselected; frontend untouched by this backend-only phase, still **297** green. See [docs/deployment/workers.md](docs/deployment/workers.md) and the rewritten [docs/deployment/strategies.md](docs/deployment/strategies.md).

**Milestone 3 now has 9 of 10 sub-phases done.** Next: 3.10, the Release Operations Center — the operator-facing assembly of everything this milestone built, and the last sub-phase.

## [Unreleased] — Phase 3.8 · Distributed Scheduler

**Milestone 3's seventh-built sub-phase, and the first half of its distributed-systems core.** Multiple scheduler instances now coordinate through PostgreSQL so a due job runs exactly once, a crashed instance's work is recovered, and business logic stays in handlers.

- **Added** `app/scheduler/` — a **sibling** of `app/runtime/` and `app/integration/`, not a child of either. The placement is forced rather than stylistic: this package registers a connector-health handler, and Milestone 2's mechanically-enforced runtime-never-knows rule fails the build if the word "connector" appears anywhere under `app/runtime/`. A scheduler that drives both domains cannot live inside one of them.
- **`FOR UPDATE SKIP LOCKED` leasing, no broker.** The same mechanism `ExecutionWorkerService.claim_next` already uses, and the same single-datastore commitment as ADR-0002. A test asserts no Celery/Redis/Kafka vocabulary appears.
- **The claim commits before the handler dispatches** — the phase's absolute rule, and the one this codebase has already paid to learn. `ToolLoopOrchestrator._execute_parallel` documents the original M1 deadlock: a claim held `FOR UPDATE` while worker threads on other connections needed `FOR KEY SHARE` on the same row, and **Postgres's deadlock detector could not see it** because the main connection looked idle. The scheduler has the identical shape, so the claim's lock is released before any handler runs. **Proven three ways**: from inside a handler (a different connection takes `FOR UPDATE NOWAIT` on the definition row and succeeds), behaviourally (instance A mid-handler does not block instance B claiming another job), and structurally.
- **Exactly-once per occurrence** via `uq_job_runs_occurrence` on `(job_definition_id, occurrence_key)`. The key derives from the instant a job was **due**, not when it was claimed — a claim-time key would differ per instance and defeat the guard. A retry and a stale-lease recovery both **reuse the same run row** rather than inserting another, which makes "no duplicate successful run" a schema property rather than something to detect afterwards. **The honest limit is stated rather than hidden**: this is exactly-once *dispatch*, not exactly-once side effects — a crash after a handler's work committed but before the run was marked SUCCEEDED will re-run it, which is why every registered handler is an idempotent reconciliation.
- **The §20 proof, both parts, on real separate connections** — never an in-process mutex or thread barrier, because the property is that two *processes* sharing only a database cannot both run one job. Part 1: two instances contend, `SKIP LOCKED` makes the loser skip rather than block, exactly one run row, handler ran once. Part 2: a crashed owner's expired lease is reclaimed by a peer, which reuses the same row, records `recovered_from`, and completes it.
- **Leases outlive their job's timeout by design.** If they were equal, a handler finishing at its deadline would race its own reclamation and two instances could briefly both believe they owned the run. The margin keeps the failures distinct: the timeout stops a *slow* handler, the lease detects a *dead* one. A heartbeat from a **dispossessed** owner is ignored — two owners is the one thing a lease prevents. An exhausted run is ABANDONED rather than reclaimed forever, so a job that kills its process every attempt cannot become an infinite loop across the fleet. **Retry and crash recovery share one mechanism** (a re-armed run's lease is put in the past), because two paths that could disagree about attempt counting would be two chances to get exactly-once wrong.
- **The scheduler dispatches; it does not decide.** Four registered handlers, each a thin adapter over the domain that already owned the logic: the connector-health sweep (2.1.3), canary auto-advance (3.5), rollback trigger evaluation (3.7), and expired-state cleanup. Both deployment methods were written to be driven on a timer — 3.5's own docstring says *"Interim until Phase 3.8: its scheduler will call exactly this method on a timer, with no change required here"* — and **no change was required there**. Tests assert no threshold, gate or weight vocabulary appears in either the scheduler or the handlers.
- **Dispatch is a fixed dictionary, not dynamic import.** An unrecognized `handler_key` raises `JOB_HANDLER_UNKNOWN`; no import path or dotted name ever comes from the database, so a row can never cause arbitrary code to execute. An AST test asserts `import_module`, `__import__`, `eval`, `exec` and `getattr` appear nowhere in dispatch.
- **The interim in-process scheduler is retired**, exactly as its own docstring specified: *"delete this module, delete its one call site in `app/main.py`'s lifespan, register the same iteration as a real job."* The sweep logic moved to `app/integration/sweep.py` **unchanged**; the `asyncio` task, `start`/`stop` pair and lifespan hook are gone. `CONNECTOR_HEALTH_SCHEDULER_ENABLED` survives with a real continuing meaning — it now decides whether the seeded definition is created *enabled*, default still false, because retiring an opt-in mechanism must not quietly turn it on. **The API process deliberately does not start a scheduler**: one inside the web process would scale with HTTP traffic rather than scheduling need, and every replica would silently become a competing instance.
- **Phase 2.1.3's `test_ac20` was updated, not deleted.** Its source assertions described a file that deliberately no longer exists; the behaviour it protected (a sweep visits active instances and records a `SCHEDULED` check) is asserted verbatim, and it is now *stricter* — it additionally asserts the retirement actually happened and the sweep is reachable as a registered handler.
- **The scheduler principal** is one non-human `users` row per organization, created on demand, because 3.5's and 3.7's bounded operations require an `actor: User`. It **cannot authenticate** (unusable password hash, `is_active=false`), asserted by a test that attempts login. Reusing a real user was rejected because it would make the audit trail claim a person triggered every scheduled rollback — undoing Phase 3.7's deliberate `initiated_by = NULL`.
- **Added** migration `0043_distributed_scheduler` (two tables: `job_definitions`, `job_runs`; reversible, verified live), 6 routes, two error codes, two audit events (`SCHEDULED_JOB_STARTED`/`_FAILED`) and two permissions (`runtime.scheduler.view`/`.manage`). Lease and attempt are **columns on `job_runs`**, not tables of their own — a lease has no life outside its run, and a retry reuses the row rather than accumulating attempt history.
- **CRON is deliberately not implemented.** The prompt offered it "if justified" and it is not: every registered job is an interval sweep, and cron would need either a new dependency or a hand-rolled expression parser. `schedule_kind` is a checked constraint a later phase widens additively — declaring a value the platform cannot honour would be the pretence Phase 3.6 refused for ROLLING.
- **Explicitly out of scope**: the execution worker fleet (3.9, which reuses this lease discipline), the frontend (3.10), and any new deployment logic — the scheduler drives 3.5's and 3.7's existing bounded operations.
- Route count 524 → 530 (+6); schema 121 → 123 tables; migration head `0042_automated_rollback` → `0043_distributed_scheduler`.
- 51 new backend tests (`tests/runtime/test_distributed_scheduler.py`). Backend **1,684** green (1,633 + 51), 0 failed, 1 deselected; frontend untouched by this backend-only phase, still **297** green. See [docs/deployment/scheduler.md](docs/deployment/scheduler.md).

**Milestone 3 now has 8 of 10 sub-phases done.** Next: 3.9 (the distributed worker fleet — the milestone's riskiest phase, reusing this phase's lease discipline and the same commit-before-dispatch lesson).

## [Unreleased] — Phase 3.7 · Automated Rollback & Release Safety

**Milestone 3's seventh sub-phase, and the safety capstone of the deployment engines.** Phases 3.5 and 3.6 gave the platform rollback *operations*; this phase gives it a **policy** — the governed, per-tenant rules that decide when a rollback happens without a human watching a dashboard at 3am.

- **A premise correction, stated rather than papered over.** The build prompt described `rollback_target_id` as "a pointer nothing reads (REPO_STATE §9.12)". That was true when it was recorded and is no longer: **Phase 3.6 already reads it** to perform a blue-green rollback. What was genuinely missing was designating it as part of a rollout and honouring it from any path other than blue-green — which is what this phase adds.
- **Three rollback implementations existed, with three different notions of "the target"**: Phase 5.0's `DeploymentService.rollback` (a caller-supplied version, and a *redeploy* rather than a traffic shift), 3.5's `request_rollback` (`plan.stable_version_id`), and 3.6's `blue_green_rollback` (`rollback_target_id`). This phase adds one authoritative answer and one operation every trigger funnels through.
- **Added** `app/runtime/deployment/rollback.py` — `RollbackService` (the unified operation), `RollbackPolicyService` (scope resolution, most-specific-wins), and `evaluate_thresholds` (the trigger arithmetic as a pure, database-free function). It holds **no reference to the traffic-weight tables**, so bypassing 3.4 is structurally impossible — asserted against the parsed AST, the same proof 3.5 and 3.6 use.
- **`rollback_target_id` is now authoritative, and fails closed.** No designated target, a target belonging to another agent, a non-published target, or a target that is the version already deployed all raise `ROLLBACK_TARGET_UNAVAILABLE` and move nothing. When a rollout is in scope its `stable_version_id` must *agree* with the field; a disagreement fails closed rather than picking a winner, because two sources naming different versions means the platform does not know what the last-known-good is, and **rolling back to a guess is worse than refusing — a wrong rollback looks like a successful one.** The field is written only through `VersionLineageService.set_rollback_target`, so making it authoritative did not break its existing lineage writers.
- **One rollback, four triggers** (`MANUAL`/`REQUESTED`/`AUTOMATIC`/`FORCED`) — data, not four code paths. When a rollout is in scope the traffic move is **delegated to 3.5's own `request_rollback`** rather than reimplemented; outside one it goes directly through 3.4's `set_weights`. `initiated_by` is deliberately null for an automatic rollback: writing a system user id there would make the audit trail claim a person acted.
- **Kill-switch dominance, and the distinction that matters (§12).** The rule is that *automation* is subordinate to a kill switch, **not that rollback is**. An automatic rollback on a killed agent does not run — automation that "rolled back to a healthy version and reactivated it" would be automation quietly undoing a human's kill. A **manual** rollback still runs, matching 3.6's own reasoning: a kill switch must never trap an operator on the version they are trying to leave. Nothing in the module writes `Agent.lifecycle_status` or a deployment's `status`, asserted structurally as `(receiver, attribute)` pairs.
- **The §12 check runs *before* health, and the ordering is load-bearing.** The health engine independently returns `UNKNOWN` for a vetoed candidate, so checking afterwards surfaced a kill switch as *"health verdict UNKNOWN is not evidence of a regression"* — safe, but the wrong explanation. An operator needs to see that automation stood down because it was **told to**, not because it could not form a judgement. This was found by a failing test, not by review.
- **INSUFFICIENT_DATA never triggers** (mirroring 3.5's discipline): below `min_samples` no trigger fires no matter how bad the few samples look — three failures out of three is a 100% error rate and still not evidence. `UNKNOWN` is treated identically: the absence of a judgement, not a bad one.
- **Trigger thresholds are deliberately wider than 3.5's stage gates**, and a test asserts the relationship rather than letting it drift. A canary stage refusing to advance is cheap and reversible; an automatic rollback moves production traffic with no human in the loop. Cost is compared **per execution**, not in total, so a candidate serving more traffic does not look expensive merely for being busier; a zero or missing baseline is skipped rather than treated as infinitely good.
- **Automation is opt-in**: absent an enabled policy, nothing ever fires, so a tenant that configures nothing keeps exactly the manual behaviour 3.5 and 3.6 gave them. `NOTIFY_ONLY` mode detects and records a regression while leaving traffic untouched, for organizations that want to watch the automation agree with their engineers before letting it act.
- **Anti-flap, two independent guards**: a cooldown (default 900s) from the most recent automatic rollback for an (agent, environment); and **only a version actually on trial is a candidate** — a version holding zero traffic is never re-judged, which is what stops the restored last-known-good being rolled back by the same policy on the next tick. Deduplication is separate and enforced by the database: a partial unique index on `dedup_key` keyed on (deployment, deployed version), the same primitive 3.4 used for `uq_traffic_allocations_current`. Manual and forced rollbacks sit outside it — a human may roll back twice, and a uniqueness index refusing them would be absurd.
- **Evidence preservation** (`rollback_events.evidence_ref`): the candidate's metrics, baseline, window, verdict and crossed thresholds, captured at the moment of rollback. A rolled-back candidate is precisely what an engineer needs to diagnose, and **the rollback must not be the act that destroys the reason for it.**
- **Recovery** (durable intent, ephemeral evaluation): the `rollback_events` row is committed as `IN_PROGRESS` **before** any traffic moves and marked `COMPLETED` only after the allocation commits, so a crash leaves a readable record of an intent that was formed but not finished. `resume_incomplete` runs at the start of every evaluation. Re-applying is harmless because 3.4's allocation declares a desired end state rather than a delta — **there is no half-applied state to compound.** A test asserts the ordering structurally, since writing the row *after* the move would lose the record of an action that had already happened.
- **Override / forced rollback (§11)**: a new elevated `runtime.deployment.force_rollback` permission, a justification required by the schema itself, audited at `CRITICAL`. Its power is narrow and specific — it may **name its target**, bypassing the designated-target requirement, which is exactly the 3am case an ordinary rollback fails closed on. It does not override the kill switch. Stated honestly: `SYSTEM_ROLE_PERMISSIONS` grants ADMIN/SUPER_ADMIN the whole catalog, so the new code does not restrict them; what it buys is that the separation becomes *expressible* for custom roles, which is impossible if the override reuses the ordinary permission.
- **Routes nested under `/deployments/{id}/rollback/...`** rather than claiming `POST .../rollback`, which has existed since Phase 5.0 and performs a redeploy. Taking that path over would have silently changed a Milestone 1 API contract and required rewriting passing tests — the identical collision Phase 3.1 resolved by nesting under `/lifecycle/...`. `/evaluate` uses `.deploy` rather than `.rollback`: an operator trusted to roll back is not thereby trusted to arm the policy engine.
- **Added** migration `0042_automated_rollback` (two tables: `rollback_trigger_policies`, `rollback_events`; reversible, verified live), 6 routes, four error codes (`ROLLBACK_TARGET_UNAVAILABLE` 409, `ROLLBACK_BLOCKED_BY_KILL_SWITCH` 423, `ROLLBACK_FORCE_UNAUTHORIZED` 403, `ROLLBACK_CONFLICT` 409) and three audit events (`ROLLBACK_TRIGGER_FIRED`, `ROLLBACK_FORCED`, `ROLLBACK_POLICY_UPDATED`) — the two moments every rollback shares reuse 3.5's `DEPLOYMENT_ROLLBACK_STARTED` and Phase 5.0's `RUNTIME_ROLLBACK_COMPLETED`, so a reader finds *all* rollbacks under one pair of names.
- **A pre-existing test caught a real collision again** (the fourth instance of this class in the repository): 3.5's `test_ac13_the_rollout_state_machine_has_one_transition_authority` greps every file mentioning `RolloutPlan` for `.state =`, and this phase's `RollbackEvent.state` false-matched. Renamed the column to `status` — which also matches the platform's own naming everywhere else — rather than suppressing the guard with a `noqa`. This phase's own AC-09 test then had to become precise about *receivers* rather than attribute names, since `event.status` is a legitimate write and `deployment.status` is not.
- **Interim, and marked as such**: `POST .../rollback/evaluate` is bounded — one call, one deployment, at most one rollback. Not a scheduler, does not loop. Phase 3.8 will call this exact method on a timer with no change here.
- **Explicitly out of scope**: the distributed scheduler (3.8), workers/frontend (3.9/3.10), any new health computation (3.5 owns it — this phase consumes its verdicts), new strategies or ROLLING (3.6/3.9), and any change to the resolver, gate, allocation, canary or strategies — a test asserts those six files are byte-identical to `main`.
- Route count 518 → 524 (+6); schema 119 → 121 tables; migration head `0041_canary_rollout` → `0042_automated_rollback`.
- 58 new backend tests (`tests/runtime/test_automated_rollback.py`), including **the §19 proof made automatic**: a candidate on trial at 50% starts failing, and the platform rolls it back on its own — stable to 100%, candidate to 0%, evidence preserved, `ROLLBACK_TRIGGER_FIRED`/`DEPLOYMENT_ROLLBACK_STARTED`/`RUNTIME_ROLLBACK_COMPLETED` all audited, with no human in the loop after the policy was configured. Backend **1,633** green (1,575 + 58), 0 failed, 1 deselected; frontend untouched by this backend-only phase, still **297** green. See [docs/deployment/rollback.md](docs/deployment/rollback.md).

**Milestone 3 now has 7 of 10 sub-phases done.** Next: 3.8 (the distributed scheduler, which drives this phase's bounded evaluation on a real timer).

## [Unreleased] — Phase 3.6 · Blue-Green & Recreate Strategy Execution

**Milestone 3's sixth sub-phase.** Makes `agent_deployments.deployment_strategy` mean something: until now it was pure data — set on create, copied on promotion, exposed in the API, and **never dispatched on**. This is its first consumer.

- **Strategies are weight patterns, not separate machinery.** Canary (3.5), RECREATE and BLUE_GREEN are all weight transitions over Phase 3.4's allocation; they differ in the pattern and in what is preserved. RECREATE: 0→100 in one cutover, previous superseded. BLUE_GREEN: 0 (warm) → 100 in one atomic switch, **old version preserved at 0%** as a rollback target. So this phase builds two new *patterns* and reuses the *mechanism* wholesale.
- **Added** `app/runtime/deployment/strategies.py` — the handler abstraction (`DeploymentStrategyHandler`), `RecreateStrategy`, `BlueGreenStrategy`, `RollingStrategy` (deferred), `CanaryStrategyPointer`, and `DeploymentStrategyService`. It holds **no reference to `DeploymentTrafficWeight`/`DeploymentTrafficAllocation`**, so bypassing 3.4 is structurally impossible rather than discouraged — asserted against the parsed AST.
- **Dispatch is on the column, not the request.** One `POST .../strategy/execute` endpoint reads `deployment_strategy`. The build prompt offered per-strategy paths instead; a `/strategy/recreate` path would let a caller run a recreate on a deployment declared BLUE_GREEN, making the column decorative again. The strategy is deliberately not read from the request body either.
- **RECREATE**: veto check → release gate (fail closed) → both weights move in one `set_weights` call → previous superseded through 3.1's lifecycle authority (`SUPERSEDED` is in 3.4's non-serving set, which is what "stops receiving new work" means concretely). **The supersede happens *after* traffic moves** — doing it first would make the old deployment non-servable, and 3.4 rejects weight on a version with no servable deployment, so the cutover would fail on its own precondition.
- **BLUE_GREEN**: prepare warms GREEN at 0% while BLUE serves 100% (a test drives real executions and asserts every one reaches BLUE); the switch moves both weights in a **single allocation revision**, so no committed state has both serving; rollback returns traffic to BLUE. **The gate is re-evaluated at the switch, not only at prepare** — a deployment can pass validation and then have its agent killed or its version revoked before anyone presses the button, and there is a test for exactly that sequence.
- **Blue preservation needed no new table, and no migration** (head unchanged at `0041`): after the switch BLUE stays lifecycle-ACTIVE, holds 0% (so it serves nothing — preserved is *not* split-serving, proven by driving real executions), and is recorded as GREEN's rollback target on the existing `AgentVersion.rollback_target_id` via `VersionLineageService.set_rollback_target` rather than a raw column write. That field was previously, in REPO_STATE's own words, "a settable pointer only; nothing reads it to perform a rollback" — blue-green rollback is the first code that acts on it. "Prepared" is likewise inferable from 3.4's existing rows (GREEN carries a zero-weight entry exactly when warmed), so no state was added for it either.
- **Rollback deliberately skips both the veto check and the gate re-run** — rolling back reduces exposure, and a kill switch must never trap an operator on the version they are trying to leave; demanding BLUE re-pass a gate before it can be returned to would make rollback fail exactly when it is most needed.
- **ROLLING is deferred to Phase 3.9, honestly** (ruling #1, SRS §3.6): declared, dispatched, and raising `STRATEGY_ROLLING_DEFERRED` (**501**, since it is a recognized value the platform genuinely does not implement — not a client mistake, not a state conflict). **Not a stub** — no partial implementation, no `NotImplemented` placeholder. Rolling means replacing running instances a few at a time and this platform has no instance substrate: the two replica-count columns are vestigial (the legacy deploy/retire set them to constants; **nothing reads them for any decision** — verified this phase). A handler decrementing them would report progress while nothing rolled, which is worse than an honest error because it would look like a working feature.
- **The no-fake-rolling constraint is mechanically enforced by a *pre-existing* test**: Phase 3.1's AC-14 asserts those column names appear nowhere in `app/runtime/deployment/` — prose included. `strategies.py` therefore refers to them only indirectly, and this phase's own AC-09 test asserts the same bare-name rule rather than relaxing it to "no attribute access".
- **Kill-switch dominance (§12)**: no strategy activates a vetoed version; the sharpest tested case is GREEN prepared and ready, agent then killed, switch refused, GREEN still at 0%. Reuses the pre-existing generic `KILL_SWITCH_ACTIVE` (423) rather than 3.5's `ROLLOUT_HALTED_BY_KILL_SWITCH` — an operator running a blue-green switch has no rollout, and no new code is minted for a condition the platform already names.
- **Added** 3 routes and four error codes (`STRATEGY_ROLLING_DEFERRED` 501, `STRATEGY_GATE_BLOCKED` 409, `BLUE_GREEN_NOT_PREPARED` 409, `STRATEGY_CONFLICT` 409) plus two audit events (`DEPLOYMENT_STARTED`, `DEPLOYMENT_SUCCEEDED`); the blue-green rollback reuses 3.5's `DEPLOYMENT_ROLLBACK_STARTED` and Phase 5.0's `RUNTIME_ROLLBACK_COMPLETED` rather than minting a third and fourth name for the same two moments. `STRATEGY_GATE_BLOCKED` is distinct from 3.1's `DEPLOYMENT_PREFLIGHT_BLOCKED`: that stops a deployment *reaching* ACTIVE, this stops an active one *taking over traffic*.
- **No migration.** §5 asked to check whether existing lineage already expressed blue preservation before adding anything; it did.
- **Explicitly out of scope**: ROLLING (3.9), automatic-rollback trigger policy (3.7 — this phase provides the operation and preserves the target), scheduler (3.8), workers/frontend (3.9/3.10), and any change to the resolver, execution gate, allocation mechanics or the canary engine — a test asserts those five files are byte-identical to `main`.
- Route count 515 → 518 (+3); schema unchanged at 119 tables; migration head unchanged at `0041_canary_rollout`.
- 34 new backend tests (`tests/runtime/test_strategies.py`): dispatch completeness against the schema's own strategy pattern, column-not-request dispatch, RECREATE cutover + supersede + allocation-atomicity across every revision, gate-BLOCK fail-closed, blue-green prepare/switch/preserve/rollback each individually and as one end-to-end narrative, real executions proving no split-serving before and after the switch, gate re-evaluation at the switch, the AST proof that traffic can only move through 3.4, the 3.4/3.5-unmodified proof, ROLLING deferral (error, not stub; no replica columns; nothing partially executed), four kill-switch tests, a deterministic real-Postgres race, and authorization/tenant/idempotency coverage. Backend **1,575** green (1,541 + 34), 0 failed, 1 deselected; frontend untouched by this backend-only phase, still **297** green. See [docs/deployment/strategies.md](docs/deployment/strategies.md).

**Milestone 3 now has 6 of 10 sub-phases done.** Next: 3.7 (automatic-rollback trigger policy, on top of the rollback operations 3.5 and 3.6 provide).

## [Unreleased] — Fix · Temporary passwords could violate the platform's own password policy

**A standalone defect fix, not a milestone phase.** Surfaced (not caused) by Phase 3.5's full-suite run and fixed in isolation.

- **The bug**: `generate_temporary_password()` built a candidate from the four required character classes and returned it **unchecked**, on the stated reasoning that sequences and repeats were "astronomically unlikely" from CSPRNG picks. That reasoning was wrong by orders of magnitude — a 16-character draw contains 13 overlapping 4-character windows, and the policy forbids runs along six known sequences in *both* directions, so values like `9876`, `abcd` and `qwer` are not rare. Measured against the real generator: **9 violations in 20,000 draws (~1 in 2,200)**.
- **Why it mattered**: a temporary password is handed to a person to log in with, and the login/set path validates it under the *same* policy. So roughly one admin password reset in two thousand issued a credential the platform itself would then refuse — an intermittent, near-impossible-to-reproduce support failure, and an internal contradiction (the system generating a value its own validator rejects). It also made `test_generated_temporary_password_satisfies_policy` fail ~2% of runs, previously recorded as a "transient flake" in REPO_STATE §9 item 15; it was never a flake.
- **The fix**: generate → validate → re-draw on failure, with a 100-attempt safety cap that **raises rather than ever returning a non-compliant password**. Validation goes through `PasswordPolicyService.validate` — the identical entry point `CredentialService._apply_new_password` uses at set time — so the rules are never duplicated and a future policy change automatically binds generation. `PasswordResetService` now passes `user=`, covering the context-dependent identity-substring rule (a password containing the user's name or email local-part) that a context-free check would have missed.
- **Re-draw, not repair**: editing the offending characters in place would be faster but leaks structure — an attacker knowing the repair rule learns which substrings can never appear at which positions. A fresh draw preserves the full entropy of the construction.
- **The policy itself is unchanged** — it was correct; the generator was wrong. No change to login/set-time validation and no other credential generator touched (verified by an empty diff on `security/passwords.py` and `credentials/policy_service.py`).
- **Test**: the flaky 50-draw test is replaced by a 5,000-draw **zero-violation** assertion, plus new tests for the safety cap (forced via a reject-all policy), shared-validator reuse (verified by call *and* by injecting a brand-new rule the generator honours with no change of its own), the two previously-violable content rules asserted directly against the policy's own detectors, identity-context compliance, and the preserved strength properties (length 16, all four character classes, confined alphabet, no collisions across 1,000 draws — none of which had any test before).
- **Verified**: 0 violations in 20,000 draws (was 9); 15 consecutive runs of the test file clean. Backend **1,535 → 1,541** passed (+6 net: 7 added, 1 replaced), 0 failed, 1 deselected preserved; frontend untouched, **297** green.

## [Unreleased] — Phase 3.5 · Canary Deployment Engine

**Milestone 3's fifth sub-phase.** Builds the engine that drives Phase 3.4's traffic allocation progressively and automatically — real canary delivery. A candidate version is promoted stage by stage (5% → 25% → 50% → 100%), and a stage only clears when **all three** of its gates are satisfied: minimum duration elapsed, minimum sample count met, and an AI-aware health requirement satisfied. Introduces `deployment_health_evaluations` (ruling #3) and a seven-state rollout machine.

- **Added** `app/runtime/deployment/rollout.py` — the pure transition graph (PENDING/IN_PROGRESS/PAUSED/SUCCEEDED/ABORTED/ROLLBACK_REQUESTED/FAILED) and the pure stage-gate logic. No I/O, the structural twin of 3.1's `lifecycle.py`. `RolloutPlan.state` is written in exactly one place (mechanically checked, mirroring 3.1's own discipline).
- **Added** `app/runtime/deployment/health.py` — the AI-aware release-health engine, and `app/runtime/deployment/canary.py` — `CanaryRolloutService`, the orchestration.
- **Traffic only ever moves through 3.4**: a stage advance calls `TrafficAllocationService.set_weights` (atomic, revisioned, eligibility-checked, audited), never a direct `deployment_traffic_weights` write. Structural, not aspirational — `canary.py` contains no reference to `DeploymentTrafficWeight`/`DeploymentTrafficAllocation` at all, asserted against the parsed AST. Every 3.4 guarantee is inherited rather than reimplemented.
- **INSUFFICIENT_DATA is first-class** (the phase's core safety property): below a stage's minimum sample count the verdict is INSUFFICIENT_DATA regardless of how clean the few samples look, and it satisfies **no** health requirement at any level. Two successful calls out of two is not "healthy" — nothing bad *observed* is not nothing bad *happening*. Evaluation order is deliberate: veto first, sample sufficiency second, thresholds and baseline only then.
- **Ruling #3 — a new health table, and why**: `deployment_health` is a *liveness heartbeat* (a worker reported in), written from an external signal. `deployment_health_evaluations` is a *release judgement* computed by aggregating `agent_executions` over a window. A model version can be perfectly alive while refusing every third request. The old table is untouched in both directions; a test asserts its row count is unchanged across a full rollout.
- **The signals used** were confirmed by reading `AgentExecution`, not assumed from the SRS: success/failure/timeout (`status`), policy denials (`status` DENIED/BLOCKED), latency (`duration_ms`, mean and p95), cost (`cost_amount`), tokens (`total_tokens`), and provider/tool failure class (`error_code`). Only *terminal* executions count — counting a still-running one as "not a failure" would make a stalled canary look healthier the more stuck it got. **Gap reported, not built around**: per-external-system failure counts are not available on an execution row (the same missing dependency link 3.2 and 3.3 already reported).
- **Baseline comparison (§7)** with two findings: a *regression vs stable* (candidate worse than the version it would replace, even when absolutely within thresholds) and *likely provider-wide degradation* (both elevated together). The provider-wide finding **softens blame but never restores HEALTHY** — a shared incident is exactly when no version should earn more traffic, so the verdict is floored at DEGRADED and the incident is named rather than silently excusing the numbers. The baseline margin is deliberately **narrower** than the degraded threshold, or the rule could never fire on its own.
- **Kill-switch dominance (§12) enforced by two independent mechanisms**: `_assert_not_vetoed` runs before every operation that could give the candidate *more* traffic (start/advance/resume/promote/auto-advance), reading the same fields 3.4's resolver reads; and the health engine independently returns UNKNOWN — never HEALTHY — for a vetoed candidate. De-escalating operations (pause/abort/request-rollback) deliberately skip the check, because a kill switch must never trap a rollout in a state an operator cannot back out of. On the automated path a veto is *reported*, not raised, so a future scheduler sweeping many rollouts is not aborted by one killed agent — it still does not advance.
- **Added** `health_requirement: "NONE"` as an explicit per-stage waiver. Health with zero executions is correctly INSUFFICIENT_DATA, so an idle agent's stage would otherwise be stuck forever with no way to say "advance anyway"; an auditable declaration is far safer than quietly treating "no data" as "fine". **`NONE` does not waive `UNKNOWN`** — that distinction is load-bearing, or `NONE` would become a way to opt out of the kill switch.
- **Interim auto-advance** (`POST .../evaluate`): bounded and idempotent, advancing by **at most one stage per call** even when several stages' gates are simultaneously clear — a call that walked 5% → 100% would defeat the purpose of staging. **Not a scheduler**; Phase 3.8 will call this exact method on a timer with no change here, the same relationship `app/integration/scheduler.py` already documents. Manual advance always available.
- **The 3.5/3.7 seam, stated**: this phase refuses to advance on a failed health gate and can *request* a rollback (traffic to stable, terminal outcome). Phase 3.7 adds the configurable per-tenant automatic *trigger policy* deciding **when** to call it — it does not reimplement what it does.
- **Added** three tables (`rollout_plans`, `rollout_stages`, `deployment_health_evaluations`) and **two genuinely necessary indexes on `agent_executions`**: `(agent_version_id, created_at)` and `(deployment_id, created_at)`. Before these the table had `agent_version_id` alone, nothing touching `created_at`, and **no index on `deployment_id` at all** — so a canary evaluating health every few seconds would have scanned a growing share of the platform's entire execution history. Verified by `EXPLAIN` to serve the aggregation as an Index Only Scan. Migration `0041_canary_rollout`, reversible, no data backfill.
- **Added** 10 routes; reuses `runtime.deployment.view`/`.deploy`, plus the pre-existing `runtime.deployment.rollback` for `request-rollback` (an organization may well want to grant "can roll back" separately from "can push a canary forward"). No production-specific permission introduced — 3.2's environment policy is where this codebase already expresses that.
- **Added** five error codes and six audit events; pause/resume deliberately reuse the pre-existing `RUNTIME_DEPLOYMENT_PAUSED`/`_RESUMED` rather than minting a second pair meaning the same thing.
- **Three real bugs found and fixed during the build**, each a variant of a lesson this repo has already recorded: (1) a candidate with *no* servable deployment was treated as "no veto to apply" and reported HEALTHY — a paused candidate could look promotable; (2) the idempotency fingerprint included mutable server state (`stage_index`), so every retry looked like a different request and deduplication never fired; (3) `StaleDataError` surfaces at the *first flush* (which the audit insert triggers), not at the commit — guarding only the commit let a raw 500 escape under a real race, exactly as 3.1 and 3.4 both documented.
- **Explicitly out of scope, per the build prompt**: automatic-rollback trigger policy (3.7), blue-green/recreate/rolling strategies (3.6/3.9), a real distributed scheduler (3.8), workers/frontend (3.9/3.10), and any change to the resolver, execution gate, or allocation mechanics (3.4 owns them — a test asserts those two files are byte-identical to `main`).
- **Five pre-existing tests updated, not weakened**: the Milestone 2 connector tests that hardcode the migration head, bumped `0040` → `0041` — the same bookkeeping 3.2/3.3/3.4 did.
- Route count 505 → 515 (+10); live schema 116 → 119 tables (+3).
- 57 new backend tests (`tests/runtime/test_canary_rollout.py`) grouped by this phase's acceptance criteria: plan/stage creation and validation, the advance-drives-3.4-allocation proof (a new revision per advance, plus the AST proof it *cannot* do otherwise), each gate independently and all-reasons-together, health computed from real execution rows, a parametrized sweep proving every one of the five health states reachable and correct, the thin-but-perfect sample refusing to advance, baseline regression and provider-wide findings, evaluation persistence with the old table untouched, four kill-switch tests (halt, no auto-promote, promote refused, abort still works), abort/rollback/promote, auto-advance boundedness/idempotency/manual-stage handling, a full 5%→100% canary ending in a real routed execution, a failing canary caught by health and rolled back, two real-Postgres races, `EXPLAIN`-verified index usage, and authorization/tenant/idempotency coverage. Backend **1,535** green (1,478 + 57), 0 failed, 1 deselected; frontend untouched by this backend-only phase, still **297** green. See [docs/deployment/canary.md](docs/deployment/canary.md).

**Milestone 3 now has 5 of 10 sub-phases done.** Next: 3.6 (blue-green and recreate deployment strategies).

## [Unreleased] — Phase 3.4 · Traffic Allocation, Version Resolver & Execution Gate

**Milestone 3's core sub-phase, and the one deliberate change to the Milestone 1 execution path.** An agent's traffic in an environment can now be split by weight across several simultaneously-serving signed versions; a resolver selects one immutable version per request (sticky where asked) and hands it to the *unchanged* M1 authorization + execution path. Three things landed together because they are one mechanism: allocation without a resolver is a table nobody reads, a resolver without allocation has nothing to resolve, and the resolver *is* where the execution gate lives.

- **⚠️ The M1 execution-path change (one place, `ExecutionRequestService._request_execution`)**: what was a direct 1:1 read of the active deployment's own `agent_version_id` is now a single `VersionResolver(db).resolve(...)` call. **Everything after that line is untouched** — the `authorize(deployment)` call, runtime-policy evaluation, the approval reroute, the queue and the worker all run exactly as before.
- **Ruling #4 was already half-enforced here, and this is reported rather than papered over**: `_request_execution` has rejected deployment-less execution since Milestone 1 (`DEPLOYMENT_NOT_FOUND` / `DEPLOYMENT_NOT_ACTIVE`). **There were therefore no deployment-less-execution tests to migrate** — the build prompt's premise did not hold against this repository. What 3.4 adds is weighted resolution plus one genuinely new fail-closed mode.
- **The gate semantics — union with veto** (the phase's central design decision, confirmed before coding): this repo has two deployment state fields written by disjoint code. `status` is written by the legacy service **and by `KillSwitchService`**; `lifecycle_state` only by `DeploymentLifecycleService` (3.1 pause, 3.2 supersede). Gating on `lifecycle_state` alone would have **disarmed the kill switch** at org/project/platform scope and stranded every legacy-deployed agent; gating on `status` alone would leave 3.1-paused deployments serving and 3.2-promoted ones permanently dead. So a deployment serves iff *either* machine says ACTIVE and *neither* vetoes. **Neither machine was rewritten** — the resolver honours both, which is why this phase touches one place rather than six. Full truth table in `docs/deployment/traffic-and-resolution.md`, pinned by a test.
- **Added** `app/runtime/deployment/traffic.py` — the servability predicate (`servable_clause()` / `is_servable()`, defined once, in SQL and Python) and `TrafficAllocationService` (the hardened weight-setting operation: authorized, tenant + eligibility checked, atomic, revisioned, idempotent, audited).
- **Added** `app/runtime/deployment/resolver.py` — `VersionResolver`, at most **three indexed queries** per execution. It **selects a version and returns a plain value; it never dispatches**. No authorization module, policy engine or worker is imported, and no lock is taken (§9's M1 deadlock lesson — deliberately lock-free so it cannot deadlock the execution path).
- **Added** `deployment_traffic_allocations` + `deployment_traffic_weights`. Revisions are append-only (a change writes a new revision and clears the previous `is_current`), so the table *is* the audit lineage. Migration `0040_traffic_allocation`, reversible.
- **Sum-to-100 is a transaction-level guarantee, not a table constraint** — a CHECK cannot span sibling rows and a deferred trigger would create a second place that understands the rule; validation happens before any write and the whole set commits once, so a partial or non-100 state is never *observable*.
- **Concurrency is an index, not a lock**: the partial unique index `uq_traffic_allocations_current` on `(agent_id, environment_id) WHERE is_current` arbitrates racing writers; the loser's `IntegrityError` becomes `TRAFFIC_ALLOCATION_CONFLICT`. The previous row's `is_current` clear is flushed *before* the new INSERT, explicitly rather than relying on SQLAlchemy unit-of-work ordering — otherwise a caller's own legitimate write can hit the index mid-flush.
- **The §15 step-2 backfill** (3.1 seeded lifecycle; 3.4 backfills allocation): every servable deployment with a governed `environment_id` gets a current 100% allocation to the version it was already serving, newest-by-`deployed_at` winning per `(agent, environment)` — the same deployment the pre-3.4 path would have chosen, so **no agent's behaviour changes at upgrade**. The migration writes the servability predicate out literally in SQL rather than importing application code that keeps evolving after the revision is pinned.
- **The implicit 100% rule**: a servable deployment with no allocation row resolves to its own version. This is what keeps deployments *created after* the migration working without an operator setting weights first; the gate is not weakened, since a servable deployment is still required.
- **Sticky routing is opt-in** — explicit `routing_key`, else `correlation_id`, else a random draw. Deliberately *not* defaulted to the principal's id: that would silently make every request from one user sticky and quietly defeat a percentage rollout for a small user base.
- **Added** 3 routes under `/agents/{agent_id}/environments/{environment_id}/traffic`(`/history`) — mounted on agent+environment, not `/deployments/{id}/traffic`, because an allocation spans several deployments and no single deployment row can own the others' weights. Reuses `runtime.deployment.view`/`.deploy`, no new permissions. `Idempotency-Key` honoured on the PUT via 3.1's `IdempotencyService`.
- **Added** four error codes (`TRAFFIC_WEIGHTS_INVALID`, `VERSION_NOT_ELIGIBLE`, `TRAFFIC_ALLOCATION_CONFLICT`, `NO_ACTIVE_DEPLOYMENT`). `NO_ACTIVE_DEPLOYMENT` covers **only** the new mode — a servable deployment exists but every version its allocation weights has been paused/superseded/revoked. The pre-existing `DEPLOYMENT_NOT_FOUND`/`DEPLOYMENT_NOT_ACTIVE` keep their exact M1 meanings and HTTP statuses; no M1 API contract was broken.
- **Added** two audit events: `DEPLOYMENT_TRAFFIC_CHANGED` (actor, revision, full from/to weight maps) and `RUNTIME_EXECUTION_NO_ACTIVE_DEPLOYMENT` (WARNING, recorded against the agent — the gate runs before an execution row exists, by design, so a rejected request leaves no phantom execution).
- **No cache, deliberately, and the absence is tested.** Every candidate cache key is mutated across three phases (pause, supersede, rollback, revoke, kill switch), so a cache would need an invalidation hook in all of them to stay correct *under the kill switch* — a fail-closed hazard for an unmeasured gain. Measured instead: **≤3 queries** per resolution (asserted by counting statements through a `before_cursor_execute` hook, so an N+1 fails the test) and **<25 ms** (observed ≈1–2 ms).
- **Authorization non-bypass verified three ways**: structurally (the resolver's parsed **AST** contains no authorization/policy import and no `AuthorizationGateway`/`authorize` identifier — checked against the AST, not raw text, because the docstring discusses the gateway at length), positionally (the resolver call site precedes `decision = authorize(deployment)`), and behaviourally (a same-tenant VIEWER is rejected 403 on an allocation-routed agent while the admin's identical request succeeds).
- **One pre-existing test migrated deliberately, and strengthened rather than weakened**: `test_environment_promotion.py::test_ac15_promoting_to_lifecycle_active_has_no_effect_on_the_legacy_execution_gate` → `..._now_serves_execution`. Written in 3.2, its own docstring named the expiry condition — *"until Phase 3.4 deliberately wires the two together"*. It still pins `status != 'ACTIVE'` before executing, so the execution can only have been admitted by `lifecycle_state`; had 3.4 gated on `status` alone it would still fail. A 3.4 test asserts this migration is present and has not been softened into accepting either outcome.
- **Five pre-existing tests updated, not weakened**: the Milestone 2 connector tests that hardcode the migration head, bumped `0039` → `0040` — the same bookkeeping 3.2 and 3.3 did.
- **Explicitly out of scope, per the build prompt**: canary/progressive orchestration (3.5 — 3.4 builds the allocation it drives, not the driver), blue-green/recreate/rolling strategies (3.6/3.9), rollback (3.7), AI-aware runtime health evaluation (3.5/3.7), scheduler/workers/frontend (3.8/3.9/3.10), and any change to how a resolved version *executes*.
- Route count 502 → 505 (+3); live schema 114 → 116 tables (+2).
- 43 new backend tests (`tests/runtime/test_traffic_resolver_gate.py`) grouped by this phase's acceptance criteria: weight validation, eligibility, atomicity (including a database-wide sum-to-100 property check), revision lineage and audit from/to, distribution over 2,000 resolutions, sticky routing as a unit, through the resolver and end-to-end over HTTP, the three authorization non-bypass proofs, version immutability across 50 resolutions, both fail-closed modes, the paused/killed/superseded/revoked non-serving cases, the servability truth table, backfill well-formedness, a **deterministic** conflict race (a real second connection holds its transaction open, so the loser blocks inside Postgres — not a timing-dependent thread barrier) plus a six-writer invariant race, the query-count and latency benchmarks, the no-cache proofs, and cross-tenant/permission/idempotency coverage. Backend **1,478** green (1,435 + 43), 0 failed, 1 deselected; frontend untouched by this backend-only phase, still **297** green. See [docs/deployment/traffic-and-resolution.md](docs/deployment/traffic-and-resolution.md).

**Milestone 3 now has 4 of 10 sub-phases done.** Next: 3.5 (progressive/canary rollout, driving this phase's allocation).

## [Unreleased] — Phase 3.3 · Deployment Preflight & Release Gate Engine

**Milestone 3's third sub-phase.** Builds the single authoritative deployment-readiness evaluation — `ReleaseGateService.evaluate()` — aggregating checks already built across Milestones 0/1/2 and Phases 3.1/3.2 into one verdict: PASS / WARNING / BLOCK. No new signature verifier, compatibility analyzer, health-check mechanism, or approval engine — every check calls an existing capability. A BLOCK prevents a deployment from reaching `DEPLOYING`/`ACTIVE` through the Phase 3.1 lifecycle authority.

- **Added** `app/runtime/release_gate/` — `checks.py` (thirteen individual checks, each calling an existing capability, plus `run_checks`/`verdict_for`), `service.py` (`ReleaseGateService`, the single evaluation path for both the preview API and in-lifecycle enforcement).
- **The verdict**: BLOCK dominates WARNING dominates PASS. Each finding carries a stable `code`, `severity`, `source` (which existing capability produced it), `explanation`, and `remediation`. Fail-closed by construction: an unevaluable check (unexpected exception) becomes a `PREFLIGHT_CHECK_UNAVAILABLE` finding, never a silently skipped one.
- **The full check-to-source mapping** (`docs/deployment/release-gates.md`): agent active/kill switch → `Agent.lifecycle_status` (Ruling #6, **absolute BLOCK, never overridable**); version published → `AgentVersion.status`; snapshot checksum → `app.runtime.services._verify_checksum`; signature/provenance → `AttestationService.verify`; compatibility → `AgentVersion.compatibility_level` (**WARNING only** — preserves `docs/runtime/versioning.md`'s own documented advisory-only boundary, not silently turned into a hard block); owners → `Agent.owner_id`; machine identity → `AgentIdentity`; provider availability/credentials → `app.runtime.providers.registry`/`ProviderCredentialService`; tools → `Tool.enabled`; environment policy → `app.runtime.environment.policy.evaluate` (Phase 3.2, called verbatim); approvals → `DeploymentLifecycleService`'s own private approval-funnel methods (Phase 3.1, called verbatim, **WARNING not BLOCK** — a pending approval is the designed reroute path, not a failure).
- **The freshness rule (the one genuinely new requirement)**: a health/availability signal older than a configured bound is treated as unproven, never a silent pass. Applied to `DeploymentHealth.checked_at`/`HealthMonitoringService` — **not** the build prompt's own suggested Milestone-2 connector-health signal, for two independent, structural reasons documented in full in `docs/deployment/release-gates.md`: the runtime-never-knows vocabulary boundary, and no existing dependency link between a runtime `Tool`/`AgentVersion` and Milestone 2's own integration-instance catalog (the identical gap Phase 3.2 already reported for `allowed_external_systems`). Reported as a gap, not built around. Default bound 900s (15 min), configurable per environment via `Environment.policy["preflight_freshness_bound_seconds"]`.
- **Every finding-code severity is configurable per environment** via `Environment.policy["preflight_severity_overrides"]`, except the kill-switch code — always absolute BLOCK, never overridable.
- **Wired into `DeploymentLifecycleService.start_deploying()`** — runs after the pre-existing 3.2 narrow environment-policy check (left completely unchanged, including its own error codes) and before the approval-reroute logic (never disturbed, since the gate's own approval finding is WARNING). A BLOCK verdict raises `DEPLOYMENT_PREFLIGHT_BLOCKED`. Promotion is gated for free — `PromotionService.promote()` already funnels through this same call, no extra wiring needed.
- **The kill switch is absolute and always re-checked live, never trusted from a prior evaluation**: `ReleaseGateService.evaluate()` never caches; a deployment that passed preflight, whose agent is then killed, and which then attempts to deploy, is blocked on re-evaluation. The pre-existing, independent Ruling #6 check still additionally fires at the literal `DEPLOYING → ACTIVE` transition for any path that bypasses the gate (e.g. `resume()`).
- **Added** the new `deployment_preflight_results` table (verdict + JSONB findings snapshot per evaluation, composite index on `(deployment_id, evaluated_at)`). Migration `0039_deployment_preflight`, purely additive, no data backfill.
- **Added** 3 new routes under `/deployments/{id}/preflight`(`/history`) — reuses `runtime.deployment.deploy`/`.view`, no new permissions.
- **Added** two new error codes (`DEPLOYMENT_PREFLIGHT_BLOCKED`, `PREFLIGHT_CHECK_UNAVAILABLE`); reused `DEPLOYMENT_NOT_FOUND` rather than duplicating it.
- **Added** three new audit events, SRS's own literal names (`DEPLOYMENT_VALIDATION_STARTED`/`_FAILED`/`_PASSED`), mirroring 3.2's `RELEASE_PROMOTED`/`RELEASE_PROMOTION_BLOCKED` unprefixed-name precedent — a kill-switch-caused BLOCK additionally tagged `severity="CRITICAL"`.
- **`POST .../preflight` deliberately not wrapped in the 3.1 idempotency contract** — FR-031 requires a fresh result on every call, the same precedent `CompatibilityAnalysisService.analyze` already establishes for a recompute-and-persist-fresh-every-call operation.
- **One pre-existing Phase 3.1 test's expectation changed, not weakened**: `test_ac09_suspended_agent_blocks_activation` now asserts `DEPLOYMENT_PREFLIGHT_BLOCKED` (was `DEPLOYMENT_AGENT_SUSPENDED`) and a `READY` post-condition (was `DEPLOYING`) — the gate now blocks *before* the `READY → DEPLOYING` mutation rather than after it, a strictly safer post-condition; the underlying guarantee is unchanged.
- **Explicitly out of scope, per the build prompt**: traffic allocation, the version resolver and execution gate (3.4), canary (3.5), strategies (3.6/3.9), rollback (3.7), scheduler/workers/frontend (3.8/3.9/3.10), building new checks (new signing/compatibility/health-check/approval engines — every check reuses an existing capability), enforcing the gate on promotion beyond the free wiring above, any change to the M1 execution path.
- **Five pre-existing tests updated, not weakened**: `test_connector_sdk.py`/`test_database_connector.py`/`test_queue_connector.py`/`test_rest_connector.py`/`test_storage_connector.py` each hardcoded the prior migration head (`"0038_environments_promotion.py"`) — bumped to the new correct filename.
- Route count 499 → 502 (+3); live schema 113 → 114 tables.
- 27 new backend tests (`tests/runtime/test_release_gate.py`) grouped by this phase's own acceptance criteria: verdict/finding structure, pure aggregation-precedence and freshness-state unit tests, a BLOCK actually preventing a lifecycle transition, reuse-verified-by-spy tests for the environment-policy and approval checks, a fail-closed unevaluable-check test, the kill switch's absolute-BLOCK and re-checked-at-transition guarantees, the freshness rule's stale/fresh/unhealthy behavior and its configurable bound, persisted latest/history retrieval, authentication and cross-tenant rejection, a per-finding-code sweep, and a full happy-path PASS. Backend **1,435** green (1,408 + 27), 0 failed, 1 deselected; frontend untouched by this backend-only phase, still **297** green. See [docs/deployment/release-gates.md](docs/deployment/release-gates.md).

**Milestone 3 now has 3 of 10 sub-phases done.** Next: 3.4 (traffic allocation + the version resolver/execution gate).

## [Unreleased] — Phase 3.2 · Environment & Promotion Model

**Milestone 3's second sub-phase.** Turns `agent_deployments.environment` from a bare, unvalidated string into a governed, tenant-scoped `Environment` entity with real policy, and adds a promotion operation that moves a version's deployment eligibility between environments while **preserving the exact same immutable version** — never cloning, never modifying.

- **Added** `app/runtime/environment/` — `policy.py` (environment-policy evaluation: `check_prohibited`/`check_allowed_models`/`check_allowed_data_classifications`/`check_concurrency`/`check_change_window`/`requires_approval`/`evaluate`), `service.py` (`EnvironmentService`, `PromotionPathService`, `PromotionService`).
- **Added** governed `Environment` entities: tenant-scoped, standard `DEVELOPMENT`/`TEST`/`STAGING`/`PRODUCTION`/`SANDBOX` (`PRODUCTION` defaults `is_production=True`) plus org-defined custom names, each carrying a `policy` JSONB document. `PromotionPath` — the org-configured directed graph a version's deployment eligibility may legally move along.
- **A second, additive `agent_deployments` field, not a widening of the existing one**: `environment_id` (nullable FK to `environments`) is new; the pre-existing `environment` string is completely unmodified, including the one place execution actually reads it (`RuntimePolicyService.evaluate`'s `prohibited_environments`/`requires_approval_environments` checks, M1 execution path).
- **The security core of this phase — promotion preserves the exact immutable version, by construction, not just by test**: `PromotionService.promote` loads the source `AgentVersion` exactly once and passes that same object straight into the pre-existing `DeploymentService.create` — nothing in the new module can construct, copy, or mutate a version row. Verified live: the promoted deployment's `agent_version_id` matches exactly, the agent's total version-row count is unchanged, and `checksum`/`manifest_digest`/`signature_id` are byte-identical before/after.
- **`prohibited_environments` (mandatory inspection) found and integrated, not paralleled**: `check_prohibited()` reads the exact same `AgentVersion.policy_snapshot["prohibited_environments"]` field `RuntimePolicyService.evaluate` already reads at execution time — a version barred from an environment by that pre-existing mechanism cannot be promoted into it either.
- **Release-channel relationship (mandatory inspection) found to be orthogonal, not overlapping**: a release channel is a global stability track a version publishes onto; an environment is a tenant-scoped deployment target a version is promoted through. Promotion never touches `release_channel_id`; no channel vocabulary appears anywhere in the new policy module — both proven by dedicated tests.
- **Added** environment-required approval, folded into the existing single approval-reroute funnel (`DeploymentLifecycleService._requires_deployment_approval`) as one additive condition — never a second, parallel approval mechanism.
- **Added** the previously declared-but-undriven `ACTIVE`/`PAUSED` → `SUPERSEDED` lifecycle edge (Phase 3.1's own machine, "3.2 drives this"): a promoted deployment reaching `ACTIVE` now supersedes any other `ACTIVE`/`PAUSED` deployment of the same agent already in the target environment, preserving lineage via `superseded_by_deployment_id`.
- **Added** a single deploy/promote-time environment-policy choke point (`DeploymentLifecycleService.start_deploying`), shared identically by a plain deploy and a promotion. Enforced: `allowed_models`, `allowed_data_classifications`, `requires_approval`, `maximum_concurrent_deployments`, `change_window`. Modeled only, stated plainly: `allowed_external_systems` (no existing link between a runtime `Tool`/`AgentVersion` and Milestone 2's own integration-instance catalog — renamed from the build prompt's own `allowed_connectors`, since that literal word is mechanically forbidden anywhere under `app/runtime`), `rollback_rules` (Phase 3.7's job).
- **Added** 10 new routes: `POST /deployments/{id}/promote` (no path collision found, used directly per the build prompt's own §6) and 9 under `/environments`/`/promotion-paths` (CRUD + policy). Two new permissions (`runtime.environment.view`/`.manage`); promoting itself reuses `runtime.deployment.deploy`.
- **Added** five new error codes (`ENVIRONMENT_NOT_FOUND`, `ENVIRONMENT_POLICY_VIOLATION`, `PROMOTION_PATH_NOT_DEFINED`, `PROMOTION_WINDOW_CLOSED`, `PROMOTION_IMMUTABILITY_VIOLATION` — the last defensive-only, structurally unreachable by this phase's own logic); reused `DEPLOYMENT_NOT_FOUND` rather than duplicating it.
- **Added** two new tables — `environments`, `promotion_paths` — plus one new `agent_deployments` column (`environment_id`). Migration `0038_environments_promotion` applies the deterministic §15 seed+backfill, once, live: the standard five environments and a default `DEVELOPMENT → TEST → STAGING → PRODUCTION` promotion chain (`STAGING → PRODUCTION` defaulting `requires_approval=true`) for every organization with existing deployments (4,559 orgs), and backfills every existing deployment's `environment_id` from its legacy string (4,706/4,706).
- **A genuine bug found and fixed before it reached a test failure**: `EnvironmentService.ensure_seeded()`'s first draft mirrored `ReleaseChannelService.ensure_seeded()`'s flush-only pattern, but that precedent's own callers all commit later as part of a larger flow — this route did not, so seeded rows were silently rolled back on session close. Fixed by adding the missing `db.commit()`, matching the actual precedent (`list_release_channels`).
- **Explicitly out of scope, per the build prompt**: traffic allocation, the version resolver and execution gate (3.4), preflight/release gates (3.3, may later gate promotion — not wired here), canary (3.5), blue-green/recreate/rolling strategies (3.6/3.9), rollback (3.7), distributed scheduler/workers (3.8/3.9), any operator frontend (3.10), enforcing environment policy on every runtime execution (only at deploy/promote time here — `RuntimePolicyService` stays the separate, unmodified execution-time mechanism).
- **Five pre-existing tests updated, not weakened**: `test_connector_sdk.py`/`test_database_connector.py`/`test_queue_connector.py`/`test_rest_connector.py`/`test_storage_connector.py` each hardcoded the prior migration head (`"0037_deployment_lifecycle.py"`) — bumped to the new correct filename.
- Route count 489 → 499 (+10); live schema 111 → 113 tables.
- 29 new backend tests (`tests/runtime/test_environment_promotion.py`) grouped by this phase's own acceptance criteria: tenant-scoped environments with standard/custom support, the live-migration and opportunistic-backfill string→row proof, every enforced policy dimension via the shared choke point, the change window, promotion-path enforcement, the immutability assertions, the full lifecycle-driven happy path and production-approval reroute, a real-Postgres idempotency proof, the `prohibited_environments` integration, the release-channel orthogonality proof, tenant isolation/authentication, a real two-thread concurrent-promotion race, and the Milestone 1 execution-gate boundary. Backend **1,408** green (1,379 + 29), 0 failed, 1 deselected; frontend untouched by this backend-only phase, still **297** green. See [docs/deployment/environments.md](docs/deployment/environments.md).

**Milestone 3 now has 2 of 10 sub-phases done.** Next: 3.3 (preflight/release gates).

## [Unreleased] — Phase 3.1 · Enterprise Deployment Core — Milestone 3 Begins

**Milestone 3 (ACT-SRS-M3, "Deployment & Release") begins here — the first of ten sub-phases.** Turns the existing, partially-wired `agent_deployments` table into a governed deployment domain: a real 15-state lifecycle with one transition authority, append-only event lineage, optimistic-concurrency protection, and idempotent commands. Deliberately stops short of the thing that makes deployment state matter for execution — the version resolver and the execution gate are Phase 3.4's own, single, scoped change to the Milestone 1 execution path.

- **Added** `app/runtime/deployment/` — `lifecycle.py` (the pure, 15-state transition graph, no I/O), `idempotency.py` (the reusable, platform-wide `Idempotency-Key` contract), `service.py` (`DeploymentLifecycleService`, the single authority that ever writes `AgentDeployment.lifecycle_state` — mechanically checked, no other write site anywhere in the codebase).
- **A second, independent lifecycle field, not a widening of the existing one**: `agent_deployments.lifecycle_state` is new; the pre-existing `status` column and all five legacy `DeploymentService` methods (`deploy`/`suspend`/`resume`/`rollback`/`retire`) are completely unmodified, including the one place execution actually gates on deployment state (`ExecutionRequestService._request_execution`'s `deployment.status != "ACTIVE"` check) — proven untouched by a grep test scoped to that function's own source and by a full execution running end to end unmodified.
- **Added** Ruling #6's suspension/kill integration: `DeploymentLifecycleService` reads (never writes) the platform's existing `Agent.lifecycle_status == "SUSPENDED"` mechanism every time a deployment would reach `ACTIVE` — including a `PAUSED → ACTIVE` resume — rejecting with `DEPLOYMENT_AGENT_SUSPENDED`. No parallel kill-switch mechanism built.
- **Added** the `runtime_approvals` precondition for `ACTIVE`: a deployment whose environment/policy demands approval reroutes to `PENDING_APPROVAL` (creating the approval row itself) rather than erroring, mirroring — without touching — the legacy `DeploymentService.deploy()`'s own mission-critical-production reroute shape.
- **Added** the reusable `Idempotency-Key` contract (`IdempotencyService`, proven generic via a unit test against a bare non-deployment stub), honored on every state-changing deployment endpoint. Uses a claim-then-poll pattern — a placeholder row is committed first, and the table's own unique constraint is the concurrency primitive — closing a genuine TOCTOU race a naive check-then-act implementation would have had; proven with two real threads racing the same key, exactly one execution happens.
- **Added** optimistic concurrency via a genuine SQLAlchemy `version_id_col` on the new `revision` column — every UPDATE carries `WHERE revision = <loaded value>`, raising `DEPLOYMENT_REVISION_CONFLICT` on a lost race; proven live with two threads racing one transition, exactly one succeeds.
- **Added** 5 new routes under `/api/v1/runtime/deployments/{id}/lifecycle/...` (`transition`/`pause`/`resume`/`retire`/`events`) — nested to avoid colliding with the pre-existing `/pause`/`/resume`/`/retire`-adjacent legacy routes already shipped in Phase 5.0; reuses the pre-existing `runtime.deployment.view`/`.deploy` permissions rather than adding new ones. `POST /deployments` extended additively with `Idempotency-Key` support.
- **Added** three new error codes (`DEPLOYMENT_INVALID_TRANSITION`, `DEPLOYMENT_REVISION_CONFLICT`, `DEPLOYMENT_AGENT_SUSPENDED`); reused two pre-existing ones (`DEPLOYMENT_NOT_FOUND`, `IDEMPOTENCY_CONFLICT`) rather than duplicating them.
- **Added** two new tables — `deployment_events` (append-only lifecycle lineage, complementary to the pre-existing platform audit trail and `runtime_events` Operations Center feed, both still written unchanged) and `idempotency_keys` (deliberately distinct from the narrower, execution-scoped `idempotency_records`, untouched) — plus four new `agent_deployments` columns (`lifecycle_state`/`revision`/`state_reason`/`superseded_by_deployment_id`). Migration `0037_deployment_lifecycle` also applies the deterministic §15 mapping, once, live, backfilling every existing deployment's legacy `status` into an initial `lifecycle_state`.
- **Two real conflicts between the build prompt and the shipped codebase were found and resolved, not silently redesigned around** — documented in `docs/deployment/lifecycle.md`: the literal `/pause`/`/resume`/`/retire` paths collide with pre-existing routes (resolved via `/lifecycle/...` nesting); the suggested `deployment.view`/`deployment.manage` permission names don't match this platform's actual `runtime.deployment.*` convention (resolved by reuse).
- **Explicitly out of scope, per the build prompt**: traffic allocation, the version resolver and execution gate (3.4), environments/promotion (3.2), preflight/release gates (3.3), canary (3.5), blue-green/recreate/rolling strategies (3.6/3.9), rollback (3.7), distributed scheduler (3.8), distributed workers (3.9), any operator frontend (3.10).
- **Five pre-existing tests updated, not weakened**: `test_connector_sdk.py`/`test_database_connector.py`/`test_queue_connector.py`/`test_rest_connector.py`/`test_storage_connector.py` each hardcoded the prior migration head (`"0036_identity_federation.py"`) — bumped to the new correct filename.
- Route count 484 → 489 (+5); live schema 109 → 111 tables.
- 27 new backend tests (`tests/runtime/test_deployment_lifecycle.py`) grouped by this phase's own acceptance criteria: the state machine itself, the idempotency contract's genericity and real concurrent race, the single-authority invariant, the vestigial-replica-column boundary, the happy path to `ACTIVE` and back through pause/resume/retire, append-only lineage, the §15 mapping's own internal consistency, Ruling #6's suspension guard, the approval-precondition reroute, tenant isolation/permission enforcement, and a real-Postgres revision-conflict race. Backend **1,379** green (1,352 + 27), 0 failed, 1 deselected; frontend untouched by this backend-only phase, still **297** green. See [docs/deployment/lifecycle.md](docs/deployment/lifecycle.md).

**Milestone 3 now has 1 of 10 sub-phases done.** Next: 3.2 (environments/promotion).

## [Unreleased] — Phase 2.3.1 · External Identity Federation — Milestone 2 Complete

**Milestone 2's ninth and final sub-phase — the Enterprise Integration Framework is now complete, 9 of 9.** Every prior 2.2.x connector authenticates the *platform* outward to an external system, holding a platform secret and presenting it; federation is the inversion — it authenticates a *user* inward to the platform, verifying a signed assertion, and holds none of the user's own credential, ever.

- **Added** `app/identity/federation/` — OIDC (authorization-code flow) and SAML 2.0 (web-browser SSO) federated authentication, configurable per organization for Entra ID, Okta, or generic OIDC/SAML providers. Deliberately placed under `app/identity/`, not `app/integration/`, since this is identity's own concern (session issuance, RBAC, user provisioning), not the connector framework's.
- **Added** `oidc.py` — ID-token verification via `python-jose` (already a platform dependency) "with care," never hand-rolled: the accepted algorithm set is fixed by the organization's own stored configuration and never taken from the token's own `alg` header (closing algorithm-confusion), the signing key is resolved from the IdP's JWKS by `kid` with no fallback on an unrecognized one, and issuer/audience/expiry/nonce are all explicitly checked. Proven against a real, freshly-generated RSA keypair — never a mock signer — rejecting tampered signatures, wrong-key signatures, `alg:none`, algorithm confusion, expiry, wrong audience/issuer, and nonce mismatch/replay.
- **Added** `saml.py` — SAML response verification via `python3-saml`/`xmlsec` (new dependencies), never hand-rolled: XML signature verification is delegated entirely to the security-audited `libxmlsec1` C library, `strict: True` always set. Signature-wrapping resistance comes from the library following the signature's own `<Reference URI="#...">` back to the exact ID-referenced element, never a weaker "find the first Assertion" query — proven against two distinct, deliberately-constructed signature-wrapping attack documents (a forged sibling assertion; a forged assertion substituted as the only direct child with the legitimate one relocated into `<samlp:Extensions>`).
- **Added** `claim_mapping.py` — pure IdP group/role claim → platform role resolution (`ACT-INT-FR-183`), configuration-driven, no code changes needed per organization's mapping rules.
- **Added** `service.py`'s `FederationService` — per-organization config CRUD; login orchestration; **maps into the platform's existing user/RBAC model, never a parallel one** (`ACT-INT-FR-182`) via stable subject id (OIDC `sub`/SAML `NameID`), never email, since email can be reassigned by an IdP admin. A federated user existing already by email is always linked (no new identity created); JIT provisioning of a genuinely new user is gated per-org by `jit_provisioning_enabled` (`ACT-INT-FR-184`), reusing the existing `UserProvisioningService` seam verbatim. Session issuance terminates in the platform's **existing** pipeline (`SessionLifecycleService`/`RefreshRotationService`/`IdentityContextResolver`/`TokenService`) — never a parallel session/token mechanism (`ACT-INT-FR-187`) — always at `AAL1`, since the platform cannot verify what MFA the IdP itself enforced.
- **Added** stateless CSRF/replay defense: OIDC `state` and SAML `RelayState` are short-lived (600s), platform-signed JWTs reusing the existing `settings.JWT_SECRET_KEY` — no new secret, no new "pending requests" table.
- **Added** 4 public routes under `/api/v1/auth/federation` (login/callback/SAML ACS/metadata) and 6 admin CRUD routes under `/api/v1/identity/federation/configs`, gated by two new permissions (`identity.federation.view`/`.manage`). `FederationConfigRead` never serializes the client secret, only `has_client_secret: bool`.
- **Added** two new tables: `identity_federation_configs` (per-organization IdP configuration; `encrypted_client_secret` nullable, via the existing `credential_crypto.py`) and `federated_identities` (links `external_subject_id` → platform `user_id`; **no credential column of any kind**). Migration `0036_identity_federation`, additive, reversible.
- **Added** six new error codes: `FEDERATION_CONFIG_NOT_FOUND`, `FEDERATION_CONFIG_INVALID`, `FEDERATION_ASSERTION_INVALID` (deliberately shared by both protocols, mirroring `INVALID_CREDENTIALS`'s generic-failure discipline), `FEDERATION_STATE_INVALID`, `FEDERATION_USER_NOT_PROVISIONED`, `FEDERATION_CLAIM_MAPPING_FAILED`.
- **New dependencies**: `python3-saml`, `xmlsec`, `lxml`, `isodate` — SAML XML signature verification delegated to `libxmlsec1`, never hand-rolled.
- **Local authentication is untouched and proven to keep working unchanged alongside federation** (`ACT-INT-FR-187`).
- **Explicitly out of scope, per the build prompt**: SCIM bulk sync, platform-layer MFA, replacing local authentication, any change to connectors or the runtime.
- **Five pre-existing tests updated, not weakened**: `test_connector_sdk.py`/`test_database_connector.py`/`test_queue_connector.py`/`test_rest_connector.py`/`test_storage_connector.py` each hardcoded the prior migration head (`"0035_connector_health.py"`) as their expected final migration filename — correct when their own phase shipped, now stale since this phase genuinely adds one; updated to the new correct filename with an explanatory comment.
- Route count 474 → 484 (+10); live schema 107 → 109 tables.
- 57 new backend tests (`tests/identity/federation/test_oidc_bypass_prevention.py`, 14 — every canonical JWT bypass vector, plus structural proof `algorithms` is never read from the token header; `test_saml_bypass_prevention.py`, 12 — including two signature-wrapping attack variants, plus structural proof of `xmlsec`/`onelogin` delegation; `test_claim_mapping.py`, 8; `test_federation_login_flow.py`, 10 — end to end against this platform's own real dev database, real session issuance, JIT provisioning; `test_federation_config_crud.py`, 13 — real HTTP, permission gating, cross-org isolation, secret-never-returned). Backend **1,352** green (1,295 + 57), 0 failed, 1 deselected; frontend untouched by this backend-only phase, still **297** green. See [docs/identity/federation.md](docs/identity/federation.md).

**Milestone 2 — the Enterprise Integration Framework — is now COMPLETE: 9 of 9 sub-phases done.** Milestone 3 (Deployment & Release) is next.

## [Unreleased] — Phase 2.2.4 · Generic Message Queue Connector

**Milestone 2's fourth and last generic connector — completing the connector framework and all four generic connectors.** Two-sided containment: publish is scoped to a queue fixed by the tool contract itself (never a model-supplied name), and consume is always bounded to at most N messages within a bounded wait, never an unbounded stream.

- **Added** `app/integration/connectors/queue/` — `QueueConnector`, built through the SDK surface with **zero deviations** (a first among the generic connectors — 2.2.2 needed one, 2.2.3 needed two; this phase's own error-code vocabulary is entirely invocation-time). Supports AMQP (RabbitMQ) and SQS by declaration; Azure Service Bus is a recognized but backend-pending value.
- **Added** `scope.py`, genuinely zero imports of any kind — simpler than 2.2.3's path enforcer by design, since the target queue is fixed by the tool contract and never a value the model supplies at all. Its one function checks whether a resolved binding's declared operation (`PUBLISH`/`CONSUME`) matches what is being attempted against it.
- **Added** bounded consume (`ACT-INT-FR-162`): never more than a binding's effective batch cap regardless of how many messages the queue holds or what the caller asks for, never past its effective wait timeout — verified live against a fixtured transport (a queue holding five messages with a cap of three yields exactly three; an empty queue with a 0.3s wait returns empty in ~0.3s, not indefinitely).
- **Added** message-size limits: a publish exceeding the effective limit is rejected before any connection is attempted. A **consumed** oversized message is truncated to the limit and flagged `truncated: true` rather than failing the whole batch or being silently dropped — a deliberate departure from 2.2.2's/2.2.3's own "reject the whole operation" precedent, since a consume batch is a set of otherwise-independent messages.
- **Added** an explicit, documented acknowledgment policy: ack-on-retrieve (AMQP `basic_get(auto_ack=True)`; SQS an explicit `delete_message` immediately after `receive_message`) — at-most-once from the queue's own perspective, a deliberate default for a bounded, discrete tool operation, not left implicit.
- **Added** `app/integration/connectors/queue/invoker.py` — the tool-invocation bridge, mirroring 2.2.3's audited shape but exposing **two** distinct entry points (`publish_message`/`consume_messages`) rather than one polymorphic `invoke_tool`, each verifying the resolved binding's declared operation before touching a broker — proven end to end against this platform's own real dev database, including a genuine stored/encrypted `BASIC` credential (an AMQP username/password) actually reaching a (fixtured) connection. **Reuses 2.2.3's `INTEGRATION_CONNECTOR_OBJECT_ACCESSED` audit event** rather than adding a new one — every publish/consume attempt, allowed or denied, is recorded. **Not wired into `ToolGatewayService`/`tools_snapshot`/the model-driven tool loop** — Milestone 1 stays untouched.
- **Added** five new error codes: `QUEUE_NOT_DECLARED`, `QUEUE_MESSAGE_TOO_LARGE`, `QUEUE_OPERATION_NOT_PERMITTED`, `QUEUE_CONSUME_TIMEOUT` (defined for vocabulary completeness but not raised by either backend this phase — a bounded consume finding nothing within its wait window is a successful empty result, never a timeout error), and `QUEUE_BACKEND_FAILED` (beyond the build prompt's own list, mirroring `DB_CONNECTION_FAILED`/`STORAGE_BACKEND_FAILED`).
- **New dependency**: `pika` (pure-Python AMQP client) for the AMQP backend. The SQS backend reuses 2.2.3's own `boto3` dependency, no new one needed.
- **Explicitly out of scope, per the build prompt**: long-lived consumers, consumer groups, offset management, subscriptions, or stream processing (adjacent to Milestone 3's worker/scheduler system, not a connector tool contract), queue administration (create/delete queues), vendor-specific connectors, identity federation (2.3.1), any change to model/tool execution.
- **No migration** — every table touched already exists (`connectors`/`connector_instances`/`connector_credentials`/`authorization_audit`). **No new HTTP route** — instance configuration reuses the existing `POST`/`PATCH /connectors` endpoints; the invocation bridge is a pair of direct, database-backed Python entry points.
- **RabbitMQ/SQS/localstack coverage boundary stated explicitly**: no live broker is reachable in this environment, so both backends' dispatch (scoped-publish success, the bounded-consume cap, the bounded-wait timing, size-limit rejection, oversized-message truncation, and the ack-on-retrieve policy) is proven against a mocked/fixtured `pika`/`boto3` transport, never a live broker. The scope-permission logic itself has full, unmocked coverage since it has no backend dependency at all.
- 50 new backend tests (`tests/integration/test_queue_scope.py`, 7 — the isolated scope-permission check, zero imports; `test_queue_connector.py`, 31 — scoped-publish/bounded-consume/size/ack mechanics against mocked transports, SDK-surface/integrity; `test_queue_connector_invocation.py`, 12 — end to end against a real, database-backed `ConnectorInstance` with a real, stored, encrypted credential). Backend **1,295** green (1,245 + 50), 0 failed, 1 deselected; frontend untouched by this backend-only phase, still **297** green. See [docs/integration/connectors.md](docs/integration/connectors.md)'s "Generic Message Queue Connector" section.

**Milestone 2's connector framework and all four generic connectors are now complete — 8 of 9 sub-phases done.** Only 2.3.1 (identity federation) remains.

## [Unreleased] — Phase 2.2.3 · Generic File & Object Storage Connector

**Milestone 2's third real connector — and the one carrying this milestone's second sharpest security rule: a model-supplied path can never escape its declared scope.** Not sanitized, not best-effort cleaned up and let through — a supplied path is canonicalized, then proven to resolve inside its declared boundary, before any read or write is attempted; anything that cannot be proven in-scope is denied outright.

- **Added** `app/integration/connectors/storage/` — `StorageConnector`, built through the SDK surface (two specific, documented, justified deviations — see below), turning declared, scoped filesystem/S3-compatible access into governed tools. Azure Blob is a recognized but backend-pending value (`azure-storage-blob` needs a genuinely heavy dependency, not added this phase, mirroring 2.2.2's SQL Server precedent).
- **Added** `scope.py`, the security-critical component — **zero dependencies on this platform, not even the SDK**, just `os`/`posixpath`/`re`/`unicodedata`/`urllib.parse`. Its only public function, `resolve_and_contain(boundary, supplied_path)`, canonicalizes (control-character rejection, iterative percent-decoding, a second control-character check on the decoded result, NFKC Unicode normalization, then `os.path.realpath` for filesystem — resolving `..` *and* symlinks in one pass — or `posixpath.normpath` for object storage) and only then contains-checks, returning the canonicalized target or raising — the canonicalized result, never the raw string, is what a caller ever receives (no TOCTOU gap). Proven against every named traversal vector — relative, absolute (POSIX/Windows-drive/UNC), single- and double-percent-encoded, backslash, literal and encoded null-byte, Unicode homoglyph, object-store prefix/bucket escape (including the sibling-prefix boundary case) — with **no live storage anywhere in the test file**, plus a real temporary symlink (or, on this environment's default unprivileged Windows user, a directory junction — a reparse point `realpath` resolves identically, genuinely exercised, not skipped).
- **Added** size limits checked before any full transfer: a read checks the object's size via metadata first (`os.path.getsize`/`head_object`, a HEAD call, never a GET) and rejects before ever opening the file or fetching the object's bytes; both reads additionally bound the actual transfer itself as a second, defense-in-depth check. A write checks the in-memory payload's length before ever calling the backend.
- **Added** read-only-by-default posture (`ACT-INT-FR-144`, mirroring `ACT-INT-FR-125`): a read-only instance declaring a write scope is rejected outright with a new `STORAGE_WRITE_NOT_PERMITTED` before it is ever stored.
- **Added** `app/integration/connectors/storage/invoker.py` — the tool-invocation bridge, mirroring 2.2.2's own exactly: fail-fast resolves the instance, resolves its credential bundle (reusing `resolve_credential_bundle()` unchanged), validates the supplied `path` against the named scope's declared boundary **before any backend call**, dispatches through `backends.py` — proven end to end against this platform's own real dev database, including a genuine stored/encrypted credential. **Not wired into `ToolGatewayService`/`tools_snapshot`/the model-driven tool loop** — Milestone 1 stays untouched.
- **Added** per-access audit trail (`ACT-INT-FR-145`, a new `INTEGRATION_CONNECTOR_OBJECT_ACCESSED` audit event) — every object access attempt, allowed or denied, is recorded via a `finally` block so a denial is audited exactly as reliably as a success, carrying the *validated* path (never the raw supplied string — a denial correctly carries none at all), backend, scope, operation, size, and outcome; credentials never appear in the recorded `meta`. This is 2.2.x's first invocation-level audit event — neither 2.2.1's nor 2.2.2's own build prompt required auditing individual calls.
- **Two justified SDK-surface deviations**: `declaration.py` raises its own `StorageScopeInvalidError` for all semantic validation (this phase's own acceptance criteria require a distinguishable declaration-time code where 2.2.2's `declaration.py` needed none); `connector.py` raises `StorageWriteNotPermittedError`, mirroring `DbWriteNotPermittedError` exactly. `scope.py` and `backends.py` both stay entirely free of `app.integration.errors`.
- **Added** filesystem (no new dependency) and S3-compatible (new `boto3` dependency) backends behind one dispatch interface — an S3 access key id/secret access key resolve through the `BASIC` scheme's generic `username`/`password` fields, the same non-HTTP-shaped-credential generalization 2.2.2 established for a database credential.
- **Added** six new error codes: `STORAGE_PATH_DENIED`, `STORAGE_OBJECT_TOO_LARGE`, `STORAGE_WRITE_NOT_PERMITTED`, `STORAGE_OBJECT_NOT_FOUND`, `STORAGE_SCOPE_INVALID`, and `STORAGE_BACKEND_FAILED` (the last one beyond the build prompt's own list, mirroring `DB_CONNECTION_FAILED`). Deliberately **no** "sanitization failed" code — a supplied path is canonicalized then proven in-scope or denied outright, there is no partial-sanitize outcome to name.
- **New dependency**: `boto3` (S3-compatible object storage; also serves MinIO/any S3-compatible target via a declared `endpoint_url`).
- **Explicitly out of scope, per the build prompt**: queue connector (2.2.4), vendor-specific connectors, identity federation (2.3.1), content parsing/extraction (the Knowledge Engine's job, Milestone 7 — this connector moves bytes, it does not parse them), any change to model/tool execution.
- **No migration** — every table touched already exists (`connectors`/`connector_instances`/`connector_credentials`/`authorization_audit`). **No new HTTP route** — instance configuration reuses the existing `POST`/`PATCH /connectors` endpoints; the invocation bridge is a direct, database-backed Python entry point.
- **S3/MinIO/Azure Blob coverage boundary stated explicitly**: S3 backend dispatch (bucket/key correctness, error translation) is proven against a mocked `boto3.client`, since no S3-compatible server is reachable in this environment — the underlying containment logic itself has full, unmocked coverage in `scope.py`'s own tests, since it is backend-agnostic pure Python. Azure Blob has no coverage beyond the "recognized but backend-pending" rejection test.
- 82 new backend tests (`tests/integration/test_storage_scope.py`, 41 — the isolated security core, no live storage anywhere in the file; `test_storage_connector.py`, 30 — scope/operations/limits/backend-dispatch/SDK-surface/integrity; `test_storage_connector_invocation.py`, 11 — end to end against a real, database-backed `ConnectorInstance` with a real, stored, encrypted credential). Backend **1,245** green (1,163 + 82), 0 failed, 1 deselected; frontend untouched by this backend-only phase, still **297** green. See [docs/integration/connectors.md](docs/integration/connectors.md)'s "Generic File & Object Storage Connector" section.

## [Unreleased] — Phase 2.2.2 · Generic Database Connector

**Milestone 2's second real connector — and the one carrying its single sharpest security rule: the model never writes SQL.** Not sanitized, not escaped, not validated-then-run — absent. There is no code path anywhere in this codebase that takes model-derived text and places it into SQL structure.

- **Added** `app/integration/connectors/database/` — `DatabaseConnector`, built through the SDK surface (one specific, documented, justified deviation — see below), turning declared, parameterized queries against PostgreSQL/MySQL into governed tools. SQL Server is a recognized but driver-pending dialect (`mssql+pyodbc` needs a system ODBC driver, not added this phase).
- **Added** `executor.py`, the security-critical component: its **only** public entry point, `execute_declared_query(engine, dialect, query: DeclaredQuery, params, row_limit, timeout_seconds)`, has no parameter position a raw SQL string could occupy — containment by absence, not a rejecting check. Parameters bound via SQLAlchemy's `text()` + a separate parameter mapping, never interpolated — proven against this platform's own real dev Postgres: `"'; DROP TABLE users; --"` and the classic UNION/comment/stacked-query/boolean-blind injection family all come back as inert literal values.
- **Added** row-limit (`fetchmany(row_limit + 1)`, rejected outright — never silently truncated — if exceeded) and timeout enforcement (a server-side `statement_timeout`/`MAX_EXECUTION_TIME` GUC plus a client-side thread + `Future.result(timeout=...)` backstop; a 3-second `pg_sleep` declared with a 1-second timeout terminates in ~1 second).
- **Added** read-only-by-default posture (`ACT-INT-FR-125`): every declared query's *trusted, human-authored* SQL (never model output) is classified read/write at configuration time by its first real keyword, fail-closed; a read-only instance declaring a mutating query is rejected outright with a new `DB_WRITE_NOT_PERMITTED`.
- **Added** `app/integration/connectors/database/invoker.py` — the tool-invocation bridge, mirroring 2.2.1's own exactly: fail-fast resolves the instance, resolves its credential bundle, gets/creates its per-instance connection pool, validates parameters against the named query's own declared schema, executes — proven end to end against this platform's own real dev Postgres, including a genuine stored/encrypted `BASIC` credential actually authenticating the connection (confirmed via `SELECT current_user`). **Not wired into `ToolGatewayService`/`tools_snapshot`/the model-driven tool loop** — Milestone 1 stays untouched.
- **Added** `ConnectorCredentialService.resolve_credential_bundle()` — an additive method returning the decrypted credential bundle itself rather than an HTTP-header-shaped `OutboundRequest`, since a database username/password has no natural HTTP-header meaning; shares its resolve/decrypt/OAuth2-refresh mechanics with 2.2.1's `resolve_and_apply_for_scheme()` via a new private helper.
- **The one justified SDK-surface deviation**: `connector.py` imports one specific, documented exception type (`DbWriteNotPermittedError`) beyond the pure-SDK-surface discipline 2.2.1 established, needed because `ACT-INT-FR-125` requires its own distinct, stable error code at configuration time — something 2.2.1 never needed. `declaration.py` itself stays exactly as SDK-surface-restricted as 2.2.1's own equivalent module.
- **Added** connection pooling per instance (an SQLAlchemy `Engine`, cached in-process per connector instance id, configurable `pool_size`/`max_overflow`) and credential protection (connection URLs built via `sqlalchemy.engine.URL.create()`, never a bare string; every driver-level failure reduced to a generic, safe message — never the connection string, host, or credential).
- **Added** six new error codes: `DB_QUERY_NOT_DECLARED`, `DB_PARAMETER_INVALID`, `DB_WRITE_NOT_PERMITTED`, `DB_RESULT_LIMIT_EXCEEDED`, `DB_QUERY_TIMEOUT`, and `DB_CONNECTION_FAILED` (the last one beyond the build prompt's own list — a small, justified addition so a connection failure has a distinct, assertable code that never echoes the connection string). Deliberately **no** "raw SQL rejected" code — no code path accepts raw SQL, so none is ever needed to reject it.
- **New dependency**: `PyMySQL` (pure-Python MySQL DBAPI driver, no system client library needed) for the MySQL dialect. PostgreSQL needed no new dependency (`psycopg2-binary` already backs the platform's own database).
- **Explicitly out of scope, per the build prompt**: storage/queue connectors (2.2.3/2.2.4), vendor-specific connectors, identity federation (2.3.1), **natural-language-to-SQL of any kind — permanently out of scope, the anti-goal this connector exists to prevent**, any change to model/tool execution.
- **No migration** — every table touched already exists (`connectors`/`connector_instances`/`connector_credentials`). **No new HTTP route** — instance configuration reuses the existing `POST`/`PATCH /connectors` endpoints; the invocation bridge is a direct, database-backed Python entry point.
- **MySQL/SQL Server coverage boundary stated explicitly**: injection-safety, bound-parameter, row-limit, and timeout tests all run against real PostgreSQL — the only dialect this test environment has a live server for. MySQL coverage this phase is driver-dispatch/declaration-parsing only, not proven against a live server; SQL Server has no driver and only the driver-pending rejection is tested.
- 42 new backend tests (`tests/integration/test_database_connector.py`, 35 — security core/declared-queries/read-only/limits/drivers/SDK-surface/integrity, most against real Postgres; `test_database_connector_invocation.py`, 7 — end to end against a real, database-backed `ConnectorInstance` with a real, stored, encrypted credential). Backend **1,163** green (1,121 + 42), 0 failed, 1 deselected; frontend untouched by this backend-only phase, still **297** green. See [docs/integration/connectors.md](docs/integration/connectors.md)'s "Generic Database Connector" section.

## [Unreleased] — Phase 2.2.1 · Generic REST Connector

**Milestone 2's first real connector, and the SDK's first real proving ground.** Any typical HTTP/JSON API becomes governed tools by declaration alone — no code, no vendor-specific logic anywhere in the runtime.

- **Added** `app/integration/connectors/rest/` — `RestConnector` (`connector.py`) built entirely through the 2.1.4 SDK surface. A connector instance's `configuration` declares a base URL, a per-instance authentication scheme, and one or more endpoints (method, path template, argument-to-request mapping, response extraction, optional pagination) — `declaration.py`'s `parse_declaration()`/`tool_contracts_for()` validate it structurally and semantically and derive one distinct `ToolContract` per endpoint (`ACT-INT-FR-102`).
- **Added** injection-safe request templating (`templating.py`): a path argument is percent-encoded with no safe characters (`"123/../admin"` renders as the single, inert segment `"123%2F..%2Fadmin"`, never escaping the declared endpoint); a header/query argument containing a control character is rejected outright; a body argument is placed into the JSON body as its own key/value, never string-interpolated.
- **Added** response extraction (`extraction.py`) — a dotted `response_field` path navigates the JSON response to the tool's output; an optional `output_schema` is validated with the same `jsonschema` library used elsewhere in this codebase.
- **Added** bounded pagination (`pagination.py`) — `offset_limit`/`page_number`/`cursor`, hard-capped at `min(declared max_pages, 100)` regardless of what the declaration or the remote server claims; a misbehaving server that never signals "done" cannot force an unbounded fetch.
- **Added** `app/integration/connectors/rest/invoker.py` — the first tool-invocation bridge built anywhere in this codebase: `invoke_tool()` fail-fast resolves a connector instance (the unchanged 2.1.3 registry), applies its declared authentication scheme via the existing 2.1.2 framework, renders and dispatches the request through `GovernedHttpClient`, drives pagination, and extracts the result — proven end to end against a real local HTTP server, including a genuine stored, encrypted `BEARER` credential reaching the server as a real header. **Not wired into `ToolGatewayService`/`tools_snapshot`/the model-driven tool loop** — Milestone 1 stays untouched, per this sub-phase's own scope.
- **Added** `ConnectorCredentialService.resolve_and_apply_for_scheme()` — an additive generalization of `resolve_and_apply()` (now a one-line wrapper over it) supporting a connector *instance's* own declared scheme rather than one scheme fixed per connector *type*, since a generic REST connector serves many vendor APIs from one registered type.
- **Fixed** `GovernedHttpClient.request()` silently dropping a query string embedded in its `url` argument (`execute_http_tool`'s `_build_target_url` only ever honored its own dedicated `query` parameter) — invisible to 2.1.4's query-free `WebhookConnector`, fatal to a paginated REST endpoint. Added a new, optional, backward-compatible `query` parameter; every existing caller (including 2.1.4's own tests) is unaffected.
- **Added** `REST_ENDPOINT_NOT_DECLARED`/`REST_TEMPLATE_INVALID`/`REST_EXTRACTION_FAILED` error codes. `TOOL_EGRESS_DENIED` is reused for allowlist/SSRF denials, per this sub-phase's own instruction not to invent a REST-specific egress code.
- **Added** a realistic four-endpoint vendor-like declaration (a support-ticketing CRM API: create/get/list-paginated/update) as the concrete `ACT-INT-FR-106` proof — a typical vendor REST integration is a configuration document, not an engineering project.
- **Explicitly out of scope, per the build prompt**: database/storage/queue connectors (2.2.2/2.2.3/2.2.4), GraphQL and vendor-specific connectors (fast-follow on this same framework), the connector marketplace/sandboxing (Milestone 12), identity federation (2.3.1), any change to model/tool execution.
- **No migration** — every table touched already exists; the declaration lives in the existing `connector_instances.configuration` JSONB column. **No new HTTP route** — instance configuration reuses the existing `POST`/`PATCH /connectors` endpoints; the invocation bridge is a direct, database-backed Python entry point.
- 41 new backend tests (`tests/integration/test_rest_connector.py`, 30 — declaration/templating/extraction/pagination/SDK-surface/integrity, no HTTP at all; `test_rest_connector_invocation.py`, 11 — end to end against a real local fixture server). Backend **1,121** green (1,080 + 41), 0 failed, 1 deselected; frontend untouched by this backend-only phase, still **297** green. See [docs/integration/connectors.md](docs/integration/connectors.md)'s "Generic REST Connector" section.

## [Unreleased] — Phase 2.1.4 · Connector SDK

**Completes the connector framework (Milestone 2, Phase 2.1).** A `Connector` now has an abstraction, a lifecycle, six authentication schemes, a registry, health monitoring, and a documented, containment-first SDK a trusted developer can author one through.

- **Added** `app/integration/sdk/` — the connector-authoring surface, explicit `__all__` re-exports only: `Connector`, the declaration types (`ConnectorDescriptor`/`ToolContract`/`ConnectorLifecycleState`), `SUPPORTED_AUTH_SCHEMES`, `validate_configuration_schema`/`ConnectorConfigInvalidError`, `GovernedHttpClient`, and the testing harness (`ConnectorTestHarness`/`HealthCheckOutcome`). Importing from `app.integration.sdk` is the supported contract; every other `app.integration.*`/`app.runtime.*` import is not, and may change without notice.
- **Added** `app/integration/sdk/http.py`'s `GovernedHttpClient` — the *only* network primitive the surface exposes, reusing Milestone 1's `egress_guard`/`http_executor` directly (not reimplemented). `allowed_hosts` is fixed at construction, never a per-call argument — a connector's own code cannot widen what it may reach at call time.
- **Added** the containment core (`ACT-INT-FR-066`): the SDK surface exposes no database session, no credential-resolution machinery (`AuthScheme`/`OutboundRequest`/`ConnectorCredentialService` all withheld), no raw HTTP client, no audit-suppression hook, and no route-registration mechanism — mechanically proven by a dedicated governance-inheritance test suite (AC-10..AC-15), not merely documented. An SDK connector cannot make an undeclared outbound call, receive a decrypted credential, suppress audit, or reach another tenant's data, because the SDK does not offer a method to do any of those.
- **Added** `app/integration/validation.py`'s `validate_declaration_complete()` — the single completeness check both the real registration path (`ConnectorTypeService.register()`, a new public method) and the SDK harness's pre-registration self-check call. A connector missing its config schema, capabilities, tool contracts, a declared/registered auth scheme, or a real `health_check()` implementation fails registration with `CONNECTOR_DECLARATION_INCOMPLETE`, naming exactly what's missing.
- **Added** `app/integration/sdk/example/webhook_connector.py`'s `WebhookConnector` (`SDK_EXAMPLE_WEBHOOK`) — a worked example built and tested using **only** the SDK surface, verified by an AST-based import-inspection test, not just by behavior. Registered through the identical `_CONNECTOR_TYPES`/`ensure_seeded` path as `MOCK`/`MOCK_AUTH` — registration parity proven by construction, not asserted.
- **Added** `ConnectorTypeService.register()` — the single, now genuinely public registration path; `ensure_seeded()` calls it once per `_CONNECTOR_TYPES` entry with no per-identifier branch.
- **Added** `CONNECTOR_DECLARATION_INCOMPLETE` error code (422).
- **Explicitly out of scope, per the build prompt**: the generic REST/database/storage/queue connectors (2.2.x — this SDK's own real proving ground), a distributable PyPI package (the surface isn't battle-tested yet), a connector marketplace/publishing/signing (Milestone 12), untrusted-third-party-code sandboxing (this SDK targets trusted, first-party authors — the module's own docstring states this boundary directly), identity federation (2.3.1).
- **No migration** — the SDK is an authoring surface over the existing schema. **No new HTTP route** — a code-authoring capability, not an API.
- 31 new backend tests (`tests/integration/test_connector_sdk.py`, 26; `test_connector_sdk_example.py`, 5 — kept in its own file so its import list is an isolated proof that the example's own tests use only the SDK harness). Backend **1,080** green (1,049 + 31), 0 failed, 1 deselected; frontend untouched by this backend-only phase, still **297** green. See [docs/integration/connectors.md](docs/integration/connectors.md)'s "Connector SDK" section.

## [Unreleased] — Phase 2.1.3 · Connector Registry & Health

- **Added** `app/integration/registry.py` — `ConnectorRegistry`, the
  single lookup surface for type resolution/listing (platform-wide) and
  tenant-scoped instance resolution/listing, wrapping 2.1.1's own
  services rather than duplicating them. Its `resolve_instance_for_invocation`
  is the **fail-fast wiring point** (`ACT-INT-FR-044`): raises
  `CONNECTOR_UNAVAILABLE` immediately for a `failed`/`disabled` instance,
  before any real call is ever attempted — Phase 2.2.x's tool bridge
  inherits this guarantee for free.
- **Added** `Connector.health_check(configuration) -> bool` — a new,
  additive abstract method on the ABC (deliberate and expected this
  sub-phase, unlike the still-absent `authenticate()`/`execute()`).
  Answers reachability only; receives only the instance's own
  `configuration`, **never a credential** — auth validity is checked
  entirely separately, by reusing `ConnectorCredentialService.validate()`
  (2.1.2), not duplicated. `MockConnector`/`MockAuthenticatedConnector`
  both implement it, configurable via `simulate_unreachable`/
  `simulate_error` in the instance's own stored configuration.
- **Added** `app/integration/health.py` — `ConnectorHealthService.check()`
  combines both probes into `HEALTHY`/`UNHEALTHY`/`ERROR`: `ERROR`
  (a probe raised) is distinct from a completed `UNHEALTHY` result —
  `POST .../health/check` returns 502 (`CONNECTOR_HEALTH_CHECK_FAILED`)
  for the former, 200 with the result body for the latter.
- **Added** automated `active -> failed`/`failed -> active` transitions:
  a failing check on an `active` instance calls the pre-existing,
  unchanged `ConnectorService.mark_failed`; a passing check on a
  `failed` instance calls a new `ConnectorService.recover` method and a
  new `recover` event added to `lifecycle.py`'s transition graph — both
  through the same, unbypassed 2.1.1 state machine.
- **Added** alerting via the *existing* audit-event mechanism, not a new
  channel: `ConnectorService._transition` now tags
  `INTEGRATION_CONNECTOR_STATE_CHANGED`'s `meta.severity` as `CRITICAL`
  when `to_state == "failed"` — the same severity-tagged, dashboard-
  reviewed (not pushed) pattern Phase 5.6a.1's `RUNTIME_TOOL_EGRESS_DENIED`
  already established. `app/services/notification_service.py` was
  examined and rejected (no subscription/recipient-list concept to hook
  a connector event into).
- **Added** `app/integration/scheduler.py` — an interim, in-process
  `asyncio` background task, off by default everywhere including every
  test run (`CONNECTOR_HEALTH_SCHEDULER_ENABLED=false`), explicitly
  documented as replaceable by Milestone 3's real scheduler rather than
  extended toward a distributed system (REPO_STATE §10.2). `run_sweep_once()`
  is a plain synchronous function tests call directly instead of waiting
  on the loop's sleep.
- **Added** `connector_health_checks` (migration `0035_connector_health`)
  — append-only history, capped at 200 rows per instance (a simple
  rollup, not a time-based policy); `connector_instances` gained a
  two-column health cache (`last_health_check_at`, `current_health`).
- **Added** 3 new routes under `/api/v1/integration` (`GET .../health`,
  `POST .../health/check`, `GET .../health/history`), reusing 2.1.1/
  2.1.2's permissions; 2 new error codes (`CONNECTOR_UNAVAILABLE`,
  `CONNECTOR_HEALTH_CHECK_FAILED`); 1 new audit event
  (`INTEGRATION_CONNECTOR_HEALTH_CHECKED`).
- **Changed** `ConnectorCredentialService.validate()`'s `actor` parameter
  to optional (`User | None`), additively, so the scheduler's
  system-triggered checks can call it with no human actor — every
  existing caller still passes a real one.
- **Fixed** (test-authoring, not production code): one pre-existing 2.1.1
  test (`test_ac03_mock_connector_satisfies_the_interface_without_an_abc_change`)
  asserted the ABC's method set was exactly `{describe,
  validate_configuration}` — updated to include the deliberately grown
  `health_check`, not a weakening (the test's actual intent still holds
  and is still checked).
- **Explicitly out of scope, per the build prompt**: the connector SDK
  (2.1.4), any real connector, the connector-to-tool bridge's actual
  invocation logic (2.1.3 built the fail-fast resolution boundary it
  will call, not the bridge itself), identity federation (2.3.1), and
  any distributed job scheduler (Milestone 3).
- 24 new backend tests (`tests/integration/test_connector_health.py`).
  Backend **1,049** green (1,025 + 24), 0 failed, 1 deselected; frontend
  untouched by this backend-only phase, still **297** green. See
  [docs/integration/connectors.md](docs/integration/connectors.md)'s
  "Registry & Health" section.

## [Unreleased] — Phase 2.1.2 · Connector Authentication Framework

- **Added** `app/integration/auth/` — a pluggable authentication scheme
  framework: `base.py` (the `AuthScheme` abstract interface and the
  connector-neutral `OutboundRequest` fixture), `registry.py` (explicit
  `register()`/`resolve()`, mirroring the provider/connector registry
  pattern), and six registered implementations under `schemes/` — static
  API key, bearer token, HTTP basic, OAuth2 client-credentials, OAuth2
  authorization-code, and mTLS.
- **Added** `ConnectorCredentialService` (`auth/service.py`) storing one
  encrypted JSON-bundle-per-`(connector_instance_id, auth_scheme)` row —
  **reusing `app/runtime/providers/credential_crypto.py`'s
  `encrypt_secret`/`decrypt_secret`/`mask_hint` directly**, verified by
  object identity in tests, not just behavior. No extraction or
  generalization was needed: those three functions already had zero
  provider-specific logic in their own bodies, the same precedent Phase
  5.6a.1's `ToolCredentialService` already set for tool credentials. The
  platform-held-Fernet-key Known Deviation is inherited from
  5.7a.5/5.6a.1, not newly introduced.
- **Added** `app/integration/auth/token_manager.py` — OAuth2 token
  acquisition, encrypted caching, and transparent refresh across all
  three grant types (client-credentials, authorization-code, refresh-
  token). **Concurrency-safe by design**: `get_valid_access_token` locks
  the *parent* `connector_instances` row (not the token row, which may
  not exist yet on a first acquisition) via `SELECT ... FOR UPDATE` —
  proven with real threads against real Postgres connections
  (`test_ac13_concurrent_refresh_does_not_double_refresh`, a fixture
  transport with an artificial delay widening the race window, asserting
  the token endpoint was hit exactly once).
- **Added** the OAuth2 authorization-code flow's built half: stored
  client configuration, `build_authorization_url()` (URL construction
  only, no HTTP route since the build prompt's own endpoint table didn't
  list one), the `GET`/`POST .../oauth/callback` code→token exchange,
  and refresh-and-apply given a stored refresh token. **Stubbed, stated
  plainly**: the interactive consent-redirect UI itself — an explicit
  front-end concern, out of scope for this backend-only sub-phase.
- **Added** `connector_credentials`/`connector_oauth_tokens` tables
  (migration `0034_connector_auth`) — neither stores a structured
  plaintext credential field, only ciphertext + a masked hint.
- **Added** `MockAuthenticatedConnector` (`app/integration/mock_authenticated.py`)
  alongside (not replacing) 2.1.1's `MockConnector`, declaring a real
  `API_KEY` auth requirement so the framework is exercised end to end
  against a mock — no real connector invokes anything yet (2.1.3/2.2.x).
- **Added** 7 new routes under `/api/v1/integration` (`GET
  /auth-schemes`, `GET`/`PUT`/`DELETE .../credentials`, `POST
  .../credentials/validate`, `GET`/`POST .../oauth/callback`), reusing
  2.1.1's two permissions rather than adding a finer
  `integration.credential.manage` (stated as not warranted — a
  credential is a property of a connector instance, not a separately
  access-controlled resource).
- **Added** 4 new error codes (`CONNECTOR_CREDENTIAL_NOT_FOUND`/
  `CONNECTOR_AUTH_SCHEME_UNSUPPORTED`/`CONNECTOR_CREDENTIAL_INVALID`/
  `CONNECTOR_OAUTH_REFRESH_FAILED`) and 3 new audit events
  (`INTEGRATION_CONNECTOR_CREDENTIAL_UPDATED`/`_DELETED`/`_VALIDATED`).
- **Explicitly out of scope, per the build prompt**: connector registry &
  health (2.1.3), the connector SDK (2.1.4), any real connector, and
  identity federation (2.3.1 — the opposite direction: a platform *user*
  authenticating via an enterprise IdP, not the platform authenticating
  itself to an external system).
- 31 new backend tests (`tests/integration/test_connector_auth.py`),
  including the real-thread OAuth2 concurrency proof and a full redaction
  sweep (no credential value in logs, audit `meta`, or API responses).
  Backend **1,025** green (994 + 31), 0 failed, 1 deselected; frontend
  untouched by this backend-only phase, still **297** green. See
  [docs/integration/connectors.md](docs/integration/connectors.md)'s
  "Authentication" section.

## [Unreleased] — Phase 2.1.1 · Connector Abstraction & Lifecycle

- **Added** `app/integration/` — a new sibling domain to `app/runtime/`
  (Milestone 2's first sub-phase): `base.py` (the `Connector` abstract
  interface — `describe()`/`validate_configuration()` abstract, deliberately
  no `authenticate()`/`execute()`/`health_check()`, all left to the
  sub-phases that actually need them), `types.py` (connector-neutral
  `ConnectorDescriptor`/`ToolContract`/`ConnectorLifecycleState` — frozen,
  slotted dataclasses, `MappingProxyType`-wrapped dict fields, mirroring
  `app/runtime/providers/types.py`'s own precedent), `lifecycle.py` (the
  single transition authority for the five-state machine
  `registered → configured → active → disabled → failed`), `mock.py`
  (`MockConnector`, the trivial reference implementation), `service.py`
  (`ConnectorTypeService`/`ConnectorService`), `errors.py`, `routes.py`,
  `schemas.py`.
- **Added** `Connector`, `ConnectorInstance`, `ConnectorLifecycleEvent` ORM
  models (`app/models/integration.py`) and migration `0033_connector_core`
  — three new tables, no existing table touched: `connectors` (registered
  types, unique on `connector_type`+`version`), `connector_instances`
  (tenant-scoped, unique on `organization_id`+`name`, **no credential
  column** — that's Phase 2.1.2), `connector_lifecycle_events`
  (append-only, no update/delete path anywhere).
- **Added** the **runtime-never-knows principle**, enforced by construction
  rather than convention: a test greps every file under `app/runtime/` for
  the substring `"connector"` and fails the build if it finds one
  (`ACT-INT-FR-006`) — currently zero.
- **Added** config validation that reuses Milestone 1's `jsonschema`
  library via a new thin wrapper (`validate_configuration_schema`), not a
  new validator.
- **Added** 8 routes under `/api/v1/integration` (connector types, tenant
  instances CRUD, `activate`/`disable`, lifecycle events) and 2 new
  permissions (`integration.connector.view`/`.manage`).
- **Added** 4 new error codes (`CONNECTOR_TYPE_NOT_FOUND`/
  `CONNECTOR_NOT_FOUND`/`CONNECTOR_CONFIG_INVALID`/
  `CONNECTOR_INVALID_TRANSITION`) and 1 new audit event
  (`INTEGRATION_CONNECTOR_STATE_CHANGED`, dual-written to both the
  lifecycle-events table and the platform-wide `AuthorizationAuditService`).
- **Explicitly out of scope, per the build prompt**: authentication
  framework (2.1.2), connector registry & health monitoring (2.1.3), the
  connector SDK (2.1.4), any real connector, and the connector-to-tool
  bridge that would actually make a declared tool contract invokable.
- 24 new backend tests (`tests/integration/test_connector_core.py`, a new
  top-level test directory with its own minimal fixtures). Backend
  **994** green (970 + 24), 0 failed, 1 deselected; frontend untouched by
  this backend-only phase, still **297** green. See
  [docs/integration/connectors.md](docs/integration/connectors.md).

## [Unreleased] — Phase 5.6a.3 · Model-Driven Tool Invocation Loop

**Completes Milestone 1** — an agent registered, versioned, signed and
deployed now genuinely executes end to end: calls a real model, the model
requests a real tool, the tool runs safely, the result feeds back, the
loop resolves to a final answer, every token/call/decision audited.

- **Added** `ToolLoopOrchestrator` (`app/runtime/services.py`), driving
  model → tool → model over `ModelGatewayService.invoke()` and
  `ToolGatewayService.invoke()`, both entirely unchanged — every existing
  authorization check, egress guard, and schema-validation/resilience path
  applies automatically, with zero new code.
- **Added** two additive, both-optional parameters to
  `ModelGatewayService.invoke()` (`conversation`, `tools`) — a version's
  frozen `tools_snapshot` is offered only to a provider whose `describe()`
  declares `supports_tools` (`MOCK` never does, so every 5.6a.1/5.6a.2
  test — all `MOCK`-based — is completely unaffected).
- **Added** four independent termination caps — max iterations, token
  budget, wall-clock, repeated-identical-call (reusing Phase 5.2.4's
  canonical serialization for "identical call" comparison) — each ending
  in a distinct, audited `agent_executions.termination_reason`.
- **Added** real parallel execution of tool calls the model requests
  together, gated by the same `idempotent` flag 5.6a.2 introduced, reused
  for a second purpose: safe-to-retry ⟺ safe-to-run-alongside-siblings. A
  single non-idempotent tool anywhere in a batch drops the whole batch to
  sequential, model-given order.
- **Fixed** a genuine deadlock, found by reproducing it directly against
  `pg_stat_activity`, not guessed at: the first parallel-execution design
  opened a fresh `Session` per worker thread, whose `INSERT INTO
  tool_calls` blocked on the still-`FOR UPDATE`-locked `agent_executions`
  row from `claim_next`, while the main thread blocked on those same
  worker threads via `future.result()`. Fixed by committing the claiming
  session immediately before any parallel dispatch.
- **Added** `TOOL_NOT_BOUND_TO_VERSION` — a tool named outside the
  version's frozen `tools_snapshot` is a scope violation, not a
  recoverable mistake the model gets to iterate past; this is also where
  "no agent-to-agent chaining" is structurally enforced, since a tool is
  the only thing this loop can ever name.
- **Added** `execution_messages` table (migration `0032_tool_loop`) — the
  full conversation transcript, exposed at `GET /executions/{id}/messages`;
  `agent_executions` gained `loop_iterations`/`termination_reason`,
  `tool_calls` gained `loop_iteration`.
- 17 new backend tests including an end-to-end proof (real fixtured model
  → real HTTP tool through the egress guard → final answer, fully
  audited). Backend **970** green (953 + 17), 0 failed, 1 deselected;
  frontend untouched, still **297** green. See
  [docs/runtime/gateways.md](docs/runtime/gateways.md)'s "Milestone 1 —
  complete" section.

## [Unreleased] — Phase 5.6a.2 · Tool Schema Validation & Resilience

- **Added** argument validation against `Tool.input_schema` before any
  side effect runs — before `FUNCTION`'s echo, and before the `HTTP`
  branch even builds an egress policy. A violation returns
  `TOOL_SCHEMA_INVALID` with a structured, JSON-encoded
  `ToolCall.validation_error`; no request is issued. A response is
  validated against an optional `output_schema` only when one is
  declared. Both frozen into the version snapshot at publish time,
  alongside `http_config.timeout_seconds` (closing a gap 5.6a.1 left
  open — that phase read the live, mutable `Tool.timeout_seconds` column
  at execution time).
- **Reused — not duplicated** — Phase 5.7a.4's `ProviderErrorClass`
  taxonomy and retry/circuit-breaker machinery for a tool's HTTP-level
  failures; the one piece that wasn't already provider-neutral (what
  happens when the circuit is open) was extracted into a shared core so
  both the model and tool paths use one implementation.
- **Added** idempotency as an explicit, opt-in `http_config.idempotent`
  declaration — never inferred from HTTP method; undeclared or `false`
  means a transient failure is never retried. A retried call gets one new
  `ToolCall` row per attempt.
- **Added** a new per-execution concurrency ceiling
  (`app/runtime/tools/concurrency.py`) — real-thread-tested, not yet
  contended until 5.6a.3's parallel tool execution.
- **Changed** (behavior change from 5.6a.1): a `FAILED` tool call (schema
  violation, exhausted retry, timeout, oversized response, open circuit,
  concurrency-ceiling rejection) no longer aborts the whole execution —
  only a governance/egress `DENIED` call still does.
- **Added** five new error codes (`TOOL_SCHEMA_INVALID`/
  `TOOL_RESPONSE_TOO_LARGE`/`TOOL_TIMEOUT`/`TOOL_EXECUTION_FAILED`/
  `TOOL_CONCURRENCY_LIMIT_EXCEEDED`) and `RUNTIME_TOOL_FAILED`; migration
  `0031_tool_resilience` (three new nullable `tool_calls` columns, no new
  table).
- 19 new backend tests. Backend **953** green (934 + 19), 0 failed, 1
  deselected; frontend untouched, still **297** green.

## [Unreleased] — Phase 5.6a.1 · HTTP Tool Execution & Egress Control

The first tool-side sub-phase of Milestone 1 — closes the other half of
the same untested assumption every phase before it rested on: every
agent so far could only call the built-in `FUNCTION`/`echo` action.

- **Added** `app/runtime/tools/` — a new package: `egress_guard.py` (pure
  logic, no network/database — `EgressPolicy`/`EgressDecision`/
  `evaluate_url`/`resolve_and_validate`, plus a permissive IP-literal
  parser catching decimal/octal/hex loopback encodings some platforms'
  libc resolvers accept but Python's `ipaddress` module rejects) and
  `http_executor.py` (`execute_http_tool`, `_PinnedTransport` — connects
  to the address the guard validated, never a freshly re-resolved
  hostname, defending against DNS rebinding; verified empirically against
  the installed `httpx`/`httpcore` before writing tests).
- **Added** a real `HTTP` action to `ToolGatewayService` (`FUNCTION`/
  `echo` unchanged), reading its egress policy from the *frozen* version
  snapshot, never live, mutable `Tool` state — `SnapshotBuilderService`
  gained a new `runtime.tool_configs` snapshot key (`tools_snapshot`
  itself deliberately untouched — three existing subsystems consume its
  bare-id-list shape).
- **Added** `tool_credentials` table and `ToolCredentialService`, reusing
  Phase 5.7a.5's `credential_crypto.py` directly.
- **Added** `TOOL_EGRESS_DENIED` error code and `RUNTIME_TOOL_INVOKED`/
  `RUNTIME_TOOL_EGRESS_DENIED` audit events — the latter `CRITICAL`
  severity (an egress denial is a signal someone may be probing the SSRF
  boundary).
- Migration `0030_http_tool_egress`: `tools.http_config` (JSONB), eight
  new columns on `tool_calls` (egress/HTTP recording), new
  `tool_credentials` table.
- 51 new backend tests: 32 in `test_egress_guard.py` (every SSRF vector
  individually, no network/database), 19 in `test_http_tool_execution.py`
  (executor mechanics against real local `127.0.0.1` fixture servers).
  Backend **934** green (883 + 51), 0 failed, 1 deselected; frontend
  untouched, still **297** green. See
  [docs/runtime/gateways.md](docs/runtime/gateways.md)'s "Egress
  control" section.

## [Unreleased] — Phase 5.7a.5 · Per-Organization Provider Credentials

**Completes the model half of Milestone 1** — only tool execution
(5.6a.1-3) remained before the platform genuinely executed end to end.

- **Added** `provider_credentials` table (migration
  `0029_provider_credentials`): one row per `(organization_id, provider)`,
  `encrypted_secret` a Fernet ciphertext
  (`app/runtime/providers/credential_crypto.py`, new file — key from
  `settings.MODEL_CREDENTIAL_ENCRYPTION_KEY` or auto-generated/persisted
  to `.keys/`, mirroring Phase 5.2.4's `LocalKeyProvider` pattern).
- **Added** `ProviderCredentialService` (`store`/`get_metadata`/
  `resolve_secret`/`delete`/`list_for_org`/`test`) with an explicit
  resolution order (`ACT-MDL-FR-082`): per-organization stored credential
  → `MODEL_PROVIDER_API_KEYS` fallback → none — a real provider rejecting
  an unauthenticated call with nothing configured anywhere is translated
  from the generic `AUTHENTICATION_FAILED` to the more specific,
  non-retryable `PROVIDER_CREDENTIAL_REQUIRED`.
- **Added** synchronous credential resolution on the worker's own thread
  in `ExecutionWorkerService._execute`, *before* the model call is handed
  to its `ThreadPoolExecutor` — a live `Session` cannot safely cross that
  thread boundary, so only the resulting plain `ResolvedCredential` value
  does.
- **Added** 4 new routes under `/api/v1/runtime/providers/{provider}/credentials`
  (`GET`/`PUT`/`DELETE`/`POST .../test`) and 2 new permissions
  (`runtime.provider.view`/`.manage`).
- **Kept** `MODEL_PROVIDER_API_KEYS` as the fallback default (not
  removed) — no previously-passing test broke.
- 25 new backend tests. Backend **883** green (858 + 25), 0 failed, 1
  deselected; frontend untouched, still **297** green.

## [Unreleased] — Phase 5.7a.4 · Error Taxonomy & Resilience

- **Added** an eight-class provider-neutral failure taxonomy
  (`ProviderErrorClass`): `RATE_LIMITED`/`PROVIDER_UNAVAILABLE`/`TIMEOUT`
  retryable; `CONTEXT_LENGTH_EXCEEDED`/`CONTENT_FILTERED`/
  `AUTHENTICATION_FAILED`/`INVALID_REQUEST`/`UNKNOWN` never retried.
  Classification lives in the adapter (`openai_compatible.py`);
  retry/backoff/circuit-breaking live in the service layer
  (`ModelGatewayService`), so a future second adapter inherits both with
  zero new retry code.
- **Added** exponential-with-jitter backoff, a provider's own
  `Retry-After` header honored in preference to computed backoff, a
  per-provider in-process three-state circuit breaker, and a streaming
  pre-/post-first-token retry boundary (a pre-first-token interruption
  retries; a post-first-token one persists the partial and is never
  retried).
- **Added** credential/base-URL scrubbing before any message reaches a
  log or caller.
- **Changed** the pre-existing execution-level retry
  (`ExecutionWorkerService._fail_or_retry`, Phase 5.0) is untouched
  except its `non_retryable` set gained the five non-retryable classes.
- **No schema migration** — `error_code` (already `VARCHAR(50)` on both
  `agent_executions` and `execution_attempts`) now stores the taxonomy
  class string in place of the old generic code.
- 36 new backend tests plus nine new committed error fixtures. Backend
  **858** green (822 + 36), 0 failed, 1 deselected; frontend untouched,
  still **297** green.

## [Unreleased] — Phase 5.7a.3 · Streaming & Token Accounting

- **Added** real SSE streaming, replacing 5.7a.2's `stream()` placeholder
  — incremental content deltas, tool-call reassembly across
  fragmented/interleaved chunks; an interrupted stream persists a partial
  via `FinishReason.ERROR` rather than raising (deliberately unlike
  `complete()`).
- **Added** an opt-in streaming path to `ModelGatewayService.invoke()`
  (`model_configuration.stream=true`) — the `(output_payload, usage)`
  contract stays unchanged for every non-streaming caller.
- **Added** real token/cost accounting: `usage` gained
  `token_accounting_complete`/`was_streamed`/`stream_interrupted`/
  `time_to_first_token_ms`/`generation_duration_ms`/`finish_reason`; a
  provider omitting usage now reports `{}` — never zero-filled (the
  never-estimate rule, `ACT-MDL-FR-046`).
- **Added** `model_pricing` table with effective dating (a price change
  inserts and closes a row, never mutates one in place) backing
  `PricingService`, replacing the flat placeholder rate; local/unpriced
  providers (`MOCK`) honestly cost `0`.
- Migration `0028_streaming_and_pricing`: new `model_pricing` table
  (seeded), 12 new columns on `agent_executions`, 4 on
  `execution_attempts`; 1,538 pre-existing non-zero-cost rows marked
  `cost_is_estimated=true`, never recomputed.
- 22 new backend tests. Backend **822** green (800 + 22), 0 failed, 1
  deselected; frontend untouched, still **297** green.

## [Unreleased] — Phase 5.7a.2 · First Real Provider Adapter

- **Added** `OpenAICompatibleProvider`
  (`app/runtime/providers/openai_compatible.py`) — the first real,
  network-calling provider, speaking the OpenAI chat-completions wire
  protocol against any `base_url` (Ollama/vLLM/LM Studio/OpenAI),
  registered as `"OPENAI_COMPATIBLE"` (names the protocol, not a vendor —
  `"OPENAI"` deliberately left free for a future vendor-specific
  adapter). Message/tool-call/finish-reason translation,
  sampling-parameter filtering, tolerant parsing of responses missing
  optional fields.
- **Fixed** `registry.resolve()` to actually forward `model`/`api_key` to
  the provider instance — a genuine 5.7a.1 gap where neither previously
  reached further than usage-reporting strings.
- **Added** `ProviderRequestFailedError`/`MODEL_PROVIDER_REQUEST_FAILED`
  — one coarse exception, not a taxonomy (classifying failure modes for
  retry is 5.7a.4's job).
- **Added** fixture-replay test infrastructure (`httpx.MockTransport`,
  six committed wire-format fixtures, a manual recorder script, a
  `live_provider` pytest marker excluded by default via
  `backend/pytest.ini`).
- 30 new backend tests (`test_openai_compatible_provider.py` plus
  additions to `test_provider_abstraction.py`); `registered_identifiers()`
  now returns `["MOCK", "OPENAI_COMPATIBLE"]`. Backend **800** green (766
  + 34 including conformance-suite additions), 0 failed, 1 deselected
  (the new `live_provider`-marked genuinely-live Ollama check); frontend
  untouched, still **297** green.

## [Unreleased] — Phase 5.7a.1 · Model Provider Abstraction & Registry

- **Added** `app/runtime/providers/` — a new package: `base.py` (the
  `ModelProvider` abstract interface: `complete()`/`stream()`/`describe()`
  abstract, `supports()` concrete and derived from `describe()`),
  `types.py` (the provider-neutral internal representation —
  `ModelMessage`, `ModelRequest`, `ModelResponse`, `ModelToolDefinition`,
  `ModelToolCall`, `ModelCapabilities`, `FinishReason` — all immutable,
  frozen/slotted dataclasses with `MappingProxyType`-wrapped dict fields),
  `registry.py` (explicit `register()`/`resolve()`, not directory-scanning
  discovery), `mock.py` (`MockProvider`, the first implementation),
  `errors.py` (`ProviderUnavailableError`, `CapabilityUnsupportedError`).
- **Migrated** `MOCK` onto the new interface with unchanged externally
  observable behavior: exact input echo, `provider == "MOCK"`, a positive
  token count. The exact wording of the completion text and exact token
  counts changed internally (dict-key-count vs. message-count), but
  nothing in the test suite ever asserted on either — zero pre-existing
  tests needed modification.
- **Refactored** `ModelGatewayService.invoke()` to resolve providers via
  the registry instead of an inline `MOCK`-only branch. Public signature
  and `(output_payload, usage)` return shape unchanged; provider selection
  still reads only from the version's frozen `model_configuration`, never
  from mutable agent/deployment state. `AuthorizationGateway` is
  untouched — it already ran at an earlier pipeline stage
  (`request_execution`, before an execution is even queued), well before
  provider resolution.
- **Added** capability declaration and enforcement
  (`ACT-MDL-FR-009`): a request asking a provider for something its own
  `describe()` says it doesn't support (e.g. tool definitions sent to
  `MockProvider`, which declares `supports_tools=False`) raises
  `MODEL_CAPABILITY_UNSUPPORTED` (422) rather than being silently ignored
  or mishandled.
- **Added** a reusable, parameterized conformance test suite
  (`PROVIDERS_UNDER_TEST` in `tests/runtime/test_provider_abstraction.py`)
  — every future adapter (starting with Phase 5.7a.2's real provider) is
  validated against it by adding one line, not copying tests.
- **Added** `MODEL_CAPABILITY_UNSUPPORTED` error code;
  `MODEL_PROVIDER_UNAVAILABLE` preserved exactly. Added
  `MODEL_DEFAULT_PROVIDER`/`MODEL_PROVIDER_BASE_URLS` settings
  (`ACT-MDL-FR-010` — per-provider base URL configuration, proven
  end-to-end even though `MOCK` has nothing to call).
- **No schema migration** — this sub-phase is purely an application-layer
  abstraction over the existing `model_configuration` JSONB column.
- **Explicitly out of scope, per the build prompt**: any real provider
  implementation (5.7a.2), streaming (5.7a.3), token accounting/cost
  (5.7a.3/5.7a.5), a real error taxonomy and retry (5.7a.4), credential
  storage (5.7a.5).
- 23 new backend tests (`tests/runtime/test_provider_abstraction.py`) —
  unit/conformance (no database) plus 4 integration tests proving the
  execution pipeline actually routes through the new abstraction
  end-to-end. Backend **766** green (743 + 23), 0 failed; frontend
  untouched by this backend-only phase, still **297** green.

## [Unreleased] — Phase 5.2.4 · Cryptographic Signing, Provenance & Portable Attestation

- **Added** `app/runtime/versioning/canonical.py` — the single canonical
  serialization implementation (sorted keys by Unicode code point, NFC
  string normalization, UTF-8, no whitespace, non-ASCII literal, floats
  rejected outright) now shared by every checksum producer/verifier.
  Refactored `_checksum()` (`services.py`) and `checksum_of()`
  (`snapshot.py`) to delegate to it; the original routines are kept,
  renamed `_legacy_checksum`/`_legacy_checksum_of` and marked deprecated,
  to verify rows created before this phase.
- **Added** `checksum_algorithm` on `agent_versions`/
  `agent_version_snapshots` (migration `0027_version_signing`) —
  `'legacy-sha256'` for existing rows (untouched by the migration itself),
  `'canonical-sha256'` for new ones; verification branches on it. Both
  `checksum` columns widened to fit the new `sha256:<hex>` prefixed format.
  `backend/scripts/recompute_checksums.py` (with `--dry-run`) is the
  explicit, audited way to upgrade legacy rows.
- **Fixed** `build_snapshot()` embedding raw `datetime` objects for
  `release_window_start`/`release_window_end`/`support_end_date`, silently
  tolerated by the old checksum routine's `default=str`; now `.isoformat()`
  strings, a precondition canonical.py's stricter typing surfaced.
- **Added** `SigningProvider` abstraction (`app/runtime/versioning/signing/`)
  — `LocalKeyProvider` (Ed25519, gitignored `.keys/`, auto-generates a dev
  keypair on first use) is the only implementation; swapping to Azure Key
  Vault at deployment is a configuration change, not a rewrite. Private key
  material never crosses the interface.
- **Added** `AttestationService` (`app/runtime/versioning/attestation.py`):
  builds an in-toto Statement v1 predicate + DSSE envelope
  (`application/vnd.in-toto+json`) per published version, signs the DSSE
  Pre-Authentication Encoding (not the raw payload) via the configured
  provider. Self-contained by design — every predicate claim is
  interpretable from the document alone, no database lookup required.
- **Added** signing to `publish()`, fail-closed — the opposite policy from
  Phase 5.2.6's advisory compatibility analysis: a signing failure raises
  out of `publish()` entirely, and the version never reaches `PUBLISHED`.
- **Added** key rotation/revocation (`SigningKeyService`,
  `app/runtime/versioning/keys.py`) — revocation marks affected signatures
  `KEY_REVOKED` without altering the version record or signature bytes;
  rotation keeps prior key versions retrievable so old signatures stay
  verifiable.
- **Wired** the previously-always-null `agent_versions.signature_id` to the
  primary (`PUBLISHER`) signature's id, rather than dropping the column.
- **Added** migration `0027_version_signing`: new tables `signing_keys`,
  `signing_key_versions`, `agent_version_signatures`,
  `agent_version_provenance`; `agent_versions` gains `signed_at`/
  `manifest_digest`.
- **Added** 8 routes (`.../signatures`, `.../provenance`,
  `.../attestation`, `.../verify`, `.../countersign`, `/signing-keys`,
  `/signing-keys/{id}/rotate`, `/signing-keys/{id}/revoke`) and 2 new
  permissions (`runtime.signing.view`/`.manage`); the countersign endpoint
  reuses the existing `runtime.agent.approve` rather than inventing a
  `runtime.version.approve` synonym.
- **Deliberately deferred** (see `docs/runtime/versioning.md`'s Known
  Deviations): a public/unauthenticated verification endpoint
  (`ACT-VER-FR-070`) — every route here is authenticated and
  organization-scoped; Azure Key Vault as a second `SigningProvider`
  (`ACT-VER-NFR-002`'s closure condition) — the local provider necessarily
  loads private key bytes into process memory to sign, by construction.
- Two pre-existing tests updated in place (asserted the legacy bare-64-hex
  checksum length; now assert the new `sha256:<hex>` format) — the only
  tests touched, per this phase's own one-exception rule.
- 47 new backend tests (`tests/runtime/test_canonical.py`,
  `test_version_signing.py`, `test_attestation.py`). Backend **743** green
  (696 + 47); frontend untouched by this backend-only phase, still **297**
  green.

## [Unreleased] — Phase 5.2.6 · Compatibility & Breaking-Change Detection

- **Added** `CompatibilityAnalysisService` (`app/runtime/versioning/compatibility.py`):
  classifies a candidate version against a resolved baseline into
  `COMPATIBLE`/`BACKWARD_COMPATIBLE`/`BREAKING`/`UNKNOWN` — input/output
  contract (JSON Schema diff on `AgentDefinition.input_schema`/
  `output_schema`), tool/capability bindings, model provider/config
  changes, a numeric resource-limit heuristic, policy tightening
  (`approved_models`, `prohibited_environments`,
  `requires_approval_environments`), and prompt/metadata changes.
- **Added** migration `0026_version_compatibility`: `agent_versions` gains
  `compatibility_baseline_id`/`compatibility_analyzed_at`; new table
  `agent_version_compatibility_findings` (one row per detected change,
  replaced wholesale on re-analysis, never accumulated).
- **Added** automatic compatibility analysis right after `publish()`'s own
  commit succeeds — failure-tolerant: an analyzer exception is logged and
  swallowed, never blocking publication. Also available on demand via
  `POST .../versions/{id}/compatibility/analyze` (recomputes and persists;
  backfills versions published before this phase existed).
- **Added** three routes: `GET`/`POST .../versions/{id}/compatibility`,
  `GET .../versions/{id}/compatibility/findings` — all reuse
  `runtime.version.view` (no new permission).
- **Replaced** `VersionReadinessService`'s `compatibility_analysis` check
  — no longer always `skipped: true`; now a real evaluation that warns
  (doesn't fail) on a correctly major-bumped breaking change and fails
  only on genuine semver/compatibility inconsistency, still never gating
  any lifecycle action.
- **Deliberate SRS deviation**: semver/compatibility-level inconsistency
  is reported (`semver_consistent: false`, a failed readiness check), not
  enforced as a `publish()` blocker — preserves Part 1's advisory-only
  boundary for comparison/readiness; see
  [docs/runtime/versioning.md](docs/runtime/versioning.md).
- 35 new backend tests (`tests/runtime/test_version_compatibility.py`,
  16 pure/database-free classification tests + 19 integration/API tests).
  Backend **696** green (661 + 35); frontend untouched by this
  backend-only phase, still **297** green.

## [Unreleased] — Phase 5.2 Part 1 · Enterprise Versioning & Release Management Foundation

- **Added** migration `0025_agent_versioning`: additive release-management
  columns on `agent_versions` (release channel, compatibility/signature
  placeholders, lineage pointers, retirement) and six new tables —
  `agent_release_channels` (seeded catalog), `agent_version_snapshots`
  (the frozen, complete release document), `agent_release_metadata`,
  `agent_release_artifacts`, `agent_release_notes`, and
  `agent_version_status_history`.
- **Added** enforced semantic versioning (§15-16): auto-derived or
  validated strictly-increasing `MAJOR.MINOR.PATCH`, replacing Phase 5.0's
  unvalidated string field.
- **Added** the snapshot builder (§10-14): one frozen, checksummed document
  per version — registry identity, definition, runtime config, and every
  release-management attachment — built exactly once, at publish.
- **Added** version lineage (§17-18): parent-version linking, supersession
  tracking, and a settable rollback-target pointer (foundation only —
  executing a rollback remains `DeploymentService`'s existing job).
- **Added** release channels (§9, §26), categorized release notes and
  artifact references (§27-28), and the version status-history ledger
  (§19, §25) — all gated by the same immutability rule once a version is
  PUBLISHED.
- **Added** the `RETIRED` terminal lifecycle state and `retire` action
  (DEPRECATED → RETIRED), reachable only from DEPRECATED, matching the SRS
  lifecycle diagram.
- **Added** version comparison (§3): a read-only structural diff between
  any two versions of the same agent — scalar fields, key-level JSONB
  config diffs, and artifact/note set differences.
- **Added** promotion readiness (§3, §30): a read-only diagnostic endpoint
  evaluating the SRS's full "Version Readiness" checklist (snapshot
  creation, validation, metadata, ownership, registry status, blocking
  governance findings, artifacts, approval) — advisory only, never a gate
  on the lifecycle actions themselves.
- **Deliberately not enforced**: the SRS's "cannot publish two active
  releases" — this platform's existing rollback/canary deployment
  strategies require multiple simultaneously-PUBLISHED versions; see
  [docs/runtime/versioning.md](docs/runtime/versioning.md) for the full
  rationale. Compatibility *analysis* and real cryptographic signing are
  out of scope (explicitly deferred by the SRS to a later part).
- 25 new backend tests (`tests/authorization/test_agent_versioning.py`);
  7 new frontend tests. Backend **661** green, frontend **297** green;
  clean typecheck and build.

## [Unreleased] — Phase 5.1 · Enterprise Agent Registry

### Part 5.1 — Enterprise Agent Registry, Definitions & Lifecycle

- **Added** migration `0024_agent_registry`: additive registry columns on
  `agents` (org-hierarchy scoping, mandatory-identity pointer, ownership
  roles, tags/metadata, `row_version` optimistic concurrency) and
  `agent_definitions` (requirement declarations); new tables
  `agent_ownership_history`, `agent_lifecycle_events`,
  `agent_validation_runs`, `agent_duplicate_matches`, `agent_import_jobs`/
  `agent_import_items`, `agent_export_jobs`, `agent_migration_records`; a
  one-identity-per-agent unique constraint on `agent_identities`.
- **Added** the full 13-state registry lifecycle (§18-§21), replacing
  Phase 5.0's collapsed 8-state one — `register`, `submit-for-approval`,
  `reject`, `resume`, `restore` are new actions; every transition gets its
  own dedicated audit event and a structured `agent_lifecycle_events` row.
- **Added** accountable ownership with transfer + immutable history, and
  mandatory machine-identity association/creation/rotation with the
  eligibility enforcement (active, unexpired, DB-uniqueness) Phase 5.0
  never checked.
- **Added** the validation-report engine (§25-§31): metadata/organization/
  ownership/identity/definition/risk rules, JSON Schema DoS guards
  (size/depth limits), entrypoint format validation per type, sample-payload
  testing.
- **Added** duplicate detection (§32, §33, §64): exact + `difflib`
  similarity matching, reviewer decisions, confirmed duplicates block
  registration.
- **Added** JSON/YAML/CSV bulk import (§39-§42, always lands as DRAFT) and
  export (§43-§44, secrets always excluded via an allowlist, CSV
  formula-injection neutralized) with job/item tracking, run synchronously
  inline (no background worker in this environment, same as the execution
  queue).
- **Added** legacy-agent classification (§70-§73) for rows created under
  Phase 5.0's simpler registry.
- **Added** ~25 new `runtime.agent.*` permissions and the frontend
  10-step registration wizard, 12-tab agent detail page, duplicate-review
  page, and import/export pages. See
  [docs/runtime/registry/](docs/runtime/registry/) for the full set.

### Part 5.1 hardening — acceptance-criteria gap closure

- **Fixed** `AgentDefinitionRead` (`app/runtime/schemas.py`) — missing
  `framework_version`, `runtime_language`, `capability_declarations`,
  `tool_declarations`, and the six `*_requirements` fields, causing a hard
  `TypeError` every time the frontend's Definition tab rendered.
- **Added** the legacy-migration frontend page (`MigrationPage.tsx`,
  `/runtime/migration`) — the classification service and API existed with
  no UI to trigger or review it.
- **Added** registration-wizard draft autosave (§22.6): persists to
  `localStorage` on every change, restores with a dismissible banner on
  return, clears on successful submit; fixed the wizard's form `<Label>`s
  to be properly associated with their inputs (`htmlFor`/`id`) along the
  way.
- **Added** performance tests (`test_agent_registry_perf.py`, §31):
  bulk-registration/search throughput and duplicate detection against a
  50+ agent pool, following the existing timing-reported convention.
- **Added** frontend test coverage for all 5 registry pages (23 tests) —
  previously untested.
- **Removed** dead Phase 5.0 schemas superseded by the registry
  (`AgentRegisterRequest`, `AgentUpdateRequest`, `AgentRuntimeRead`,
  `AgentDefinitionCreate`).
- Backend **636** green (incl. 2 new perf tests); frontend **290** green;
  clean typecheck and build.

## [Unreleased] — Phase 5.0 · Agent Runtime & Lifecycle Management

### Part 5.0 — Agent Runtime & Lifecycle Management

- **Added** the `/api/v1/runtime` control plane (§66) — `app/runtime/`:
  agent registry and lifecycle, immutable versioning, deployments, the
  Runtime Gateway, executions, capabilities, tools, runtime approvals,
  health/workers and the kill switch. Gated by 32 new `runtime.*`
  permissions and new builtin roles `ROLE_RUNTIME_ADMIN`/
  `ROLE_RUNTIME_OPERATOR`.
- **Added** migration `0023_agent_runtime`: additive `lifecycle_status`,
  `slug`, `project_id`, `owner_type`/`owner_id`, `criticality`,
  `data_classification`, `default_environment`, `archived_at` on the
  existing `agents` table (no parallel registry — see
  [docs/runtime/architecture.md](docs/runtime/architecture.md)); new
  `agent_definitions`, `agent_versions`, `agent_deployments`,
  `agent_executions`, `execution_attempts`, `execution_locks`,
  `capabilities`, `agent_capabilities`, `tools`, `agent_tools`,
  `tool_calls`, `runtime_events`, `deployment_health`,
  `idempotency_records`, `runtime_approvals`.
- **Added** immutable, checksummed agent versions (§11, §12): DRAFT →
  READY_FOR_REVIEW → APPROVED → PUBLISHED → DEPRECATED/REVOKED; publish
  recomputes and compares the `sha256` checksum, blocking on tamper.
- **Added** the Runtime Gateway (§24-§28, §33): the only execution entry
  point — agent/deployment/version state → idempotency → the existing
  Phase 4.3.6 `AuthorizationGateway` (RBAC/ABAC) → runtime policy → human
  approval → the Postgres-backed queue. Denials and policy blocks are
  saved as inspectable execution rows rather than raised as errors.
- **Added** the worker runtime (§31-§37): `SELECT ... FOR UPDATE SKIP
  LOCKED` claim + `execution_locks` lease, per-attempt retry with a
  non-retryable error allowlist, dead-lettering after `maximum_retries`.
  Driven inline/eagerly by the Runtime Gateway in this environment (no
  Redis/Celery dependency added).
- **Added** the Model Gateway (§40-§42) and Tool Gateway (§43, §44):
  provider-/tool-neutral contracts; only the `MOCK` model provider and the
  `FUNCTION`/`echo` tool action actually execute — every other provider or
  tool type is fully authorized but fails closed
  (`MODEL_PROVIDER_UNAVAILABLE`/`TOOL_ACTION_NOT_ALLOWED`).
- **Added** runtime approvals (§39, new `runtime_approvals` table — the
  existing `Approval` model is 1:1 with `agent_action_id` and doesn't fit
  a deployment/execution-scoped approval) and the kill switch (§60,
  execution/agent/organization scope, always audited and reason-required).
- **Added** the runtime dashboard and Operations Center (§70, §75):
  live KPIs, 7-day execution trend, status distribution, worker health
  derived from heartbeat age.
- **Added** frontend `modules/runtime`: 11 pages + `RuntimeNav`
  (permission-filtered, mirrors `GovernanceNav`); `/runtime/*` routes;
  linked from `AdminNav`.
- **Added** 17 new backend integration tests
  (`tests/authorization/test_runtime.py`): lifecycle, checksum tampering,
  deployment gating, idempotency, concurrency limits, tool authorization
  with retry, mission-critical approval, kill switch, and role-scoping.
  Backend **561** green; frontend tsc + build clean; verified end-to-end
  in a real browser (register → activate an agent → publish a version →
  deploy → run an execution to `SUCCEEDED`).
- Docs: [docs/runtime/](docs/runtime/) — overview, architecture,
  agent-lifecycle, versioning, deployments, executions, workers-and-queue,
  capabilities-and-tools, gateways, runtime-policy-and-approvals,
  health-and-observability, operations-and-kill-switch, security.

### Part 5.0 hardening — acceptance-criteria gap closure

- **Fixed** runtime limits: `maximum_executions_per_minute` and
  `maximum_cost` (rolling daily budget) are now enforced alongside
  `maximum_concurrent_executions`; `maximum_tokens` is checked pre-flight.
  Every count excludes the execution under evaluation — without that, a
  request always counted against its own limit before being decided.
- **Added** execution timeout enforcement (§36):
  `maximum_execution_seconds` bounds the model call via
  `ThreadPoolExecutor` + `future.result(timeout=)` (cross-platform, unlike
  `signal.alarm`); exhausted retries after a timeout report `TIMED_OUT`.
- **Added** `ExecutionWorkerService.reap_expired_locks` (§32): recovers
  executions left `RUNNING` by a worker that never renewed its
  `execution_locks` lease, called opportunistically before every claim;
  `POST /runtime/workers/reap` for operator-triggered recovery.
- **Added** tool constraint enforcement (§23): `read_only`,
  `maximum_calls_per_execution` and `allowed_domains` are real checks in
  the Tool Gateway now, not just stored JSONB.
- **Added** kill-switch PROJECT and PLATFORM scopes (§60); PLATFORM
  additionally requires the actor's role to be `SUPER_ADMIN` — the
  ordinary per-organization permission grant is not sufficient on its own
  for a cross-tenant action.
- **Added** input/output JSON Schema contract validation (§7.2, new
  `jsonschema` dependency): execution input is validated against the
  agent definition's `input_schema` before an execution row is created;
  output against `output_schema` before an attempt can report `SUCCEEDED`.
- **Added** a central execution state-machine transition guard (§27):
  every `AgentExecution.status` change goes through
  `_set_execution_status`/`_EXECUTION_TRANSITIONS`, which rejects any
  transition outside the documented machine instead of trusting every call
  site.
- **Added** 16 new backend tests (577 total green), including regression
  coverage for two real bugs the new tests caught: a per-minute
  rate-limit off-by-one, and a test-isolation leak in the worker-reaper
  tests that could starve a later test's execution behind an orphaned
  `QUEUED` row (the claim query is intentionally global/non-tenant-scoped
  — see [docs/runtime/workers-and-queue.md](docs/runtime/workers-and-queue.md)).

## [Unreleased] — Phase 4.3 · Enterprise Authorization Platform

### Part 4.3.8 — Identity Governance & Administration (IGA)

- **Added** the `/api/v1/governance` control plane (§19) — 40 endpoints in
  `app/governance/`: certification campaigns (a thin proxy over the 4.3.7
  `AccessReviewService`, extended with `campaign_type` and MODIFIED/DELEGATED
  decisions), SoD rules/findings, toxic-permission rules/findings, governance
  findings, privileged accounts/reviews, orphaned-account detection, risk
  scores, remediation actions, compliance reports/frameworks, and the
  governance dashboard/analytics. Gated by 11 new `governance.*` permissions
  and a new builtin `ROLE_COMPLIANCE_ADMIN`.
- **Added** migration `0022_governance_iga`: `sod_rules`,
  `governance_findings`, `remediation_actions`, `governance_risk_scores`,
  `compliance_reports`, `privileged_account_reviews`, plus an additive
  `campaign_type` column on `access_review_campaigns`.
- **Added** Separation of Duties / toxic-permission detection (§9, §10): one
  rule engine (`rule_type=SOD|TOXIC_PERMISSION`) — an identity trips a rule
  when its effective, role-hierarchy-resolved permissions intersect both of
  the rule's permission sets. Detection runs on an org-wide scan endpoint
  *and* as a best-effort check after every `POST /role-assignments`
  (continuous detection, §10), never blocking the assignment it observes.
- **Added** privileged access governance (§11): lists identities holding a
  tracked admin-tier role with a live risk score and last session activity;
  review/approve/revoke — revoke removes the grant through the RBAC service.
- **Added** orphaned identity detection (§12): disabled-but-still-granted
  users, 90-day-inactive users with live assignments, stale API keys, unused
  roles — deduplicated against already-open findings.
- **Added** governance risk scoring (§13): 0–100 score from five weighted
  factors (privileged roles, open toxic/SoD findings, inactivity, failed
  certifications, outstanding approvals) → LOW/MEDIUM/HIGH/CRITICAL band.
- **Added** automated remediation (§14): typed actions against a finding.
  REMOVE_ROLE/DISABLE_ACCOUNT/DISABLE_API_KEY/EXPIRE_DELEGATION execute
  against live state; NOTIFY_MANAGER/CREATE_APPROVAL_REQUEST/REQUIRE_MFA/
  CREATE_SECURITY_TICKET are recorded as audit-tracked hooks (documented gap:
  no manager hierarchy, ticketing integration, or per-user MFA-required flag
  exists yet to wire into).
- **Added** compliance reporting (§15, §16): SOC 2/ISO 27001/HIPAA/GDPR/NIST/
  CIS/Internal control → platform-evidence mapping; immutable evidence
  snapshots; JSON/CSV export (PDF/Excel via client-side conversion).
- **Added** the governance dashboard + analytics (§21, §26): 10 widgets, 5
  charts, computed live from current governance/certification tables.
- **Added** frontend `modules/governance`: 12 pages (dashboard, campaigns,
  certification review, SoD rules/findings, toxic permissions, privileged
  access, orphaned accounts, findings, remediation, compliance, analytics) +
  `GovernanceNav`; `/governance/*` routes; linked from `AdminNav` and a new
  Settings → Security governance card.
- Docs: `docs/governance/{governance-dashboard,access-certification,
  sod-analysis,toxic-permissions,privileged-access,orphaned-identities,
  risk-scoring,remediation,compliance-reporting}.md`.
- Backend **544** tests green (14 new); frontend **267** tests green; `tsc -b`
  and `vite build` clean; verified end-to-end against a live Postgres
  database in a real headless-Chromium session (register → login → create
  and activate an SoD rule → create, launch and review a certification
  campaign — zero console errors, all mutations reflected live).

### Part 4.3.7 — Enterprise authorization administration portal

- **Added** the `/api/v1/admin` control plane (§18) — 20 endpoints in
  `app/authorization/admin/`, each a thin, permission-gated delegation to the
  existing phase services (no duplicated authorization logic, all enforcement
  through the 4.3.6 gateway): dashboard, roles CRUD, the permission catalog,
  the organization tree, the resource registry, ABAC policy CRUD, the policy
  simulator, the authorization decision explorer, access reviews and security
  analytics.
- **Added** the administration dashboard (§6): twelve tenant-scoped widgets
  (users, roles, permissions, policies, sessions, requests/denied 24h, pending
  approvals, MFA challenges, high-risk decisions, cache hit ratio, evaluation
  latency) and five charts (authorization trend, top permissions, policy
  matches, decision breakdown, approval queue).
- **Added** **access review campaigns** (§14; migration `0021`):
  `access_review_campaigns` + `access_review_items` with the DRAFT → SCHEDULED
  → ACTIVE → COMPLETED → ARCHIVED lifecycle. Activation snapshots every
  in-scope role assignment; reviewers certify or revoke each item — a revoke
  removes the underlying assignment through the RBAC service (caches
  invalidate, `ROLE_REMOVED` fires); completion requires every item decided;
  reports export as JSON with an `AUDIT_EXPORTED` event.
- **Added** the **authorization decision explorer** (§13): filterable,
  tenant-isolated decision history (identity, permission, resource, outcome,
  time range) with per-row detail; every query emits `DECISION_VIEWED`.
- **Added** the **security analytics dashboard** (§17): denied trends,
  high-risk decisions, MFA/approval rates, latency (avg/p95), cache
  performance, ABAC denies/challenges, top denied permissions and resource
  sharing trends.
- **Added** 10 portal permissions (`admin.*`, §21 — separable from the raw
  `role.manage`/`authorization.abac.*` sets) and 8 audit events (§22:
  `ACCESS_REVIEW_*`, `SIMULATION_EXECUTED`, `DECISION_VIEWED`,
  `AUDIT_EXPORTED`).
- **Frontend**: `modules/admin` — AdminDashboardPage, DecisionExplorerPage,
  AccessReviewsPage (create/activate/decide/complete/export), 
  SecurityAnalyticsPage and the permission-aware `AdminNav` unifying the
  4.3.1–4.3.5 pages (roles, organization explorer, resources, ABAC builder,
  simulator, audit) into one §5 navigation; routes under `/admin`; portal
  entry card in Settings → Security.
- **Docs**: `docs/admin/{dashboard,roles,organization-explorer,
  resource-management,abac-builder,policy-simulator,decision-explorer,
  access-reviews,audit-center,security-analytics}.md`; ERD + README + ROADMAP
  updated.

### Part 4.3.6 — Enterprise authorization middleware & enforcement architecture

- **Added** `app/authorization/middleware/`: the **AuthorizationGateway** (§22) —
  the single coordination point through which every enforcement surface authorizes;
  an immutable **AuthorizationContext** (frozen dataclass + read-only mappings,
  `identity.*` spoofing stripped at build time) assembled only by the
  `AuthorizationContextBuilder`; a pinned ten-stage **pipeline** (AUTHENTICATION →
  IDENTITY_CONTEXT → SESSION_VALIDATION → ORGANIZATION_CONTEXT → RBAC →
  RESOURCE_AUTHORIZATION → ABAC → OBLIGATIONS → AUDIT → CACHE) whose trace service
  rejects out-of-order recording; an **ObligationExecutor** (approval / MFA /
  justification flags, recursive field masking, parameter clamping, security
  notification); a **DecisionCacheService** keyed by identity × permission ×
  resource × org × RBAC-version × ABAC-generation (+ TTL and per-identity epoch —
  role, policy, org and session-revocation changes all invalidate; challenges and
  dynamic contexts never cached); `PipelineMetricsService` (§34) and the six §24
  audit events (`AUTHORIZATION_STARTED/COMPLETED/FAILED`, `DECISION_GENERATED`
  with the full pipeline trace, `OBLIGATIONS_APPLIED`, `EXECUTION_COMPLETED`).
- **Changed** every enforcement point onto the gateway (§27–§31):
  `require_permission` (all routes) now runs the full pipeline — ABAC challenges
  surface as typed errors (`APPROVAL_REQUIRED` 403, `MFA_REQUIRED` 401,
  `JUSTIFICATION_REQUIRED` 403, satisfiable in-band via `X-Justification`),
  constraint decisions ride on `request.state.authorization`, and plain denials
  keep the legacy 403 contract; `POST /api/v1/authorization/check` became a thin
  gateway call; the **agent runtime** (`process_agent_action`) applies the ABAC
  layer for agent principals (deny → BLOCK, approval → PENDING_APPROVAL into the
  human-review queue) and reports EXECUTION_COMPLETED; background workers,
  schedulers and workflow nodes authorize via `authorize_background(...)` (no
  session; account state still enforced).
- **Added** `evaluate_for_agent` to the ABAC engine (subject = AI_AGENT built
  server-side; `ai_context` may only contribute `ai.*` / `environment.*` keys) and
  a monotonic `generation` to the policy cache powering decision-cache rotation.
- **Fixed** a get-or-create race in the permission-version bootstrap (concurrent
  first requests for one org) with `ON CONFLICT DO NOTHING`.
- **Security (§36)**: middleware mandatory (bypass test proves routes fail without
  it); default deny preserved; ABAC evaluation errors **fail closed**; immutable
  context; challenge errors leak no policy internals; cached decisions are
  per-identity (poisoning impossible by key construction) and tamper-proof
  (copies out); session revocation invalidates instantly.
- **Added** `GET /api/v1/authorization/middleware/metrics` (§34) and error codes
  `ABAC_DENIED`, `APPROVAL_REQUIRED`, `JUSTIFICATION_REQUIRED` (§25).
- **Frontend (§32, §33)**: `AuthorizationProvider` (wraps the 4.3.2
  PermissionProvider; routes gateway decisions and typed API errors to the
  matching UI), `ApprovalRequiredDialog`, `MFAChallenge`, `ObligationDialog`
  (justification capture, mask/limit display), `AuthorizationErrorBoundary`,
  `PermissionGuard`, `useAuthorize` (live gateway check) and
  `decisionToUi` / `maskFields` / `actionLimits` utilities.
- **Docs**: `docs/authorization/{middleware,pipeline,obligations,context,gateway}.md`;
  README + ROADMAP updated.

### Part 4.3.5 — Attribute-Based Access Control engine (ABAC)

- **Added** the ABAC schema (migration `0020`): `abac_policies` (versioned,
  lifecycle-managed context policies — a NULL `organization_id` marks a platform policy
  no tenant can override), `abac_policy_versions` (immutable published snapshots, no FK
  so history survives deletion), `attribute_definitions` (the attribute registry),
  `abac_evaluations` (one row per decision with the redacted explanation) and
  `abac_policy_exceptions` (time-boxed, approved, auto-expiring exemptions).
- **Added** `app/authorization/abac/`: attribute registry + five providers
  (subject/resource/action/environment/AI) behind an `AttributeContextBuilder` — only
  registered attributes may appear in policies; an `OperatorRegistry` mapping all 16
  comparison operators to safe functions (no dynamic code execution, regex length +
  nested-quantifier guards against ReDoS); a recursive `ConditionEvaluator` for nested
  ALL/ANY/NOT trees (depth-capped, with a per-condition trace);
  `PolicyValidationService` (schema, attribute existence, data types, operators,
  effects, obligations); policy lifecycle DRAFT → VALIDATED → ACTIVE →
  DISABLED/DEPRECATED/ARCHIVED with publish-time snapshots, clone and rollback;
  a `PolicyResolver` (scope + target matching over the org hierarchy, per-org cache
  invalidated on any policy/attribute change); five combining algorithms
  (`DENY_OVERRIDES` default — deny → approval → MFA → justification → mask/limit →
  allow); an `ObligationService` (CREATE_APPROVAL, REQUIRE_MFA, REQUIRE_JUSTIFICATION,
  MASK_FIELDS, LIMIT_ACTION, LOG_ONLY) and a `DecisionExplanationService` that redacts
  RESTRICTED attribute values from user-facing output.
- **Changed** `POST /api/v1/authorization/check` to run ABAC **after** the baseline:
  RBAC/resource deny is final (ABAC can never grant); on baseline allow ABAC may deny,
  challenge (`REQUIRE_APPROVAL` / `REQUIRE_MFA` / `REQUIRE_JUSTIFICATION`) or constrain
  (`MASK_FIELDS` / `LIMIT_ACTION`); no applicable policy → the baseline decision stands.
  Responses now carry `decision` + `obligations`.
- **Added** 26 `/api/v1/authorization` endpoints (§30): policy CRUD, validate / publish /
  disable / archive / clone, versions + rollback, simulate (stack-wide and single-policy,
  read-only — the simulator never executes the action and is the only place subject
  attributes may be overridden), evaluate, the evaluation log, ABAC metrics, the
  attribute catalog and policy exceptions (expiry mandatory).
- **Security (§40)**: default deny preserved; only registered operators/attributes;
  caller context can never spoof `identity.*` attributes; platform policies are not
  overridable; published history is immutable; cross-tenant policies and evaluations are
  invisible; sensitive values masked in explanations and logs; 13 error codes; 17 audit
  events; 10 permissions (`authorization.abac.*`, `authorization.attribute.manage`,
  `authorization.exception.manage`) with authoring and publishing separable for
  segregation of duties.
- **Added** the admin portal (Settings → Security → Context policies): ABAC policies
  (list/detail/create/edit with the **visual policy builder** — nested condition groups,
  attribute/operator/typed-value selectors, human-readable preview, raw JSON for
  advanced admins), version history, the **Policy Simulator**, the attribute catalog,
  the evaluation viewer and policy exceptions.
- **Docs**: `docs/authorization/abac/{overview,policy-language,attributes,operators,
  combining-algorithms,policy-lifecycle,policy-simulation,security}.md`; ERD + README +
  ROADMAP updated.

### Part 4.3.4 — Enterprise resource-based authorization (RBAC + Resource ACL)

- **Added** the protected-resource registry and per-resource authorization metadata
  (migration `0019`): `resources` (owner + owner_type, visibility PRIVATE→PUBLIC_INTERNAL,
  status, JSONB resource policy), `resource_acl`, `resource_shares`, `ownership_history`,
  `resource_delegations` — all org-anchored, satellites cascading with the registry.
- **Added** `app/authorization/resources/`: `ResourceAuthorizationService` (the §5/§18
  evaluation chain — org scope → roles → explicit deny → policy → ownership → ACL →
  delegation → sharing → visibility → default deny, with a step trace), plus registry,
  ACL, sharing, ownership (audited transfers + preserved history), delegation and policy
  services and a `MembershipResolver` for USER/ROLE/TEAM/DEPARTMENT/ORGANIZATION
  principals.
- **Changed** the Permission Engine check (`POST /api/v1/authorization/check`) to route
  **registered** resources through the resource-level chain — identical roles, different
  per-resource answers; unregistered resources keep the 4.3.2/4.3.3 path.
- **Added** 20 `/api/v1/resources` endpoints (§19): registry CRUD + types,
  owner / transfer-ownership / ownership-history, ACL CRUD, share/update/revoke,
  delegate/revoke/list, policy, and `POST /resources/{id}/authorize` with identity
  simulation (`resource.manage`) powering the **Authorization Inspector**.
- **Security (§22)**: default deny; explicit deny overrides every allow; owners cannot
  bypass global denies or resource policies; platform admins cannot be ACL-denied on
  SYSTEM resources; cross-org lookups 404 and cross-org sharing is rejected; expired
  ACL entries/shares/delegations are ignored. 14 audit events
  (`RESOURCE_SHARED/UNSHARED`, `RESOURCE_OWNER_CHANGED`, `RESOURCE_ACL_CREATED/UPDATED/
  DELETED`, `RESOURCE_DELEGATED/DELEGATION_REVOKED`, `RESOURCE_POLICY_UPDATED`,
  `RESOURCE_ACCESS_GRANTED/DENIED`, …); 9 error codes; permissions
  `resource.view` / `resource.manage`.
- **Added** the admin portal (Settings → Security → Resources): Resource permissions,
  Resource ACL (search/filter + effect toggle), Sharing, Ownership transfer (+history),
  Delegation management, Authorization Inspector.
- **Docs**: `docs/authorization/{resource-authorization,resource-acl,resource-sharing,
  delegation}.md`, `resource-ownership.md` + ERD + README updated.
- **Tests**: backend **442** green (21 new: ownership/transfer, ACL deny precedence +
  expiry, sharing levels + cross-tenant, delegation lifecycle + expiry, visibility,
  policy, inspector, audit, §25 perf); frontend **242** green (7 new). tsc + build clean.

### Part 4.3.3 — Enterprise organization hierarchy

- **Added** the full hierarchy — Platform → Organization → Business Unit → Department →
  Team → Project → Resources — extending existing tables (migration `0018`): new
  `business_units`, `projects`, `resource_ownership`, `delegations`; `organizations`
  +slug/owner, `departments` +business_unit/status, `teams` +status.
- **Added** services: entity CRUD (org/BU/dept/team/project) with parent validation and
  child-deletion guards, `HierarchyResolverService`, `ResourceOwnershipService`,
  `OrganizationHierarchyService` (tree), `DelegationService` (with boundary enforcement).
- **Changed** the Permission Engine to resolve a resource's ownership path into the
  check's `ResourceContext` — scoped grants now apply via **downward inheritance** — and
  to enforce **cross-organization isolation** (foreign-org resources denied unless the
  caller holds `*` or an active delegation).
- **Added** 20+ `/api/v1` endpoints (organizations, business-units, departments, teams,
  projects, hierarchy/tree, resource-ownership, delegations) gated
  `organization.view`/`.manage`; 10 org audit events; error codes `CROSS_ORG_FORBIDDEN`,
  `ENTITY_HAS_CHILDREN`, `DELEGATION_EXCEEDS_AUTHORITY`, `BUSINESS_UNIT_NOT_FOUND`, ….
- **Added** the admin portal (Settings → Security → Organization): a searchable Hierarchy
  Explorer tree plus Business units, Departments, Teams, Projects and Delegation pages.
- **Docs**: `docs/authorization/{organization-hierarchy,hierarchy-resolution,
  resource-ownership,delegated-administration}.md`.
- **Tests**: backend **421** (8 new: CRUD/tree, department inheritance, cross-org
  isolation, delegation boundary, resolver); frontend **235** (3 new). tsc + build clean.

### Part 4.3.2 — Enterprise Permission Engine

- **Added** a centralized `PermissionEngine` (`app/authorization/engine.py`) with pure
  resolvers: Role (assigned + inherited), Permission (grant list), Wildcard (`resource.*`
  + global `*`), Scope (global→resource), Conflict (**explicit deny wins**, default deny).
- **Added** a Postgres permission cache: `permission_cache` (resolved grants per identity)
  + `permission_versions` (per-org invalidation token, bumped on any role/permission/
  assignment change) + `role_permissions.effect` (ALLOW/DENY) + `authorization_decisions`
  (decision audit with timing). Migration `0017`.
- **Changed** `require_permission` to gate through the engine platform-wide — inheritance,
  wildcards, scope and deny now apply on every endpoint (all existing checks preserved).
- **Added** `POST /api/v1/authorization/check` (evaluate the caller's access;
  `evaluation_time_ms`, `cache_hit`), role create/update `denied_permissions`, and error
  codes `ROLE_NOT_ASSIGNED`, `RESOURCE_FORBIDDEN`, `EXPLICIT_DENY`, `AUTHORIZATION_FAILED`,
  `PERMISSION_CACHE_MISS` (§28).
- **Added** the frontend permission layer: `PermissionProvider`, `usePermissions`/`useCan`,
  `ProtectedComponent` / `RequirePermission` (wildcard-aware; server is source of truth).
- **Docs**: `docs/authorization/{permission-engine,permission-resolution,wildcards,scopes,
  caching}.md`.
- **Tests**: backend **408** (25 new: wildcards, scope, conflict/deny, cache invalidation,
  `/check`, decision audit); frontend **232** (8 new). tsc + build clean.

### Part 4.3.1 — Enterprise RBAC foundation

- **Added** a new `app/authorization/` package extending the existing flat RBAC:
  role category/status/priority/assignability, a domain-grouped `resource.action`
  permission catalog, scoped role assignments (global → resource, time-boxed), an acyclic
  role hierarchy (senior inherits descendants), and an `authorization_audit` trail.
- **Added** three tables (`permission_groups`, `role_hierarchy`, `authorization_audit`)
  and columns on `roles`/`rbac_permissions`/`role_permissions`/`user_roles` — migration
  `0016`, additive. 18 built-in roles seeded globally alongside the legacy four.
- **Added** 15+ `/api/v1` endpoints (roles, permissions, permission-groups,
  role-assignments, role-hierarchy, authorization/audit) gated on
  `role.view`/`role.manage`/`role.assign`, and error codes `ROLE_ALREADY_EXISTS`,
  `CIRCULAR_ROLE_HIERARCHY`, `SYSTEM_ROLE_PROTECTED`, `ROLE_HAS_ASSIGNMENTS`,
  `INVALID_PERMISSION_NAME`, `INVALID_SCOPE`, … (§24).
- **Added** the admin portal (Settings → Security → Authorization): Roles, Permissions,
  Permission groups, Assignments, Hierarchy, Audit.
- **Docs**: `docs/authorization/{rbac,roles,permissions,role-hierarchy}.md`.
- **Tests**: backend **383** (31 new: cycle detection, scope validation, CRUD, inheritance,
  audit); frontend **221** (4 new). tsc + build clean.

## [0.4.0] — Phase 4.2.2 · Enterprise Human Authentication

The identity platform now spans authentication → sessions → registration → password
policy → recovery → account protection, closed out by an integration & release pass.

### Part 4.2.2.3.5 — Backend APIs, integration & release (close-out)

- **Added** cross-cutting HTTP middleware (`app/core/middleware.py`):
  - `RequestContextMiddleware` — a stable `X-Request-ID` on every request/response
    (inbound if supplied, else a generated UUID4), threaded into the error envelope (§15).
  - `SecurityHeadersMiddleware` — `X-Content-Type-Options: nosniff`, `X-Frame-Options:
    DENY`, `Referrer-Policy`, deny-by-default `Content-Security-Policy`,
    `Permissions-Policy`, and opt-in HSTS on every response, errors included (§16, §23).
- **Added** the standard §5 **response envelope**: `ResponseEnvelopeMiddleware` wraps
  every 2xx JSON response under `/api` as `{success, data, meta:{request_id, timestamp}}`
  (leaving `/health`, `/openapi.json` and file exports untouched); errors gain a matching
  `meta`. The SPA unwraps it centrally (`services/envelope.ts`, used by the axios
  interceptor and the bare refresh client), so no service code changed. Toggle:
  `RESPONSE_ENVELOPE_ENABLED`.
- **Added** a full-stack deployment: `frontend/Dockerfile` (Vite build → nginx serving the
  SPA and reverse-proxying `/api`), `frontend/nginx.conf`, a `web` service in
  `docker-compose.yml` (web + api + db, same-origin, no CORS), and `docs/deployment.md`
  with the §24 release checklist (provided vs operator-supplied).
- **Added** `SECURITY_*`, `REQUEST_ID_HEADER`, `RESPONSE_ENVELOPE_ENABLED` settings;
  `docs/api/http-conventions.md`, `docs/testing/strategy.md`, this changelog.
- **Verified** the §4 API contract end-to-end. Remaining honest deviation:
  admin/invitation/password routes live under `/identity` & `/security` (stable paths);
  no unreachable `logout-all`/`device-delete` stubs added.
- **Tests**: backend **352 passing** (+11 hardening/envelope tests); measured **92%** line
  coverage on `app.identity` + `app.core`. Frontend tsc + production build clean; web
  Docker image builds.

### Part 4.2.2.3.4 — Account protection & risk-based authentication

- **Added** risk scoring (0–100), progressive lockout (15m→30m→1h→24h→review),
  brute-force/credential-stuffing detection, blocked IPs, protection-rule engine, adaptive
  rate limiting and a CAPTCHA seam. Tables `account_locks`, `identity_risk_events`,
  `blocked_ips`, `identity_protection_rules` (migration `0015`). Security console UI.
- **Known limitations**: MFA `CHALLENGE` decisions fail-safe **deny** until MFA enrolment
  lands; CAPTCHA is a disabled, provider-agnostic seam.

### Part 4.2.2.3.3 — Password reset, account recovery & email change

- **Added** forgot/reset password (30-min single-use tokens, non-enumerating responses,
  revokes all sessions), verified email change, recovery-events dashboard (migration `0014`).

### Part 4.2.2.3.2 — Enterprise password policy & credential management

- **Added** single-source password policy, password history (no reuse of last 10), 90-day
  expiration with warnings, admin temporary-password reset, mandatory first-login change
  (migration `0013`).

### Part 4.2.2.3.1 — Registration, invitations & email verification

- **Added** invited + self-serve registration, invitation lifecycle, email verification,
  Postgres-backed rate limiting (migrations `0011`–`0012`).

### Part 4.2.2.2 — Login, logout & session lifecycle

- **Added** stateful session validation on every request (immediate revocation), device
  trust/block, refresh-token families with reuse detection, admin session management
  (migrations `0009`–`0010`).

### Part 4.2.2.1 — Enterprise human authentication

- **Added** `/api/v1/auth/*` on argon2id, rotating refresh tokens, account lockout, login
  history, silent refresh (migration `0008`).

## [0.3.0] — Phase 3 · Enterprise Dashboard UI

- React 19 + TypeScript SPA: agents, policies, approvals, audit, analytics dashboards.

## [0.2.0] — Phase 2 · Production-oriented platform

- Agent API-key auth, database-driven policy engine, advanced RBAC, email notifications,
  forensic audit, dashboard APIs, risk engine v2, Docker.

## [0.1.0] — Phase 1 · Backend MVP

- FastAPI + PostgreSQL control plane: agents, permissions, risk scoring, approvals,
  immutable audit logs, JWT auth.
