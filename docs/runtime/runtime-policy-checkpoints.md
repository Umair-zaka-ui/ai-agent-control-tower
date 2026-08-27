# The six checkpoints — where governance runs, and what it can decide

> **Phase 4.3 (ACT-SRS-M4 §8-4.3).** The checkpoint reference: where each one
> sits in `ToolLoopOrchestrator.run`, what its transaction state is, and which
> constraints it evaluates. For the engine, the planes and the API, see
> [runtime-governance.md](./runtime-governance.md).

## Where they sit

```
ToolLoopOrchestrator.run()
│
├─ bind the engine (resolve + snapshot the policy set — once per attempt)
│
└─ while True:
     iteration += 1
     ├── ① BEFORE_FIRST_MODEL_CALL  (iteration 1)
     │   ⑤ BEFORE_NEXT_ITERATION    (iteration > 1)
     │
     ├── model call ──────────────────────────────── network I/O
     │
     ├── ② AFTER_MODEL_RESPONSE
     │
     ├── if no tool calls requested:
     │     ├── ⑥ BEFORE_FINAL_OUTPUT
     │     └── return
     │
     ├── for each requested tool call:
     │     └── ③ BEFORE_TOOL_EXECUTION   (per call, before dispatch)
     │
     ├── execute the tool batch ─────────────────── network I/O
     │
     └── ④ AFTER_TOOL_EXECUTION
```

### Why ① and ⑤ are one site

At iteration *n>1*, the top of the loop body is the same boundary as the end of
iteration *n-1* — **there is no code between them**. So they are one checkpoint
evaluated at one place, not two.

This is why the wall-clock and token-budget checks that used to sit at the
*bottom* of the loop body are evaluated at the top of the next iteration
instead. The sequence a continuing iteration used to reach was:

```
[end of iteration n]     wall-clock      -> WALL_CLOCK,     iterations = n
[end of iteration n]     token budget    -> TOKEN_BUDGET,   iterations = n
[top of iteration n+1]   iteration cap   -> MAX_ITERATIONS, iterations = n
[top of iteration n+1]   wall-clock      -> WALL_CLOCK,     iterations = n
```

Nothing runs between the second and third of those, and the fourth is a
re-check of the first. Folding them into one checkpoint changes no outcome
**provided the order is preserved** — which matters only when two caps breach
on the same turn, and that is exactly the corner case a refactor silently
inverts. So the order is asserted by a test rather than trusted, and it is:
**wall-clock, token budget, iteration cap.**

Every cap at this boundary reports `iteration - 1` as the completed-iteration
count, which is the same value all four inline checks wrote.

## Transaction state at each checkpoint

**No checkpoint holds a lock across model or tool I/O.** This is the M1
deadlock discipline (§9), now inside the loop.

| # | Checkpoint | DB work | Lock held after |
|---|---|---|---|
| ① | `BEFORE_FIRST_MODEL_CALL` | one non-locking `SELECT`; `INSERT` only if material | FK `KEY SHARE` on this execution's row, only if a decision row was written |
| ② | `AFTER_MODEL_RESPONSE` | same | same |
| ③ | `BEFORE_TOOL_EXECUTION` | same | same |
| ④ | `AFTER_TOOL_EXECUTION` | same | same |
| ⑤ | `BEFORE_NEXT_ITERATION` | same | same |
| ⑥ | `BEFORE_FINAL_OUTPUT` | same (always material) | as above |

Three facts make this safe:

1. **No checkpoint takes `FOR UPDATE` or `FOR NO KEY UPDATE`.** Asserted over
   the AST, including raw-SQL string constants.
2. **An ALLOW writes nothing.** A non-material decision is not persisted, so
   the overwhelmingly common case leaves the session holding no lock at all on
   the execution row — provable by taking the *exclusive* lock from another
   connection with `NOWAIT`.
