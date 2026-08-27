# ADR-0009 — Runtime governance is a fail-closed plane, evaluated on one enforcement path

- **Status:** Accepted
- **Date:** 2026-08-26
- **Deciders:** Phase 4.3 (Milestone 4 — Runtime Governance & Observability)
- **Supersedes:** —

## Context

Phase 4.3 puts governance checkpoints *inside* the model→tool→model loop. Two
questions had to be answered before a line of it was written, and both of them
decide the shape of the execution path rather than the shape of a feature.

**1. What happens when a governance checkpoint cannot be evaluated?**

[ADR-0008](./0008-telemetry-as-a-derived-plane.md) decided, four months and two
sub-phases ago, that the telemetry plane fails **open**: a failed telemetry
write is swallowed and the execution proceeds. Phase 4.1 implemented that with
a deliberately total exception guard, and Phase 4.2 built a read surface on top
of it that cannot affect the executions it describes.

Phase 4.3 now adds a second plane to the *same loop* — and it must behave in
exactly the opposite way. These two rules will from now on live within a few
dozen lines of each other:

```python
except Exception:            # app/observability/events.py — telemetry
    logger.warning(...)      # swallow; the execution continues
    return False
```

```python
except Exception:            # app/runtime/governance/engine.py — governance
    return self._unevaluable_decision(...)   # STOP; fail closed
```

A reader who confuses them will introduce either a governance bypass or an
outage. The decision has to be recorded, not merely implemented.

**2. The loop already enforced four termination caps.**

Phase 5.6a.3 built the tool loop with four inline limits — iteration count,
wall-clock, token budget, and repeated-identical-call — each an `if` statement
in the loop body raising `TOOL_LOOP_LIMIT_EXCEEDED` and writing a
`termination_reason`. They work, they are tested, and executions in production
depend on their exact outcomes.

Phase 4.3 adds richer constraints (cost ceilings, restricted models and tools,
data sensitivity, approval obligations, duration) that need to be evaluated at
the same and additional points. The obvious implementation adds a second
mechanism beside the first.

The forces:

1. **Two enforcers can disagree.** If the inline caps and a new engine both
   independently decide "may this loop continue", there are states where one
   says stop and the other says continue. Whichever runs first wins, and which
   runs first is an implementation detail nobody wrote down.
2. **Behaviour preservation is non-negotiable.** A regression here breaks agent
   execution, not a dashboard. Every existing `termination_reason`, error code
   and `loop_iterations` value has readers.
3. **The evaluation order is observable.** When two caps breach on the same
   turn, which one is reported is a fact the existing tests assert.
4. **The hot path is hot.** Six checkpoints per iteration, on the platform's
   busiest code path.
5. **`AuthorizationGateway` already exists** and is authoritative for *may this
   principal act*. A governance engine that started answering authorization
   questions would be a second authorization system — the exact failure this
   platform spent Milestone 1 avoiding.

## Options considered

### Option A — Governance fails open, like telemetry
- Pros: one rule for the whole of Milestone 4; no new failure mode; an outage
  in the policy store cannot stop executions.
- Cons: a governance control that stops working silently stops governing. An
  operator who configured a cost ceiling would have no way to know it was not
  being applied. "We could not check the rule you told us was non-negotiable"
  becomes a reason to proceed.

### Option B — Governance fails closed, unconditionally
- Pros: maximally safe; one rule inside the governance plane.
- Cons: an advisory policy — one an organization added to *watch* a threshold
  before enforcing it — would halt production the first time it misbehaved. A
  control that dangerous to add is a control nobody adds.

### Option C — Governance fails closed, scoped by an explicit `mandatory` flag
- Pros: the safe default where it matters; an advisory rule can misbehave
  without stopping anything; the operator states which is which.
- Cons: two behaviours to understand; a policy author can get the flag wrong.

