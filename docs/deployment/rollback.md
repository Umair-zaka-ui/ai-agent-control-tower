# Automated rollback and release safety

Phase 3.7 (ACT-SRS-M3 §Phase-3.7, §11, §12). Phases 3.5 and 3.6 gave this
platform rollback *operations*. This phase gives it a **policy** — the governed,
per-tenant rules that decide when a rollback should happen without a human
watching a dashboard at 3am.

---

## What was actually missing

The build prompt for this phase described `rollback_target_id` as "a pointer
nothing reads". That was true when REPO_STATE recorded it, and it is worth
correcting rather than repeating: **Phase 3.6 already reads it** — a blue-green
rollback resolves its target from that field. What no phase had yet done was
*designate* it as part of a rollout, or honour it from any path other than
blue-green.

So there were three rollback implementations and three different notions of
"the target":

| Path | Target it used | What it did |
|---|---|---|
| `DeploymentService.rollback` (Phase 5.0) | caller-supplied version id | a **redeploy** — reassigns `agent_version_id`, no traffic shift |
| `CanaryRolloutService.request_rollback` (3.5) | `plan.stable_version_id` | candidate weight → 0 via 3.4 |
| `blue_green_rollback` (3.6) | `version.rollback_target_id` | atomic switch back via 3.4 |

This phase adds one authoritative answer and one operation that every trigger
funnels through.

---

## The authoritative target

`AgentVersion.rollback_target_id` on the **currently deployed version** is the
answer to "where does this rollback go".

When a rollout is in scope, its `stable_version_id` must agree with it. A
disagreement **fails closed** with `ROLLBACK_TARGET_UNAVAILABLE` rather than
picking a winner: two sources naming different versions means the platform does
not actually know what the last-known-good is, and rolling back to a guess is
worse than refusing — because a wrong rollback looks like a successful one.

Fail-closed is likewise the answer when there is no target, when the target
belongs to another agent, when it is not `PUBLISHED`/`DEPRECATED`, or when it is
the version already deployed. **Rolling back to nothing is not a rollback.**

The field is written through `VersionLineageService.set_rollback_target` — the
existing writer, which validates same-agent and rollback-eligible status —
never by a raw column assignment. That is what makes it authoritative without
breaking the lineage rules it already had, and a test asserts the module
contains no direct assignment to the column.

---

## One rollback, four triggers

`RollbackService.execute` is the single implementation. The triggers are data,
not four code paths:

| Trigger | Who | Kill switch blocks it? | `initiated_by` |
|---|---|---|---|
| `MANUAL` | an operator | **no** | the operator |
| `REQUESTED` | 3.5 / 3.6 | no | the operator |
| `AUTOMATIC` | the trigger policy | **yes** | `null` |
| `FORCED` | an operator with elevated authority | no | the operator |

When a rollout is in scope, the traffic move is **delegated to 3.5's own
`request_rollback`** rather than reimplemented — that method already moves the
candidate to zero through 3.4's allocation and drives the plan's state machine.
Outside a rollout the move goes directly through 3.4's `set_weights`. Either
way, `strategies.py`-style discipline applies: this module holds no reference to
the weight tables at all, asserted against the parsed AST, so bypassing 3.4 is
structurally impossible.

`initiated_by` is deliberately null for an automatic rollback. Writing a system
user id there would make the audit trail claim a person acted.

---

## Kill-switch dominance — and the distinction that matters (§12)

The rule is that **automation** is subordinate to a kill switch. It is not that
**rollback** is. Conflating those would make the platform less safe, not more.

- An **automatic** rollback on a killed agent does not run. It records why and
  stops. Automation that "rolled back to a healthy version and reactivated it"
  would be automation quietly undoing a human's kill — the single thing §12
  exists to prevent.
- A **manual** rollback on a killed agent still runs. This matches Phase 3.6's
  reasoning exactly: rolling back reduces the candidate's exposure, and a kill
  switch must never trap an operator on the version they are trying to leave.

Nothing in `rollback.py` writes `Agent.lifecycle_status` or lifts a deployment's
suspension, and a structural test asserts the *absence* of those writes rather
than the intention to avoid them. Automation cannot clear a kill switch it has
no code to clear.

**The check runs before health, and that ordering is load-bearing.** The health
engine independently returns `UNKNOWN` for a vetoed candidate, so checking
afterwards would surface a kill switch as *"health verdict UNKNOWN is not
evidence of a regression"* — safe, but the wrong explanation. An operator needs
to see that automation stood down because it was **told to**, not because it
could not form a judgement. (It is checked again before executing, because a
kill activated during the aggregation must still stop the rollback.)

---

## The trigger policy

Per-organization, optionally per-environment and per-agent, resolved
most-specific-wins. **Absent an enabled policy, nothing ever fires** — automation
is opt-in, so a tenant that configures nothing keeps exactly the manual
behaviour 3.5 and 3.6 gave them, and no organization acquires automation by
accident.

