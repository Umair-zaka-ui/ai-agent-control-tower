# Environments & Promotion

`/api/v1/runtime/environments`, `/api/v1/runtime/promotion-paths`,
`/api/v1/runtime/deployments/{id}/promote` ·
`runtime.environment.view`/`.manage`, `runtime.deployment.deploy` permissions.

Phase 3.2 turns `agent_deployments.environment` — a bare, unvalidated string
— into a governed, tenant-scoped `Environment` entity with real policy, and
adds a promotion operation that moves a version's *deployment eligibility*
between environments while **preserving the exact same immutable version**.
It builds directly on Phase 3.1: promotion is a deployment created through
`DeploymentLifecycleService`, its idempotency reuses
`app.runtime.deployment.idempotency.IdempotencyService` unchanged, and it
still leaves the Milestone 1 execution entry path untouched — that is Phase
3.4's own, single, deliberate change.

## The two `environment` fields, and why there are two

`agent_deployments.environment` (Phase 5.0) is a bare string, still read by
the Milestone 1 execution gate's own policy engine
(`RuntimePolicyService.evaluate`, `app.runtime.services`) and by the legacy
`DeploymentService` methods, completely unchanged. This phase adds a second,
additive column, `environment_id`, a real foreign key to the new
`environments` table:

- The legacy `environment` string is never removed, widened, or repointed.
  Every existing read of it — in particular the execution-time
  `prohibited_environments`/`requires_approval_environments` checks inside
  `RuntimePolicyService.evaluate` — is unchanged.
- `environment_id` is populated three ways: (1) migration `0038`'s own §15
  backfill for every pre-existing row, (2) an opportunistic, best-effort
  string→row lookup inside `DeploymentLifecycleService.create()` for the
  plain `POST /deployments` path (only when a row of that name already
  exists for the caller's organization — it never fails a create), and (3)
  directly, by `PromotionService.promote()`, which always sets both
  `environment` and `environment_id` together, in sync, on the deployment it
  creates.

**Whether the legacy string column will eventually be retired** is not
decided by this phase — the assessment is left for a later phase once every
consumer (in particular the M1 execution-path policy checks above) has a
clear replacement; both columns coexist correctly today, and nothing in this
phase requires retiring either.

## Environments as first-class entities (`M3-3.2-FR-001..004`)

`Environment` rows are tenant-scoped (`organization_id`, unique with `name`).
Every organization is entitled to the standard five —
`DEVELOPMENT`/`TEST`/`STAGING`/`PRODUCTION`/`SANDBOX` — seeded two ways:
migration `0038` seeds them once, live, for every organization that already
has at least one deployment; `EnvironmentService.ensure_seeded` is a
defensive get-or-create (mirroring `ReleaseChannelService.ensure_seeded`'s
own precedent) called from `GET /environments` and `POST /environments`, so
an organization created after this phase still gets a usable catalog on
first touch. Custom, org-defined environment names are also supported
(`POST /environments {"name": "QA", ...}`). `PRODUCTION` defaults
`is_production=True` — a production-class flag with stricter approval
defaults (see below); the other four default `False`.

## Environment policy (`app.runtime.environment.policy`, `M3-3.2-FR-010..013`)

An `Environment.policy` JSONB document may declare `allowed_models`,
`allowed_data_classifications`, `requires_approval`,
`maximum_concurrent_deployments`, `change_window`, `allowed_external_systems`,
and `rollback_rules`. Not every dimension is deeply enforced this phase —
the build prompt's own allowance:

| Dimension | Status |
|---|---|
| `allowed_models` | **Enforced.** The version's `model_configuration.model` must be in the list. |
| `allowed_data_classifications` | **Enforced.** Every tool in the version's frozen `tools_snapshot` must carry a `Tool.data_classification` within the list. |
| `requires_approval` | **Enforced**, folded into the *existing* single approval-reroute funnel — see below. `is_production=True` requires approval unconditionally. |
| `maximum_concurrent_deployments` | **Enforced.** Counts this agent's other `ACTIVE`-lifecycle deployments in the same environment. |
| `change_window` | **Enforced.** `PROMOTION_WINDOW_CLOSED` outside the configured days/hours (UTC). |
| `allowed_external_systems` | **Modeled only.** There is no existing link in this codebase between a runtime `Tool`/`AgentVersion` row and Milestone 2's own integration-instance catalog — deliberately, the runtime-never-knows boundary those instances are built behind (see `app.runtime.environment`'s own package docstring). Inventing one to check against here is out of this phase's scope; the field is stored and returned by the API so a later phase can wire real enforcement without a schema change. |
| `rollback_rules` | **Modeled only.** Rollback itself is Phase 3.7's own job. |