3. **The FK `KEY SHARE` a decision INSERT implies is compatible with the one a
   tool thread needs.** The M1 deadlock was a `FOR UPDATE` held by the main
   session while a tool thread's fresh session needed `KEY SHARE` on the same
   row — and the main thread was meanwhile blocked joining that worker. Two
   `KEY SHARE` holders do not conflict. It is also exactly the lock
   `_append_message` has been taking every turn since Phase 5.6a.3, so this
   phase introduces nothing new in kind.

`claim_next` already committed before the attempt began (Phase 3.9), so no
claim lock exists to be held by any of this.

## What each checkpoint evaluates

Built-in caps run before policy constraints at every checkpoint: platform
loop-safety must not be extendable by a tenant policy objecting first and
terminating with a different reason.

### ① `BEFORE_FIRST_MODEL_CALL`

| Kind | Constraint | Decision |
|---|---|---|
| cap | iteration cap | STOP `MAX_ITERATIONS` |
| cap | wall clock | STOP `WALL_CLOCK` |
| policy | `prohibited_environments` | STOP |
| policy | `restricted_models` / `allowed_models` | STOP |
| policy | `max_execution_cost` | STOP |
| policy | `requires_approval` | CHALLENGE *(resumable)* |
| policy | `requires_approval_criticality` | CHALLENGE *(resumable)* |

A restricted model refused here means the provider is **never contacted**.

`prohibited_environments` is evaluated here and nowhere else: an execution's
environment is fixed by its deployment and cannot change mid-loop, so
re-checking it at every checkpoint would spend work re-deriving a constant. It
reuses the same policy key `RuntimePolicyService.evaluate` and Phase 3.2's
`check_prohibited` already read.

### ② `AFTER_MODEL_RESPONSE`

| Kind | Constraint | Decision |
|---|---|---|
| policy | `restricted_models` / `allowed_models` | STOP |
| policy | `max_total_tokens` | STOP |
| policy | `max_execution_cost` | STOP |
| policy | `max_execution_duration_seconds` | STOP |

The model check here reads what the gateway reports as the model that answered.
Today `ModelGatewayService` echoes the *configured* model back, so this check is
currently redundant with ①'s. It is here because the after-position is the only
place a provider-resolved model could ever be observed — an alias expanded by
the provider, a version pin, a fallback — and a restriction that only looked at
intent would be silently bypassed the day a provider adapter starts reporting
what it actually used. The redundant check costs a dictionary lookup;
discovering the gap later would cost a restricted model running in production.

### ③ `BEFORE_TOOL_EXECUTION` — per call, before dispatch

| Kind | Constraint | Decision |
|---|---|---|
| cap | tool bound to the frozen snapshot | DENY `TOOL_DENIED` |
| cap | repeated identical call | STOP `REPEATED_CALL` |
| policy | `restricted_tools` / `restricted_tool_classes` | DENY |
| policy | `restricted_data_classifications` / `allowed_data_classifications` | DENY |
| policy | `max_tool_calls` | STOP |
| policy | `max_calls_per_tool` | DENY |
| policy | `min_remaining_cost` | STOP |
| policy | `high_risk_actions` | CHALLENGE *(not resumable)* |

The last point at which a specific call can be refused **without side effects**.
A denied tool leaves no `tool_calls` row, which is the difference between
refusing an action and logging that it happened.

Data sensitivity reads `Tool.data_classification` — the same column Phase 3.2
checks at deploy time. No new taxonomy was invented. The classifications for a
version's tools are read **once at loop start**, not per call, so a governance
constraint stays off the per-call query path.

### ④ `AFTER_TOOL_EXECUTION`

| Kind | Constraint | Decision |
|---|---|---|
| policy | `max_execution_cost` | STOP |
| policy | `max_execution_duration_seconds` | STOP |

### ⑤ `BEFORE_NEXT_ITERATION`

| Kind | Constraint | Decision |
|---|---|---|
| cap | wall clock | STOP `WALL_CLOCK` |
| cap | token budget | STOP `TOKEN_BUDGET` |
| cap | iteration cap | STOP `MAX_ITERATIONS` |
| policy | `max_execution_cost` | STOP |
| policy | `min_remaining_cost` | STOP |
| policy | `max_total_tokens` | STOP |
| policy | `max_model_calls` | STOP |
| policy | `max_execution_duration_seconds` | STOP |
| policy | `restricted_models` / `allowed_models` | STOP |

