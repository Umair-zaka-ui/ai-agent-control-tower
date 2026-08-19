# Deployment strategies: RECREATE, BLUE_GREEN, ROLLING

> **Updated for Phase 3.9.** This document was written in 3.6, when ROLLING
> was deliberately deferred for want of an instance substrate. Phase 3.9
> built the worker fleet, so ROLLING is now implemented over real cohorts.
> The 3.6 reasoning is preserved below rather than deleted — it is why the
> implementation looks the way it does.

Phase 3.6 (ACT-SRS-M3 §Phase-3.6, §3.6, §12). This phase makes
`agent_deployments.deployment_strategy` mean something. Until now it was pure
data — set on create, copied on promotion, exposed in the API, and **never
dispatched on**. This is its first consumer.

---

## Strategies are weight patterns, not separate machinery

Canary (3.5), RECREATE and BLUE_GREEN are all *weight transitions over Phase
3.4's traffic allocation*. They differ in the pattern and in what is preserved —
not in the mechanism.

| Strategy | Weight pattern | What happens to the old version |
|---|---|---|
| **CANARY** (3.5) | 5 → 25 → 50 → 100, gated per stage | superseded at the end |
| **RECREATE** | 0 → 100 in one cutover | superseded immediately |
| **BLUE_GREEN** | 0 (warm) → 100 in one atomic switch | **preserved at 0%** as a rollback target |
| **ROLLING** | fleet-derived steps, cohort by cohort | superseded at the end |

So this phase builds two new *patterns* and reuses the *mechanism* wholesale.
Every traffic change goes through `TrafficAllocationService.set_weights`
(atomic, revisioned, eligibility-checked, audited), every cutover is gated by
3.3's release gate, every state change goes through 3.1's lifecycle authority,
and the §12 veto reads the same fields 3.4's resolver reads.

`strategies.py` holds **no reference to `DeploymentTrafficWeight` or
`DeploymentTrafficAllocation`**, so bypassing 3.4 is structurally impossible
rather than merely discouraged. A test asserts that against the parsed AST.

---

## Dispatch is on the column, not the request

```
POST /api/v1/runtime/deployments/{id}/strategy/execute
```

One endpoint, dispatching on `deployment_strategy`. The build prompt offered
either this or per-strategy paths (`/strategy/recreate`); this is the choice and
the reason: **a `/strategy/recreate` path would let a caller run a recreate on a
deployment declared BLUE_GREEN**, making the column decorative again. The
declaration on the row is the input. To deploy differently, change the
declaration. The strategy is deliberately not read from the request body either,
for the same reason.

What `execute` does per strategy:

| `deployment_strategy` | `execute` performs |
|---|---|
| `RECREATE` | the cutover |
| `BLUE_GREEN` | the **prepare** (warm GREEN at 0%) |
| `ROLLING` | starts a rolling conversion of the worker fleet (Phase 3.9) |
| `CANARY` | points at 3.5's rollout API |

Blue-green's switch and rollback are separate endpoints because they are
separate operator decisions — warming a candidate is not agreeing to send it
production traffic, and rolling back is not the inverse of preparing.

---

## RECREATE

A single clean cutover, no overlap.

1. Veto check (§12), then the release gate — **fail closed** on BLOCK.
2. Candidate → 100%, previous → 0%, in **one** `set_weights` call.
3. The previous deployment is superseded through 3.1's lifecycle authority.

"Stops receiving new work" is concrete: `SUPERSEDED` is in 3.4's
`NON_SERVING_LIFECYCLE`, so the resolver will not route to it at all. Executions
already running are untouched — this changes what is *routed*, not what is
mid-flight.

**Ordering matters, and it is deliberate.** The supersede happens *after* traffic
moves. Doing it first would make the old deployment non-servable, and 3.4 rejects
weight on a version with no servable deployment — the cutover would fail on its
own precondition.

Atomicity (FR-012) is inherited, not re-implemented: both weights move in one
allocation revision, so there is no committed state in which neither version
serves or both serve fully. A test asserts this over *every* revision an agent
has ever had, not just the final one.

---

