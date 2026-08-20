# The Release Operations Center (Phase 3.10)

The operator-facing surface over everything Milestone 3 built. Twelve views at
`/operations`, assembled from the Phase 3.1–3.9 engines.

## The read-and-trigger principle

**This phase adds no deployment logic.** Every action in the UI dispatches to a
server endpoint that already existed and already enforces authorization, tenant
isolation, idempotency, audit and the safety rules. A "roll back" button *calls*
Phase 3.7's rollback; it does not perform one.

That is not a stylistic preference. The browser is not a trust boundary —
anything the UI could decide, a user could decide differently with the developer
console open. So it decides nothing:

- **Server authorization is authoritative.** The UI hides controls a user cannot
  use, because offering them would be a lie about what will happen. Hiding is
  courtesy; the server still returns 403 to anyone who types the URL.
- **No state-changing endpoint was added.** The four new endpoints are read-only,
  and a test asserts the read-model module contains no `add`/`commit`/`delete`/
  `flush` call and imports no mutating service.
- **No migration.** This phase reads existing data. A new table would have meant
  it invented domain state.

## Truthful state

§10's rule: **never present a blocked, killed or unproven release as safe.**

The UI can only show what the server tells it, so the read models surface the
uncomfortable facts as first-class fields rather than leaving them to be inferred:

| Field | Why it is explicit |
|---|---|
| `kill_switch_active` | A boolean, not a lifecycle string the UI must know how to parse |
| `gate_verdict` | `BLOCK` renders destructive and is never summarised away |
| `release_health.is_proving` | `false` for `UNKNOWN`/`INSUFFICIENT_DATA` — the absence of evidence must never render as "fine" |
| `servable` | Phase 3.4's own union-with-veto predicate, reported rather than re-derived in the browser |

A deployment's blockers are shown **all of them, most severe first**, above
everything else on the detail view. An operator who clears a kill switch and
finds a BLOCK verdict waiting has been told twice as much as one who clears it
and has to look again.

## Guarded actions

Two tiers, because uniform friction is friction people learn to click through:

| Tier | Used for | Examples |
|---|---|---|
| **Confirm** | reversible operations | drain a worker, pause a rollout, disable a job |
| **Type-to-confirm** | irreversible, or moves production traffic | promote to production, roll back, abort a rollout, change traffic weights, arm a scheduled job |

A required reason is not decoration — it lands in the audit trail the server
writes, so the next engineer reading the timeline finds out *why*, not only
*what*.

This is a guard against the **accidental**, not the unauthorized. The server
decides whether an operator *may* roll back; the dialog exists so that an
operator who may do it does not do it by reflex, in the wrong tab, at 3am.

## Concurrency conflicts

Every Milestone 3 engine uses optimistic concurrency. An operator who acts on
stale state gets the server's conflict code (`ROLLOUT_CONFLICT`,
`TRAFFIC_ALLOCATION_CONFLICT`, `STRATEGY_CONFLICT`, …).

The UI **never auto-retries** one — that would re-apply an intent formed against
state that no longer exists — and never shows it as a generic failure, which
reads as "the platform is broken" rather than "your colleague just paused this".
It says someone else acted first, refreshes, and closes the dialog.

Safety refusals (`KILL_SWITCH_ACTIVE`, `ROLLBACK_TARGET_UNAVAILABLE`,
`STRATEGY_GATE_BLOCKED`, `ROLLING_COHORT_INVALID`, …) pass through **verbatim**,
because the server's message names precisely which rule fired.

## The twelve views