| Threshold | Default | Meaning |
|---|---|---|
| `error_rate` | 0.20 | absolute error rate on the candidate |
| `denial_rate` | 0.20 | policy-denial surge — the version runs fine and is being refused |
| `latency_regression_multiplier` | 2.0 | candidate p95 versus the baseline's |
| `cost_regression_multiplier` | 2.0 | candidate cost **per execution** versus the baseline's |
| `rollback_on_unhealthy` | on | a 3.5 `UNHEALTHY` verdict is itself sufficient |

These are deliberately **wider than Phase 3.5's stage-gate thresholds**. A canary
stage refusing to advance is cheap and reversible — the candidate simply waits.
An automatic rollback is neither: it moves production traffic with no human in
the loop. The bar for acting unilaterally is higher than the bar for declining
to promote, and the numbers say so. A test asserts the relationship rather than
leaving it to drift.

Cost is compared per execution, not in total, so a candidate serving more
traffic than the baseline does not look expensive merely for being busier. A
zero or missing baseline value is skipped rather than treated as infinitely
good — dividing by an absent measurement would manufacture a regression out of
nothing.

### `NOTIFY_ONLY`

`mode` separates *detecting* a regression from *acting* on one. `NOTIFY_ONLY`
evaluates and records exactly as `AUTO_EXECUTE` does but leaves traffic
untouched. An organization may reasonably want to watch the automation agree
with its engineers for a month before letting it act. `AUTO_EXECUTE` is the
default for a policy someone deliberately created.

### INSUFFICIENT_DATA never triggers

Below `min_samples` the verdict is `INSUFFICIENT_DATA` and **no trigger may
fire**, no matter how bad the few samples look. Three failures out of three is a
100% error rate and still not evidence — the same discipline Phase 3.5 applies
to its stage gates, for the same reason. `UNKNOWN` is treated identically: it is
the absence of a judgement, not a bad one.

---

## Anti-flap

A rollback that immediately re-triggers is worse than no automation. Two
independent guards, either of which alone would be insufficient:

1. **A cooldown** (`cooldown_seconds`, default 900) measured from the most
   recent automatic rollback for the same (agent, environment). Within it, a
   crossing is reported and acting is declined.
2. **Only a version on trial is a candidate.** A version holding zero traffic
   has already been rolled away from, so it is never re-judged. This is what
   keeps the restored last-known-good from being rolled back by the same policy
   on the next tick.

Deduplication is separate from both and is enforced by the database, not by
application timing: a partial unique index on `rollback_events.dedup_key`, keyed
on `(deployment, deployed version)`, so one threshold crossing produces exactly
one automatic rollback. It is the same primitive Phase 3.4 used for
`uq_traffic_allocations_current`. Manual and forced rollbacks are deliberately
outside the constraint — a human may roll the same deployment back twice, and
being refused by a uniqueness index would be absurd. Automation is not owed that
latitude.

---

## Evidence preservation

`rollback_events.evidence_ref` holds the candidate's health metrics, baseline,
window, verdict and the specific thresholds crossed, captured at the moment of
rollback. A rolled-back candidate is precisely the thing an engineer needs to
diagnose, and **the rollback must not be the act that destroys the reason for
it**. The candidate version itself is never deleted or mutated.

This is also why `rollback_events` exists as a table rather than only as audit
events: the trigger engine must *read* rollback history to enforce the cooldown
and to deduplicate. Querying an append-only, indexed, purpose-shaped table for
that is honest; scraping the generic audit log for control-flow decisions would
couple safety behaviour to an observability surface that is free to change.

---

## Recovery: durable intent, ephemeral evaluation

Mapping onto `RECOVERY.md`'s own durable/ephemeral split:

**Durable.** A `RollbackEvent` row is committed as `IN_PROGRESS` *before* any
traffic moves, and marked `COMPLETED` only after the allocation commits. A
process dying between the two leaves a readable record of an intent that was
formed but not finished. `resume_incomplete` finds such rows and completes them,
and it runs at the start of every evaluation — so a crashed rollback is never
left behind by the next tick.

The ordering is the entire guarantee, and a test asserts it structurally: if the
row were written *after* the move, a crash would lose the record of an action
that had already happened, which is the worse of the two failure modes.

Re-applying the move is harmless because 3.4's allocation is a declaration of
the desired end state rather than a delta — setting the same weights twice
leaves the same allocation. **There is no half-applied state for a resume to
compound**, because the allocation never has one.

**Ephemeral.** Health verdicts, threshold arithmetic and cooldown windows are
recomputed from the database on demand and kept nowhere.

---

## Override / forced rollback (§11)

A dangerous operation, treated as one: it requires the elevated
`runtime.deployment.force_rollback` permission, a written justification enforced
by the schema itself, and is audited at `CRITICAL` severity with the
justification recorded.

