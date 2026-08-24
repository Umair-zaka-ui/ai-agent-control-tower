# Canary rollouts, release health, and the stage gates

Phase 3.5 (ACT-SRS-M3 §Phase-3.5, §6, §7, §12). Phase 3.4 built weighted traffic
allocation and the operation to *set* weights. This phase builds the engine that
**drives** those weights through a governed progression — the driver 3.4 was
built for.

A candidate version is promoted stage by stage (5% → 25% → 50% → 100%), and a
stage only clears when **all three** of its gates are satisfied: minimum
duration elapsed, minimum sample count met, and an AI-aware health requirement
satisfied. A kill switch halts the whole thing instantly, and a thin sample is
never mistaken for proof of health.

---

## The shape of a rollout

```
rollout_plans          one canary promotion of a candidate within (agent, environment)
  state, current_stage_index, revision
      │
      └── rollout_stages     ordered; each carries target_weight + three gates
                             (min_duration_seconds, min_samples, health_requirement)
                             and advance_mode (MANUAL | AUTO)

deployment_health_evaluations   the AI-aware verdicts that gate decisions consult
```

### The state machine

```
PENDING --start--> IN_PROGRESS --(all stages cleared)--> SUCCEEDED
   |                  |  ^                |
   |                  |  |                +--> FAILED
   |             pause|  |resume
   |                  v  |
   |               PAUSED
   |                  |
   +----abort---------+----abort--> ABORTED
                      |
                      +--request-rollback--> ROLLBACK_REQUESTED
```

One transition authority: `CanaryRolloutService._transition`, over the pure
graph in `app/runtime/deployment/rollout.py`. Nothing else in the codebase
assigns `RolloutPlan.state` — mechanically checked, the same discipline Phase
3.1 established for `AgentDeployment.lifecycle_state`.

---

## Traffic only ever moves through Phase 3.4

**A stage advance never writes `deployment_traffic_weights`.** It calls
`TrafficAllocationService.set_weights` — 3.4's atomic, revisioned,
eligibility-checked, audited mechanism — with the candidate at the stage's
target weight and the stable version holding the remainder.

Every guarantee that matters is therefore inherited rather than reimplemented:
weights validated to total exactly 100, each version checked eligible
(published, signed, backed by a servable deployment in this environment), the
change written as a new allocation revision with the previous one retired in the
same transaction, and a `DEPLOYMENT_TRAFFIC_CHANGED` audit event. The canary
engine contributes only the numbers.

This is structural, not aspirational: `canary.py` contains no reference to
`DeploymentTrafficWeight` or `DeploymentTrafficAllocation` at all, so it
*cannot* bypass 3.4. A test asserts that against the parsed AST.

### Why a staged canary requires a stable version