## BLUE_GREEN

### Prepare — warm GREEN at 0%

BLUE keeps 100% while GREEN is brought to a servable, gate-passing state holding
**zero** traffic. Validation *is* the gate (FR-021): warming a candidate that
could not pass would be pointless work and a misleading "ready" signal.

GREEN is genuinely warm — deployed, lifecycle-ACTIVE, eligible — just not routed
to, because 3.4's resolver skips zero-weight entries. A test drives real
executions during this state and asserts every one reaches BLUE.

### Switch — atomic

One `set_weights` call moves BLUE 100→0 and GREEN 0→100 in a **single allocation
revision**. There is no committed interval in which both serve. The test asserts
exactly one new revision appears.

**The gate runs again at the switch, not only at prepare.** A deployment can pass
validation and then have its agent killed, its version revoked, or its signature
invalidated before anyone presses the button. Re-checking is the entire value of
a gate, and there is a test for precisely that sequence.

### Blue preservation — and why it needed no new table

After the switch, BLUE:

- stays **lifecycle-ACTIVE** (not superseded — this is the defining difference
  from RECREATE);
- holds **0%** of the allocation, so it serves nothing — preserved is *not*
  split-serving, and a test drives real executions to prove it;
- is recorded as GREEN's rollback target on the existing
  `AgentVersion.rollback_target_id`, written through
  `VersionLineageService.set_rollback_target` (which validates same-agent and
  rollback-eligible status) rather than by a raw column assignment.

That field had been, in REPO_STATE's own words, "a settable pointer only; nothing
reads it to perform a rollback". Blue-green rollback now reads it — the first
code that acts on it.

**"Prepared" needs no state either.** GREEN carries a zero-weight entry in the
current allocation exactly when it has been warmed, so `BLUE_GREEN_NOT_PREPARED`
is inferable from 3.4's existing rows. No new table, no new column, no migration
— the migration head is unchanged at `0041`.

### Rollback

Returns traffic to BLUE in one allocation transition. This is the *operation*;
Phase 3.7 adds the *policy* that decides when to call it automatically.

Two deliberate omissions, both for the same reason — **rollback must work when
things are worst**:

- **No veto check.** Rolling back reduces the candidate's exposure, and a kill
  switch must never trap an operator on the version they are trying to leave.
- **No gate re-run.** BLUE is the version that was already serving; demanding it
  re-pass a gate before it can be returned to would make rollback fail exactly
  when it is most needed.

---

## ROLLING — over the real worker fleet

### Why 3.6 refused, and why the refusal was right

Rolling means "replace running instances a few at a time", and in Phase 3.6
**this platform had no instance substrate to roll over**. The two replica-count
columns on `agent_deployments` are vestigial: the legacy
`DeploymentService.deploy`/`retire` set them to constants, and nothing reads
them to make any decision.

A handler that decremented and incremented them would have reported progress
while nothing rolled — the precise pretence SRS §3.6 forbids, and worse than
an honest error because it would look like a working feature. So 3.6 declared
ROLLING, dispatched it, and raised `STRATEGY_ROLLING_DEFERRED` (501) naming
Phase 3.9.

**Those columns are still untouched.** Phase 3.1's AC-14 test asserts their
names appear *nowhere* in `app/runtime/deployment/` — prose included — and
Phase 3.9 kept that guard rather than relaxing it. The rolling implementation
refers to them only indirectly, for the same reason: a module that cannot even
name them cannot quietly grow a fake rolling handler around them.

### What a cohort actually is

A **cohort** is a declared, labelled partition of the registered worker fleet
(`worker_registrations.cohort`). Its **capacity** is the summed declared
concurrency of its live, currently-heartbeating workers — how many executions
those processes can actually run at once, reported by the processes
themselves. See [workers.md](workers.md).

### What rolls, precisely

A rolling deployment converts the fleet cohort by cohort, and each step moves
the candidate's traffic share to the fraction of total fleet capacity
converted so far.

| Fleet | Steps |
|---|---|
| two cohorts holding 8 and 2 slots | **80% → 100%** |
| four equal cohorts | 25 → 50 → 75 → 100 |
| one undivided cohort | 100 (one step) |

