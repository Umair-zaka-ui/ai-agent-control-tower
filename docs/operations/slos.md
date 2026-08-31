# Service Level Objectives (SLOs)

> **Phase 4.7 (ACT-SRS-M4 §3.6, §4.7; Gate J).** Express runtime reliability as
> objectives — an SLI, a target, an observation window, an error budget —
> evaluated deterministically with INSUFFICIENT_DATA honesty. A breach is a
> **signal**: it raises an alert (see [alerts.md](./alerts.md)); it never stops
> an execution (Phase 4.3 does that) and never pages anyone (a future
> integration consumes the alert record).

## What an SLO is

```
POST /api/v1/runtime/slos          (runtime.slo.manage)
{
  "name": "prod success rate",
  "sli": "success_rate",
  "target": 0.99,
  "window": "24h",
  "scope_type": "ENVIRONMENT",
  "scope_id": "<environment id>"
}
```

| Field | Meaning |
|---|---|
| `sli` | *What* is measured — one of the six below |
| `target` | A ratio in `(0, 1]` for the rate SLIs; milliseconds for the latency ones |
| `window` | A rolling spec: `1h` / `6h` / `24h` / `7d` / `30d` — a closed vocabulary, not a free-form duration |
| `scope_type` | `ORGANIZATION` / `AGENT` / `VERSION` / `ENVIRONMENT`; `scope_id` required for all but `ORGANIZATION` |
| `error_budget` | The allowed "bad fraction" over the window. **Defaulted on create**, never absent (see below); overridable in `(0, 1]` |

**The objective direction is not a stored field.** `success_rate` is always
"higher is better"; `latency_p95` is always "lower is better"
(`app.slo.sli.SLI_SPECS`). An operator cannot store a self-contradictory "success
rate below 0.99 is good", and evaluation never guesses which way the comparison
runs.

## The six SLIs

Every SLI reads `agent_executions` / `tool_calls` **directly** — not the 4.6
`/metrics` surface. The 4.6 metrics are windowed gauges rounded to
bounded-cardinality dimensions (right for a Prometheus dashboard); an SLO needs
an exact count over its own window and a precise percentile. Both share a
*source of truth* (the domain rows), not a query.

| SLI | Definition | Direction | Unit |
|---|---|---|---|
| `success_rate` | `SUCCEEDED` / terminal executions | higher better | ratio |
| `timeout_rate` | `TIMED_OUT` / terminal executions | lower better | ratio |
| `provider_error_rate` | executions whose `error_code` is a 5.7a.4 `ProviderErrorClass` value / terminal | lower better | ratio |
| `tool_failure_rate` | failed tool calls (5.6a.2 predicate) / tool calls | lower better | ratio |
| `latency_p95` | p95 of `duration_ms` over terminal executions | lower better | ms |
| `queue_delay` | p95 of `started_at − queued_at` over executions that queued | lower better | ms |

"Terminal" = `SUCCEEDED / FAILED / TIMED_OUT / DEAD_LETTERED / DENIED / BLOCKED
/ CANCELLED` — identical to 3.5's `TERMINAL_FOR_HEALTH` and 4.5's
`TERMINAL_FOR_BEHAVIOR` (a test asserts the three are equal).

## Evaluation — the 3.5 / 4.5 shape

`POST /api/v1/runtime/slos/evaluate` (`runtime.slo.manage`) runs one cycle for
the tenant. It is the **interim, idempotent** trigger for Phase 3.8's scheduler
to adopt — the same pattern 4.5, 3.7 and 3.5 built. **No scheduler is built
here.**

Each SLO is evaluated in order:

1. **Veto.** An `AGENT`-scoped SLO whose agent is suspended or archived is
   `UNKNOWN` — its recent data describes the intervention, not the objective.
2. **Sufficiency.** Below **20** terminal samples (`MIN_SAMPLES`, a platform
   constant like 3.5's and 4.5's) the state is `INSUFFICIENT_DATA` — neither
   `MET` nor `BREACHED`. "No failures observed" is not "the objective is met"
   (M4-4.7-FR-004).
3. **Objective.** Compare the observed value to the target in the SLI's fixed
   direction → `MET` / `BREACHED`.
4. **Budget.** `budget_consumed = bad_fraction / error_budget`. Above `1.0` the
   budget for the window is spent; `budget_remaining = max(0, 1 − consumed)`.

Every number is a pure function of the rows in the window and the SLO's own
fields. Same rows, same window ⇒ byte-identical verdict (a test runs it three
times). No model, no scoring, no randomness.

### The error-budget default

| SLI kind | Default `error_budget` |
|---|---|
| `success_rate` | `1 − target` (the allowed failure fraction) |
| `timeout_rate` / `provider_error_rate` / `tool_failure_rate` | `target` (the allowed rate itself) |
| `latency_p95` / `queue_delay` | `0.05` (fraction of samples permitted to exceed the target) |

## The evaluation record

`slo_evaluations` is **append-only** (see `RECOVERY.md`). One row per
`(slo_id, window_start, window_end)` — a re-run over the same window is a no-op
(`on_conflict_do_nothing`), which is what makes the op safe for the 3.8
scheduler to drive on a timer.

`GET /api/v1/runtime/slos/{id}/evaluations` returns the history newest-first
with the observed value, state, and `budget_consumed` / `budget_remaining`, and
an `explanation` that carries everything to recompute the verdict by hand.

## What this is NOT

- **Not enforcement.** A breach never stops or alters an execution — Phase 4.3's
  governance engine is the only thing that can. `app/slo` references no
  execution-state mutation, no kill switch, no governance engine (AST-asserted).
- **Not a notification.** Nothing here sends a Slack message, an email, a page,
  or a webhook. That is 4.7's explicit line (§4.7): build the signal, not the
  notification platform. A test walks the AST of `app/slo` and fails on any
  delivery client. A future integration consumes these records.
- **Not new SLI computation.** The six SLIs read existing rows with the same
  aggregation 3.5 and 4.5 already run. No new metric-source table, no
  per-execution-id label.
