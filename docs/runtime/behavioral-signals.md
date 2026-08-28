# Behavioral signals — deterministic, explainable runtime anomaly detection

> **Phase 4.5 (ACT-SRS-M4 §4.5, Gate L).** How the platform detects that an
> agent's behavior has *changed*, why every finding must explain itself, and
> the one attribution it deliberately cannot provide.

## The one-paragraph version

Seven deterministic rules run over a window of an agent's real executions and
compare each metric against an absolute threshold and against the same agent's
preceding window. A non-normal result becomes a **finding** carrying the metric,
both window bounds with their sample counts, the observed value, the threshold
and/or baseline, and the crossing in words. A thin window is
`INSUFFICIENT_DATA`, never anomalous. A finding is a **signal**: nothing here
can stop an execution.

## Why no machine learning

§4.5 forbids opaque anomaly scoring, and the reason is worth stating rather than
merely obeying.

> "This agent is 0.87 anomalous" is **unauditable, unappealable and
> ungovernable.** A regulated tenant cannot act on it, cannot dispute it, and
> cannot show a regulator why it fired.
>
> "Tool `send_email` failed 34% of 118 calls this week against a 3% baseline
> over the previous week" is all three.

So every rule here is arithmetic over a window. There is no model, no training
data, and no threshold learned from anything — the knobs are declared in
`DEFAULT_THRESHOLDS` and overridable per environment. A test asserts the package
imports no numerical or ML library, and that the rules are pure functions of
`(candidate, baseline, thresholds)`: no session, no clock, no globals. That last
part is what makes *"the same data always yields the same finding"* testable
rather than aspirational, and there is a test that runs a full evaluation three
times and compares every field.

This is a smaller claim than an ML system would make, and it is a claim the
platform can defend.

## The engine is Phase 3.5's, reused

```
1. Veto        → UNKNOWN            (before a single row is aggregated)
2. Sufficiency → INSUFFICIENT_DATA  (below the minimum sample count)
3. Threshold   → absolute rules
4. Baseline    → relative rules
```

That is `HealthEvaluationService.evaluate`'s order, for its reasons, applied to
a broader signal set. Three of the five state values are **byte-identical** to
3.5's — `DEGRADED`, `INSUFFICIENT_DATA`, `UNKNOWN` — and a test asserts it, so a
rename on either side breaks the build rather than silently diverging.

### Where it differs, and why

**The endpoints are named differently.** 3.5 uses `HEALTHY`/`UNHEALTHY`; this
uses `NORMAL`/`ANOMALOUS`. The build prompt asked for the second set while also
saying "do not fork a parallel vocabulary" — which, taken literally, is
self-contradictory, since the proposed set differs from the existing one in two
positions. It was resolved by keeping the shared middle exactly and letting the
endpoints differ, because they are genuinely different claims:

| | 3.5 asks | 4.5 asks |
|---|---|---|
| Question | Is this version fit for more traffic? | Has this agent's behavior changed? |
| Axis | **fitness** | **deviation** |

The two come apart in both directions. A p95 latency that drops 80% overnight is
**anomalous** — something changed and someone should find out what — and in no
sense unhealthy. An agent that has failed 30% of its calls every day for a month
is **unhealthy** and not anomalous at all, because nothing changed. Calling the
first "UNHEALTHY" or the second "NORMAL" would each be wrong.

**The baseline axis differs.** 3.5 compares a *candidate version against the
stable version over the same window* — right for "should this version get more
traffic". This compares *an agent against itself over the preceding window* —
right for "has this agent changed". Same engine shape, different axis.

**The veto has its own reason.** 3.5 vetoes because automation reads its verdict
to move traffic. This vetoes because *a killed agent's runtime data describes
the kill, not the agent*: executions cancelled by a kill switch would show as a
huge spike, and reporting that as ANOMALOUS would raise an alarm about the
intervention at the exact moment an operator is already using it.

## The seven signals

