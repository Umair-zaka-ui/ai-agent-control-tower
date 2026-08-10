# Deployment Lifecycle

`/api/v1/runtime/deployments` · `runtime.deployment.view`/`runtime.deployment.create`/`runtime.deployment.deploy` permissions.

**Milestone 3 (ACT-SRS-M3) begins here.** Phase 3.1 turns the existing,
partially-wired `agent_deployments` table into a governed deployment domain:
a real 15-state lifecycle with one transition authority, append-only event
lineage, optimistic-concurrency protection, and idempotent commands. It
deliberately stops short of the thing that makes deployment state *matter*
for execution — the version resolver and the execution gate — because that
change to the Milestone 1 execution entry path belongs with traffic
allocation in Phase 3.4, where it can be introduced and tested in one place.

## The two deployment machines, and why there are two

`agent_deployments` (Phase 5.0) already had an 11-value `status` column and
five service methods (`deploy`/`suspend`/`resume`/`rollback`/`retire`) that
write it directly — no single authority, no event lineage, no optimistic
concurrency. This phase does **not** widen or replace that column. It adds a
second, new one, `lifecycle_state`, governed by a real state machine
(`app.runtime.deployment.lifecycle`) and written in exactly one place
(`app.runtime.deployment.service.DeploymentLifecycleService`).

The two fields are reconciled once, deterministically, by this phase's own
migration (§15 mapping, below) and then evolve **independently**:

- `status` keeps being read and written by the five pre-existing
  `DeploymentService` methods, completely unchanged — including the one
  place execution actually gates on deployment state,
  `ExecutionRequestService._request_execution`'s
  `deployment.status != "ACTIVE"` check. Nothing in this phase touches that
  function; a dedicated grep-based regression test
  (`test_ac13_execution_path_does_not_reference_the_new_lifecycle_state`)
  proves it.
- `lifecycle_state` is written only through the new authority, by the new
  `/lifecycle/...` routes below.

A consequence worth stating plainly: a deployment's legacy `status` can keep
changing after migration (an operator calling the old `/suspend`/`/resume`
endpoints, for instance) while its `lifecycle_state` sits untouched, or vice
versa. This is not a bug to reconcile — it is the deliberate seam between
"the field Milestone 1 execution actually reads" and "the field this
Milestone builds toward," and it is *why* Phase 3.4's execution-gate change
is scoped as its own phase rather than folded in here.

**Why a second field is safer than widening `status`:** the existing
`status` values are already the load-bearing input to a real, running
execution gate. Any change to what that column can hold, or to which values
mean "serving," is a change to Milestone 1's execution path — exactly what
this phase's own scope boundary forbids. A brand-new, additive column lets
the new lifecycle exist, be fully tested, and even be driven by real
operators, with provably zero effect on execution until Phase 3.4
deliberately flips the gate over.

## The state machine

