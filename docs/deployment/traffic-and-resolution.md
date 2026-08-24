# Traffic allocation, version resolution, and the execution gate

Phase 3.4 (ACT-SRS-M3 §Phase-3.4). This is the phase where deployment starts
to *govern execution*: an agent's traffic in an environment can be split by
weight across several simultaneously-serving signed versions, a resolver picks
one per request, and execution is gated on there being something servable to
pick.

Three things landed together because they are one mechanism. Allocation
without a resolver is a table nobody reads; a resolver without allocation has
nothing to resolve; and the resolver *is* where the gate lives — "resolve a
version from an active deployment's allocation, else fail closed" is
simultaneously the routing logic and the gate.

---

## The one change to the Milestone 1 execution path

`ExecutionRequestService._request_execution` (`app/runtime/services.py`) is the
single entry point every execution passes through, whether requested by a user
(`request_execution`) or by an agent for itself (`request_execution_as_agent`).

**Before 3.4** it selected a version by reading the active deployment's own
column:

```python
deployment = <explicit deployment_id> or DeploymentService.active_for_agent(...)
if deployment is None:              raise DEPLOYMENT_NOT_FOUND
if deployment.status != "ACTIVE":   raise DEPLOYMENT_NOT_ACTIVE
version = db.get(AgentVersion, deployment.agent_version_id)   # a direct 1:1
```

**After 3.4** that block is replaced by one call:

```python
resolution = VersionResolver(db).resolve(
    agent, deployment_id=..., environment=..., routing_key=...)
deployment, version = resolution.deployment, resolution.version
```

Everything after that line is untouched — including the `authorize(deployment)`
call, the runtime-policy evaluation, the approval reroute, the queue, and the
worker.

### Ruling #4 was already half-true here

Worth stating plainly, because the build prompt anticipated otherwise: **this
codebase never allowed deployment-less execution.** The two raises above have
been in `_request_execution` since Milestone 1. Ruling #4's "an execution
requires an active deployment, fail closed" was therefore already enforced;
what 3.4 adds is

1. *weighted resolution* through an allocation rather than a 1:1 read, and
2. a new fail-closed mode, `NO_ACTIVE_DEPLOYMENT`, for the case that only
   becomes possible once allocations exist (below).

Consequently there were **no deployment-less-execution tests to migrate**. The
real, deliberate migration this phase owns is a different one — see
"[The migrated test](#the-migrated-test)".

---

## What "servable" means: union with veto

This repository carries two deployment state fields, written by disjoint code.
Getting the gate right means understanding both.

| Field | Written by | Not written by |
|---|---|---|
| `agent_deployments.status` | legacy `DeploymentService.deploy/suspend/resume/rollback/retire`, **and `KillSwitchService`** | anything in Phase 3.1+ |
| `agent_deployments.lifecycle_state` | `DeploymentLifecycleService` only (3.1 pause/resume/retire, 3.2 promote/supersede) | the legacy service, the kill switch |

Neither field alone is a correct gate:

- **`lifecycle_state` alone** would disarm the kill switch at
  ORGANIZATION/PROJECT/PLATFORM scope — those write only `status` — and would
  strand every deployment activated the legacy way (`lifecycle_state` stays
  `DRAFT`). A killed org would keep serving traffic. Non-negotiable failure.
- **`status` alone** would let a 3.1-paused deployment keep serving, and would
  leave every 3.2-promoted deployment permanently unable to execute.

So a deployment serves iff **either machine says ACTIVE and neither vetoes**:

```python
servable(d) = (d.status == "ACTIVE" or d.lifecycle_state == "ACTIVE")
              and d.status         not in {SUSPENDED, RETIRED, FAILED, ROLLING_BACK}
              and d.lifecycle_state not in {PAUSED, SUPERSEDED, RETIRED, FAILED,
                                            ROLLING_BACK, REJECTED, VALIDATION_FAILED}
```

Defined once, in `app/runtime/deployment/traffic.py`, as both a SQL clause
(`servable_clause()`) and a Python predicate (`is_servable()`).

### Truth table

| `status` | `lifecycle_state` | Serves? | Why it matters |
|---|---|---|---|
| `ACTIVE` | `DRAFT` | ✅ | Legacy deploy — every pre-3.4 execution test |
| `CREATED` | `ACTIVE` | ✅ | 3.1 lifecycle deploy, 3.2 promotion |
| `ACTIVE` | `ACTIVE` | ✅ | Both machines agree |
| `ACTIVE` | `PAUSED` | ❌ | 3.1 pause vetoes |
| `ACTIVE` | `SUPERSEDED` | ❌ | 3.2 supersede vetoes |
| `SUSPENDED` | `ACTIVE` | ❌ | **Kill switch vetoes** |
| `RETIRED` | `ACTIVE` | ❌ | Retirement vetoes |
| `CREATED` | `DRAFT` | ❌ | Never deployed by either machine |