| Signal | Metric | Rule |
|---|---|---|
| `error_rate_shift` | error rate | absolute thresholds, then baseline margin |
| `policy_denial_surge` | denial rate | as above — a denied execution is refused, not broken |
| `latency_drift` | p95 duration | ratio against baseline, **either direction** |
| `cost_drift` | cost per execution | ratio against baseline |
| `tool_failure_spike` | per-tool failure rate | absolute + baseline, **per tool** |
| `tool_pattern_shift` | tool-mix distance | total-variation distance from the baseline mix |
| `loop_termination_anomaly` | cap-termination rate | absolute + baseline |

Three of them deserve a note.

**`latency_drift` reports speedups too.** A metric that halves overnight is not
good news to be filtered out; it usually means the agent stopped doing something
it used to do. This is the clearest place a behavioral signal differs from a
health signal, which only cares about getting worse.

**`tool_failure_spike` is per tool, and names the worst.** An aggregate across
every tool an agent uses hides the case that matters: one broken integration
among five healthy ones barely moves the average. Each tool is rated on its own
against a minimum call count, and the finding names it.

**`loop_termination_anomaly` is the signal invisible in the error rate.** A model
that has started looping is stopped by Phase 5.6a.3's caps working exactly as
designed — so nothing errors from the caller's point of view, and only the
termination mix shows it. There is a test asserting precisely that: the loop
signal fires while `error_rate_shift` stays NORMAL.

### `tool_pattern_shift`, stated fully

The metric is the **total-variation distance** between the candidate's tool mix
and the baseline's: half the sum of absolute differences in each tool's share.
It lands in `[0, 1]` — `0` for an identical mix, `1` for completely disjoint
ones. Chosen because it is a stated arithmetic operation on two distributions
that an operator can recompute by hand from the breakdown in the finding, which
a distance with a less obvious derivation would not be.

A tool an agent has never used appearing at 40% of its calls is a real
behavioral change even when nothing fails.

## `INSUFFICIENT_DATA` is first-class

Below the minimum sample count the answer is `INSUFFICIENT_DATA` regardless of
how clean or how alarming the few samples look. Three catastrophic executions
are not evidence of a change, and three perfect ones are not evidence of health.

**A thin *baseline* is treated as no baseline**, not a weak one — comparing
against three executions would manufacture drift out of noise. The absolute
thresholds still apply, so the signal is still evaluated; only the relative part
is withheld.

`INSUFFICIENT_DATA` and `UNKNOWN` are **persisted**, unlike `NORMAL`. "We could
not tell" is the answer to a question an operator will otherwise keep asking.

## Attribution — and the one gap

Findings name the **provider**, **model** and **tool** where the data supports
it: a latency drift names the model that answered, a tool-failure spike names
the tool.

**Connector attribution is deferred, and every finding says so.** The runtime
has no record of which external system a version depends on — that is
ACT-INT-FR-006, the runtime-never-knows boundary, and Phases 3.2, 3.3 and 3.5
each reported the same gap in turn. So "which connector caused today's failures"
cannot be answered without inventing a dependency link that does not exist.

Rather than omit the key, every finding carries:

```json
"connector": null,
"connector_attribution": "unavailable: no runtime-to-integration dependency link"
```

Naming the gap in the record is more useful than leaving a reader to assume it
was never considered. A test asserts the package imports nothing from
`app.integration`, so the boundary is intact rather than merely respected.

## A finding is a signal, never enforcement

Nothing in `app/behavior` writes an execution's status, raises a governance
exception, or reaches the kill switch — asserted over the AST, the same proof
Phase 4.4 gave for budgets. Phase 4.3's engine remains the only thing on this
platform that can stop an execution.

A future policy could *read* these findings; that would still route enforcement
through 4.3.

**Emission is non-gating** (§9). Behavioral signals are telemetry-plane, and the
telemetry plane fails **open**: an evaluation that fails produces no finding, and
never a STOP. That is the deliberate inverse of the governance plane, and it is
tested.

## The 4.4 / 4.5 cost boundary

Both phases look at cost. They ask different questions, and each fires where the
other is silent.

| | Phase 4.4 spend anomaly | Phase 4.5 cost drift |
|---|---|---|
| Question | Did this **tenant** spend more this period than usual? | Did this **agent** start costing more per run? |
| Unit | absolute dollars | cost per execution |
| Scope | tenant, calendar period | agent, rolling window |
| Kind | FinOps | behavioral |