### Option D — Add the new engine beside the existing caps
- Pros: smallest diff; zero risk to the existing caps; ships fastest.
- Cons: two systems that can disagree about whether to stop an execution, with
  precedence decided by statement order. Every future constraint has to be
  reasoned about twice.

### Option E — Generalize the existing caps into the engine
- Pros: exactly one place decides "may this loop continue"; new constraints are
  added once; the enforcement path is a structural property that can be tested.
- Cons: it modifies the hottest, most consequential code in the platform, and
  the behaviour-preservation burden is entirely on this phase.

## Decision

We chose **Option C and Option E**: runtime governance is a **fail-closed
plane** whose posture on an unevaluable checkpoint is governed by an explicit
`mandatory` flag, and the four pre-existing termination caps are **generalized
into that one engine** rather than left running beside it.

**On failing closed (C over A and B).** Option A was never seriously in play.
Every other control in this codebase fails closed — an authorization error
denies, a policy error blocks, a release gate failure halts a rollout, a
traffic-allocation gate with no servable version refuses the execution — and
telemetry is the deliberate exception, justified in ADR-0008 by the fact that
telemetry *observes* rather than *decides*. Governance decides. It belongs on
the same side of the line as everything else that decides.

Option B was rejected for a reason that only shows up in adoption: an
organization's first governance policy is almost never enforcement. It is
someone watching a threshold for a month to see whether the platform agrees
with their engineers — the same reasoning that gave Phase 3.7's rollback
triggers a `NOTIFY_ONLY` mode. A plane where every rule is load-bearing the
moment it is written is a plane where the first rule never gets written. The
`mandatory` flag makes the safe behaviour the *stated* one rather than the
universal one, and the asymmetry is the point: a mandatory policy that cannot
be evaluated STOPs, an advisory one is recorded and skipped.

**On one enforcement path (E over D).** Option D is the cheaper decision today
and the more expensive one every day after. The specific failure it invites is
not that the two systems disagree loudly — it is that they disagree quietly,
and the winner is whichever `if` statement the loop happens to reach first. The
cost of Option E is paid once, in this phase, under test.

Behaviour preservation was treated as the phase's primary deliverable rather
than a constraint on it. The four caps became constraints inside the engine
carrying their original `termination_reason` strings and error codes; the
evaluation order that decides which cap is reported when two breach on the same
turn was derived from the pre-4.3 statement order and is asserted by a test
rather than trusted. The two checks that used to sit at the bottom of the loop
body moved to the top of the next iteration — the adjacent half of the same
boundary, with no code between them — which is why folding them changes
nothing.

**On not becoming a second authorization system.** The engine answers *may this
execution continue*, inside a request `AuthorizationGateway` has already
authorized. It never grants, never replaces a permission check, and does not
import the gateway at all — asserted over the AST, not by convention.

## Consequences

### Positive

- **One place decides.** After this phase there is exactly one answer to "may
  this loop continue", reached through one `evaluate()` call at six sites. A
  new constraint is added once and is immediately available at every checkpoint
  that makes sense for it.
- **The one-path property is testable, not aspirational.** The orchestrator no
  longer names `TOOL_LOOP_MAX_TOTAL_TOKENS` or `TOOL_LOOP_MAX_WALL_CLOCK_SECONDS`
  in any comparison and no longer raises `TOOL_LOOP_LIMIT_EXCEEDED` itself,
  asserted over the AST — so "someone added just one quick check beside the
  engine" fails CI rather than being noticed in review, or not.
- **The two planes' opposite postures are legible.** Fail-closed and fail-open
  now have a written owner each, and a test asserts both directions: a
  telemetry failure does not stop an execution or change a governance decision,
  and a broken telemetry plane cannot suppress a governance stop either.
- **Governance evidence is durable and append-only.** `runtime_governance_decisions`
  answers *why* an execution stopped, complementing `termination_reason`'s
  record of *what state it reached*.