3.4's weights must total exactly 100, so a candidate at 5% is literally
unrepresentable without another version holding the other 95. Creating a staged
rollout with no resolvable stable version is rejected with an explanation rather
than silently becoming a 100% cutover. The stable version is inferred from 3.4's
current allocation (the highest-weighted version that isn't the candidate),
falling back to the newest servable deployment.

---

## The three gates

An advance is permitted only when **all three** pass:

| Gate | Satisfied when |
|---|---|
| Duration | `now - stage.entered_at >= min_duration_seconds` |
| Samples | terminal executions in the window `>= min_samples` |
| Health | the health verdict is at least `health_requirement` |

`entered_at` is null until a stage becomes current, and an unentered stage can
never satisfy its duration gate — which is what stops a freshly-created rollout
from advancing instantly.

When an advance is refused, **every** unmet reason is reported, not just the
first: an operator staring at a stuck canary learns in one call that it needs
both 40 more seconds and 12 more samples, rather than discovering the second
only after the first clears.

### `health_requirement: "NONE"` — the explicit waiver

A stage may declare `health_requirement: "NONE"` to gate on duration and samples
alone. It exists because the alternative is worse: health with zero observed
executions is `INSUFFICIENT_DATA` (correctly — nothing has been proven), so a
stage on a genuinely idle agent would otherwise be stuck forever with no way to
say "I know, advance it anyway". Making that an explicit, per-stage, auditable
declaration is far safer than the tempting alternative of quietly treating "no
data" as "fine".

**`NONE` does not waive `UNKNOWN`.** The distinction is load-bearing:
`INSUFFICIENT_DATA` means "evaluable, nothing proven yet", which an operator may
legitimately accept; `UNKNOWN` means "not evaluable at all" — suspended, killed,
or no servable deployment. No stage configuration may wave that through, or
`NONE` would become a way to opt out of the kill switch.

---

## The AI-aware health engine (ruling #3)

### Why a second health table

The pre-existing `deployment_health` table is a **liveness heartbeat**: a worker
reported in, the process is up. That is a fine answer to "is it running" and a
useless answer to "should this version get more traffic". A model version can be
perfectly alive while refusing every third request, timing out on long prompts,
tripping policy denials, or quietly costing four times as much per call.

So `deployment_health_evaluations` is a **release judgement**, computed by
aggregating `agent_executions` over a window. The old table is untouched by this
phase in either direction (ruling #3), and a test asserts its row count is
unchanged across a full rollout.

### The signals actually available

Confirmed by reading `AgentExecution`, not assumed from the SRS wish-list:

| Signal | Source |
|---|---|
| success / failure / timeout | `status` (SUCCEEDED / FAILED, DEAD_LETTERED / TIMED_OUT) |
| policy denials | `status` (DENIED, BLOCKED) |
| latency | `duration_ms` (mean and p95) |
| cost | `cost_amount` |
| tokens | `total_tokens` |
| provider / tool failure class | `error_code` (the 5.7a.4 taxonomy) |

Only executions in a **terminal** state count. One still queued or running has
not produced a verdict yet, and counting it as "not a failure" would make a
stalled canary look healthier the more stuck it got.

**Gap reported, not built around:** per-external-system failure counts are not
available on an execution row — there is no dependency link telling this layer
which external system a version depends on. That is the same gap Phases 3.2 and
3.3 already reported, and the runtime-never-knows boundary keeps that vocabulary
out of `app/runtime` entirely. Provider and tool failures are captured through
`error_code` instead.

### The states

| State | Meaning |
|---|---|
| `HEALTHY` | Enough evidence, within all thresholds |
| `DEGRADED` | Elevated error or denial rate, or a regression against stable |
| `UNHEALTHY` | Error or denial rate at or above the unhealthy threshold |
| `INSUFFICIENT_DATA` | Evaluable, but below the stage's minimum sample count |
| `UNKNOWN` | Not evaluable — suspended, killed, or no servable deployment |

Thresholds default to 5% / 20% error rate and 10% / 30% denial rate, overridable
per environment via `Environment.policy["canary_health_thresholds"]` — the same
policy-carries-the-override pattern Phase 3.3 established, not a second
configuration mechanism.

### INSUFFICIENT_DATA is first-class

The single most dangerous bug this engine could have is reporting two successful
calls out of two as HEALTHY. **Nothing bad observed is not nothing bad
happening.** Below the stage's minimum sample count the verdict is
`INSUFFICIENT_DATA` regardless of how clean the few samples look, and it
satisfies no health requirement at any level.

Evaluation order is deliberate, and each step exists to stop a specific wrong
answer:

1. **Veto first** — a killed or non-servable candidate is `UNKNOWN` before a
   single row is aggregated.
2. **Sample sufficiency next** — below the minimum, the answer is
   `INSUFFICIENT_DATA` no matter how good the samples look.
3. **Only then** thresholds and the baseline.

---

## Baseline comparison (§7)

Candidate metrics are compared against the stable version's over the same
window, producing two findings:

**1. Regression relative to stable.** If the candidate's error rate exceeds
stable's by more than the margin (2 percentage points by default), the candidate
is worse than what it would replace — even if its absolute rate sits under the
degraded threshold. That earns a `DEGRADED` floor, because "better than an
arbitrary constant" is the wrong bar when a known-good comparator is running
right now.

The margin is deliberately **narrower** than the degraded threshold. If it were
as wide, the baseline rule could never fire on its own — any gap big enough to
breach it would already have tripped the absolute check — and catching exactly
that case is the whole point of §7.

**2. Likely provider-wide degradation** (the FR-031 attempt). If *both*
candidate and stable are elevated together, the candidate is probably not the
cause — an upstream provider or shared dependency is. Recorded as
`likely_provider_wide` in `baseline_ref`.

Crucially, finding 2 **softens blame but never restores HEALTHY**. It would be
an easy and dangerous mistake to let "it's not the candidate's fault" mean "so
carry on promoting": a provider-wide incident is exactly when *no* version
should be earning more traffic. The verdict is floored at `DEGRADED`, which no
sensible stage accepts, and the incident is named in the explanation rather than
silently excusing the numbers. Full causal analysis stays deferred (§7).

When stable has no traffic in the window, absolute thresholds are used alone and
`baseline_ref.comparable` is `false`.

---

## Kill-switch dominance (§12)

**The sharpest safety rule in this phase.** A rollout in progress, when the agent
is killed at any covering scope, halts: no advance, no promotion, and no path by
which automation reaches "candidate looks healthy → promote".

Enforced by **two independent mechanisms**, so a bug in either alone cannot open
the gate:

1. `_assert_not_vetoed` runs before every operation that could give the
   candidate *more* traffic — start, advance, resume, promote, and the automated
   evaluate-and-advance. It reads the same fields Phase 3.4's resolver reads, so
   a rollout can never advance a candidate the execution gate would refuse to
   serve. `KillSwitchService` suspends the agent at AGENT scope and the
   deployment's `status` at ORGANIZATION/PROJECT/PLATFORM scope; both are
   covered, as is "no servable deployment at all".
2. The health engine independently returns `UNKNOWN` — never `HEALTHY` — for a
   vetoed candidate, and `UNKNOWN` satisfies no requirement including `NONE`.

**De-escalating operations deliberately stay available.** Pause, abort and
request-rollback do *not* check the veto, because a kill switch must never trap
a rollout in a state an operator cannot back out of — aborting is precisely what
someone does *after* hitting the kill switch.

On the automated path a veto is **reported, not raised**: a scheduler sweeping
many rollouts must not have one killed agent abort the whole sweep. It still
does not advance, which is the point.

---

## Interim auto-advance, and how 3.8 replaces it

`POST /rollouts/{id}/evaluate` is a bounded, idempotent "evaluate health,
advance if every gate is satisfied" operation. It advances by **at most one
stage per call**, even when several stages' gates are simultaneously clear — a
call that walked 5% → 100% because everything happened to be green would defeat
the entire purpose of staging.

**This is not a scheduler, and this phase does not build one.** Phase 3.8 owns
the real distributed scheduler.

> **Since shipped.** Phase 3.8 calls this exact method on a timer — registered
> as the `deployment.canary_auto_advance` job — and **required no change
> here**, which was the point of bounding it this way. Phase 2.1.3's interim
> in-process loop (`app/integration/scheduler.py`), cited here as the same
> relationship, was retired in the same phase along the replacement path it had
> specified for itself. See [scheduler.md](scheduler.md).

Manual advance is always available regardless of `advance_mode`. A stage marked
`MANUAL` is never advanced by the automated path; the response says so.

The response always carries a `gate_evaluation` block explaining what happened,
so a caller that did *not* advance learns why.

---

## The 3.5 / 3.7 seam

This phase handles the rollout's **own** safety:

- a stage whose health gate fails does not advance;
- the rollout can be paused, aborted, or can **request** a rollback, which
  returns all traffic to stable atomically and records the terminal outcome.

Phase 3.7 adds the **configurable automatic-rollback trigger policy** — governed,
per-tenant rules like "roll back automatically if the error rate exceeds X for Y
minutes". 3.7 decides *when* to call `request-rollback`; it does not
reimplement what it does. `ROLLBACK_REQUESTED` is terminal here precisely so
that seam stays clean.

---

## API

| Method | Path | Permission |
|---|---|---|
| `POST` | `/api/v1/runtime/agents/{agent_id}/environments/{environment_id}/rollouts` | `runtime.deployment.deploy` |
| `GET` | `/api/v1/runtime/rollouts/{id}` | `runtime.deployment.view` |
| `GET` | `.../rollouts/{id}/health` | `runtime.deployment.view` |
| `POST` | `.../rollouts/{id}/advance` | `runtime.deployment.deploy` |
| `POST` | `.../rollouts/{id}/evaluate` | `runtime.deployment.deploy` |
| `POST` | `.../rollouts/{id}/pause` \| `/resume` \| `/abort` \| `/promote` | `runtime.deployment.deploy` |
| `POST` | `.../rollouts/{id}/request-rollback` | `runtime.deployment.rollback` |

Mounted on the existing `/api/v1/runtime` router, as 3.4's traffic routes are.
`request-rollback` uses the pre-existing `runtime.deployment.rollback`
permission rather than `.deploy`: rolling back is the one rollout operation an
organization may well want to grant separately from the ability to push a canary
forward.

No production-specific permission is introduced. Phase 3.2's environment policy
(`requires_approval`, evaluated at deploy time) is where this codebase already
expresses "production needs more authority"; a second parallel mechanism here
would fragment it.

`Idempotency-Key` is honoured on every state-changing operation via 3.1's
`IdempotencyService`. The fingerprint carries the caller's **intent only** (the
rollout id) — never server-side state like the current stage index, since 3.1
treats a changed payload under the same key as a genuinely different request,
which would make every retry look new and defeat deduplication entirely.

### Error codes

| Code | HTTP | Meaning |
|---|---|---|
| `ROLLOUT_NOT_FOUND` | 404 | Unknown rollout, or another tenant's |
| `ROLLOUT_STAGE_GATE_NOT_MET` | 409 | Duration, samples and/or health not satisfied |
| `ROLLOUT_INVALID_TRANSITION` | 409 | Illegal state transition |
| `ROLLOUT_HALTED_BY_KILL_SWITCH` | 423 | §12 — the candidate is vetoed |
| `ROLLOUT_CONFLICT` | 409 | Lost an optimistic-concurrency race |

---

## Concurrency

`RolloutPlan.revision` is a SQLAlchemy `version_id_col`, so two actors advancing
one rollout cannot both win — the loser gets `ROLLOUT_CONFLICT` from the
database, not from timing.

Two details are load-bearing:

- **The stage index is committed before any traffic moves.** The loser of a race
  is rejected while the allocation is still untouched, so a rollout can never
  half-advance.
- **The whole mutation sequence sits inside the `StaleDataError` guard, not just
  the commit.** With a `version_id_col` mapper, SQLAlchemy raises at the *first
  flush* that emits the row's UPDATE — and the audit insert triggers exactly
  such a flush. Guarding only the commit lets a raw `StaleDataError` escape as a
  500 under a real race. Same lesson Phases 3.1 and 3.4 both recorded.

No advisory locks are taken anywhere in this engine, so nothing here can
deadlock against the execution path's own locks.

---

## Performance

Health aggregation runs on every stage-gate check — potentially every few
seconds for an active canary — so migration 0041 adds two indexes that
`agent_executions` genuinely lacked:

- `ix_agent_executions_version_created` on `(agent_version_id, created_at)` —
  the exact shape of the aggregation predicate. Verified by `EXPLAIN` to serve
  it as an **Index Only Scan**.
- `ix_agent_executions_deployment_created` on `(deployment_id, created_at)` —
  the per-deployment equivalent, and the **first index this column has ever
  had**.

Before them the table had `agent_version_id` alone and nothing touching
`created_at`, so every evaluation would have scanned a growing share of the
platform's entire execution history.

The health window is bounded to one hour of lookback even when a stage has been
open longer: a canary that was healthy this morning and started failing ten
minutes ago must not be rescued by the morning's good numbers.

---

## Deliberately not here

> **Milestone 3 is now complete (10/10).** Every phase named as an owner in
> this table has since shipped — the scope statement below is what *this*
> document's phase deliberately left alone, not a list of missing features.
> See [operations-center.md](operations-center.md) for the operator surface
> over all of it, and [workers.md](workers.md) for the execution fleet.

| Excluded | Owning phase |
|---|---|
| Automatic-rollback **trigger policy** (error-spike/cost/latency rules) | 3.7 — this phase requests rollback and reacts to a failed gate |
| Blue-green / recreate / rolling strategies | 3.6 / 3.9 |
| A real distributed scheduler | 3.8 — auto-advance here is interim and bounded |
| Workers / operator frontend | 3.9 / 3.10 |
| Any change to the resolver, execution gate, or allocation mechanics | 3.4 owns them; this phase drives them |
