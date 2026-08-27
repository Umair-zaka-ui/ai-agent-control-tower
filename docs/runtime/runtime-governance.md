# Runtime governance — the engine, its decisions, and the two planes

> **Phase 4.3 (ACT-SRS-M4 §8-4.3, §9, §17, §19).** How the platform governs an
> agent *while it runs*. For the checkpoints themselves and the constraint
> reference, see [runtime-policy-checkpoints.md](./runtime-policy-checkpoints.md).
> For why it fails closed, see
> [ADR-0009](../architecture/adr/0009-runtime-governance-as-a-fail-closed-plane.md).

## The one-paragraph version

One engine — `RuntimeGovernanceEngine` — is consulted at six points inside the
model→tool→model loop and returns a structured decision: **ALLOW / DENY /
CHALLENGE / STOP**, plus an obligation and a reason with a stable code. It is
the *only* thing that decides whether a loop may continue: the four termination
caps that used to be `if` statements in the loop body are now constraints
inside it. It is enforced **around** the model — the model is never asked to
comply with anything. And it **fails closed**: a mandatory checkpoint that
cannot be evaluated stops the execution.

## The two planes now live in one loop

This is the single most important thing to understand before changing anything
in either package, because the two rules sit within a few dozen lines of each
other and look superficially alike.

| | Governance plane | Telemetry plane |
|---|---|---|
| Package | `app.runtime.governance` | `app.observability` |
| Phase | 4.3 | 4.1 / 4.2 |
| Question | *May this execution continue?* | *What happened?* |
| On failure | **Fails CLOSED** — STOP | **Fails OPEN** — swallow, continue |
| Authority | Decides | Observes |

**A telemetry failure never changes a governance decision**, and **a governance
decision never reads the telemetry plane.** Both directions are tested, and the
second is structural: the governance package does not import
`app.observability`'s read models at all, and there is no telemetry handle in
a `CheckpointContext` for a constraint to read even if it wanted one.

The more dangerous direction is the less obvious one: a broken telemetry plane
must not be able to *suppress* a governance stop either. Fail-open must not
leak into fail-open-for-governance-too. There is a test for exactly that.

## One enforcement path

Before Phase 4.3, `ToolLoopOrchestrator.run` enforced four caps inline:

```python
if iteration > max_iterations:                         # MAX_ITERATIONS
if (time.monotonic() - loop_start) > WALL_CLOCK:       # WALL_CLOCK
if key in seen_calls:                                  # REPEATED_CALL
if total_sum > MAX_TOTAL_TOKENS:                       # TOKEN_BUDGET
```

None of those comparisons exists in the orchestrator any more. They are
constraints in `app.runtime.governance.constraints`, reached through the same
`evaluate()` call as every richer rule, and they still write the same
`termination_reason` values (`MAX_ITERATIONS`, `WALL_CLOCK`, `REPEATED_CALL`,
`TOKEN_BUDGET`) and raise the same `TOOL_LOOP_LIMIT_EXCEEDED`.

**Why this mattered enough to touch the execution path.** Two enforcers can
disagree. If the inline caps and a new engine both independently decided "may
this loop continue", there would be states where one says stop and the other
says continue, and the winner would be whichever `if` the loop reached first —
an implementation detail nobody wrote down. Generalizing was the expensive
option once; adding a second path is the cheap option that stays expensive.

The property is **tested structurally, not documented**: the orchestrator no
longer names the cap settings in any comparison and no longer raises the cap
error code, asserted over the AST so that a check reintroduced in a helper, a
comprehension or a nested function is caught too. A grep would only catch
someone restoring the old lines verbatim; the failure mode this guards against
is someone adding *just one quick check* beside the engine.

### What the loop looks like now

Each of the six sites is one line and contains no comparison of its own:

```python
check(Checkpoint.BEFORE_FIRST_MODEL_CALL if iteration == 1
      else Checkpoint.BEFORE_NEXT_ITERATION)
```

`check` builds the `CheckpointContext` and calls `governance.enforce`, which
evaluates, records, and raises if the decision halts. A caller cannot evaluate
without recording, or record without acting.

## The decision

```python
GovernanceDecision(
    checkpoint=Checkpoint.BEFORE_NEXT_ITERATION,
    decision=Decision.STOP,
    reason_code=ReasonCode.MAX_EXECUTION_COST,
    reason="Execution cost 0.003000 reached the governed ceiling of 0.002500.",
    obligation=None,
    policy_id=UUID(...),
    termination_reason="GOVERNANCE_STOP",
    error_code="GOVERNANCE_EXECUTION_STOPPED",
    stop_action=StopAction.NONE,
)
```

`ALLOW` continues. **`DENY` refuses a specific act** — this tool call, this
model — and still halts the loop, because a denied call the model requested
cannot simply be skipped: the model would be handed a transcript that silently
omits what it asked for. **`CHALLENGE`** raises a human approval obligation.
**`STOP`** halts the execution.

