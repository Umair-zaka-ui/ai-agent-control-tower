# Deployment Preflight & Release Gate

`/api/v1/runtime/deployments/{id}/preflight` (POST, GET),
`/api/v1/runtime/deployments/{id}/preflight/history` (GET) ·
`runtime.deployment.deploy`/`.view` permissions (reused, no new permission
codes).

Phase 3.3 builds the **single authoritative deployment-readiness
evaluation** — `ReleaseGateService.evaluate()` — that aggregates checks
already built across Milestones 0/1/2 and Phases 3.1/3.2 into one verdict:
**PASS / WARNING / BLOCK**. It does not build a new signature verifier, a
new compatibility analyzer, a new health-check mechanism, or a new approval
engine — it calls the existing ones and reports what they say. A BLOCK
prevents a deployment from reaching `DEPLOYING`/`ACTIVE` through the Phase
3.1 lifecycle authority (fail closed).

This phase does not touch traffic allocation, the version resolver, the
execution gate (3.4), canary, strategies, rollback, the scheduler, workers,
the frontend, or the Milestone 1 execution path.

## The verdict and its findings

`ReleaseGateService.evaluate(actor, deployment)` runs every check in
`app.runtime.release_gate.checks._CHECKS`, collects the `Finding`s each one
returns, and combines them:

- **BLOCK** dominates: any BLOCK-severity finding makes the whole verdict
  BLOCK.
- Otherwise **WARNING** dominates: any WARNING-severity finding (with no
  BLOCK) makes the verdict WARNING.
- No findings at all → **PASS**.

Each `Finding` carries a stable `code`, a `severity` (`WARNING`/`BLOCK`), a
`source` (which existing capability produced it), a human-readable
`explanation`, and `remediation` guidance. A check that cannot be evaluated
(an unexpected exception) never fails silently — `run_checks()` wraps every
check call and converts an exception into a `PREFLIGHT_CHECK_UNAVAILABLE`
finding instead, honoring the fail-closed spine: absence of a positive
signal is not a positive signal.

Every result is persisted (`deployment_preflight_results`) and re-running
`evaluate()` always produces a fresh result — a prior PASS never
permanently certifies a deployment (`GET .../preflight` returns the latest;
`GET .../preflight/history` returns every prior evaluation, most recent
first).

## Severity is configurable, per environment

`_DEFAULT_SEVERITY` in `app.runtime.release_gate.checks` is the platform
default for every finding code. An `Environment.policy` (the same JSONB
document Phase 3.2 introduced) may override any of them, escalating a
WARNING to a BLOCK (or the reverse) for that organization's environment:

```json
{"preflight_severity_overrides": {"PREFLIGHT_PROVIDER_CREDENTIALS_UNAVAILABLE": "BLOCK"}}
```

One code is exempt and can never be overridden: `PREFLIGHT_KILL_SWITCH_ACTIVE`
is always BLOCK (see below).

## The check set: what exists, what's reused, and the one gap

Every SRS §Phase-3.3 check, mapped to the existing capability it calls (no
check in this list is reimplemented):