Pinned by `test_ac10_servability_predicate_truth_table`, so a future rename of
either machine's states fails loudly instead of silently opening or closing the
gate.

**Neither machine was rewritten.** 3.4 reconciled nothing; it taught the
resolver to honour both. That is why this phase touches one place rather than
six.

---

## The domain model

```
deployment_traffic_allocations          one revision of one agent's split
  (organization, agent, environment)    in one environment
  revision, is_current, created_by
      │
      └── deployment_traffic_weights    (version, deployment, weight)
            weight 0..100, set sums to 100
```

Allocation is a **sanctioned new domain object** (ruling #2), not columns on
`agent_deployments`: a split spans several deployments, so no single deployment
row can own it, and the resolver's lookup key (agent + environment) would be
unexpressible.

**Revisions, not mutations.** A weight change writes a *new* allocation and
clears the previous one's `is_current`, in one transaction. Prior revisions are
retained as the audit lineage — `GET .../traffic/history` reads them directly.

### The sum-to-100 invariant

A SQL `CHECK` cannot span sibling rows, and a deferred constraint trigger would
create a second place that understands the rule. Instead
`TrafficAllocationService.set_weights` validates the complete set *before*
writing anything and inserts the allocation and all its weights in one
transaction with a single commit. A partial or non-100 set never commits, so it
is never observable by another connection — which is what FR-003 actually
requires. The resolver additionally ignores zero-weight and unservable entries
at read time, so it never depends on the stored set being currently routable.

### Concurrency: an index, not a lock

`uq_traffic_allocations_current` is a **partial unique index** on
`(agent_id, environment_id) WHERE is_current`. Two admins racing both try to
insert a current allocation; Postgres admits exactly one and the loser's
`IntegrityError` becomes `TRAFFIC_ALLOCATION_CONFLICT`.

Two details worth keeping:

- **No advisory lock is taken anywhere in this domain.** The resolver runs
  inside the execution path's transaction context, and §9's Milestone 1
  deadlock lesson says not to introduce a lock that path's existing locks can
  deadlock against. Lock-free is the point.
- **The previous row's `is_current` clear is flushed before the new INSERT**,
  explicitly rather than relying on SQLAlchemy's unit-of-work ordering.
  Otherwise the insert can reach the partial index while the old row is still
  current, and a caller's *own* legitimate write fails.

`expected_revision` on the PUT provides an additional If-Match style
precondition for callers that want to detect a lost update before attempting it.

---

## The resolver

`app/runtime/deployment/resolver.py`. At most **three indexed queries**:

1. servable deployments for this agent (optionally filtered by environment),
   ordered newest-first — the same ordering the pre-3.4 path used;
2. the current allocation for `(agent, environment_id)`, hitting
   `ix_traffic_allocations_agent_environment_current`;
3. the weights joined to their deployments and versions, filtered to
   `weight > 0`, servable deployment, and version status in
   `{PUBLISHED, DEPRECATED}`.

Then a weighted draw. Resolution outcomes:

| Situation | Result |
|---|---|
| Caller pinned `deployment_id` | That deployment is honoured (tenant + servability checked); no re-routing |
| No servable deployment at all | `DEPLOYMENT_NOT_FOUND` (unchanged M1 code, 404) |
| Pinned deployment not servable | `DEPLOYMENT_NOT_ACTIVE` (unchanged M1 code, 409) |
| Servable deployment, no allocation row | **Implicit 100%** to that deployment's own version |
| Allocation exists, ≥1 servable weighted version | Weighted selection |
| Allocation exists, nothing it weights can serve | `NO_ACTIVE_DEPLOYMENT` (409, new) |

### The implicit 100% rule

An agent with a servable deployment but no allocation row resolves to that
deployment's own version. This is what keeps every previously-executable agent
executing: migration 0040 materialises explicit rows for deployments that
existed at upgrade time, and this rule covers deployments created *afterwards*
without an operator having to set weights first. The gate is not weakened — a
servable deployment is still required, which is exactly what ruling #4 asks.

On the implicit path the version's own status is deliberately *not* filtered by
the resolver, so the pre-existing `AGENT_VERSION_REVOKED` /
`AGENT_VERSION_NOT_PUBLISHED` checks in `_request_execution` still fire exactly
as they always have.

### Why `NO_ACTIVE_DEPLOYMENT` is a separate code

It is reachable only once allocations exist: a servable deployment is present,
but every version the operator gave weight to has been paused, superseded or
revoked. The alternative — falling through to the servable deployment's own
version — would silently run a version the operator's weights deliberately gave
0%. That is the failure the fail-closed rule exists to prevent, so it gets its
own code rather than being folded into the two pre-existing ones (whose M1
meanings and HTTP statuses are unchanged).

### Sticky routing

Deterministic selection is a pure function of the routing key and the entry
set: `sha256(key) % total_weight`, walked over entries sorted by version id.
No stored session state.

Stickiness is **opt-in**, in this precedence:

1. explicit `routing_key` on the execution request;
2. otherwise the request's `correlation_id`;
3. otherwise a random draw.

It is deliberately *not* defaulted to the principal's id — that would silently
make every request from one user sticky, quietly defeating a percentage
rollout for a small user base. The caller declares when a session must not flip
versions mid-flight.

Changing the weights re-shuffles which keys land where. A key is sticky *for a
given allocation*, not pinned forever — which is what makes a canary meaningful.

---

## Authorization is not bypassed

The sharpest line in this milestone (§27 §10.2). The ordering is:

```
agent checks → RESOLVER → execution row → AuthorizationGateway → policy → queue
```

The resolver **selects a version and returns a plain value**. It never
dispatches. Every authorization decision still happens afterwards, in the
pre-existing gateway call, on the resolved version's execution, exactly as
before this phase.

Verified three ways:

- **Structurally** — `resolver.py`'s parsed AST contains no import of any
  authorization or policy module and no identifier named `AuthorizationGateway`,
  `RuntimePolicyService`, `ExecutionWorkerService` or `authorize`. Checked
  against the AST, not raw text, because the module's docstring discusses the
  gateway at length.
- **Positionally** — a test asserts the resolver call site precedes
  `decision = authorize(deployment)` in `_request_execution`'s source, and that
  the `if not decision.allowed:` branch still exists.
- **Behaviourally** — a VIEWER in the same tenant, on an agent whose traffic
  *is* resolved through an allocation, is rejected 403; the admin's identical
  request succeeds, proving the rejection is the permission check and not a
  broken fixture.

---

## Performance

No cache. Deliberately.

FR-030 makes caching optional and demands proven invalidation. Every candidate
cache key here — deployment state, allocation revision, version status — is
mutated by code spread across three phases (pause, supersede, rollback, revoke,
kill switch), so a cache would need an invalidation hook in all of them to stay
correct *under the kill switch*. That is a fail-closed hazard bought for an
unmeasured gain. This phase measures instead:

- **≤ 3 queries per resolution**, asserted by counting statements through a
  SQLAlchemy `before_cursor_execute` hook — a naive multi-join or an N+1 fails
  the test, not just a review.
- **< 25 ms per resolution** wall time over 200 consecutive resolutions;
  observed ≈ 1–2 ms locally.
- The hot-path index `ix_traffic_allocations_agent_environment_current` is
  asserted to exist in `pg_indexes`.

Absence of caching is itself tested: a weight change is visible to the very next
resolution, and the resolver module is asserted to hold no mutable module-level
state that could go stale.

---

## The §15 step-2 backfill

Phase 3.1 seeded `lifecycle_state`; 3.4 completes the mapping by backfilling
allocations. Migration `0040_traffic_allocation` gives every **servable**
deployment with a governed `environment_id` a current allocation holding a
single 100% entry: its own current version.

- "Servable" in the migration is the same union-with-veto predicate the runtime
  uses, written out literally in SQL (a migration must not import application
  code that keeps evolving after the revision is pinned). Backfilling anything
  else would either strand a legacy-deployed agent or hand traffic to a paused
  one.
- Where several servable deployments share one `(agent, environment)`, the
  newest by `deployed_at` wins the 100% — the same deployment the pre-3.4 path
  would have chosen, so no agent's behaviour changes at upgrade.
- Deployments with a NULL `environment_id` (the legacy string-only create path)
  are skipped: an allocation is keyed by a real environment row, and the
  implicit-100% rule serves them unchanged.

Reversible; `downgrade()` drops both tables, leaving no residue on any
pre-existing table.

---

## The migrated test

One test changed its expected outcome, deliberately:

`tests/runtime/test_environment_promotion.py` —
`test_ac15_promoting_to_lifecycle_active_has_no_effect_on_the_legacy_execution_gate`
→ **`test_ac15_promoting_to_lifecycle_active_now_serves_execution`**

Written in Phase 3.2, it asserted that a promoted deployment reaching
`lifecycle_state=ACTIVE` still could *not* execute, because the M1 gate read
only `status`. Its own docstring named the expiry condition: *"until Phase 3.4
deliberately wires the two together."* This is that wiring, so the expectation
inverts.

It was **strengthened, not relaxed**. It still pins `status != 'ACTIVE'` before
executing, so the execution can only have been admitted by `lifecycle_state` —
precisely the union half of the predicate under test. Had 3.4 gated on `status`
alone, it would still fail. `test_ac12_...` in the 3.4 suite asserts this
migration is present and has not been softened into accepting either outcome.

No other test changed behaviour. Five Milestone 2 tests that pin the migration
head were repointed from `0039` to `0040`, the same bookkeeping 3.2 and 3.3 did.

---

## API

| Method | Path | Permission |
|---|---|---|
| `GET` | `/api/v1/runtime/agents/{agent_id}/environments/{environment_id}/traffic` | `runtime.deployment.view` |
| `PUT` | same | `runtime.deployment.deploy` |
| `GET` | `.../traffic/history` | `runtime.deployment.view` |

Mounted under agent+environment rather than `/deployments/{id}/traffic`: an
allocation spans several deployments, so hanging it off one deployment id would
make that deployment arbitrarily own the others' weights and would leave the
resolver's own lookup key unexpressible. Permissions are reused verbatim from
3.2/3.3 — changing what serves production traffic is a deployment operation.

`Idempotency-Key` is honoured on the PUT via 3.1's `IdempotencyService`
(operation `deployment.traffic.set`) — a replay returns the same revision
rather than creating a second one.

### Error codes

| Code | HTTP | Meaning |
|---|---|---|
| `TRAFFIC_WEIGHTS_INVALID` | 422 | Weights don't total 100, out of range, or a version repeated |
| `VERSION_NOT_ELIGIBLE` | 422 | Not this agent's version, not PUBLISHED, unsigned, or no active deployment in this environment |
| `TRAFFIC_ALLOCATION_CONFLICT` | 409 | Lost an optimistic-concurrency race |
| `NO_ACTIVE_DEPLOYMENT` | 409 | Allocation resolves to nothing servable (fail closed) |

### Eligibility

A version may receive weight only if it is this agent's, in this organization,
`PUBLISHED`, signed, and backed by a servable deployment **in this
environment**. Every published version is signed — `publish()` fails closed if
signing fails — so the signature check is belt-and-braces rather than a new
constraint.

Note the asymmetry, which is intentional: eligibility (the hardened admin
write) is strict; *routing* (the read path) re-checks only servability and
version status, so an allocation set yesterday keeps behaving sanely when a
deployment is paused today, without an allocation rewrite.

---

## Audit

- `DEPLOYMENT_TRAFFIC_CHANGED` — actor, environment, new revision, and the
  full **from/to** weight maps, so "who changed the split to what" is
  answerable without diffing revisions by hand.
- `RUNTIME_EXECUTION_NO_ACTIVE_DEPLOYMENT` — severity `WARNING`, makes the
  fail-closed rejection observable (§8). Recorded against the agent, because
  the gate runs *before* an execution row exists by design: a rejected request
  must not leave a phantom execution behind.

No secret appears in an allocation, a weight, or either event.

---

## Deliberately not here

> **Milestone 3 is now complete (10/10).** Every phase named as an owner in
> this table has since shipped — the scope statement below is what *this*
> document's phase deliberately left alone, not a list of missing features.
> See [operations-center.md](operations-center.md) for the operator surface
> over all of it, and [workers.md](workers.md) for the execution fleet.

| Excluded | Owning phase |
|---|---|
| Progressive/canary orchestration (auto-advancing weights) | 3.5 — 3.4 builds the allocation it drives |
| Blue-green / recreate / rolling strategies | 3.6 / 3.9 |
| Rollback | 3.7 |
| AI-aware runtime health evaluation | 3.5 / 3.7 |
| Scheduler / workers / frontend | 3.8 / 3.9 / 3.10 |
| Any change to how a resolved version *executes* | none — the M1 path runs it unchanged |

3.4 ships the substrate and the operation to *set* weights (an admin can set
90/10). It does not ship the engine that advances them automatically against
health — that is 3.5, driving this.