The override it grants is narrow and specific: **a forced rollback may name its
target explicitly**, bypassing the designated-target requirement that makes an
ordinary rollback fail closed. That is the whole point — it is the escape hatch
for when the designation itself is what is wrong, at 3am, with production down.

It does **not** override the kill switch, and cannot: a kill switch is the one
control whose value comes entirely from being unconditional.

One honest note about what the new permission buys in *this* codebase:
`SYSTEM_ROLE_PERMISSIONS` grants SUPER_ADMIN and ADMIN the entire catalog, so a
new code does not restrict them. What it does is make the separation
*expressible* — an organization can build a custom role holding
`runtime.deployment.rollback` without `runtime.deployment.force_rollback`, which
is impossible if the override reuses the ordinary permission. The distinction is
real at the tier below admin, and it is asserted by a test rather than assumed.

---

## The 3.5 / 3.7 seam

Stated in 3.5 and honoured here:

- **3.5** reacts to a failing health gate by refusing to advance, and can
  *request* a rollback.
- **3.7** configures the per-tenant rules that decide *when* an automatic
  rollback fires, and executes it — reusing 3.5's operation rather than
  reimplementing it.

They are complementary, not redundant. "The health gate failed, so do not
promote" and "health crossed a rollback threshold, so actively retreat" are
different decisions with different costs.

---

## API

| Method | Path | Permission |
|---|---|---|
| `POST` | `/api/v1/runtime/deployments/{id}/rollback/execute` | `runtime.deployment.rollback` |
| `POST` | `.../rollback/force` | `runtime.deployment.force_rollback` |
| `POST` | `.../rollback/evaluate` | `runtime.deployment.deploy` |
| `GET` | `.../rollback/history` | `runtime.deployment.view` |
| `GET`/`PUT` | `/api/v1/runtime/rollback-policies` | `.view` / `.deploy` |

**Why nested under `/rollback/...`.** `POST /deployments/{id}/rollback` has
existed since Phase 5.0 and performs a *redeploy*, not a traffic shift. Taking
that path over would have silently changed a Milestone 1 API contract and
required rewriting passing tests. Nesting is the identical resolution Phase 3.1
used when its `/pause`, `/resume` and `/retire` collided with Phase 5.0's, and it
leaves every pre-existing endpoint untouched.

`/evaluate` uses `.deploy` rather than `.rollback`: deciding whether automation
should act is a release-management act, and an operator trusted only to roll
back is not thereby trusted to arm or run the policy engine.

`Idempotency-Key` is honoured on all state-changing operations via 3.1's
`IdempotencyService`.

### Error codes

| Code | HTTP | Meaning |
|---|---|---|
| `ROLLBACK_TARGET_UNAVAILABLE` | 409 | no valid designated target — fail closed |
| `ROLLBACK_BLOCKED_BY_KILL_SWITCH` | 423 | automation stood down; a kill covers this agent |
| `ROLLBACK_FORCE_UNAUTHORIZED` | 403 | override without authority or justification |
| `ROLLBACK_CONFLICT` | 409 | lost an optimistic-concurrency or deduplication race |

`ROLLBACK_BLOCKED_BY_KILL_SWITCH` is distinct from 3.5's
`ROLLOUT_HALTED_BY_KILL_SWITCH` (a rollout is frozen) and from
`KILL_SWITCH_ACTIVE` (one execution refused). This one says the *automatic
rollback system* declined to act, and an operator needs to know automation stood
down rather than quietly reactivating something.

---

## Interim, and what 3.8 replaced

`POST .../rollback/evaluate` is a **bounded** operation: one call evaluates one
deployment and performs at most one rollback. It is not a scheduler and does not
loop.

> **Since shipped.** Phase 3.8 calls this exact method on a timer — registered
> as the `deployment.rollback_trigger_evaluation` job — and **required no change
> here**, which is what bounding it this way was for. Phase 2.1.3's interim
> in-process loop (`app/integration/scheduler.py`), cited here as the same
> relationship, was retired in that phase along the replacement path it had
> specified for itself. See [scheduler.md](scheduler.md).

---

## Deliberately not here

> **Milestone 3 is now complete (10/10).** Every phase named as an owner in
> this table has since shipped — the scope statement below is what *this*
> document's phase deliberately left alone, not a list of missing features.
> See [operations-center.md](operations-center.md) for the operator surface
> over all of it, and [workers.md](workers.md) for the execution fleet.

| Excluded | Owning phase |
|---|---|
| The distributed scheduler | 3.8 |
| Workers / operator frontend | 3.9 / 3.10 |
| Any new health computation | 3.5 owns it; this phase consumes its verdicts |
| New strategies / ROLLING | 3.6 / 3.9 |
| Changes to the resolver, gate, allocation, canary or strategies | driven, never modified — asserted against `main` by a test |