**The shape of the rollout is dictated by the shape of the fleet.** That is
the entire difference between rolling and a canary — a canary's ladder is
declared by the operator, a rolling deployment's is derived — and the entire
reason it could not be written before the fleet existed.

The derivation is recorded on the plan as `cohort_plan`, because a rollout
whose step sizes become unexplainable minutes later is not much better than an
invented one. The final step is pinned to exactly 100 rather than left to
rounding: without the pin a rollout could finish at 99% and leave the old
version quietly serving one request in a hundred forever.

### The honest limit

**Workers are not version-pinned.** An execution's version is chosen at
*enqueue* time by Phase 3.4's resolver and written onto the execution row; any
worker may run any execution it claims. So what a rolling step shifts is the
*share of new work routed to the candidate*, in units of real fleet capacity —
it does not make cohort A's processes exclusively serve the new version.

That limit is deliberate. Pinning workers to versions would put version
filtering in the hot claim path, make the worker second-guess 3.4's routing
decision (3.4 is the sole allocator), and starve any execution whose version
had no converted worker yet. The design keeps one allocator and makes the
fleet the thing that **sizes** and **gates** the rollout:

- **Sizing** — step weights are computed from live capacity, so a step can
  never describe capacity that does not exist.
- **Gating** — before each step, the cohort it names must still be present and
  heartbeating. A rolling deployment cannot advance over a cohort that died
  mid-rollout; it fails closed with `ROLLING_COHORT_INVALID`.

Neither is expressible without a real fleet, and a counter on a deployment row
could never have done either.

### There is no rolling state machine

Phase 3.5 already built one — seven states, pause, resume, abort,
rollback-request, per-stage health gates, optimistic concurrency, idempotency,
audit. Rolling needs exactly that machine and differs only in where the stage
weights come from.

So **a rolling deployment *is* a `RolloutPlan`**, with `kind='ROLLING'`. Every
operation after the start is Phase 3.5's, unmodified:

```
POST /api/v1/runtime/deployments/{id}/strategy/rolling   # start (3.9)
POST /api/v1/runtime/rollouts/{id}/advance               # convert next cohort
POST /api/v1/runtime/rollouts/{id}/pause | /resume | /abort
POST /api/v1/runtime/rollouts/{id}/request-rollback
```

There is deliberately no `/strategy/rolling/advance`. One set of controls for
both plan kinds means no second half-copy to drift — and the cohort-liveness
gate lives *inside* the advance (`CanaryRolloutService._assert_kind_preconditions`),
so choosing the generic route cannot bypass it.

Rollback integration (M3-3.9-FR-033) is inherited the same way: a rolling
plan's `ROLLBACK_REQUESTED` is the same state Phase 3.7 already understands.

### Starting one

```http
POST /api/v1/runtime/deployments/{deployment_id}/strategy/rolling
Idempotency-Key: <optional>

{ "health_requirement": "HEALTHY", "min_samples": 50, "advance_mode": "MANUAL" }
```

Notably absent from the request: **the stages**. A caller may set how each
derived step is *gated* — a governance decision — but not the weights, which
are a claim about capacity that only the fleet can make.

With no live workers the call fails closed with `ROLLING_COHORT_INVALID` (422).
A rolling deployment over an empty fleet would be a progress bar over nothing.

---

## Kill-switch dominance (§12)

No strategy activates a vetoed version. `assert_not_vetoed` runs before every
operation that could give a candidate *more* traffic — RECREATE cutover,
blue-green prepare, blue-green switch — and reads the same two fields 3.4's
resolver reads, so a strategy can never activate something the execution gate
would refuse to serve.

`KillSwitchService` suspends the agent at AGENT scope and the deployment's
`status` at ORGANIZATION/PROJECT/PLATFORM scope; both are covered.

The sharpest tested case: GREEN is prepared and ready, the agent is then killed,
and the switch is refused — GREEN stays at 0%.

Rollback deliberately stays available while killed (see above).