Fifteen states (`app.runtime.deployment.lifecycle`, the single source of
truth — see that module's own docstring for the full transition diagram):

```
DRAFT → VALIDATING → READY → (PENDING_APPROVAL → APPROVED →) DEPLOYING → ACTIVE
  ↑          ↓                                                              │
  │    VALIDATION_FAILED                                     ┌──── pause ──┤
  │                                                           ↓             │
  └── revise ──────────────────────────────────────────────  PAUSED ── resume
                                                                             │
PENDING_APPROVAL → REJECTED → DRAFT (revise) | RETIRED               supersede
                                                                             ↓
DEPLOYING → FAILED → RETIRED                                        SUPERSEDED
ACTIVE/DEGRADED → ROLLING_BACK → ACTIVE | FAILED                           │
ACTIVE/DEGRADED → DEGRADED → ACTIVE | ROLLING_BACK | FAILED          RETIRED
(most non-in-flight states) → RETIRED  ←──────────────────────────────────┘
```

`app.runtime.deployment.service.DeploymentLifecycleService.transition()` is
the one function that ever assigns `AgentDeployment.lifecycle_state` — a
mechanically checked invariant
(`test_ac02_lifecycle_state_is_never_assigned_outside_the_authority`), the
same discipline Milestone 2's connector framework and this platform's own
agent/version lifecycles already established.

**What this phase drives end to end**, with a real service method and a
real HTTP route behind it: creation (→ `DRAFT`), the whole happy path
through to `ACTIVE`, pause/resume, retire, and the `DEPLOYING → FAILED`
failure edge.

**What this phase declares but leaves for a later phase to drive** — every
edge below is nonetheless a real, individually-tested entry in the
transition graph (`M3-3.1-FR-002`'s "complete machine" requirement), just
not yet reachable through a dedicated route:

| Edge | Owning phase |
|---|---|
| `ACTIVE`/`PAUSED` → `SUPERSEDED` | 3.2 (environments/promotion) — a newer deployment promoted into the same environment slot |
| `ACTIVE`/`DEGRADED` → `ROLLING_BACK`, `ROLLING_BACK` → `ACTIVE`\|`FAILED` | 3.7 (rollback) |
| `ACTIVE` → `DEGRADED`, `DEGRADED` → `ACTIVE`\|`ROLLING_BACK`\|`FAILED` | 3.5's canary health signal, hardened in 3.7 |

A caller can still exercise any of these today via the generic
`POST .../lifecycle/transition` endpoint (below) — the graph itself doesn't
distinguish "has a dedicated route" from "generic-only."

### Reaching `ACTIVE` is where the guards live

Every transition landing in `ACTIVE` — whether the happy path's
`DEPLOYING → ACTIVE` or a `PAUSED → ACTIVE` resume — goes through the same
two checks inside `transition()` itself, not duplicated per call site:

1. **Ruling #6 — the agent must not be suspended.** See "Suspension/kill
   integration" below. Failure: `DEPLOYMENT_AGENT_SUSPENDED`.
2. **The approval precondition, where policy demands it.** A deployment
   whose environment is in the version's `policy_snapshot.requires_approval_environments`,
   or whose agent is `MISSION_CRITICAL` in `PRODUCTION`, must have an
   `APPROVED` `runtime_approvals` row before it can become `ACTIVE`.
   Failure: `DEPLOYMENT_INVALID_TRANSITION`.

`DeploymentLifecycleService.start_deploying()` is what actually drives
`READY`/`APPROVED → ... → ACTIVE` end to end (there is no distributed worker
in this phase — deployment is synchronous, the same simplification this
platform's execution queue already made for local dev). When a `READY`
deployment needs approval and has none yet, it reroutes to
`PENDING_APPROVAL` and creates the `runtime_approvals` row itself — never an
error — mirroring the *legacy* `DeploymentService.deploy()`'s own
mission-critical-production reroute shape for the new machine, without
touching that method.

## Suspension/kill integration (Ruling #6)

**The mechanism found**: `Agent.lifecycle_status` reaching `"SUSPENDED"` —
driven either by the ordinary agent lifecycle
(`app.runtime.registry.services.AgentLifecycleService`) or by an operator's
kill switch (`app.runtime.services.KillSwitchService`, §60, scopes
`EXECUTION`/`AGENT`/`PROJECT`/`ORGANIZATION`/`PLATFORM`). Both are
pre-existing, Phase 5.0-and-earlier mechanisms.

**The integration**: `DeploymentLifecycleService._assert_can_reach_active()`
*reads* `agent.lifecycle_status` every time a deployment would land in
`ACTIVE`. It never writes that field and never introduces a second
suspension concept — a suspended agent's deployment simply cannot become
`ACTIVE` (or resume into `ACTIVE` from `PAUSED`), full stop, regardless of
which of the two suspension paths put it there.

## The idempotency contract (`M3-3.1-FR-010..013`)

`app.runtime.deployment.idempotency.IdempotencyService` is a **generic**,
reusable capability — proven so by a unit test that exercises it against a
bare, non-deployment stub callable
(`test_ac08_idempotency_service_is_reusable_by_a_non_deployment_operation`).
Every later Milestone 3 command (promotion, rollout, rollback, ...) reuses
it directly rather than redefining its own key→result bookkeeping.

- **Header**: `Idempotency-Key`, honored on every state-changing deployment
  endpoint below.
- **Scope**: `(organization_id, operation, idempotency_key)`, unique.
- **TTL**: 24 hours.
- **Conflict detection**: the request payload is hashed
  (`request_fingerprint`); the same key reused with a *different* payload is
  rejected with `IDEMPOTENCY_CONFLICT` — the pre-existing, generic error
  code (Phase 5.0 §33's own `IdempotencyService` already established it;
  this phase reuses it rather than adding a near-duplicate
  `IDEMPOTENCY_KEY_CONFLICT`).

**A different, more general table from the pre-existing
`idempotency_records`** (Phase 5.0 §33): that one dedupes *execution
requests* specifically — scoped to `agent_id`, resolving to a hard FK on
`AgentExecution` — and sits on the Milestone 1 execution path this phase
must not touch. This phase's `idempotency_keys` table stores an opaque JSON
`result_ref` instead of a typed FK, so any command can adopt it.

**Claim-then-poll, not check-then-act.** A naive "SELECT, then on miss call
the operation and INSERT" has a genuine TOCTOU gap under real concurrency —
two callers racing the same key could both miss the check and both run the
operation, exactly the double-execution the contract exists to prevent.
Instead, a caller first *commits* a placeholder claim row; the table's own
`(organization_id, operation, idempotency_key)` unique constraint is the
concurrency primitive — Postgres guarantees only one of two racing inserts
for the same key can ever commit. The loser catches the resulting
`IntegrityError` and polls briefly (a bounded, sub-second wait in practice)
for the winner's real result rather than running the operation at all. A
real-Postgres, two-thread test proves exactly one execution happens
(`test_concurrent_same_idempotency_key_runs_fn_exactly_once`).

## Optimistic concurrency (`M3-3.1-FR-005`, AC-05)

`AgentDeployment.revision` is a SQLAlchemy `version_id_col`
(`__mapper_args__ = {"version_id_col": revision}`) — every `UPDATE` of the
row SQLAlchemy issues carries `WHERE revision = <the value loaded into this
session>` and auto-increments it, raising `StaleDataError` when a concurrent
writer already moved the row. `DeploymentLifecycleService.transition()`
translates that into `DEPLOYMENT_REVISION_CONFLICT`. A real-Postgres,
two-thread test against one deployment proves exactly one transition
succeeds (`test_ac05_concurrent_transitions_exactly_one_succeeds`).

A caller may additionally pass `expected_revision` on any mutating
`/lifecycle/...` request — a client-side "If-Match"-style precondition,
distinct from and in addition to the database-level compare-and-swap above:
it tells the server whether the *caller's own* view is already stale,
independent of any race actually occurring.

**A deliberately accepted side effect**: `version_id_col` applies
mapper-wide, not just to `lifecycle_state` writes — so a legacy
`DeploymentService` method changing only `.status` (e.g. the pre-existing
`/suspend` endpoint) also bumps `revision`. This is harmless: the new
authority always re-reads a deployment fresh via `get_or_404` immediately
before every transition, so it never compares against a stale in-memory
`revision` value; it simply means `revision` counts *any* update to the
row, not only lifecycle transitions.

## Routes

New, under the pre-existing `/lifecycle/...` sub-path — see "A routing
conflict, resolved" below for why.

| Method | Path | Notes |
|---|---|---|
| `POST` | `/deployments` | Existing route, extended additively: honors `Idempotency-Key`, seeds `lifecycle_state=DRAFT`. |
| `POST` | `/deployments/{id}/lifecycle/transition` | Generic — `{"to_state", "reason"?, "expected_revision"?}`. Drives the whole declared graph, including the READY/APPROVED→...→ACTIVE happy path (see above). |
| `POST` | `/deployments/{id}/lifecycle/pause` | `ACTIVE → PAUSED`. |
| `POST` | `/deployments/{id}/lifecycle/resume` | `PAUSED → ACTIVE` (both ACTIVE-reaching guards apply). |
| `POST` | `/deployments/{id}/lifecycle/retire` | `→ RETIRED`. |
| `GET` | `/deployments/{id}/lifecycle/events` | The append-only lineage for one deployment, oldest first. |

All five mutating actions honor `Idempotency-Key`; all reuse the
pre-existing `runtime.deployment.view`/`.deploy` permissions (see "A
permission-naming difference" below).

### A routing conflict, resolved

The build prompt's own literal paths (`/deployments/{id}/pause`,
`/resume`, `/retire`) collide with routes this codebase already shipped in
Phase 5.0, operating on the legacy `status` field — FastAPI cannot register
two handlers on one `(path, method)` pair, and merging the two machines'
semantics into one handler was rejected (it would make the "one transition
authority" claim false: the legacy methods would need to know about
`lifecycle_state`, or vice versa). Nesting the new lifecycle's routes under
`/lifecycle/...` resolves the conflict without touching a single existing,
already-tested endpoint. `/transition` and `/events` had no legacy
counterpart to collide with.

### A permission-naming difference

The build prompt's suggested `deployment.view`/`deployment.manage`
permission names don't match this platform's actual, already-shipped
convention: `runtime.deployment.view` and `runtime.deployment.deploy`
already exist (`PERMISSION_CATALOG`), already gate every pre-existing
deployment mutation (`deploy`/`suspend`/`resume`/`rollback`/`retire`) behind
the *same* one permission. The new `/lifecycle/...` routes reuse these two
verbatim rather than introduce parallel, near-duplicate permission strings.

## Data model

`agent_deployments` gains four columns — `lifecycle_state`, `revision`,
`state_reason`, `superseded_by_deployment_id` — plus a foreign key from the
last back onto `agent_deployments` itself (lineage: which newer deployment
superseded this one). `desired_replicas`/`active_replicas` (vestigial per
this repository's own earlier analysis — the runtime has no replica model)
are neither read nor written anywhere in the new lifecycle
(`test_ac14_replica_columns_not_read_or_written_by_the_new_lifecycle`).

`deployment_events` (new, append-only): one row per transition —
`from_state`/`to_state`/`event_type`/`reason`/`actor_id`/`idempotency_key`.
Enforced append-only the same way this codebase's own connector framework
already established its equivalent table (Phase 2.1.1): no service method
updates or deletes a row, no route exposes `PATCH`/`DELETE` on the
collection — checked mechanically, not by a database-level `REVOKE`.

**How `deployment_events` relates to the platform audit trail and to
`runtime_events`**: every transition still calls the pre-existing
`_record_event` helper unchanged, which dual-writes the platform-wide
`AuthorizationAuditEvent` stream (the security record) and the pre-existing
`runtime_events` table (the Operations Center timeline feed). `deployment_events`
is a third, complementary write — the typed, deployment-specific lineage
record this phase's own acceptance criteria require, distinct from both.

`idempotency_keys` (new): see "The idempotency contract" above.

### The §15 migration mapping

Every pre-existing `agent_deployments` row's legacy `status` value maps
deterministically into an initial `lifecycle_state` (migration
`0037_deployment_lifecycle`, applied once, live):

| Legacy `status` | New `lifecycle_state` | Why |
|---|---|---|
| `CREATED` | `DRAFT` | Hasn't gone through the new validation/approval pipeline yet |
| `PENDING_APPROVAL` | `PENDING_APPROVAL` | Direct match |
| `SCHEDULED` | `DEPLOYING` | Closest equivalent: about to deploy, not yet serving |
| `DEPLOYING` | `DEPLOYING` | Direct match |
| `HEALTH_CHECKING` | `DEPLOYING` | Closest equivalent: mid-activation, not yet confirmed serving |
| `ACTIVE` | `ACTIVE` | Direct match — a currently-serving deployment lands `ACTIVE` |
| `DEGRADED` | `DEGRADED` | Direct match |
| `FAILED` | `FAILED` | Direct match |
| `SUSPENDED` | `PAUSED` | Direct semantic match: was active, not serving, still intact |
| `ROLLING_BACK` | `ROLLING_BACK` | Direct match |
| `RETIRED` | `RETIRED` | Direct match |

**No allocation backfill here** — that is Phase 3.4's own half of this same
§15 mapping (this phase seeds lifecycle; 3.4 backfills traffic allocation).
No `deployment_events` row is synthesized for historical transitions that
predate this table — lineage starts from this migration forward, not
retroactively invented. Reversible: `downgrade()` drops the two new tables
and the four new columns; verified live (`alembic downgrade -1` then
`upgrade head`, both clean).

## Security

- Every deployment operation is tenant-isolated — `get_or_404` scopes by
  `organization_id`; cross-tenant access is a `404`
  (`DEPLOYMENT_NOT_FOUND`), never a `403` that would confirm the row
  exists.
- Every mutating operation requires `runtime.deployment.deploy`, checked
  server-side via the pre-existing `require_permission` dependency — the UI
  hiding a control is convenience only.
- A published version referenced by a deployment is never mutated by any
  lifecycle transition — deployments point at versions, they don't touch
  them (unchanged from Phase 5.0's own immutability guarantee).
- No secret ever reaches `deployment_events`, the audit `meta`, or an
  idempotency `result_ref` — none of the fields this phase writes carry
  credential material in the first place (`secret_references` stays
  references-only, untouched).

## What this phase deliberately does not do

| Excluded | Owning phase |
|---|---|
| Traffic allocation / weighted routing | 3.4 |
| The version resolver and the execution gate | 3.4 |
| Environments as governed entities, promotion | 3.2 |
| Preflight / release gates | 3.3 |
| Canary / progressive rollout | 3.5 |
| Blue-green / recreate / rolling strategies | 3.6 (rolling → 3.9) |
| Rollback (manual or automated) | 3.7 |
| Distributed scheduler | 3.8 |
| Distributed workers | 3.9 |
| Any operator frontend | 3.10 |
| Any change to the Milestone 1 execution entry path | not this phase — 3.4 owns the one change |

## Testing

27 new tests (`backend/tests/runtime/test_deployment_lifecycle.py`) — grouped by
this phase's own §12 acceptance criteria: the state machine itself (pure, no
database), the idempotency contract's genericity and its real concurrent
race, `AgentDeployment.lifecycle_state`'s single-authority invariant
(grep-based), the vestigial-replica-column boundary, the happy path through
to `ACTIVE` and back down through pause/resume/retire, append-only event
lineage, the §15 migration mapping's own internal consistency, Ruling #6's
suspension guard (including the `PAUSED → ACTIVE` resume path), the
approval-precondition reroute (mission-critical/production), tenant
isolation and permission enforcement, and the real-Postgres revision-conflict
race. `test_ac13_full_execution_still_works_end_to_end` and
`test_ac13_execution_path_does_not_reference_the_new_lifecycle_state`
together prove the Milestone 1 execution path is provably untouched, not
just asserted to be.