### ⑥ `BEFORE_FINAL_OUTPUT`

| Kind | Constraint | Decision |
|---|---|---|
| policy | `max_execution_cost` | STOP |
| policy | `max_execution_duration_seconds` | STOP |

The last chance to refuse to return a result produced in violation. Its ALLOW
is always persisted — that row is the positive evidence the engine ran and
permitted the outcome.

## Constraint reference

Every key below is validated on write. A misspelled key is **rejected**
(`GOVERNANCE_POLICY_INVALID`) rather than stored: a governance control that
silently never fires is worse than one that is absent, because someone believes
it works.

| Key | Type | Meaning |
|---|---|---|
| `max_execution_cost` | number | Stop when accumulated cost reaches this |
| `min_remaining_cost` | number | Stop while at least this much headroom remains |
| `max_total_tokens` | number | Stop at this many tokens |
| `max_model_calls` | number | Stop at this many model calls |
| `max_tool_calls` | number | Stop at this many tool calls |
| `max_calls_per_tool` | number or `{tool: number}` | Deny a tool past its own limit |
| `restricted_models` | list | Models this policy refuses |
| `allowed_models` | list | If set, only these are permitted |
| `restricted_tools` | list | Tools by name |
| `restricted_tool_classes` | list | Tool types (`HTTP`, `FUNCTION`) |
| `restricted_data_classifications` | list | `Tool.data_classification` values refused |
| `allowed_data_classifications` | list | If set, only these are permitted |
| `prohibited_environments` | list | Environments this policy refuses |
| `max_execution_duration_seconds` | number | Stop past this elapsed time |
| `high_risk_actions` | list | Tool names that require approval |
| `requires_approval` | boolean | The whole execution requires approval |
| `requires_approval_criticality` | list | Criticality levels requiring approval |
| `stop_action` | `NONE`/`KILL_EXECUTION`/`KILL_AGENT` | What a STOP additionally does |

### `max_execution_cost` versus `min_remaining_cost`

These are not two ways of saying the same thing, and the difference decides
whether spend stays *within* a bound.

A bare ceiling can only ever notice an overshoot: the cost of a model call is
unknowable until it returns, so the iteration that crossed the line has already
been paid for. With a 0.0025 ceiling and turns costing 0.001, the loop stops on
the third turn having spent 0.003.

`min_remaining_cost` is the headroom rule. Set it to roughly what one iteration
costs and the loop stops *before* dispatching a turn the budget could not
absorb — same ceiling, same turns, stopped after two, total spend 0.002. Both
behaviours are tested, including the overshoot, because a document that only
described the good case would be misleading.

The engine reads existing cost and reserves nothing (M4-4.3-FR-011). Two
concurrent executions under one ceiling can therefore each pass a check the
other is about to invalidate. Budgets and reservations are Phase 4.4's, and
this checkpoint will consult them when they exist.

### `stop_action`

Defaults to `NONE`: halting the execution *is* the intervention. Suspending an
agent is a separate, explicit choice an operator makes in the policy —
automation does not escalate on its own. See
[runtime-governance.md](./runtime-governance.md#the-kill-switch-is-triggered-never-paralleled-19)
for why `PROJECT`, `ORGANIZATION` and `PLATFORM` are unreachable from a policy.

## Adding a constraint

1. Write a `_c_*` function in `app.runtime.governance.constraints` returning
   `(Decision, ReasonCode, message)` or `None`.
2. Add its `ReasonCode` — these are an interface; adding one is safe, renaming
   one is a breaking change.
3. List it under the checkpoint(s) it belongs to in `POLICY_CONSTRAINTS`.
4. Add its key to `KNOWN_CONSTRAINT_KEYS` and its shape to `validate_constraints`.

Nothing in `ToolLoopOrchestrator` changes. That is the point of the
generalization: a new constraint is added once, and is enforced at every
checkpoint it was listed under, through the one path that already exists.