| # | View | Route | Fed by |
|---|---|---|---|
| 1 | Deployment Overview | `/operations` | `GET /runtime/operations/overview` † |
| 2 | Environment Matrix | `/operations/environments` | the same overview response, pivoted |
| 3 | Release History | `/operations/history` | `GET /runtime/operations/release-history` † |
| 4 | Deployment Detail | `/operations/deployments/:id` | `GET /runtime/operations/deployments/{id}` † |
| 5 | Rollout Timeline | `/operations/rollouts` | `GET /runtime/rollouts` † |
| 6 | Canary Dashboard | `/operations/rollouts/:id` | `GET /runtime/rollouts/{id}` + `/health`; advance / pause / resume / abort / request-rollback |
| 7 | Traffic Allocation | `/operations/traffic` | `GET`/`PUT .../traffic`, `/traffic/history` |
| 8 | Health Gates | `/operations/gates` | `GET`/`POST /deployments/{id}/preflight`, `/preflight/history` |
| 9 | Promotion Wizard | `/operations/promote` | `GET /promotion-paths`, `POST /deployments/{id}/promote` |
| 10 | Rollback Wizard | `/operations/rollback` | `/rollback/history`, `POST /rollback/execute`, `/rollback/force` |
| 11 | Worker Fleet | `/operations/fleet` | `GET /runtime/fleet`, `/fleet/queue-depth`, `POST .../drain`, `/fleet/reap` |
| 12 | Scheduler Jobs | `/operations/scheduler` | `GET /scheduler/jobs`, `/jobs/{id}/runs`, `PATCH /jobs/{id}` |

† = added by this phase. **Eight of the twelve views needed no new endpoint.**

## The four read-only endpoints, and why each was necessary

```
GET /api/v1/runtime/operations/overview
GET /api/v1/runtime/operations/release-history
GET /api/v1/runtime/operations/deployments/{deployment_id}
GET /api/v1/runtime/rollouts
```

- **`overview`** — the deployment list existed, but a row on this screen needs
  the agent name, the version's semantic version and signature state, the
  environment, the current traffic weight, any live rollout and the latest health
  verdict. Fetching those per row is five extra requests per deployment; forty
  deployments becomes two hundred round trips to render one table. A test asserts
  the server side is *flat* — batched queries, not proportional to row count.
- **`release-history`** — genuinely missing. Lifecycle events and rollback
  history were both exposed *per deployment*, so reconstructing "what shipped
  last night" required knowing every deployment id in advance. §13 requires a
  release be reconstructable; this makes that true.
- **`deployments/{id}`** — §22 lists thirteen things the detail view must show,
  spread across eight endpoints. Composing client-side would make the most
  important screen in the product the slowest, and would let it render in a
  half-state where the health block has arrived and the kill-switch banner has
  not.
- **`/rollouts`** — the sharpest gap of the four. Phase 3.5 shipped
  `GET /rollouts/{id}` and no list, so a rollout was findable only if you had
  kept the id returned when you created it. A canary could be advancing through
  production traffic with no way to see it in the API at all.

All four are tenant-scoped, gated on `runtime.deployment.view`, and read-only.

### Path note

The build prompt's §6 sketched these at `/api/v1/deployments/overview`. This
repository's runtime API is uniformly `/api/v1/runtime/...`, and
`/deployments/{deployment_id}` would have swallowed "overview" as an id — so
they are nested under `/runtime/operations/`. The rollout list is the exception:
it is not an aggregation for a screen, it is the list endpoint 3.5's resource
was missing, so it sits beside `GET /rollouts/{id}`.

## What the UI deliberately cannot do

- **Run a job.** Phase 3.8 built its API so no HTTP route dispatches. A "run now"
  button would execute a handler with no occurrence row and no lease, defeating
  exactly-once by never taking one.
- **Register a worker.** That would inject phantom capacity into the fleet — and
  rolling deployment derives *real step weights* from that capacity.
- **Choose an arbitrary rollback target.** Phase 3.7 made `rollback_target_id`
  authoritative and fails closed when it is absent. The wizard *displays* the
  target; when there isn't one it says so, rather than offering a picker that
  would reintroduce the guess.
- **Normalise traffic weights.** The page shows the running total and colours it
  when it is not 100, but never silently corrects it — that would be making an
  allocation decision, and would hide from the operator that what they typed was
  not what shipped.
- **Predict a gate.** The advance button does not evaluate stage gates; the
  server does, and refuses with `ROLLOUT_STAGE_GATE_NOT_MET`. A UI that predicted
  the gate would eventually predict it wrong, and a disabled button that should
  have been enabled is just as damaging during an incident as the reverse.

## Recovery

Nothing here changes recovery. The Operations Center holds no state of its own —
no tables, no cache that outlives a page load. After a restore it shows whatever
the restored engines contain. See [workers.md](workers.md) for the one thing
worth knowing operationally: an in-flight rolling deployment will refuse to
advance until its cohorts have live workers again.