**`evaluate()` is the single deploy/promote-time choke point.** It is called
from exactly one place, `DeploymentLifecycleService.start_deploying` — which
means it runs identically for a plain deploy (once `environment_id` is
resolved) and for a promotion (`PromotionService.promote` creates its new
deployment and calls that same method). It never runs on every execution
request — that would put it on the Milestone 1 execution path this phase
must not touch.

### `prohibited_environments` — the mandatory integration (build prompt §2)

**Found**: `AgentVersion.policy_snapshot["prohibited_environments"]`, a list
of environment name strings, already read by the pre-existing
`RuntimePolicyService.evaluate` at *execution* time (`app.runtime.services`)
to block an execution whose deployment's `environment` string is in the
list. A second, narrower mechanism also named `prohibited_environments`
exists on `Capability` (§18/§19) — a capability-level restriction, unrelated
to deployment/promotion and untouched by this phase.

**The integration**: `app.runtime.environment.policy.check_prohibited` reads
the *exact same* `AgentVersion.policy_snapshot["prohibited_environments"]`
field `RuntimePolicyService.evaluate` already reads — never a second,
parallel list. A version barred from an environment by that pre-existing
mechanism cannot be deployed or promoted into it here either
(`ENVIRONMENT_POLICY_VIOLATION`), and the same fact is represented in exactly
one place.

### Approval — one funnel, not two

`DeploymentLifecycleService._requires_deployment_approval` already gated
`ACTIVE` behind an approval for two legacy reasons (a version's
`policy_snapshot.requires_approval_environments`, and
`MISSION_CRITICAL`+`PRODUCTION`). This phase adds a third, additive
condition to the *same* function — a governed `Environment`'s own
`is_production` flag or `policy.requires_approval` — so a governed
environment can demand approval without a second, parallel approval
mechanism. All three conditions land a deployment in `PENDING_APPROVAL`
identically, through `DeploymentLifecycleService.start_deploying`'s own
pre-existing reroute (creates the `runtime_approvals` row, never an error).

`PromotionPath.requires_approval` (the column the build prompt's own §5
schema names) is stored and returned by the API but **not** independently
enforced as a second approval gate this phase — the target environment's own
policy (above) is the single source of truth for "does landing here need
approval." A per-path approval requirement, distinct from the target
environment's own, is left for a later phase to wire if a real need for it
emerges, rather than building a second approval-request type now.

## Promotion paths (`M3-3.2-FR-020..021`)

`PromotionPath` rows are a per-organization, directed graph
(`from_environment_id → to_environment_id`). Promoting between two
environments with no such row is rejected, `PROMOTION_PATH_NOT_DEFINED` —
this is enforced even when the two environments both exist and both belong
to the caller's organization.

**§15 default seeding**: migration `0038` (and `EnvironmentService.
ensure_seeded`, identically) seeds a linear
`DEVELOPMENT → TEST → STAGING → PRODUCTION` chain for every organization
that gets its standard environments seeded — `STAGING → PRODUCTION` defaults
`requires_approval=True`, mirroring the pre-existing mission-critical-
production precedent. `SANDBOX` is deliberately left out of the chain — an
isolated environment, not a promotion rung. This is a choice, not the only
valid one (the build prompt explicitly allows starting with an empty,
org-configured graph instead); it was made so the promotion API has
something to promote along immediately, rather than requiring an
undocumented extra setup step first. Organizations remain free to add,
remove, or reconfigure paths via `POST`/`DELETE /promotion-paths`.

