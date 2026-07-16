"""The Authorization Gateway (Phase 4.3.6 §21, §22).

Every internal module — REST dependency, explicit check endpoint, background
worker, workflow node, scheduled job, agent runtime, integration surface —
calls ``AuthorizationGateway.authorize*``. Nothing calls RBAC, resource
authorization or ABAC directly anymore.

The gateway walks the §9 pipeline in its fixed order:

    AUTHENTICATION → IDENTITY_CONTEXT → SESSION_VALIDATION →
    ORGANIZATION_CONTEXT → RBAC → RESOURCE_AUTHORIZATION → ABAC →
    OBLIGATIONS → AUDIT → CACHE

and returns one normalized ``GatewayDecision`` (§17). It is a policy decision
point: it never executes the business action (enforcement points do), and it
never grants what the baseline denied (default deny, §36).
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from app.authorization.middleware.audit import AuthorizationAuditService
from app.authorization.middleware.cache import DecisionCacheService
from app.authorization.middleware.context import (
    AuthorizationContext,
    AuthorizationContextBuilder,
)
from app.authorization.middleware.metrics import PipelineMetricsService
from app.authorization.middleware.obligations import ObligationExecutor, ObligationOutcome
from app.authorization.middleware.pipeline import AuthorizationPipeline as P
from app.authorization.middleware.pipeline import DecisionTraceService
from app.models.user import User

_OK, _FAIL, _SKIP = "✓", "✗", "-"


@dataclass
class GatewayDecision:
    """§17 — the one decision object every enforcement point receives."""

    allowed: bool
    decision: str  # ALLOW / DENY / REQUIRE_* / MASK_FIELDS / LIMIT_ACTION
    reason: str
    permission: str
    matched_policies: list[dict] = field(default_factory=list)
    obligations: list[dict] = field(default_factory=list)
    obligation_outcome: ObligationOutcome | None = None
    scope: str | None = None
    source_role: str | None = None
    events: list[str] = field(default_factory=list)
    pipeline_trace: list[dict] = field(default_factory=list)
    request_id: str | None = None
    correlation_id: str | None = None
    evaluation_time_ms: float = 0.0
    cache_hit: bool = False
    baseline_source: str = "RBAC"  # RBAC / RESOURCE
    context: AuthorizationContext | None = None

    def as_payload(self) -> dict[str, Any]:
        """Cacheable/serializable form (no live ORM or context references)."""
        return {
            "allowed": self.allowed, "decision": self.decision, "reason": self.reason,
            "permission": self.permission, "matched_policies": self.matched_policies,
            "obligations": self.obligations, "scope": self.scope,
            "source_role": self.source_role, "events": self.events,
            "pipeline_trace": self.pipeline_trace,
            "evaluation_time_ms": self.evaluation_time_ms,
            "baseline_source": self.baseline_source,
        }


class AuthorizationGateway:
    """§22 — coordinates RBAC, resource authorization, ABAC, obligations,
    audit, caching and metrics behind one call."""

    def __init__(self, db: Session) -> None:
        self.db = db

    # ------------------------------------------------------------------ #
    # Users (REST dependency, /check, workers, workflow, scheduled jobs)
    # ------------------------------------------------------------------ #
    def authorize(
        self,
        user: User,
        permission: str,
        *,
        resource_type: str | None = None,
        resource_id: uuid.UUID | None = None,
        context: dict[str, Any] | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
        request_id: str | None = None,
        correlation_id: str | None = None,
        session_id: str | None = None,
        source: str = "API",
        justification: str | None = None,
        use_cache: bool = True,
        record_decision: bool = True,
        force_record: bool = False,
        audit_events: bool = True,
        session_validated: bool = True,
    ) -> GatewayDecision:
        """Authorize a *user* principal. ``session_validated`` is True on HTTP
        paths (get_current_user already enforced the session, §10/§11) and
        False for background sources, where the session stage is N/A (§28)."""
        started = time.perf_counter()
        ctx = AuthorizationContextBuilder(self.db).build(
            identity_id=user.id, identity_kind="USER",
            organization_id=user.organization_id, permission=permission,
            resource_type=resource_type, resource_id=resource_id,
            session_id=session_id, ip_address=ip_address, user_agent=user_agent,
            source=source, attributes=context, justification=justification,
            request_id=request_id, correlation_id=correlation_id,
        )
        trace = DecisionTraceService()
        trace.record(P.AUTHENTICATION, _OK, "verified upstream")
        # IDENTITY_CONTEXT — the account itself must still be usable (§11).
        if not user.is_active:
            trace.record(P.IDENTITY_CONTEXT, _FAIL, "account disabled")
            return self._finish_denied(ctx, trace, started, "Account is disabled.",
                                       audit_events=audit_events)
        trace.record(P.IDENTITY_CONTEXT, _OK)
        trace.record(P.SESSION_VALIDATION, _OK if session_validated else _SKIP,
                     None if session_validated else f"no session for {source}")

        # Decision cache (§19): only for static contexts — dynamic context or a
        # justification changes the evaluation and must never be replayed.
        cacheable = use_cache and not context and not justification
        key_parts = self._cache_key_parts(user, permission, resource_type, resource_id)
        if cacheable:
            cached = DecisionCacheService.get(**key_parts)
            if cached is not None:
                decision = self._from_payload(cached, ctx)
                decision.cache_hit = True
                decision.evaluation_time_ms = round(
                    (time.perf_counter() - started) * 1000, 3)
                PipelineMetricsService.observe(decision=decision.decision,
                                               latency_ms=decision.evaluation_time_ms)
                return decision

        if audit_events:
            AuthorizationAuditService(self.db).started(ctx)

        decision = self._evaluate(user, ctx, trace)
        decision.evaluation_time_ms = round((time.perf_counter() - started) * 1000, 3)

        self._audit_and_record(user, ctx, decision, trace,
                               record_decision=record_decision,
                               force_record=force_record,
                               audit_events=audit_events)
        if cacheable:
            DecisionCacheService.put(decision.as_payload(), **key_parts)
            trace.record(P.CACHE, _OK, "stored")
        else:
            trace.record(P.CACHE, _SKIP, "dynamic context")
        decision.pipeline_trace = trace.trace.as_list()
        PipelineMetricsService.observe(decision=decision.decision,
                                       latency_ms=decision.evaluation_time_ms)
        return decision

    # ------------------------------------------------------------------ #
    # Background principals (§28, §30): workers, schedulers, workflow nodes.
    # ------------------------------------------------------------------ #
    def authorize_background(
        self,
        principal_id: uuid.UUID,
        permission: str,
        *,
        source: str = "WORKER",  # WORKER / SCHEDULER / WORKFLOW
        job_name: str | None = None,
        resource_type: str | None = None,
        resource_id: uuid.UUID | None = None,
        context: dict[str, Any] | None = None,
        request_id: str | None = None,
        correlation_id: str | None = None,
    ) -> GatewayDecision:
        """Authorize a background execution on behalf of a stored principal.
        There is no HTTP session; identity/account state is still enforced."""
        user = self.db.get(User, principal_id)
        if user is None:
            ctx = AuthorizationContextBuilder(self.db).build(
                identity_id=principal_id, identity_kind="SYSTEM",
                organization_id=None, permission=permission, source=source,
                request_id=request_id, correlation_id=correlation_id,
            )
            trace = DecisionTraceService()
            trace.record(P.AUTHENTICATION, _FAIL, "unknown principal")
            return self._finish_denied(ctx, trace, time.perf_counter(),
                                       "Unknown background principal.",
                                       audit_events=False)
        job_context = dict(context or {})
        return self.authorize(
            user, permission,
            resource_type=resource_type, resource_id=resource_id,
            context=job_context or None, source=source,
            request_id=request_id or (f"{source.lower()}:{job_name}" if job_name else None),
            correlation_id=correlation_id,
            session_validated=False, use_cache=not job_context,
        )

    # ------------------------------------------------------------------ #
    # Agent principals (§29, §31): AI runtime and API-key integrations.
    # ------------------------------------------------------------------ #
    def authorize_agent(
        self,
        agent,
        action: str,
        *,
        ai_context: dict[str, Any] | None = None,
        ip_address: str | None = None,
        request_id: str | None = None,
        correlation_id: str | None = None,
        audit_events: bool = True,
    ) -> GatewayDecision:
        """ABAC layer for the agent runtime. The Phase-2 governance pipeline
        (agent permission → risk → policy) is the agent baseline; this applies
        the context-aware layer on top — deny wins, approval routes to the
        human-review queue (§29)."""
        from app.authorization.abac.engine import ABACEngine

        started = time.perf_counter()
        ctx = AuthorizationContextBuilder(self.db).build(
            identity_id=agent.id, identity_kind="AGENT",
            organization_id=agent.organization_id, permission=action,
            source="AGENT", attributes=ai_context,
            ip_address=ip_address, request_id=request_id,
            correlation_id=correlation_id,
        )
        trace = DecisionTraceService()
        trace.record(P.AUTHENTICATION, _OK, "api key verified upstream")
        trace.record(P.IDENTITY_CONTEXT, _OK, "agent")
        trace.record(P.SESSION_VALIDATION, _SKIP, "agents have no session")
        trace.record(P.ORGANIZATION_CONTEXT, _OK)
        trace.record(P.RBAC, _SKIP, "agent baseline decided by governance pipeline")
        trace.record(P.RESOURCE_AUTHORIZATION, _SKIP)

        if audit_events:
            AuthorizationAuditService(self.db).started(ctx)
        abac = ABACEngine(self.db).evaluate_for_agent(
            agent, action, ai_context=dict(ctx.attributes),
            ip_address=ip_address, request_id=ctx.request_id,
            correlation_id=ctx.correlation_id,
        )
        trace.record(P.ABAC, _OK if abac.allowed or not abac.applicable else _FAIL,
                     abac.decision)
        outcome = ObligationExecutor(self.db).execute(
            abac.obligations, organization_id=agent.organization_id,
            identity_id=agent.id, identity_kind="AGENT", action=action,
            request_id=ctx.request_id,
        )
        trace.record(P.OBLIGATIONS, _OK if abac.obligations else _SKIP)

        decision = GatewayDecision(
            allowed=abac.allowed or not abac.applicable,
            decision=abac.decision if abac.applicable else "ALLOW",
            reason=abac.reason, permission=action,
            matched_policies=abac.matched_policies, obligations=abac.obligations,
            obligation_outcome=outcome, events=[f"ABAC_{abac.decision}"],
            request_id=ctx.request_id, correlation_id=ctx.correlation_id,
            baseline_source="AGENT_GOVERNANCE", context=ctx,
        )
        decision.evaluation_time_ms = round((time.perf_counter() - started) * 1000, 3)
        if audit_events:
            audit = AuthorizationAuditService(self.db)
            audit.decision_generated(ctx, decision.as_payload(), trace.trace.as_list())
            if abac.obligations:
                audit.obligations_applied(ctx, abac.obligations)
            if decision.allowed:
                audit.completed(ctx, decision.as_payload())
            else:
                audit.failed(ctx, decision.as_payload())
        trace.record(P.AUDIT, _OK if audit_events else _SKIP)
        trace.record(P.CACHE, _SKIP, "agent decisions are never cached")
        decision.pipeline_trace = trace.trace.as_list()
        PipelineMetricsService.observe(decision=decision.decision,
                                       latency_ms=decision.evaluation_time_ms)
        return decision

    # ------------------------------------------------------------------ #
    # Post-execution hook (§24): enforcement points report completion.
    # ------------------------------------------------------------------ #
    def execution_completed(self, decision: GatewayDecision, *, outcome: str,
                            detail: dict[str, Any] | None = None) -> None:
        if decision.context is not None:
            AuthorizationAuditService(self.db).execution_completed(
                decision.context, outcome=outcome, detail=detail)

    # ------------------------------------------------------------------ #
    # Internals
    # ------------------------------------------------------------------ #
    def _cache_key_parts(self, user: User, permission: str,
                         resource_type: str | None,
                         resource_id: uuid.UUID | None) -> dict:
        from app.authorization.abac.policies import PolicyCache
        from app.authorization.cache import PermissionCacheService

        return {
            "identity_id": user.id, "permission": permission,
            "resource_type": resource_type, "resource_id": resource_id,
            "organization_id": user.organization_id,
            "rbac_version": PermissionCacheService(self.db).current_version(
                user.organization_id),
            "abac_generation": PolicyCache.generation,
        }

    def _evaluate(self, user: User, ctx: AuthorizationContext,
                  trace: DecisionTraceService) -> GatewayDecision:
        """ORGANIZATION_CONTEXT → RBAC/RESOURCE → ABAC → OBLIGATIONS, exactly
        as the 4.3.2–4.3.5 engines defined them, now behind one gateway."""
        from app.authorization.abac.engine import ABACEngine
        from app.authorization.cache import PermissionCacheService
        from app.authorization.engine import (
            GLOBAL_WILDCARD,
            PermissionEngine,
            ResourceContext,
        )
        from app.authorization.hierarchy.services import (
            DelegationService,
            ResourceOwnershipService,
        )
        from app.authorization.resources.services import (
            ResourceAuthorizationService,
            ResourceRegistryService,
        )

        events: list[str] = []
        registered = None
        allowed: bool
        reason: str
        scope = None
        source_role = None
        baseline_source = "RBAC"

        # RESOURCE_AUTHORIZATION (4.3.4 §18): registered resources run the full
        # per-resource chain, which embeds the role decision.
        if ctx.resource_type and ctx.resource_id:
            registered = ResourceRegistryService(self.db).by_external(
                ctx.resource_type, ctx.resource_id)
        if registered is not None:
            trace.record(P.ORGANIZATION_CONTEXT, _OK, "resource registry")
            rd = ResourceAuthorizationService(self.db).authorize(
                user, ctx.permission, registered, record=False)
            allowed, reason = rd.allowed, rd.reason
            scope, source_role = rd.scope, rd.source_role
            events = list(rd.steps)
            baseline_source = "RESOURCE"
            trace.record(P.RBAC, _OK, "embedded in resource chain")
            trace.record(P.RESOURCE_AUTHORIZATION, _OK if rd.allowed else _FAIL)
        else:
            # ORGANIZATION_CONTEXT (4.3.3 §7/§9/§14): resolve the resource's
            # organizational path and enforce cross-org isolation.
            res_ctx = None
            if ctx.resource_type and ctx.resource_id:
                path = ResourceOwnershipService(self.db).resolve_path(
                    ctx.resource_type, ctx.resource_id)
                res_ctx = ResourceContext(
                    organization_id=(path or {}).get("organization_id")
                    or user.organization_id,
                    business_unit_id=(path or {}).get("business_unit_id"),
                    department_id=(path or {}).get("department_id"),
                    team_id=(path or {}).get("team_id"),
                    project_id=(path or {}).get("project_id"),
                    resource_type=ctx.resource_type, resource_id=ctx.resource_id,
                )
            elif ctx.resource_type or ctx.resource_id:
                res_ctx = ResourceContext(
                    organization_id=user.organization_id,
                    resource_type=ctx.resource_type, resource_id=ctx.resource_id,
                )
            grants, cache_hit = PermissionCacheService(self.db).get_grants(user)
            isolation_denied = False
            if (res_ctx is not None and res_ctx.organization_id
                    and res_ctx.organization_id != user.organization_id):
                has_star = any(g.pattern == GLOBAL_WILDCARD for g in grants)
                delegated = any(
                    d.organization_id == res_ctx.organization_id
                    for d in DelegationService(self.db).active_for_user(user.id)
                )
                isolation_denied = not (has_star or delegated)
            trace.record(P.ORGANIZATION_CONTEXT,
                         _FAIL if isolation_denied else _OK)
            if isolation_denied:
                allowed, reason = False, "Cross-organization access denied"
                events = ["CROSS_ORG_DENIED"]
                trace.record(P.RBAC, _SKIP)
            else:
                result = PermissionEngine(self.db).evaluate(
                    user, ctx.permission, grants, res_ctx)
                allowed, reason = result.allowed, result.reason
                scope, source_role = result.scope, result.source_role
                events = list(result.trace)
                if not cache_hit:
                    events.insert(0, "PERMISSION_CACHE_REFRESHED")
                trace.record(P.RBAC, _OK if allowed else _FAIL)
            trace.record(P.RESOURCE_AUTHORIZATION, _SKIP, "unregistered resource")

        decision_name = "ALLOW" if allowed else "DENY"
        matched: list[dict] = []
        obligations: list[dict] = []

        # ABAC (4.3.5 §4/§25): baseline deny is final; baseline allow may be
        # denied, challenged or constrained. NOT_APPLICABLE keeps the baseline.
        if allowed:
            try:
                abac = ABACEngine(self.db).evaluate(
                    user, ctx.permission, registered,
                    overrides=dict(ctx.attributes) or None,
                    ip_address=ctx.ip_address, request_id=ctx.request_id,
                    correlation_id=ctx.correlation_id,
                    record_applicable_only=True,
                )
            except Exception:
                # Fail closed (§36): an evaluation error never becomes an allow.
                PipelineMetricsService.policy_error()
                trace.record(P.ABAC, _FAIL, "evaluation error")
                allowed, decision_name = False, "DENY"
                reason = "Authorization could not be evaluated."
                events.append("ABAC_ERROR")
            else:
                if abac.applicable:
                    decision_name = abac.decision
                    matched = abac.matched_policies
                    obligations = abac.obligations
                    events.append(f"ABAC_{abac.decision}")
                    if abac.decision == "REQUIRE_JUSTIFICATION" and ctx.justification:
                        # The challenge is satisfied in-band (§16); keep the
                        # obligation in the response so the audit shows it.
                        decision_name = "ALLOW"
                        allowed = True
                        reason = abac.reason + " Justification provided."
                        events.append("JUSTIFICATION_ACCEPTED")
                    elif not abac.allowed:
                        allowed = False
                        reason = abac.reason
                    trace.record(P.ABAC, _OK if allowed else _FAIL, abac.decision)
                else:
                    trace.record(P.ABAC, _SKIP, "no applicable policy")
        else:
            trace.record(P.ABAC, _SKIP, "baseline denied")

        outcome = ObligationExecutor(self.db).execute(
            obligations, organization_id=user.organization_id,
            identity_id=user.id, identity_kind="USER",
            action=ctx.action, request_id=ctx.request_id,
        ) if obligations else None
        trace.record(P.OBLIGATIONS, _OK if obligations else _SKIP)

        return GatewayDecision(
            allowed=allowed, decision=decision_name, reason=reason,
            permission=ctx.permission, matched_policies=matched,
            obligations=obligations, obligation_outcome=outcome,
            scope=scope, source_role=source_role, events=events,
            request_id=ctx.request_id, correlation_id=ctx.correlation_id,
            baseline_source=baseline_source, context=ctx,
        )

    def _audit_and_record(self, user: User, ctx: AuthorizationContext,
                          decision: GatewayDecision, trace: DecisionTraceService,
                          *, record_decision: bool, force_record: bool,
                          audit_events: bool) -> None:
        from app.authorization.decisions import AuthorizationDecisionService
        from app.authorization.engine import AuthorizationResult

        if audit_events:
            audit = AuthorizationAuditService(self.db)
            audit.decision_generated(ctx, decision.as_payload(),
                                     trace.trace.as_list())
            if decision.obligations:
                audit.obligations_applied(ctx, decision.obligations)
            if decision.allowed:
                audit.completed(ctx, decision.as_payload())
            else:
                audit.failed(ctx, decision.as_payload())
            self._commit_audit()
        trace.record(P.AUDIT, _OK if audit_events else _SKIP)

        if record_decision:
            result = AuthorizationResult(
                allowed=decision.allowed, permission=decision.permission,
                reason=decision.reason, scope=decision.scope,
                source_role=decision.source_role,
                evaluation_time_ms=decision.evaluation_time_ms,
                resource_type=ctx.resource_type,
                resource_id=ctx.resource_id, trace=decision.events,
            )
            AuthorizationDecisionService(self.db).record(
                user, result, request_id=ctx.request_id,
                evaluation_time_ms=decision.evaluation_time_ms,
                force=force_record or not decision.allowed or ctx.source != "API",
            )

    def _commit_audit(self) -> None:
        """Persist staged pipeline audit events. The gateway runs before the
        business handler (dependency phase / pre-execution), so nothing else is
        staged yet; a read-only request would otherwise drop the events when
        its session closes without a commit. Best-effort — an audit write
        failure must never break authorization itself (it fails *closed* only
        for decisions, never open)."""
        try:
            self.db.commit()
        except Exception:
            self.db.rollback()

    def _finish_denied(self, ctx: AuthorizationContext, trace: DecisionTraceService,
                       started: float, reason: str, *,
                       audit_events: bool) -> GatewayDecision:
        decision = GatewayDecision(
            allowed=False, decision="DENY", reason=reason,
            permission=ctx.permission, request_id=ctx.request_id,
            correlation_id=ctx.correlation_id, context=ctx,
            evaluation_time_ms=round((time.perf_counter() - started) * 1000, 3),
        )
        if audit_events:
            AuthorizationAuditService(self.db).failed(ctx, decision.as_payload())
        decision.pipeline_trace = trace.trace.as_list()
        PipelineMetricsService.observe(decision="DENY",
                                       latency_ms=decision.evaluation_time_ms)
        return decision

    @staticmethod
    def _from_payload(payload: dict[str, Any],
                      ctx: AuthorizationContext) -> GatewayDecision:
        # Events describing the *original* evaluation's cache state don't apply
        # to this replayed request.
        events = [e for e in payload.get("events", [])
                  if e != "PERMISSION_CACHE_REFRESHED"]
        return GatewayDecision(
            allowed=payload["allowed"], decision=payload["decision"],
            reason=payload["reason"], permission=payload["permission"],
            matched_policies=payload.get("matched_policies", []),
            obligations=payload.get("obligations", []),
            scope=payload.get("scope"), source_role=payload.get("source_role"),
            events=events,
            pipeline_trace=payload.get("pipeline_trace", []),
            request_id=ctx.request_id, correlation_id=ctx.correlation_id,
            baseline_source=payload.get("baseline_source", "RBAC"), context=ctx,
        )