This reuses the pre-existing, generic `KILL_SWITCH_ACTIVE` (423) rather than
3.5's `ROLLOUT_HALTED_BY_KILL_SWITCH`: an operator running a blue-green switch
has no rollout, and "rollout halted" would be the wrong vocabulary for what they
just did. No new code is minted for a condition the platform already names.

---

## API

| Method | Path | Permission |
|---|---|---|
| `POST` | `/api/v1/runtime/deployments/{id}/strategy/execute` | `runtime.deployment.deploy` |
| `POST` | `.../strategy/blue-green/switch` | `runtime.deployment.deploy` |
| `POST` | `.../strategy/blue-green/rollback` | `runtime.deployment.rollback` |

Rollback uses the pre-existing `runtime.deployment.rollback` permission, matching
3.5's own rollout rollback: an organization may well grant "can return to the
previous version" separately from "can push a new one forward". No
production-specific permission is introduced — 3.2's environment policy is where
this codebase already expresses that, and a second parallel mechanism would
fragment it.

`Idempotency-Key` is honoured on all three via 3.1's `IdempotencyService`, with
the fingerprint carrying the caller's intent (the deployment id) only.

### Error codes

| Code | HTTP | Meaning |
|---|---|---|
| `ROLLING_COHORT_INVALID` | 422 | No live fleet, or a step's cohort has died (Phase 3.9) |
| `STRATEGY_GATE_BLOCKED` | 409 | The release gate blocked a cutover or switch |
| `BLUE_GREEN_NOT_PREPARED` | 409 | Switch before prepare, or rollback with no preserved BLUE |
| `STRATEGY_CONFLICT` | 409 | Lost an optimistic-concurrency race |

`STRATEGY_ROLLING_DEFERRED` (501) was 3.6's answer to an invoked ROLLING.
Phase 3.9 implemented the strategy, so nothing raises it any more — asserted
mechanically in `test_ac11_nothing_raises_the_deferred_error_any_more`. The
`ErrorCode` member is deliberately *kept* rather than deleted: it was returned
to real API consumers with a documented meaning, and a consumer holding that
string in a retry table should find it still explicable rather than vanished.

`ROLLING_COHORT_INVALID` is **422, not 409**: the fleet the request implies
does not exist, which is a problem with what was asked for rather than a
conflict with current state.

`STRATEGY_GATE_BLOCKED` is distinct from 3.1's `DEPLOYMENT_PREFLIGHT_BLOCKED`:
that one stops a deployment *reaching* ACTIVE, this one stops an already-active
deployment *taking over traffic*. Different operator decisions, different
remedies.

---

## Concurrency

A 3.4 optimistic-concurrency loss (`TRAFFIC_ALLOCATION_CONFLICT`) is re-raised as
`STRATEGY_CONFLICT`, so the caller sees a failure in the vocabulary of the
operation they actually invoked, with 3.4's own reason preserved in the message.
`StaleDataError` on the deployment row is translated the same way.

The race test is **deterministic**, not a timing-dependent thread barrier: a real
second connection commits a competing allocation and holds its transaction open,
so the strategy under test blocks inside Postgres on 3.4's partial unique index
and loses. Same pattern as 3.4's and 3.5's own races.

---

## The 3.6 / 3.7 seam

This phase provides the rollback *operations*:

- 3.5: `POST .../rollouts/{id}/request-rollback` (canary)
- 3.6: `POST .../strategy/blue-green/rollback` (blue-green)

and it **preserves the rollback target** that makes an instant return possible.

Phase 3.7 adds the configurable, per-tenant automatic **trigger policy** — rules
like "roll back if the error rate exceeds X for Y minutes" — deciding *when* to
call these. It does not reimplement what they do.

---

## Deliberately not here

| Excluded | Owning phase |
|---|---|
| Version-pinned worker cohorts | not built — see "The honest limit" above |
| Any use of the vestigial replica columns | never — they have no substrate |
| Automatic-rollback trigger policy | 3.7 |
| Canary / progressive rollout | 3.5 (already built) |
| Release Operations Center | 3.10 |
| Changes to the resolver, gate, or allocation mechanics | 3.4 owns them; this phase drives them |