`termination_reason` and `reason_code` are two vocabularies and are deliberately
not merged. `termination_reason` is the execution's terminal state, written
since Phase 5.6a.3 and read by existing clients. `reason_code` is this phase's
governance lineage, stable enough for an operator's saved filter or an alert
rule to name.

## Policies

`runtime_governance_policies`, scoped organization → environment → agent, with
**most-specific-wins ordering** — the same shape `rollback_trigger_policies`
already uses, so an operator who has learned one has learned both.

Resolution returns a **list**, not a single winner, and that is the substantive
difference from rollback triggers. Rollback asks "which rule fires", where
picking one is right. Governance asks "what may this execution do", where
picking one would mean a narrow per-agent policy *silently switched off* the
organization-wide mandatory ceiling above it. Constraints accumulate; the most
specific is merely evaluated first, so its message is the one an operator sees
when several would object.

**Absent any policy, nothing changes.** The built-in loop-safety caps always
apply; everything configurable is opt-in. A tenant that configures nothing gets
exactly the execution behaviour Phase 5.6a.3 gave them, which is what made
shipping an engine on the execution path survivable.

### `mandatory` and failing closed

```
mandatory = true   ->  a checkpoint that cannot be evaluated STOPs the execution
mandatory = false  ->  the failure is logged and the policy is skipped
```

The asymmetry is the design. "We could not check the rule you told us was
non-negotiable" is not a reason to proceed. But an advisory rule that halted
production the first time it misbehaved would be a worse control than no rule
at all — and an organization's first governance policy is almost never
enforcement, it is someone watching a threshold for a month to see whether the
platform agrees with their engineers.

Policy **resolution** failing is the strongest form of unevaluable: the
platform does not merely not know what the rules say, it does not know whether
a mandatory one applies. That fails closed regardless of any flag.

### Consistency: policy is snapshotted per execution

An execution is governed by the policy set in force **when its loop began**. A
policy edited mid-flight applies to executions that start after it.

Re-resolving at every checkpoint would let a tightened policy stop an execution
at iteration 5 having permitted iterations 1 through 4 under looser rules —
a half-governed execution whose decision lineage cannot be read as a single
story. It also keeps six checkpoints per iteration off the query path.

The operational consequence, stated plainly: tightening a ceiling during an
incident takes effect for the *next* execution, not the ones already running.
Use the kill switch for the ones already running — which is what it is for.

## Interventions

| Intervention | How |
|---|---|
| Stop before the model call | `STOP` at `BEFORE_FIRST_MODEL_CALL` / `BEFORE_NEXT_ITERATION` |
| Stop before a tool call | `DENY`/`STOP` at `BEFORE_TOOL_EXECUTION` |
| Reject one specific tool call | `DENY` naming the tool |
| Require approval | `CHALLENGE` — a `RuntimeApproval` through the existing funnel |
| Stop further iterations | `STOP` at any checkpoint |
| Suspend | `stop_action: KILL_EXECUTION` / `KILL_AGENT` — the **existing** kill switch |

### The kill switch is triggered, never paralleled (§19)

A `STOP` whose policy declares a `stop_action` calls
`KillSwitchService.activate_system`, which reuses the same `_cancel_executions`
and `_suspend_deployments` the operator-facing `activate` uses and writes the
same `RUNTIME_KILL_SWITCH_ACTIVATED` audit event. The engine implements no
suspension of its own.

**Automation reaches two scopes only**: `EXECUTION` and `AGENT`. `PROJECT`,
`ORGANIZATION` and `PLATFORM` are unreachable from a policy — a rule
misconfigured by one tenant must not be able to halt a project, an
organization, or the platform, and those scopes stay behind a human holding the
permission to use them.

**The engine never clears a kill.** There is no assignment anywhere in the
governance package that sets `lifecycle_status` back to `ACTIVE` or
`cancel_requested` back to `False`, asserted over the AST. And a governance
stop after a kill is non-retryable — an automatic retry past a kill would be
automation overruling an operator.

Kill state is checked **first at every checkpoint**, before caps and before
policy, and read fresh from the database rather than from the session's cached
row: a kill fired by an operator arrives on a different connection, so the
identity map cannot see it.

### CHALLENGE, and the one thing this platform cannot do

A challenge raised at `BEFORE_FIRST_MODEL_CALL` parks the execution in
`PENDING_APPROVAL` with a `RuntimeApproval(requested_action="EXECUTION")`.
Nothing has been dispatched, so the existing funnel's *approve → QUEUED → run*
path resumes it honestly.

A challenge raised **later** cannot be resumed. This platform has no mechanism
to re-enter a partially-run loop, and re-queuing would re-execute tool calls
that already had their side effects. So it raises a
`RuntimeApproval(requested_action="POLICY_EXCEPTION")` and the execution
terminates in `BLOCKED` with the obligation standing for a human.

Parking it in `PENDING_APPROVAL` where nothing could move it out again would be
the worst of the three options, which is why the non-resumable case ends rather
than waits. Approving it authorizes a *fresh* execution.

## Decision lineage

`runtime_governance_decisions` — append-only, one row per **material** decision,
indexed by `(execution_id, evaluated_at)`.