Two tests demonstrate the boundary rather than asserting it:

- **Per-execution cost doubles while traffic halves.** Total spend is flat, so
  4.4 sees nothing; the agent got twice as expensive per run, so 4.5 fires.
- **Traffic multiplies at unchanged per-execution cost.** 4.4 sees the spend
  spike; 4.5 correctly sees no behavioral change, because the agent is behaving
  exactly as it always did — there is just more of it.

Neither package imports the other, and a test asserts that in both directions.

## Evaluation cadence

`POST /api/v1/runtime/behavior/evaluate` is the **interim** trigger. Phase 3.8's
distributed scheduler is what should drive this on a timer, and wiring it there
is that phase's registry work rather than this one's — building a second
scheduler here would be the fork this milestone has refused three times.

So the operation is idempotent at two levels, and adopting it into the scheduler
is a registration rather than a rewrite:

1. Phase 3.1's `Idempotency-Key` contract on the request.
2. A unique constraint on `(agent_id, signal_type, window_start, window_end)`
   beneath it.

A scheduler run that overlaps or retries produces one finding per window either
way — enforced by the database rather than by the application remembering to
check first, the same reasoning Phase 4.4 used for budget reservations.

## Performance

At 115,381 executions, busiest agent 500 rows:

| Query | p50 | p95 |
|---|---|---|
| agent-scoped window aggregate | **0.57 ms** | 1.42 ms |
| termination-reason breakdown | 0.42 ms | 0.66 ms |
| per-tool failure breakdown | 0.22 ms | 0.49 ms |

**No index was added.** The interesting part is the plan, not the number: no
composite covers `(organization_id, agent_id, created_at)`, and Postgres does
not need one — it combines Phase 4.2's `ix_agent_executions_org_created` with
Milestone 1's `ix_agent_executions_agent` via a `BitmapAnd`. Two indexes built
for other queries intersect to answer this one.

One shape is named rather than fixed on suspicion: `tool_calls` has an index on
`agent_id` alone, so the window's time bound is applied as a post-index
**Filter**. That is the shape Phase 4.2 found dangerous on `agent_executions` —
cheap while the discriminator selects few rows, O(all rows for that agent) once
it does not. It **cannot be demonstrated** on this data (5,210 tool calls
platform-wide, 10 for the busiest agent), and adding an index against a
projection rather than a measurement is what Phases 4.2 and 4.4 both refused.
The trigger is recorded in migration `0049` instead:

> Revisit when any single agent exceeds roughly 50,000 tool calls, or when the
> per-tool breakdown's p50 passes 10 ms.

## Configuration

Thresholds ride on `Environment.policy["behavioral_thresholds"]` — the same
carrier Phase 3.3 used for preflight and 3.5 for canary health, rather than a
third configuration mechanism. An unknown key is **ignored**, so a misspelled
threshold cannot look configured while doing nothing.

The absolute defaults are deliberately looser than 3.5's canary equivalents. A
canary is a candidate asking for more traffic and should be judged strictly; a
production agent is being watched for *change*, and flagging it at a 5% error
rate it has always had would produce a permanent alarm nobody reads.

## API

| Method | Path | Permission |
|---|---|---|
| GET | `/api/v1/runtime/behavior/findings` | `runtime.telemetry.view` |
| GET | `/api/v1/runtime/agents/{id}/behavior` | `runtime.telemetry.view` |
| POST | `/api/v1/runtime/behavior/evaluate` | `runtime.telemetry.view` |

**No new permission.** `runtime.telemetry.view` already existed and its
description already reads *"View runtime telemetry and execution traces"* — a
behavioral finding is derived telemetry about an execution stream, the same
plane and the same capability. Reused rather than shadowed by a synonym, for the
reason Phase 4.2 gave when it declined `runtime.observability.view` and 4.4 gave
when it reused `runtime.cost.view`.

## See also

- [runtime-governance.md](./runtime-governance.md) — the engine that enforces;
  behavioral findings never do
- [cost-governance.md](./cost-governance.md) — the 4.4 side of the cost boundary
- [deployments.md](./deployments.md) — Phase 3.5's release-health engine, whose
  shape this reuses