| Check | Finding code(s) | Default severity | Existing capability reused |
|---|---|---|---|
| Agent active | `PREFLIGHT_AGENT_NOT_ACTIVE` | BLOCK | `Agent.lifecycle_status` |
| No active kill switch | `PREFLIGHT_KILL_SWITCH_ACTIVE` | **BLOCK, absolute** | `Agent.lifecycle_status == "SUSPENDED"` — Ruling #6 (Phase 3.1): the platform's one suspension mechanism, driven by `AgentLifecycleService` or `KillSwitchService` |
| Version published | `PREFLIGHT_VERSION_NOT_PUBLISHED` | BLOCK | `AgentVersion.status` |
| Snapshot checksum valid | `PREFLIGHT_CHECKSUM_INVALID` | BLOCK | `app.runtime.services._verify_checksum` |
| Signature valid | `PREFLIGHT_SIGNATURE_MISSING` / `PREFLIGHT_SIGNATURE_INVALID` | BLOCK | `AttestationService.verify` (Phase 5.2.4) |
| Provenance/attestation valid | `PREFLIGHT_PROVENANCE_INVALID` | BLOCK | `AttestationService.verify`'s `snapshot_intact` |
| Compatibility complete, no blocking finding | `PREFLIGHT_COMPATIBILITY_BREAKING` | **WARNING** (see below) | `AgentVersion.compatibility_level` (Phase 5.2.6) |
| Owners valid | `PREFLIGHT_OWNER_MISSING` | WARNING | `Agent.owner_id` (§30 readiness precedent) |
| Machine identity valid | `PREFLIGHT_IDENTITY_MISSING` (WARNING) / `PREFLIGHT_IDENTITY_INVALID` (BLOCK) | see codes | `Agent.identity_id` / `AgentIdentity` — same severity split `AgentValidationService`'s §28.4 check already uses |
| Provider available | `PREFLIGHT_PROVIDER_UNAVAILABLE` | BLOCK | `app.runtime.providers.registry.registered_identifiers` |
| Provider credentials available | `PREFLIGHT_PROVIDER_CREDENTIALS_UNAVAILABLE` | WARNING | `ProviderCredentialService.resolve_for_version` |
| Tools valid | `PREFLIGHT_TOOLS_INVALID` | BLOCK | `AgentVersion.tools_snapshot` / `Tool.enabled` |
| External-system dependencies healthy | — | — | **Gap — see below** |
| Environment policy satisfied | `ENVIRONMENT_POLICY_VIOLATION` / `PROMOTION_WINDOW_CLOSED` | BLOCK | `app.runtime.environment.policy.evaluate` (Phase 3.2), called verbatim |
| Required approvals complete | `PREFLIGHT_APPROVAL_PENDING` | WARNING (see below) | `DeploymentLifecycleService._requires_deployment_approval` / `._approved_deployment_approval` (Phase 3.1) |
| Health/availability signal is fresh | `PREFLIGHT_HEALTH_SIGNAL_STALE` (WARNING) / `PREFLIGHT_HEALTH_SIGNAL_UNHEALTHY` (BLOCK) | see codes | `DeploymentHealth` / `HealthMonitoringService` — the freshness rule's actual signal, see below |
| Any check that raises | `PREFLIGHT_CHECK_UNAVAILABLE` | BLOCK | fail-closed wrapper around every check above |

### Two deliberate severity choices, not silent redesigns

- **Compatibility is WARNING, never BLOCK.** `docs/runtime/versioning.md`
  explicitly documents compatibility analysis and version readiness as
  advisory-only — "readiness has never gated anything." Turning a BREAKING
  compatibility verdict into a hard deployment BLOCK would silently reverse
  that documented design decision. The gate surfaces it (and an environment
  may still escalate it to BLOCK via `preflight_severity_overrides` if an
  organization wants that), but the platform default preserves the existing
  advisory boundary.
- **"Approval required, not yet granted" is WARNING, never BLOCK.**
  `DeploymentLifecycleService.start_deploying`'s own pre-existing behavior
  (Phase 3.1) is to *reroute* such a deployment to `PENDING_APPROVAL` rather
  than fail it — that is the correct, designed next step, not an error. A
  BLOCK here would break that flow. The gate call inside `start_deploying`
  runs *before* the approval-reroute logic specifically so this WARNING
  never disturbs it (see `app/runtime/deployment/service.py`'s own comment
  at the call site).

### The external-system dependency health gap

The build prompt's own example for "connector dependencies healthy" points
at Milestone 2's own per-instance health-check mechanism and its recorded
timestamp. Two independent, structural reasons keep this out of the check
set this phase ships, both confirmed by reading the code rather than
assumed:

1. **The runtime-never-knows boundary.** Milestone 2's own
   mechanically-enforced tests (`tests/integration/test_connector_health.py`,
   `test_connector_core.py`, `test_connector_auth.py`) scan every file under
   `app/runtime` for that Milestone's vendor/integration vocabulary and fail
   the build if it appears. `app.runtime.release_gate` lives under
   `app/runtime` and is bound by the same rule.