## Promotion — the immutability-preserving operation (`M3-3.2-FR-022..025`, §3.2)

**The rule**: promoting a version from one environment to another must
deploy *the exact same* version — same row, same `checksum`, same
`manifest_digest`, same `signature_id`. Promoting version 1.5.0 from STAGING
to PRODUCTION must never clone it, never modify it, never create a new
version row. This is the security core of the whole phase: the point of an
immutable, signed version (Milestone 0) is that what is running in
PRODUCTION is provably the exact thing that was reviewed and signed —
cloning or re-deriving a version at promotion time would silently break that
provenance chain.

**How it's structurally impossible to violate, not just tested against**:
`PromotionService.promote` loads the source version exactly once
(`self.db.get(AgentVersion, deployment.agent_version_id)`) and passes that
*same Python object* straight into `DeploymentService.create` — nothing in
this module ever constructs a new `AgentVersion`, copies one, or assigns to
any of its columns. `PROMOTION_IMMUTABILITY_VIOLATION` exists purely as a
defensive assertion against a future regression (checked once, right after
the new deployment is created); it is not a code path this module's own
logic can actually reach. Verified live by
`test_ac06_ac07_promotion_preserves_the_exact_version`: the promoted
deployment's `agent_version_id` matches the source exactly, the agent's
total `AgentVersion` row count is unchanged before/after, and the version's
`checksum`/`manifest_digest`/`signature_id` are byte-identical before/after.

**A promotion is a new deployment, not a new version** — `PromotionService.
promote`:

1. Resolves the target `Environment` and the configured `PromotionPath`
   (`PROMOTION_PATH_NOT_DEFINED` if none).
2. Evaluates environment policy against the *same* source version
   (`ENVIRONMENT_POLICY_VIOLATION`/`PROMOTION_WINDOW_CLOSED` if it fails) —
   fail-fast, before any row is created.
3. Creates a new `AgentDeployment` (via the same `DeploymentService.create`
   the plain create path uses) referencing that version, in the target
   environment.
4. Drives it through Phase 3.1's own lifecycle authority —
   `DRAFT → VALIDATING → READY → start_deploying()` — which re-runs the
   *same* environment-policy check (the shared choke point) and the
   Ruling #6/approval guards `ACTIVE` already required.
5. If it reaches `ACTIVE`, supersedes (not retires) any other `ACTIVE`/
   `PAUSED` deployment of the same agent already in the target environment —
   the `ACTIVE|PAUSED → SUPERSEDED` edge Phase 3.1's own lifecycle module
   declared but left undriven, "for 3.2 to drive... when a newer deployment
   is promoted into the same environment slot." `superseded_by_deployment_id`
   preserves the lineage to its successor.
6. Records `RELEASE_PROMOTED` (or `RELEASE_PROMOTION_BLOCKED` for any
   rejection above — a governance signal, audited even though nothing was
   created).