- **No lock is held across model or tool I/O.** Every checkpoint read is a
  plain non-locking `SELECT`; the only lock a checkpoint can cause is the
  foreign-key `KEY SHARE` the transcript writer has already been taking since
  5.6a.3, which is compatible with what a tool thread needs. The M1 deadlock
  shape cannot recur.

### Negative / accepted cost

- **This phase modified the platform's hottest code path.** That is a real,
  permanent increase in the blast radius of a mistake in
  `ToolLoopOrchestrator.run`, and no amount of testing makes it zero.
- **A checkpoint costs a query.** Kill state is read fresh at every checkpoint,
  because a kill fired by an operator arrives on a different connection and the
  session's cached row cannot see it. Measured at **0.42ms p50 / 0.68ms p95**
  per checkpoint, roughly 1.7ms per loop iteration against model calls that
  take hundreds of milliseconds — but it is not free, and it grows with any
  future constraint that needs its own read.
- **`mandatory` is a foot-gun in one direction.** An operator who leaves it
  false on a control they believe is enforcing gets an advisory rule that
  silently skips itself when it fails. The flag is explicit and documented, and
  it defaults to false — which is the safe default for *availability* and the
  unsafe one for *governance*. We accepted that ordering because a plane whose
  every rule is load-bearing on creation is a plane nobody configures.
- **Two vocabularies for termination.** `termination_reason` (the execution's
  terminal state) and `reason_code` (the governance lineage) both exist and are
  deliberately not merged. A reader must know which question they are asking.
- **The state machine gained two edges.** `RUNNING → PENDING_APPROVAL` and
  `RUNNING → BLOCKED` did not exist before, because nothing could intervene in
  an execution that was already running. They exist now, and every reader of
  the execution state machine has one more transition to account for.

### Residual risk

- **A mid-loop CHALLENGE cannot be resumed.** This platform has no mechanism to
  re-enter a partially-run loop, so a challenge raised after work has been
  dispatched terminates the execution (in `BLOCKED`) with the obligation
  standing, rather than parking it in `PENDING_APPROVAL` where nothing could
  move it out again. Approving it authorizes a *fresh* execution. This is
  stated plainly in the docs and the code rather than papered over, but it is a
  capability gap and will surprise someone.
- **Policy is snapshotted per execution.** A policy tightened mid-flight does
  not apply to executions already running. That is the stated consistency rule
  and the stronger guarantee, but an operator reacting to an incident by
  tightening a ceiling should know it takes effect for the *next* execution.
- **`mandatory` fail-closed can amplify an outage.** A policy-store failure
  stops every execution governed by a mandatory policy. That is the intended
  behaviour and it is also, precisely, a way for one dependency to halt the
  platform. `GOVERNANCE_CHECKPOINT_UNEVALUABLE` is deliberately left *retryable*
  so a transient failure recovers on its own.
- **The engine reads existing cost.** It does not reserve budget, so two
  concurrent executions under one ceiling can each pass a check the other is
  about to invalidate. Reservations are Phase 4.4's, and the cost checkpoint
  will consult them when they exist.

## Revisit when

- **Phase 4.4 introduces budgets and reservations.** The cost checkpoint should
  consult a reservation rather than a running sum, which closes the concurrent-
  execution gap above. That is the phase that should reopen this ADR's cost
  reasoning.
- **A checkpoint's measured p50 exceeds 5ms**, or the per-iteration overhead
  becomes a measurable fraction of loop latency. The kill-state read is the
  first thing to look at; it is currently a join, and could become a narrower
  read or an advisory-lock-free notification if it ever mattered.
- **Someone needs to resume a partially-run loop.** That capability would
  change the mid-loop CHALLENGE decision above from "terminate honestly" to
  "park and resume", and this ADR's residual risk section is where the
  reasoning to overturn lives.
- **A second automated trigger for the kill switch appears.** `activate_system`
  currently restricts automation to EXECUTION and AGENT scope. If a future
  phase needs a broader automated scope, that restriction — and the reason for
  it — should be reopened here rather than quietly relaxed.