2. **No dependency link exists.** Even setting (1) aside, there is no
   existing column or table in this codebase connecting a runtime `Tool` or
   `AgentVersion` row to *which* Milestone-2 integration-instance(s) it
   depends on. Phase 3.2 already documented this identical gap for its own
   `allowed_external_systems` policy field
   (`app.runtime.environment.policy`'s own docstring) — this phase inherits
   the same boundary rather than inventing a parallel dependency-modeling
   feature to work around it (explicitly out of scope: "Building NEW
   checks... is out of scope. Report gap.").

This is reported as a gap, not built around. The freshness *rule* itself
(below) is still real and tested — it is simply applied to a different,
genuinely reachable signal.

## The freshness rule — the one genuinely new requirement

A health/availability signal older than a configured bound is treated as
**unproven**, not a pass. `evaluate_freshness(observed_at, bound_seconds)`
(`app.runtime.release_gate.checks`, pure and independently unit-tested)
returns `"MISSING"` (no signal recorded — nothing to be stale about, not
itself a finding), `"FRESH"`, or `"STALE"`.

Applied to `DeploymentHealth.checked_at` (§49/§50,
`app.runtime.services.HealthMonitoringService`) — the one health/availability
signal with a real timestamp that is both already inside the runtime domain
and has no missing dependency link, unlike the gap above. A deployment with
no heartbeat history yet (the common case for a brand-new deployment)
produces no finding; once a heartbeat exists, it must be both fresh *and*
report `HEALTHY`, or the gate reports it:

- Stale (older than the bound): `PREFLIGHT_HEALTH_SIGNAL_STALE`, WARNING by
  default.
- Fresh but not `HEALTHY`: `PREFLIGHT_HEALTH_SIGNAL_UNHEALTHY`, BLOCK.

**The bound is configurable**, per environment, via
`Environment.policy["preflight_freshness_bound_seconds"]`; the platform
default (`_DEFAULT_FRESHNESS_BOUND_SECONDS` in `checks.py`) is **900 seconds
(15 minutes)** when unset. A production-class environment can set a tighter
bound than a sandbox.

## Fail-closed, and what "absolute" means for the kill switch

Two guarantees this phase is built around, both verified by test
(`tests/runtime/test_release_gate.py`):

- **An unevaluable required check is never a silent PASS.** Every check
  call is wrapped; an exception becomes a `PREFLIGHT_CHECK_UNAVAILABLE`
  finding (BLOCK by default, itself overridable) rather than being skipped.
- **The kill switch is absolute and re-checked at the moment of transition,
  never trusted from a prior evaluation.** `ReleaseGateService.evaluate()`
  always reads live state — there is no caching between a preview
  `POST .../preflight` and the moment `DeploymentLifecycleService.
  start_deploying()` calls the gate again for the actual transition attempt.
  A deployment that passed preflight, whose agent is then killed, and which
  then attempts to deploy, is blocked — the gate re-evaluates fresh every
  single call, it does not remember or reuse a prior verdict. This is on top
  of (not instead of) the pre-existing, independent Ruling #6 check
  (`DeploymentLifecycleService._assert_can_reach_active`), which still fires
  at the literal `DEPLOYING -> ACTIVE` transition for any code path that
  reaches `ACTIVE` without going through `start_deploying`'s gate call (e.g.
  `resume()`).

## Wiring into the lifecycle (`M3-3.3-FR-005`)

`DeploymentLifecycleService.start_deploying()` (`app/runtime/deployment/
service.py`) calls `ReleaseGateService.evaluate()` once, after the
pre-existing narrow environment-policy check (Phase 3.2, left completely
unchanged — including its own error codes — so no existing 3.2 test needed
to change its *expectations* beyond one: see below) and before the
approval-reroute logic. A BLOCK verdict raises `DEPLOYMENT_PREFLIGHT_BLOCKED`
(409) carrying the blocking finding codes in its message; the full result,
including any WARNINGs, is always persisted and retrievable regardless of
verdict.

**One pre-existing Phase 3.1 test's expectation changed, not weakened.**
`test_ac09_suspended_agent_blocks_activation` previously asserted the raw
`DEPLOYMENT_AGENT_SUSPENDED` code and a `DEPLOYING` post-condition. Because
the gate now runs *before* the `READY -> DEPLOYING` mutation (rather than
`_assert_can_reach_active` firing only after that mutation already
committed, at the `DEPLOYING -> ACTIVE` step), the deployment now correctly
stays at `READY` on rejection — a strictly safer post-condition — and
surfaces the gate's own, more specific `DEPLOYMENT_PREFLIGHT_BLOCKED`. The
underlying guarantee the test protects ("a suspended agent's deployment
cannot activate") is unchanged and, if anything, enforced earlier and more
cleanly. See that test's own updated comment.

**Promotion is gated for free.** `PromotionService.promote()` (Phase 3.2)
already funnels its new deployment through this exact same
`start_deploying()` call — no extra wiring was needed to gate a promotion
too, per the build prompt's own "if wiring into promotion is trivial via
3.2's path, it's acceptable" allowance.

## Data model

`deployment_preflight_results` (migration `0039`, chained from `0038`,
reversible):

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `deployment_id` | UUID FK → `agent_deployments`, indexed | |
| `organization_id` | UUID FK → `organizations`, indexed | tenant scope |
| `verdict` | VARCHAR(12) | `PASS` / `WARNING` / `BLOCK` |
| `findings` | JSONB | list of `{code, severity, source, explanation, remediation}` — a snapshot of that one evaluation, not normalized into rows |
| `evaluated_at` | TIMESTAMP | |
| `evaluated_by` | UUID, nullable | |

Composite index on `(deployment_id, evaluated_at)` for the latest-result and
history lookups.

## APIs

| Method | Path | Permission |
|---|---|---|
| POST | `/api/v1/runtime/deployments/{id}/preflight` | `runtime.deployment.deploy` |
| GET | `/api/v1/runtime/deployments/{id}/preflight` | `runtime.deployment.view` (returns the latest result, or `null` if none yet) |
| GET | `/api/v1/runtime/deployments/{id}/preflight/history` | `runtime.deployment.view` |

`POST .../preflight` is **not** wrapped in the Phase 3.1 idempotency
contract: FR-031 requires every call to produce a fresh result ("a prior
PASS does not permanently certify"), the opposite of idempotent replay —
the same precedent `CompatibilityAnalysisService.analyze`
(`POST .../analyze`, Phase 5.2.6) already establishes in this codebase for
a recompute-and-persist-fresh-every-call operation.

New error codes: `DEPLOYMENT_PREFLIGHT_BLOCKED` (409 — a BLOCK stopped a
lifecycle transition), `PREFLIGHT_CHECK_UNAVAILABLE` (409 — reserved for a
caller that wants to specifically detect the fail-closed case; in practice
this code appears as a finding's own `code`, embedded inside a
`DEPLOYMENT_PREFLIGHT_BLOCKED` response, rather than being raised on its
own). `DEPLOYMENT_NOT_FOUND` is reused verbatim for a deployment looked up
ahead of a preflight call — there is no separate "preflight not found"
code, mirroring Phase 3.2's own promotion precedent.

New audit events (SRS §13's own literal names, unprefixed — mirroring
Phase 3.2's `RELEASE_PROMOTED`/`RELEASE_PROMOTION_BLOCKED` precedent):
`DEPLOYMENT_VALIDATION_STARTED`, `DEPLOYMENT_VALIDATION_FAILED` (a BLOCK
verdict), `DEPLOYMENT_VALIDATION_PASSED` (this phase's own name for the
build prompt's unnamed "passed-validation event"). A kill-switch-caused
BLOCK is additionally tagged `severity="CRITICAL"` on its audit/event-stream
row, regardless of the overall verdict's own severity — a security-relevant
signal, not just a routine validation failure.

## Security

- Fail closed: an unevaluable required check, or a stale positive signal,
  is never treated as a pass.
- The kill switch is absolute and always re-checked live — never cached or
  trusted from a prior evaluation.
- Tenant isolation on every preflight endpoint (`DeploymentService.
  get_or_404`, reused verbatim — cross-tenant access is `404
  DEPLOYMENT_NOT_FOUND`, not `403`).
- No secret ever appears in a finding, a persisted result, or an audit
  event — every check reads only metadata (status flags, timestamps,
  booleans), never a credential or its ciphertext.
- Existing signature/provenance verification (`AttestationService.verify`)
  is called, never re-implemented or weakened.

## What this phase deliberately does not do

- No traffic allocation, version resolver, or execution gate (Phase 3.4).
- No canary or rollout (3.5). No strategies (3.6/3.9). No rollback (3.7).
  No scheduler, workers, or frontend (3.8/3.9/3.10).
- No enforcement of the gate on the Milestone 1 execution path — that path
  is completely untouched by this phase.
- No new dependency link between a runtime `Tool`/`AgentVersion` and
  Milestone 2's integration-instance catalog (the reported gap above).
- `PromotionPath.requires_approval` (Phase 3.2) is still not an independent
  second approval gate — unchanged from 3.2's own documented scope.

## Testing

`tests/runtime/test_release_gate.py`, grouped by this phase's own §12
acceptance criteria — real Postgres throughout, matching every other test
file in this suite. Includes: verdict/finding structure (AC-01/02), pure
aggregation-precedence and freshness-state unit tests with no database
(AC-03, AC-09), a BLOCK actually preventing a lifecycle transition (AC-04),
reuse-verified-by-call spy tests for the environment-policy and approval
checks (AC-05/AC-11), a fail-closed unevaluable-check test (AC-06), the
kill switch's absolute-BLOCK and re-checked-at-transition guarantees
(AC-07/AC-08), the freshness rule's stale/fresh/unhealthy behavior and its
configurable bound (AC-09/AC-10), persisted latest/history retrieval
(AC-12), authentication and cross-tenant rejection (AC-13), a
per-finding-code sweep (checksum tamper, invalid machine identity, a
disabled bound tool, an unregistered provider, a missing owner, an
environment-policy violation, a pending-approval WARNING that doesn't
disturb the reroute), a full happy-path PASS, and vocabulary/TODO-marker
sweeps mirroring Milestone 2's own precedent.