Material means: anything that is not a plain ALLOW, plus the ALLOW at
`BEFORE_FINAL_OUTPUT`. Recording all six checkpoints on every iteration would
write roughly sixty rows for a ten-iteration execution to say "nothing
happened" sixty times, burying the rows that matter. Keeping the terminal ALLOW
means the table still carries positive evidence that the engine ran and
permitted the result — an empty decision history would otherwise be
indistinguishable from an engine that never ran.

Append-only is enforced at the database (`REVOKE UPDATE, DELETE ... FROM
PUBLIC`), not only by convention. A governance decision that could be edited
after the fact is not evidence of anything.

`trace_id` is a plain string rather than a foreign key, because a trace is not
a row — Phase 4.2 assembles traces from existing tables. It is the same value
`app.observability.trace.trace_id_for` derives, so a decision joins a trace
timeline without either side owning the other.

## The engine is not a second authorization system

`AuthorizationGateway` stays authoritative for *may this principal act*. This
engine answers *may this execution continue*, inside a request that gateway has
already authorized. It never grants anything, never replaces a permission
check, and does not import the gateway at all — asserted over the AST.

## Commit-before-dispatch (§9, the M1 deadlock)

Every checkpoint does at most two kinds of database work: one plain
**non-locking** `SELECT` of kill state, and — for a material decision only —
one `INSERT` into `runtime_governance_decisions`.

No statement in the governance package takes `FOR UPDATE` or `FOR NO KEY
UPDATE`. The only lock a checkpoint can cause is the foreign-key `KEY SHARE` on
the execution's own row implied by the decision INSERT — which is exactly the
lock `ToolLoopOrchestrator._append_message` has been taking on every turn since
Phase 5.6a.3, and which is *compatible* with the `KEY SHARE` a tool-executing
thread needs for its `tool_calls` insert.

The M1 deadlock required a `FOR UPDATE` held across dispatch. Nothing here can
produce one, proven both structurally and behaviourally: a test evaluates a
checkpoint that writes a decision row, leaves it uncommitted, and takes the
tool-thread's lock from a second real connection with `NOWAIT`.

## Performance (§25)

One full checkpoint evaluation — kill-state read, built-in caps, policy
constraints — measured against a realistic policy:

| | |
|---|---|
| p50 | **0.42 ms** |
| p95 | **0.68 ms** |
| Per loop iteration | ~1.7 ms (four checkpoints; five when a tool is called) |

Against model calls that take hundreds of milliseconds this is noise, but it is
not free. The measurement is a recorded test rather than a note in a commit
message, so it keeps being checked.

## API

| Method | Path | Permission |
|---|---|---|
| GET/POST | `/api/v1/runtime/governance/policies` | `runtime.governance.manage` |
| GET/PATCH | `/api/v1/runtime/governance/policies/{id}` | `runtime.governance.manage` |
| GET | `/api/v1/runtime/executions/{id}/governance-decisions` | `runtime.execution.view` |

Policy writes accept `Idempotency-Key`, reusing Phase 3.1's platform-wide
contract: two overlapping ceilings created by a retried request would both
evaluate, and the operator would see the tighter one fire with no obvious
explanation.

**Enforcement is not in the API.** No route can invoke a checkpoint — which is
what keeps "one enforcement path" true of the HTTP surface as well as of the
loop.

Only one permission was added. Reading a decision reuses
`runtime.execution.view` ("View executions, tool calls and telemetry"), because
*why did this execution stop* is a fact about an execution rather than a
separate capability; a second code would leave operators holding execution-view
unable to answer the one question this phase exists to answer.

## Errors

| Code | HTTP | Meaning |
|---|---|---|
| `GOVERNANCE_POLICY_INVALID` | 422 | A constraint key or shape the engine cannot evaluate |
| `GOVERNANCE_POLICY_NOT_FOUND` | 404 | Also returned for another tenant's policy (§34) |
| `GOVERNANCE_CHECKPOINT_UNEVALUABLE` | 503 | The fail-closed signal — **retryable** |
| `GOVERNANCE_EXECUTION_STOPPED` | 403 | A governed refusal — **not** retryable |

`GOVERNANCE_CHECKPOINT_UNEVALUABLE` is deliberately retryable. Fail-closed says
an unevaluable mandatory checkpoint stops *this attempt*; it does not say the
condition is permanent, and a transient dependency failure is exactly what the
retry policy exists for.

## See also

- [runtime-policy-checkpoints.md](./runtime-policy-checkpoints.md) — the six
  checkpoints, every constraint, and the transaction boundary at each
- [ADR-0009](../architecture/adr/0009-runtime-governance-as-a-fail-closed-plane.md)
  — why fail-closed, and why one path
- [ADR-0008](../architecture/adr/0008-telemetry-as-a-derived-plane.md) — the
  other plane, and why it fails open
- [operations-and-kill-switch.md](./operations-and-kill-switch.md) — the kill
  switch this engine triggers
- [runtime-policy-and-approvals.md](./runtime-policy-and-approvals.md) — the
  pre-existing *admission-time* policy gate, distinct from this in-loop engine