**Version lineage**: promotion does not add a parallel lineage field.
`AgentVersion.parent_version_id`/`superseded_by_id` continue to mean what
they already meant (version-to-version lineage from the versioning domain);
a *promotion's* own lineage — which deployment replaced which, in which
environment — lives entirely on `AgentDeployment.superseded_by_deployment_id`
(Phase 3.1's own column, first driven by this phase).

**Idempotent, via the exact 3.1 contract** — `PromotionService.promote` calls
`IdempotencyService.execute` scoped to operation `"deployment.promote"`,
identical to how `DeploymentLifecycleService.create` uses it for plain
creates. A retried promotion with the same `Idempotency-Key` returns the
same deployment, never a second one — proven under a real two-thread
Postgres race (`test_ac13_concurrent_identical_promotions_yield_one_deployment`).

## Release channels vs. environments — orthogonal, not duplicated

**Found**: `AgentReleaseChannel` (Phase 5.2 Part 1, `app.runtime.versioning.
channels`) — a global (not per-organization) catalog, `STABLE`/`BETA`/
`CANARY`/`INTERNAL`, referenced by `AgentVersion.release_channel_id`.

**The relationship**: a release channel is a *stability track* a version is
published onto (chosen once, at publish time, global across the platform); an
environment is a *deployment target* a published version's deployments are
promoted through (tenant-scoped, configured per organization). They are
orthogonal — a `BETA`-channel version can be promoted through
`DEVELOPMENT → TEST → STAGING` exactly like a `STABLE` one; promotion never
reads or writes `release_channel_id`
(`test_ac11_promotion_does_not_touch_release_channel`). Environment policy
does not duplicate channel semantics — no channel vocabulary
(`STABLE`/`BETA`/`CANARY`/`INTERNAL`) appears anywhere in
`app.runtime.environment.policy`
(`test_ac11_environment_policy_has_no_release_channel_field`). A later phase
remains free to let an environment's policy *reference* a required channel
(e.g. "PRODUCTION only accepts STABLE") — nothing here forecloses it, but it
is not built now.

## APIs

| Method | Path | Permission | Notes |
|---|---|---|---|
| `GET` | `/environments` | `runtime.environment.view` | Seeds the standard five on first call for the caller's organization. |
| `POST` | `/environments` | `runtime.environment.manage` | Custom environments supported. |
| `GET` | `/environments/{id}` | `runtime.environment.view` | |
| `PATCH` | `/environments/{id}` | `runtime.environment.manage` | `display_name`/`is_production` only — renaming is not supported (identity, not metadata). |
| `GET`/`PUT` | `/environments/{id}/policy` | `.view`/`.manage` | |
| `GET`/`POST` | `/promotion-paths` | `.view`/`.manage` | |
| `DELETE` | `/promotion-paths/{id}` | `runtime.environment.manage` | |
| `POST` | `/deployments/{id}/promote` | `runtime.deployment.deploy` | `{"to_environment_id", "reason"?}`. Honors `Idempotency-Key`. |

**Why `/deployments/{id}/promote`, not `/versions/{id}/promote`**: a
promotion's "from" side is *which environment a specific deployment
currently occupies* (`deployment.environment_id`), not merely which version
is being promoted — the same version can be independently deployed into
several environments at once, each with its own promotion history. Attaching
promotion to the deployment resource is what lets `PromotionPath` resolution
(`from_environment_id → to_environment_id`) be unambiguous.

**No routing conflict** (unlike 3.1's own `/pause`/`/resume`/`/retire`):
`/deployments/{id}/promote` was free — confirmed against the full existing
route table before adding it — so it is used directly, exactly as the build
prompt's own §6 suggests, with no `/lifecycle/...`-style nesting needed.

**Permission naming**: the build prompt's own suggested `environment.manage`
was checked against the existing catalog first — nothing matched, so
`runtime.environment.view`/`.manage` were added, matching this platform's
`runtime.<domain>.<verb>` convention (e.g. `runtime.signing.view`/`.manage`).
Promoting itself reuses `runtime.deployment.deploy` verbatim rather than a
third permission — a promotion *is* a deployment operation.

New error codes: `ENVIRONMENT_NOT_FOUND` (404), `ENVIRONMENT_POLICY_VIOLATION`,
`PROMOTION_PATH_NOT_DEFINED`, `PROMOTION_WINDOW_CLOSED`,
`PROMOTION_IMMUTABILITY_VIOLATION` (all 409). `DEPLOYMENT_NOT_FOUND` and
`IDEMPOTENCY_CONFLICT` are reused verbatim (no new "promotion not found"/
"promotion idempotency conflict" codes — a promotion is not itself an
independently-addressable stored resource).

## Data model

`environments` — `organization_id`, `name`, `display_name`, `is_production`,
`policy` (JSONB), unique on `(organization_id, name)`.

`promotion_paths` — `organization_id`, `from_environment_id`,
`to_environment_id`, `requires_approval`, unique on
`(organization_id, from_environment_id, to_environment_id)`.

`agent_deployments.environment_id` — nullable FK to `environments`,
`ondelete="SET NULL"`. See "The two `environment` fields" above.

### The §15 migration (`0038_environments_promotion`)

Applied once, live, for every organization with at least one existing
deployment:

1. Seed the standard five `environments` rows.
2. Backfill `agent_deployments.environment_id` by matching the existing
   `environment` string to the newly seeded row of the same name.
3. Seed the default `DEVELOPMENT → TEST → STAGING → PRODUCTION`
   `promotion_paths` chain (see "Promotion paths" above for the choice and
   its rationale).

Verified live: 4,559 organizations backfilled, 22,795 `environments` rows
(5 × 4,559) and 13,677 `promotion_paths` rows (3 × 4,559) seeded, 4,706/4,706
existing deployments' `environment_id` correctly resolved (100%) —
cross-checked directly against Postgres before any application code depended
on the result. `alembic downgrade -1` then `upgrade head` both verified
clean, restoring/re-deriving the exact same state either way. No allocation/
traffic backfill here (Phase 3.4's own job). No `deployment_events`/audit row
is synthesized for this one-time seed — it is schema/reference-data setup,
not a lifecycle transition.

## Security

- Every environment/promotion-path/promotion operation is tenant-isolated —
  `get_or_404` scopes by `organization_id`; cross-tenant access is a `404`
  (`ENVIRONMENT_NOT_FOUND`), never a `403` that would confirm the row
  exists.
- Every mutating operation requires `runtime.environment.manage` or
  `runtime.deployment.deploy`, checked server-side.
- Environment policy is enforced fail-closed: an unset/empty policy
  dimension never blocks (opt-in constraints only); a violation always
  rejects rather than warns.
- `prohibited_environments` is integrated, not paralleled (above).
- No secret in `Environment.policy`, `deployment_events` meta, or the
  `RELEASE_PROMOTED`/`RELEASE_PROMOTION_BLOCKED` audit `meta` — none of the
  fields this phase writes carry credential material.

## What this phase deliberately does not do

| Excluded | Owning phase |
|---|---|
| Traffic allocation / weighted routing / the version resolver / the execution gate | 3.4 |
| Enforcing environment policy on every runtime execution (only at deploy/promote time here) | not this phase — runtime-execution policy stays `RuntimePolicyService`'s own, separate, unmodified job |
| Preflight / release gate evaluation (may later gate promotion; not wired here) | 3.3 |
| Canary / progressive rollout | 3.5 |
| Blue-green / recreate / rolling strategies | 3.6 (rolling → 3.9) |
| Rollback (manual or automated) | 3.7 |
| Distributed scheduler / workers / any operator frontend | 3.8 / 3.9 / 3.10 |
| Any change to the Milestone 1 execution entry path | not this phase — 3.4 owns the one change |

A dedicated regression test proves the boundary is real, not just
documented: `test_ac15_promoting_to_lifecycle_active_has_no_effect_on_the_legacy_execution_gate`
promotes a deployment to `lifecycle_state=ACTIVE` and then shows the
Milestone 1 execution path still rejects it (`DEPLOYMENT_NOT_ACTIVE`) because
the *legacy* `status` column — the only thing `ExecutionRequestService.
_request_execution` reads — was never touched.

## Testing

29 new tests (`backend/tests/runtime/test_environment_promotion.py`) —
grouped by this phase's own §12 acceptance criteria: environments as
tenant-scoped first-class entities with standard + custom support (AC-01),
the string→row backfill both live-migrated and opportunistic (AC-02/AC-14),
every enforced policy dimension including the shared plain-deploy/promotion
choke point (AC-03), the change window (AC-04, plus a pure unit test with no
database), promotion-path enforcement (AC-05), the immutability assertions
(AC-06/AC-07), the full lifecycle-driven happy path and the production-
approval reroute (AC-08), a real-Postgres idempotency proof (AC-09), the
`prohibited_environments` integration (AC-10), the release-channel
orthogonality proof (AC-11), tenant isolation and authentication (AC-12), a
real two-thread concurrent-promotion race (AC-13), the Milestone 1
execution-gate boundary (AC-15), and a scan for stray TODO/FIXME/skip
markers in the new package (AC-17). All 1,379 pre-existing tests continue to
pass unchanged; full suite: 1,408 passed, 0 failed, 1 deselected
(`live_provider`).
