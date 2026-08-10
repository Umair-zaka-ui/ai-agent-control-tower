"""ACT-SRS-M3 §Phase-3.3 (M3-3.3-FR-010..023) -- the individual preflight
checks, each aggregating an *existing* capability rather than reimplementing
one (build prompt §0/§15's reuse mandate). See this package's
``service.py`` for the orchestration (``ReleaseGateService``) and
``docs/deployment/release-gates.md`` for the full check-to-source mapping,
including the one check this phase reports as a **gap** rather than builds:
external-system dependency health (see the module-level note below
``_CHECKS``, and ``docs/deployment/release-gates.md`` for exactly which
Milestone-2 capability that gap refers to -- deliberately not named here;
see reason (1) below).

Every check function takes one ``GateContext`` and returns ``list[Finding]``
(empty = that check found nothing to report -- not necessarily "passed";
see each function's own docstring). ``run_checks()`` wraps each call so an
unexpected exception from any one check becomes a ``PREFLIGHT_CHECK_UNAVAILABLE``
finding rather than crashing the whole evaluation or -- worse -- silently
skipping that check (build prompt §3's fail-closed spine: "absence of a
positive signal is not a positive signal").

**Severity is data, not hardcoded per call site** (``_DEFAULT_SEVERITY``
below), and every code except ``PREFLIGHT_KILL_SWITCH_ACTIVE`` (absolute,
AC-07) may be overridden per environment via
``Environment.policy["preflight_severity_overrides"]`` -- FR-006's "an
environment policy may elevate specified WARNINGs to BLOCK". An unrecognized
code (defensively, should not happen) defaults to BLOCK, matching the
fail-closed spine.

**The freshness rule (FR-020..023)** -- the phase's one genuinely new
requirement -- is implemented as ``evaluate_freshness()``, a pure,
database-free function, and applied to ``DeploymentHealth.checked_at``
(``check_health_freshness`` below), **not** to Milestone 2's own
integration-instance health-check timestamp as the build prompt's own
example suggests. Two independent, structural reasons, both confirmed by
reading the code rather than assumed:

1. The "runtime-never-knows" boundary (Milestone 2's own
   mechanically-enforced vocabulary tests under ``tests/integration/``)
   forbids naming that Milestone-2 vendor/integration vocabulary anywhere
   under ``app/runtime`` -- this package included.
2. Even setting (1) aside, there is no existing link in this codebase
   between a runtime ``Tool``/``AgentVersion`` row and Milestone 2's own
   integration-instance catalog to know *which* external-system instances a
   given deployment even depends on -- the identical, already-documented
   reason Phase 3.2 left ``allowed_external_systems`` modeled-only
   (``app.runtime.environment.policy``'s own docstring).

Both are reported here as a **gap**, not built around with a parallel
dependency-modeling feature (out of this phase's scope per build prompt §1).
``DeploymentHealth`` (§49/§50, ``app.runtime.services.HealthMonitoringService``)
is the one health/availability signal with a real timestamp that *is*
reachable, already inside the runtime domain, with no missing link -- so the
freshness *rule* itself is still real, tested, and wired to a genuine signal,
not vaporware; it is simply reading a different (but structurally identical)
input than the build prompt's own suggested example. See
``docs/deployment/release-gates.md`` for the full account, spelled out
plainly outside the runtime tree."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.identity.errors import IdentityError
from app.identity.models.agent_identity import AgentIdentity
from app.models.agent import Agent
from app.models.runtime import AgentDeployment, AgentVersion, DeploymentHealth, Environment, Tool
from app.runtime.environment import policy as environment_policy

# Platform default freshness bound (15 minutes) -- FR-022: "configurable
# (per environment or platform default -- state which)". This constant is
# the platform default; ``Environment.policy["preflight_freshness_bound_seconds"]``
# overrides it per environment (production-class environments may want a
# tighter bound than a sandbox).
_DEFAULT_FRESHNESS_BOUND_SECONDS = 900


@dataclass(frozen=True)
class Finding:
    code: str
    severity: str  # "WARNING" | "BLOCK"
    source: str
    explanation: str
    remediation: str

    def as_dict(self) -> dict:
        return {"code": self.code, "severity": self.severity, "source": self.source,
               "explanation": self.explanation, "remediation": self.remediation}


@dataclass
class GateContext:
    db: Session
    agent: Agent
    version: AgentVersion
    deployment: AgentDeployment
    environment: Environment | None = None


# --------------------------------------------------------------------------- #
# Severity resolution (FR-006, FR-011) -- default per finding code, with a
# per-environment override map. ``PREFLIGHT_KILL_SWITCH_ACTIVE`` is
# deliberately absent: it is never looked up here (see ``_severity_for``).
# --------------------------------------------------------------------------- #
_DEFAULT_SEVERITY: dict[str, str] = {
    "PREFLIGHT_AGENT_NOT_ACTIVE": "BLOCK",
    "PREFLIGHT_VERSION_NOT_PUBLISHED": "BLOCK",
    "PREFLIGHT_CHECKSUM_INVALID": "BLOCK",
    "PREFLIGHT_SIGNATURE_MISSING": "BLOCK",
    "PREFLIGHT_SIGNATURE_INVALID": "BLOCK",
    "PREFLIGHT_PROVENANCE_INVALID": "BLOCK",
    # Advisory only -- mirrors docs/runtime/versioning.md's own "readiness
    # has never gated anything" / compatibility-is-advisory precedent (build
    # prompt §15's "validate against the repository" mandate: this phase does
    # not silently turn an established advisory-only signal into a hard
    # block).
    "PREFLIGHT_COMPATIBILITY_BREAKING": "WARNING",
    "PREFLIGHT_OWNER_MISSING": "WARNING",
    # Mirrors AgentValidationService's own §28.4 severity split (identity_id
    # unset = WARNING, "the hard gate is enforced at
    # AgentLifecycleService.activate"; identity_id set but invalid = BLOCKING).
    "PREFLIGHT_IDENTITY_MISSING": "WARNING",
    "PREFLIGHT_IDENTITY_INVALID": "BLOCK",
    "PREFLIGHT_PROVIDER_UNAVAILABLE": "BLOCK",
    # WARNING, not BLOCK: ``ProviderCredentialService`` itself documents that
    # it "has no way to know in advance whether a given provider endpoint
    # actually requires one" (a credential-free local provider is valid,
    # ACT-MDL-FR-083) -- an absent credential is surfaced, not assumed fatal.
    "PREFLIGHT_PROVIDER_CREDENTIALS_UNAVAILABLE": "WARNING",
    "PREFLIGHT_TOOLS_INVALID": "BLOCK",
    # A deployment correctly awaiting approval is the *designed* next step
    # (DeploymentLifecycleService.start_deploying's own PENDING_APPROVAL
    # reroute), not a failure -- WARNING surfaces it without blocking that
    # flow (FR-006).
    "PREFLIGHT_APPROVAL_PENDING": "WARNING",
    "PREFLIGHT_HEALTH_SIGNAL_STALE": "WARNING",
    "PREFLIGHT_HEALTH_SIGNAL_UNHEALTHY": "BLOCK",
    "PREFLIGHT_CHECK_UNAVAILABLE": "BLOCK",
    # Reused verbatim from app.runtime.environment.policy (AC-11) -- same
    # codes that module's own narrow choke point in start_deploying() raises.
    "ENVIRONMENT_POLICY_VIOLATION": "BLOCK",
    "PROMOTION_WINDOW_CLOSED": "BLOCK",
}


def _severity_for(code: str, environment: Environment | None) -> str:
    if code == "PREFLIGHT_KILL_SWITCH_ACTIVE":
        return "BLOCK"  # AC-07: absolute, never configurable.
    overrides = (environment.policy or {}).get("preflight_severity_overrides", {}) if environment else {}
    override = overrides.get(code) if isinstance(overrides, dict) else None
    if override in ("WARNING", "BLOCK"):
        return override
    return _DEFAULT_SEVERITY.get(code, "BLOCK")


def _freshness_bound_seconds(environment: Environment | None) -> int:
    if environment is None:
        return _DEFAULT_FRESHNESS_BOUND_SECONDS
    raw = (environment.policy or {}).get("preflight_freshness_bound_seconds")
    if not isinstance(raw, (int, float)) or raw <= 0:
        return _DEFAULT_FRESHNESS_BOUND_SECONDS
    return int(raw)


def evaluate_freshness(observed_at: datetime | None, bound_seconds: int, *,
                       now: datetime | None = None) -> str:
    """Pure, database-free (FR-023's "keep it bounded" spirit + directly unit
    testable). Returns ``"MISSING"`` (no signal recorded at all -- distinct
    from stale: nothing to be stale about), ``"FRESH"``, or ``"STALE"``."""
    if observed_at is None:
        return "MISSING"
    now = now or datetime.now(timezone.utc)
    age_seconds = (now - observed_at).total_seconds()
    return "STALE" if age_seconds > bound_seconds else "FRESH"


# --------------------------------------------------------------------------- #
# Individual checks -- each maps to one existing capability (AC-05).
# --------------------------------------------------------------------------- #
def check_agent_active_and_kill_switch(ctx: GateContext) -> list[Finding]:
    """Ruling #6 (see ``app.runtime.deployment.lifecycle``'s own module
    docstring): the platform's one suspension/kill mechanism is
    ``Agent.lifecycle_status == "SUSPENDED"``, driven by either
    ``AgentLifecycleService`` or ``KillSwitchService``
    (``app.runtime.services``, §60). Reused here verbatim -- never a second
    suspension concept -- exactly as
    ``DeploymentLifecycleService._assert_can_reach_active`` already reads it
    at the ACTIVE transition (AC-08's re-check happens there, not here; see
    that method)."""
    if ctx.agent.lifecycle_status == "SUSPENDED":
        return [Finding(
            code="PREFLIGHT_KILL_SWITCH_ACTIVE", severity="BLOCK",
            source="Agent.lifecycle_status (Ruling #6 / KillSwitchService, app.runtime.services)",
            explanation="This agent is suspended -- an active kill switch or other administrative "
                       "suspension is in effect.",
            remediation="Resume the agent (or deactivate the kill switch) before deploying.",
        )]
    if ctx.agent.lifecycle_status != "ACTIVE":
        return [Finding(
            code="PREFLIGHT_AGENT_NOT_ACTIVE", severity=_severity_for("PREFLIGHT_AGENT_NOT_ACTIVE", ctx.environment),
            source="Agent.lifecycle_status",
            explanation=f"Agent lifecycle_status is {ctx.agent.lifecycle_status}, not ACTIVE.",
            remediation="Activate the agent (registry lifecycle) before deploying it.",
        )]
    return []


def check_version_published(ctx: GateContext) -> list[Finding]:
    """``AgentVersion.status`` -- ``DeploymentService.create`` already
    requires PUBLISHED at creation time; this re-verifies at preflight/deploy
    time in case the version was deprecated/revoked after the deployment row
    was created."""
    if ctx.version.status != "PUBLISHED":
        return [Finding(
            code="PREFLIGHT_VERSION_NOT_PUBLISHED", severity="BLOCK", source="AgentVersion.status",
            explanation=f"Version status is {ctx.version.status}, not PUBLISHED.",
            remediation="Publish this version, or deploy a different, published version.",
        )]
    return []


def check_snapshot_checksum(ctx: GateContext) -> list[Finding]:
    """Reuses ``app.runtime.services._verify_checksum`` verbatim -- the same
    tamper check ``AgentVersionService.validate``/``.publish`` already run."""
    from app.runtime.services import _verify_checksum

    if not _verify_checksum(ctx.version):
        return [Finding(
            code="PREFLIGHT_CHECKSUM_INVALID", severity="BLOCK", source="app.runtime.services._verify_checksum",
            explanation="This version's snapshot checksum no longer matches its configuration -- it may "
                       "have been tampered with.",
            remediation="Do not deploy; investigate the checksum mismatch immediately.",
        )]
    return []


def check_signature_and_provenance(ctx: GateContext) -> list[Finding]:
    """Reuses ``AttestationService.verify`` verbatim (AC-11: verified by
    call, not copy) -- never re-implements signature or snapshot-intactness
    verification (§10's "do not weaken existing signature/provenance
    verification")."""
    if ctx.version.signature_id is None:
        return [Finding(
            code="PREFLIGHT_SIGNATURE_MISSING", severity="BLOCK",
            source="app.runtime.versioning.attestation.AttestationService.verify",
            explanation="This version has not been signed.",
            remediation="Publish/sign the version before deploying.",
        )]
    from app.runtime.versioning.attestation import AttestationService

    try:
        result = AttestationService(ctx.db).verify(ctx.version)
    except IdentityError:
        return [Finding(
            code="PREFLIGHT_SIGNATURE_MISSING", severity="BLOCK",
            source="app.runtime.versioning.attestation.AttestationService.verify",
            explanation="This version has not been signed.",
            remediation="Publish/sign the version before deploying.",
        )]

    findings: list[Finding] = []
    if not result["snapshot_intact"]:
        findings.append(Finding(
            code="PREFLIGHT_PROVENANCE_INVALID", severity="BLOCK",
            source="app.runtime.versioning.attestation.AttestationService.verify",
            explanation="The frozen release snapshot no longer matches what was signed.",
            remediation="Do not deploy; investigate the snapshot/signature mismatch immediately.",
        ))
    if not all(check["passed"] for check in result["signatures"]):
        findings.append(Finding(
            code="PREFLIGHT_SIGNATURE_INVALID", severity="BLOCK",
            source="app.runtime.versioning.attestation.AttestationService.verify",
            explanation="One or more signatures on this version do not verify (invalid signature or a "
                       "revoked signing key).",
            remediation="Re-sign the version with a valid, non-revoked key before deploying.",
        ))
    return findings


def check_compatibility(ctx: GateContext) -> list[Finding]:
    """Reuses ``AgentVersion.compatibility_level`` (``app.runtime.versioning.
    compatibility``) -- WARNING only, preserving that module's own
    documented advisory-only boundary ("readiness has never gated anything";
    see docs/runtime/versioning.md)."""
    if ctx.version.compatibility_analyzed_at is None or ctx.version.compatibility_level in (None, "UNKNOWN"):
        return []
    if ctx.version.compatibility_level == "BREAKING":
        return [Finding(
            code="PREFLIGHT_COMPATIBILITY_BREAKING",
            severity=_severity_for("PREFLIGHT_COMPATIBILITY_BREAKING", ctx.environment),
            source="app.runtime.versioning.compatibility (AgentVersion.compatibility_level)",
            explanation="This version introduces BREAKING changes relative to its resolved compatibility "
                       "baseline.",
            remediation="Review the compatibility findings (GET .../compatibility) and downstream "
                       "consumers before proceeding.",
        )]
    return []


def check_owners(ctx: GateContext) -> list[Finding]:
    """Reuses ``Agent.owner_id`` -- the same field
    ``VersionReadinessService``'s §30 ``owners_assigned`` check already
    reads."""
    if ctx.agent.owner_id is None:
        return [Finding(
            code="PREFLIGHT_OWNER_MISSING", severity=_severity_for("PREFLIGHT_OWNER_MISSING", ctx.environment),
            source="Agent.owner_id",
            explanation="This agent has no assigned business owner.",
            remediation="Assign a business owner to the agent.",
        )]
    return []


def check_machine_identity(ctx: GateContext) -> list[Finding]:
    """Reuses ``Agent.identity_id`` / ``AgentIdentity`` -- the same fields
    ``AgentIdentityAssociationService._check_eligible`` and
    ``AgentValidationService``'s §28.4 check already read, with the same
    severity split that validation module already establishes."""
    if ctx.agent.identity_id is None:
        return [Finding(
            code="PREFLIGHT_IDENTITY_MISSING",
            severity=_severity_for("PREFLIGHT_IDENTITY_MISSING", ctx.environment),
            source="Agent.identity_id",
            explanation="This agent has no associated machine identity.",
            remediation="Associate a machine identity with the agent.",
        )]
    identity = ctx.db.get(AgentIdentity, ctx.agent.identity_id)
    if identity is None or identity.agent_id != ctx.agent.id:
        return [Finding(
            code="PREFLIGHT_IDENTITY_INVALID", severity="BLOCK", source="AgentIdentity",
            explanation="identity_id does not reference an eligible identity for this agent.",
            remediation="Associate a valid machine identity with the agent.",
        )]
    if identity.status != "ACTIVE":
        return [Finding(
            code="PREFLIGHT_IDENTITY_INVALID", severity="BLOCK", source="AgentIdentity",
            explanation=f"The agent's machine identity is {identity.status}, not ACTIVE.",
            remediation="Reactivate or replace the agent's machine identity.",
        )]
    if identity.expires_at and identity.expires_at <= datetime.now(timezone.utc):
        return [Finding(
            code="PREFLIGHT_IDENTITY_INVALID", severity="BLOCK", source="AgentIdentity",
            explanation="The agent's machine identity has expired.",
            remediation="Rotate/replace the agent's machine identity before deploying.",
        )]
    return []


def check_provider_available(ctx: GateContext) -> list[Finding]:
    """Reuses ``app.runtime.providers.registry.registered_identifiers`` --
    never re-derives the set of usable providers."""
    from app.runtime.providers.registry import registered_identifiers

    provider = ((ctx.version.model_configuration or {}).get("provider") or "").upper()
    if not provider or provider not in registered_identifiers():
        return [Finding(
            code="PREFLIGHT_PROVIDER_UNAVAILABLE", severity="BLOCK",
            source="app.runtime.providers.registry.registered_identifiers",
            explanation=f"Model provider '{provider or '(none configured)'}' is not registered.",
            remediation="Configure a registered model provider on this version's model_configuration.",
        )]
    return []


def check_provider_credentials(ctx: GateContext) -> list[Finding]:
    """Reuses ``ProviderCredentialService.resolve_for_version`` verbatim --
    never re-derives credential resolution order."""
    from app.runtime.services import ProviderCredentialService

    resolved = ProviderCredentialService(ctx.db).resolve_for_version(ctx.agent.organization_id, ctx.version)
    if resolved.api_key is None:
        provider = ((ctx.version.model_configuration or {}).get("provider") or "").upper()
        return [Finding(
            code="PREFLIGHT_PROVIDER_CREDENTIALS_UNAVAILABLE",
            severity=_severity_for("PREFLIGHT_PROVIDER_CREDENTIALS_UNAVAILABLE", ctx.environment),
            source="app.runtime.services.ProviderCredentialService.resolve_for_version",
            explanation=f"No credential is configured for provider '{provider}' (this may be expected for "
                       "a credential-free local provider).",
            remediation="Configure a provider credential if this provider requires one.",
        )]
    return []


def check_tools_valid(ctx: GateContext) -> list[Finding]:
    """Reuses the same ``AgentVersion.tools_snapshot`` UUID-parsing pattern
    ``app.runtime.environment.policy._tool_data_classifications`` already
    established -- checks every bound tool still exists and is enabled."""
    tool_ids: list[uuid.UUID] = []
    for raw in ctx.version.tools_snapshot or []:
        try:
            tool_ids.append(uuid.UUID(raw))
        except (ValueError, TypeError):
            continue
    if not tool_ids:
        return []
    rows = ctx.db.execute(select(Tool.id, Tool.enabled).where(Tool.id.in_(tool_ids))).all()
    found = {row[0]: row[1] for row in rows}
    missing = [str(tool_id) for tool_id in tool_ids if tool_id not in found]
    disabled = [str(tool_id) for tool_id in tool_ids if tool_id in found and not found[tool_id]]
    if not missing and not disabled:
        return []
    parts = []
    if missing:
        parts.append(f"{len(missing)} bound tool(s) no longer exist")
    if disabled:
        parts.append(f"{len(disabled)} bound tool(s) are disabled")
    return [Finding(
        code="PREFLIGHT_TOOLS_INVALID", severity="BLOCK", source="app.models.runtime.Tool",
        explanation="; ".join(parts) + ".",
        remediation="Remove or replace the invalid tool bindings, or re-enable the disabled tools.",
    )]


def check_environment_policy(ctx: GateContext) -> list[Finding]:
    """Reuses ``app.runtime.environment.policy.evaluate`` verbatim (AC-11) --
    the exact same evaluation ``DeploymentLifecycleService.start_deploying``'s
    own narrow choke point already runs; this is a second, redundant read of
    the same pure function (cheap), not a second implementation."""
    if ctx.environment is None:
        return []
    violation = environment_policy.evaluate(
        ctx.db, ctx.environment, ctx.version, ctx.agent.id, exclude_deployment_id=ctx.deployment.id,
    )
    if violation is None:
        return []
    return [Finding(
        code=violation.code, severity=_severity_for(violation.code, ctx.environment),
        source="app.runtime.environment.policy.evaluate",
        explanation=violation.message,
        remediation="Adjust the environment's policy or the version, or choose a different target "
                   "environment.",
    )]


def check_approvals(ctx: GateContext) -> list[Finding]:
    """Reuses ``DeploymentLifecycleService``'s own private approval-funnel
    methods verbatim (AC-11-style reuse; a local import avoids the circular
    import ``app.runtime.deployment.service`` <-> this package would
    otherwise create -- see ``service.py``'s own note). WARNING, not BLOCK:
    "approval required, not yet granted" is the designed reroute-to-
    PENDING_APPROVAL path, not a failure (FR-006)."""
    from app.runtime.deployment.service import DeploymentLifecycleService

    lifecycle_service = DeploymentLifecycleService(ctx.db)
    if not lifecycle_service._requires_deployment_approval(ctx.agent, ctx.deployment):
        return []
    if lifecycle_service._approved_deployment_approval(ctx.deployment) is not None:
        return []
    return [Finding(
        code="PREFLIGHT_APPROVAL_PENDING",
        severity=_severity_for("PREFLIGHT_APPROVAL_PENDING", ctx.environment),
        source="app.runtime.deployment.service.DeploymentLifecycleService (3.1 approval funnel)",
        explanation="This deployment requires an approved runtime_approvals record before it can become "
                   "ACTIVE.",
        remediation="Obtain approval via the runtime approvals workflow.",
    )]


def check_health_freshness(ctx: GateContext) -> list[Finding]:
    """The freshness rule (FR-020..023), applied to ``DeploymentHealth`` --
    see this module's own docstring for why not the Milestone-2 signal the
    build prompt names. No recorded signal at all is not itself a finding (a
    brand-new deployment has nothing to be stale about yet)."""
    latest = ctx.db.execute(
        select(DeploymentHealth).where(DeploymentHealth.deployment_id == ctx.deployment.id)
        .order_by(DeploymentHealth.checked_at.desc()).limit(1)
    ).scalar_one_or_none()
    if latest is None:
        return []
    bound = _freshness_bound_seconds(ctx.environment)
    state = evaluate_freshness(latest.checked_at, bound)
    if state == "STALE":
        return [Finding(
            code="PREFLIGHT_HEALTH_SIGNAL_STALE",
            severity=_severity_for("PREFLIGHT_HEALTH_SIGNAL_STALE", ctx.environment),
            source="app.runtime.services.HealthMonitoringService (DeploymentHealth.checked_at)",
            explanation=f"The most recent health signal is older than the configured freshness bound "
                       f"({bound}s) -- a stale positive is not treated as proof of health.",
            remediation="Trigger a fresh heartbeat/health check before deploying.",
        )]
    if latest.status != "HEALTHY":
        return [Finding(
            code="PREFLIGHT_HEALTH_SIGNAL_UNHEALTHY", severity="BLOCK",
            source="app.runtime.services.HealthMonitoringService (DeploymentHealth.status)",
            explanation=f"The most recent (fresh) health signal reports status={latest.status}.",
            remediation="Investigate and resolve the reported health issue before deploying.",
        )]
    return []


# Every SRS §Phase-3.3 check except "external-system dependencies healthy"
# (the documented gap above). Order is deliberate: cheap/local checks first,
# checks that call into another service module last.
_CHECKS = (
    check_agent_active_and_kill_switch,
    check_version_published,
    check_snapshot_checksum,
    check_signature_and_provenance,
    check_compatibility,
    check_owners,
    check_machine_identity,
    check_provider_available,
    check_provider_credentials,
    check_tools_valid,
    check_environment_policy,
    check_approvals,
    check_health_freshness,
)


def run_checks(ctx: GateContext) -> list[Finding]:
    """FR-011: a check that raises is never silence -- it becomes a
    ``PREFLIGHT_CHECK_UNAVAILABLE`` finding (fail closed), not a skipped
    check and not a crashed evaluation."""
    findings: list[Finding] = []
    for check in _CHECKS:
        try:
            findings.extend(check(ctx))
        except Exception as exc:  # noqa: BLE001 -- an unevaluable check must never silently pass
            findings.append(Finding(
                code="PREFLIGHT_CHECK_UNAVAILABLE",
                severity=_severity_for("PREFLIGHT_CHECK_UNAVAILABLE", ctx.environment),
                source=check.__name__,
                explanation=f"This check could not be evaluated: {str(exc)[:300]}",
                remediation="Investigate why this check failed to run; treated as unproven, not a pass.",
            ))
    return findings


def verdict_for(findings: list[Finding]) -> str:
    """FR-004: BLOCK dominates WARNING dominates PASS."""
    if any(finding.severity == "BLOCK" for finding in findings):
        return "BLOCK"
    if any(finding.severity == "WARNING" for finding in findings):
        return "WARNING"
    return "PASS"
