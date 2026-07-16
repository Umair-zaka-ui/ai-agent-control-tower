"""The ABAC engine (Phase 4.3.5 §13–§17, §23–§26, §43).

``ABACEngine.evaluate`` runs the §17 flow: build attribute context → resolve
applicable policies → evaluate conditions → combine effects → generate
obligations → build the explanation → audit → return one normalized decision.

The engine is a *policy decision point*: it never executes business operations
(§26). Obligations are returned to the enforcement point (route dependency,
service command, agent gateway) which acts on them.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from app.authorization.abac.attributes import (
    AttributeContextBuilder,
    AttributeRegistryService,
    AuthorizationAttributeContext,
)
from app.authorization.abac.conditions import ConditionEvaluator, ConditionTrace
from app.authorization.abac.enums import (
    ABACAuditEvent,
    ABACDecision,
    CHALLENGE_EFFECTS,
    CombiningAlgorithm,
    PolicyEffect,
)
from app.authorization.abac.policies import PolicyResolver, record_abac_event
from app.models.abac import ABACEvaluation
from app.models.resource_authorization import ProtectedResource
from app.models.user import User

_REDACTED = "[REDACTED]"

# Challenge severity: approval > MFA > justification (§13 precedence).
_CHALLENGE_ORDER = [
    PolicyEffect.REQUIRE_APPROVAL.value,
    PolicyEffect.REQUIRE_MFA.value,
    PolicyEffect.REQUIRE_JUSTIFICATION.value,
]


# --------------------------------------------------------------------------- #
# Metrics (§43) — in-process counters, exposed via the metrics endpoint.
# --------------------------------------------------------------------------- #
class ABACMetrics:
    counters: dict[str, int] = {
        "abac_evaluations_total": 0,
        "abac_allows_total": 0,
        "abac_denies_total": 0,
        "abac_challenges_total": 0,
        "abac_policy_matches_total": 0,
        "abac_policy_errors_total": 0,
        "abac_missing_attributes_total": 0,
        "abac_obligations_total": 0,
    }
    latencies_ms: list[float] = []

    @classmethod
    def observe(cls, *, decision: str, matched: int, missing: int, obligations: int,
                latency_ms: float) -> None:
        cls.counters["abac_evaluations_total"] += 1
        cls.counters["abac_policy_matches_total"] += matched
        cls.counters["abac_missing_attributes_total"] += missing
        cls.counters["abac_obligations_total"] += obligations
        if decision == ABACDecision.ALLOW.value:
            cls.counters["abac_allows_total"] += 1
        elif decision == ABACDecision.DENY.value:
            cls.counters["abac_denies_total"] += 1
        elif decision in CHALLENGE_EFFECTS:
            cls.counters["abac_challenges_total"] += 1
        cls.latencies_ms.append(latency_ms)
        if len(cls.latencies_ms) > 1000:
            del cls.latencies_ms[: len(cls.latencies_ms) - 1000]

    @classmethod
    def snapshot(cls) -> dict:
        from app.authorization.abac.policies import PolicyCache

        lat = cls.latencies_ms
        total_cache = PolicyCache.hits + PolicyCache.misses
        return {
            **cls.counters,
            "abac_evaluation_latency_ms": round(sum(lat) / len(lat), 3) if lat else 0.0,
            "abac_cache_hit_ratio": round(PolicyCache.hits / total_cache, 3) if total_cache else 0.0,
        }

    @classmethod
    def reset(cls) -> None:
        for key in cls.counters:
            cls.counters[key] = 0
        cls.latencies_ms.clear()


# --------------------------------------------------------------------------- #
# Combining algorithms (§13, §24)
# --------------------------------------------------------------------------- #
@dataclass
class MatchedPolicy:
    policy: dict
    trace: ConditionTrace


class CombiningAlgorithmService:
    """Resolves the final effect from the matched policies. ``LOG_ONLY``
    matches are observations only — they never change the decision (§8)."""

    @classmethod
    def combine(cls, matched: list[MatchedPolicy], algorithm: str) -> tuple[str, dict | None]:
        """Returns (winning effect, winning policy dict | None). ``matched``
        arrives already sorted by scope precedence + priority."""
        deciding = [m for m in matched if m.policy["effect"] != PolicyEffect.LOG_ONLY.value]
        if not deciding:
            return ABACDecision.NOT_APPLICABLE.value, None

        if algorithm == CombiningAlgorithm.FIRST_APPLICABLE.value:
            first = deciding[0]
            return first.policy["effect"], first.policy

        if algorithm == CombiningAlgorithm.HIGHEST_PRIORITY.value:
            top = max(deciding, key=lambda m: m.policy["priority"])
            ties = [m for m in deciding if m.policy["priority"] == top.policy["priority"]]
            return cls._deny_overrides(ties)

        if algorithm == CombiningAlgorithm.ALL_MUST_ALLOW.value:
            if all(m.policy["effect"] == PolicyEffect.ALLOW.value for m in deciding):
                allow = deciding[0]
                return PolicyEffect.ALLOW.value, allow.policy
            non_allow = next(m for m in deciding
                             if m.policy["effect"] != PolicyEffect.ALLOW.value)
            if non_allow.policy["effect"] == PolicyEffect.DENY.value:
                return PolicyEffect.DENY.value, non_allow.policy
            return non_allow.policy["effect"], non_allow.policy

        if algorithm == CombiningAlgorithm.ALLOW_OVERRIDES.value:
            allow = next((m for m in deciding if m.policy["effect"] == PolicyEffect.ALLOW.value), None)
            if allow is not None:
                return PolicyEffect.ALLOW.value, allow.policy
            return cls._deny_overrides(deciding)

        # Default: DENY_OVERRIDES (§13).
        return cls._deny_overrides(deciding)

    @classmethod
    def _deny_overrides(cls, deciding: list[MatchedPolicy]) -> tuple[str, dict | None]:
        """§13 precedence: deny → challenge (approval > MFA > justification) →
        constraint (mask/limit) → allow."""
        deny = next((m for m in deciding if m.policy["effect"] == PolicyEffect.DENY.value), None)
        if deny is not None:
            return PolicyEffect.DENY.value, deny.policy
        for effect in _CHALLENGE_ORDER:
            challenge = next((m for m in deciding if m.policy["effect"] == effect), None)
            if challenge is not None:
                return effect, challenge.policy
        constraint = next((m for m in deciding if m.policy["effect"] in (
            PolicyEffect.MASK_FIELDS.value, PolicyEffect.LIMIT_ACTION.value)), None)
        if constraint is not None:
            return constraint.policy["effect"], constraint.policy
        allow = next((m for m in deciding if m.policy["effect"] == PolicyEffect.ALLOW.value), None)
        if allow is not None:
            return PolicyEffect.ALLOW.value, allow.policy
        return ABACDecision.NOT_APPLICABLE.value, None


# --------------------------------------------------------------------------- #
# Obligations (§8, §15, §24)
# --------------------------------------------------------------------------- #
class ObligationService:
    """Normalizes the winning policy's obligations for the enforcement point.
    The engine returns them; it never performs them (§26)."""

    @staticmethod
    def build(effect: str, matched: list[MatchedPolicy]) -> list[dict]:
        obligations: list[dict] = []
        for m in matched:
            p_effect, extra = m.policy["effect"], m.policy.get("obligations") or {}
            if p_effect == PolicyEffect.REQUIRE_APPROVAL.value:
                obligations.append({
                    "type": "CREATE_APPROVAL",
                    "priority": extra.get("priority", "HIGH"),
                    "reviewer_role": extra.get("reviewer_role"),
                    "policy_id": m.policy["id"],
                })
            elif p_effect == PolicyEffect.REQUIRE_MFA.value:
                obligations.append({"type": "REQUIRE_MFA", "policy_id": m.policy["id"]})
            elif p_effect == PolicyEffect.REQUIRE_JUSTIFICATION.value:
                obligations.append({"type": "REQUIRE_JUSTIFICATION", "policy_id": m.policy["id"]})
            elif p_effect == PolicyEffect.MASK_FIELDS.value:
                obligations.append({
                    "type": "MASK_FIELDS", "fields": extra.get("fields", []),
                    "policy_id": m.policy["id"],
                })
            elif p_effect == PolicyEffect.LIMIT_ACTION.value:
                obligations.append({
                    "type": "LIMIT_ACTION",
                    "limits": {k: v for k, v in extra.items() if k != "fields"},
                    "policy_id": m.policy["id"],
                })
            elif p_effect == PolicyEffect.LOG_ONLY.value:
                obligations.append({"type": "LOG_ONLY", "policy_id": m.policy["id"]})
        # A DENY renders challenge/constraint obligations moot (§14).
        if effect == PolicyEffect.DENY.value:
            obligations = [o for o in obligations if o["type"] == "LOG_ONLY"]
        return obligations


# --------------------------------------------------------------------------- #
# Explanation (§15, §16, §24)
# --------------------------------------------------------------------------- #
class DecisionExplanationService:
    def __init__(self, db: Session) -> None:
        self.registry = AttributeRegistryService(db)

    def build(self, *, considered: list[dict], matched: list[MatchedPolicy],
              winning_effect: str, winning: dict | None, decision: str,
              missing_attributes: list[str]) -> tuple[dict, str]:
        """Returns (explanation object, human-readable reason). RESTRICTED
        attribute values are redacted from the user-facing parts (§16)."""
        sensitive = {
            d.name for d in self.registry.list() if d.sensitivity == "RESTRICTED"
        }

        def redact(entry: dict) -> dict:
            if entry["attribute"] in sensitive:
                return {**entry, "expected": _REDACTED}
            return entry

        matched_out = [{
            "policy_id": m.policy["id"], "name": m.policy["name"],
            "effect": m.policy["effect"], "priority": m.policy["priority"],
            "conditions": [redact(r) for r in m.trace.results],
        } for m in matched]

        reason = self._reason(decision, winning)
        explanation = {
            "considered_policies": [
                {"policy_id": p["id"], "name": p["name"], "effect": p["effect"]}
                for p in considered
            ],
            "matched_policies": matched_out,
            "winning_effect": winning_effect,
            "winning_policy_id": winning["id"] if winning else None,
            "missing_attributes": missing_attributes,
            "decision": decision,
            "reason": reason,
        }
        return explanation, reason

    @staticmethod
    def _reason(decision: str, winning: dict | None) -> str:
        name = winning["name"] if winning else None
        if decision == ABACDecision.DENY.value:
            return f"Denied by policy '{name}'."
        if decision == ABACDecision.REQUIRE_APPROVAL.value:
            return f"Policy '{name}' requires human approval."
        if decision == ABACDecision.REQUIRE_MFA.value:
            return f"Policy '{name}' requires stronger authentication."
        if decision == ABACDecision.REQUIRE_JUSTIFICATION.value:
            return f"Policy '{name}' requires a justification."
        if decision == ABACDecision.MASK_FIELDS.value:
            return f"Allowed with field masking by policy '{name}'."
        if decision == ABACDecision.LIMIT_ACTION.value:
            return f"Allowed with limits by policy '{name}'."
        if decision == ABACDecision.ALLOW.value:
            return f"Allowed by policy '{name}'." if name else "Allowed."
        return "No applicable ABAC policy; the baseline decision applies."


# --------------------------------------------------------------------------- #
# The engine (§17, §24)
# --------------------------------------------------------------------------- #
@dataclass
class ABACResult:
    decision: str
    allowed: bool
    reason: str
    matched_policies: list[dict] = field(default_factory=list)
    obligations: list[dict] = field(default_factory=list)
    explanation: dict = field(default_factory=dict)
    evaluation_time_ms: float = 0.0
    request_id: str | None = None
    applicable: bool = True  # False = NOT_APPLICABLE → baseline decision stands


class ABACEngine:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.resolver = PolicyResolver(db)
        self.explainer = DecisionExplanationService(db)

    def evaluate(
        self,
        user: User,
        action: str,
        resource: ProtectedResource | None = None,
        *,
        overrides: dict[str, Any] | None = None,
        ip_address: str | None = None,
        request_id: str | None = None,
        correlation_id: str | None = None,
        record: bool = True,
        record_applicable_only: bool = False,
        audit_event_meta: dict | None = None,
        allow_subject_overrides: bool = False,
    ) -> ABACResult:
        started = time.perf_counter()
        # §40 — subject attributes always come from the server-side provider; a
        # caller-supplied context can never spoof identity.* (the permission-
        # gated simulator is the only place that may).
        if overrides and not allow_subject_overrides:
            overrides = {k: v for k, v in overrides.items() if not k.startswith("identity.")}
        try:
            ctx = AttributeContextBuilder(self.db).build(
                user, action, resource, ip_address=ip_address,
                request_id=request_id, correlation_id=correlation_id, overrides=overrides,
            )
            result = self._evaluate_context(user, action, ctx, request_id=request_id)
        except Exception:
            ABACMetrics.counters["abac_policy_errors_total"] += 1
            raise
        result.evaluation_time_ms = round((time.perf_counter() - started) * 1000, 3)

        missing = len(result.explanation.get("missing_attributes", []))
        ABACMetrics.observe(decision=result.decision, matched=len(result.matched_policies),
                            missing=missing, obligations=len(result.obligations),
                            latency_ms=result.evaluation_time_ms)
        # 4.3.6 hot path: the per-route gate evaluates ABAC on every request —
        # recording NOT_APPLICABLE outcomes there would flood the evaluation log.
        if record and not (record_applicable_only and not result.applicable):
            self._record(user, action, resource, result, correlation_id, audit_event_meta)
        return result

    def evaluate_for_agent(
        self,
        agent,
        action: str,
        *,
        ai_context: dict[str, Any] | None = None,
        ip_address: str | None = None,
        request_id: str | None = None,
        correlation_id: str | None = None,
        record: bool = True,
    ) -> ABACResult:
        """Phase 4.3.6 §29 — evaluate policies for an *agent* principal.

        Subject attributes are built server-side from the agent row
        (identity.type = AI_AGENT); ``ai_context`` may only contribute ``ai.*``
        and ``environment.*`` keys, so an agent request can never spoof its own
        identity any more than a user request can.
        """
        from app.authorization.abac.attributes import (
            ActionAttributeProvider,
            EnvironmentAttributeProvider,
        )

        started = time.perf_counter()
        subject = {
            "identity.id": str(agent.id),
            "identity.type": "AI_AGENT",
            "identity.status": getattr(agent.status, "value", agent.status),
            "identity.organization_id": str(agent.organization_id),
        }
        ai_attrs = {"ai.agent_id": str(agent.id)}
        env_extra: dict[str, Any] = {}
        for name, value in (ai_context or {}).items():
            if name.startswith("ai."):
                ai_attrs[name] = value
            elif name.startswith("environment."):
                env_extra[name] = value
        environment = EnvironmentAttributeProvider().collect(
            ip_address=ip_address, request_id=request_id, correlation_id=correlation_id
        )
        environment.update(env_extra)
        ctx = AuthorizationAttributeContext(
            subject=subject,
            action=ActionAttributeProvider().collect(action),
            environment=environment,
            ai=ai_attrs,
        )
        try:
            result = self._evaluate_flat(
                subject_id=agent.id, organization_id=agent.organization_id,
                ctx=ctx, request_id=request_id,
            )
        except Exception:
            ABACMetrics.counters["abac_policy_errors_total"] += 1
            raise
        result.evaluation_time_ms = round((time.perf_counter() - started) * 1000, 3)
        missing = len(result.explanation.get("missing_attributes", []))
        ABACMetrics.observe(decision=result.decision, matched=len(result.matched_policies),
                            missing=missing, obligations=len(result.obligations),
                            latency_ms=result.evaluation_time_ms)
        if record and result.applicable:
            self.db.add(ABACEvaluation(
                organization_id=agent.organization_id, identity_id=agent.id,
                resource_type="AI_AGENT", resource_id=agent.id, action=action,
                decision=result.decision,
                matched_policy_ids=[m["policy_id"] for m in result.matched_policies],
                obligations=result.obligations, explanation=result.explanation,
                evaluation_time_ms=result.evaluation_time_ms,
                request_id=request_id, correlation_id=correlation_id,
            ))
            self.db.flush()
        return result

    def _evaluate_context(self, user: User, action: str,
                          ctx: AuthorizationAttributeContext, *,
                          request_id: str | None) -> ABACResult:
        return self._evaluate_flat(subject_id=user.id,
                                   organization_id=user.organization_id,
                                   ctx=ctx, request_id=request_id)

    def _evaluate_flat(self, *, subject_id, organization_id,
                       ctx: AuthorizationAttributeContext,
                       request_id: str | None) -> ABACResult:
        flat = ctx.flat()
        considered = self.resolver.resolve(organization_id, flat, subject_id=subject_id)

        matched: list[MatchedPolicy] = []
        missing: list[str] = []
        for p in considered:
            ok, trace = ConditionEvaluator.evaluate(p["conditions"], flat)
            missing.extend(a for a in trace.missing_attributes if a not in missing)
            if ok:
                matched.append(MatchedPolicy(policy=p, trace=trace))

        algorithm = (matched[0].policy["combining_algorithm"]
                     if matched else CombiningAlgorithm.DENY_OVERRIDES.value)
        effect, winning = CombiningAlgorithmService.combine(matched, algorithm)

        decision = effect
        allowed = effect in (PolicyEffect.ALLOW.value, PolicyEffect.MASK_FIELDS.value,
                             PolicyEffect.LIMIT_ACTION.value)
        applicable = effect != ABACDecision.NOT_APPLICABLE.value

        obligations = ObligationService.build(effect, matched) if matched else []
        explanation, reason = self.explainer.build(
            considered=considered, matched=matched, winning_effect=effect,
            winning=winning, decision=decision, missing_attributes=missing,
        )
        return ABACResult(
            decision=decision, allowed=allowed, reason=reason,
            matched_policies=[{
                "policy_id": m.policy["id"], "name": m.policy["name"],
                "effect": m.policy["effect"], "priority": m.policy["priority"],
            } for m in matched],
            obligations=obligations, explanation=explanation,
            request_id=request_id, applicable=applicable,
        )

    def _record(self, user: User, action: str, resource: ProtectedResource | None,
                result: ABACResult, correlation_id: str | None,
                audit_event_meta: dict | None) -> None:
        self.db.add(ABACEvaluation(
            organization_id=user.organization_id, identity_id=user.id,
            resource_type=resource.resource_type if resource else None,
            resource_id=resource.resource_id if resource else None,
            action=action, decision=result.decision,
            matched_policy_ids=[m["policy_id"] for m in result.matched_policies],
            obligations=result.obligations, explanation=result.explanation,
            evaluation_time_ms=result.evaluation_time_ms,
            request_id=result.request_id, correlation_id=correlation_id,
        ))
        self.db.flush()

        if not result.applicable:
            return
        event = (ABACAuditEvent.ABAC_APPROVAL_REQUIRED
                 if result.decision == ABACDecision.REQUIRE_APPROVAL.value
                 else ABACAuditEvent.ABAC_ACCESS_ALLOWED if result.allowed
                 else ABACAuditEvent.ABAC_ACCESS_DENIED)
        meta = {
            "action": action, "decision": result.decision,
            "matched_policy_ids": [m["policy_id"] for m in result.matched_policies],
            **(audit_event_meta or {}),
        }
        record_abac_event(self.db, event, organization_id=user.organization_id,
                          actor_id=user.id, meta=meta)
        if result.obligations:
            record_abac_event(self.db, ABACAuditEvent.ABAC_OBLIGATION_APPLIED,
                              organization_id=user.organization_id, actor_id=user.id,
                              meta={"action": action,
                                    "obligations": [o["type"] for o in result.obligations]})


# --------------------------------------------------------------------------- #
# Simulation (§24, §35) — read-only; never executes the action.
# --------------------------------------------------------------------------- #
class PolicySimulationService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def simulate(
        self,
        actor: User,
        *,
        subject: User,
        action: str,
        resource: ProtectedResource | None,
        overrides: dict[str, Any] | None,
        draft_policy: dict | None = None,
    ) -> dict:
        """Full-stack what-if: baseline RBAC, resource authorization (when a
        resource is named) and ABAC — none of it recorded as a live decision."""
        from app.authorization.engine import PermissionEngine
        from app.authorization.resources.services import ResourceAuthorizationService

        rbac = PermissionEngine(self.db).authorize(subject, action)
        resource_decision = None
        if resource is not None:
            rd = ResourceAuthorizationService(self.db).authorize(
                subject, action, resource, record=False
            )
            resource_decision = {"allowed": rd.allowed, "reason": rd.reason, "source": rd.source}

        engine = ABACEngine(self.db)
        if draft_policy is not None:
            abac = self._simulate_single(engine, subject, action, resource, overrides, draft_policy)
        else:
            abac = engine.evaluate(subject, action, resource, overrides=overrides,
                                   record=False, allow_subject_overrides=True)

        record_abac_event(self.db, ABACAuditEvent.ABAC_POLICY_SIMULATED,
                          organization_id=actor.organization_id, actor_id=actor.id,
                          meta={"action": action, "subject_id": str(subject.id),
                                "decision": abac.decision})
        return {
            "baseline_rbac": {"allowed": rbac.allowed, "reason": rbac.reason},
            "resource_authorization": resource_decision,
            "abac": abac,
        }

    def _simulate_single(self, engine: ABACEngine, subject: User, action: str,
                         resource: ProtectedResource | None,
                         overrides: dict[str, Any] | None, policy: dict) -> ABACResult:
        """Evaluate one (possibly draft) policy in isolation against the context."""
        ctx = AttributeContextBuilder(self.db).build(subject, action, resource, overrides=overrides)
        flat = ctx.flat()
        ok, trace = ConditionEvaluator.evaluate(policy.get("conditions"), flat)
        p = {
            "id": policy.get("id", "draft"), "name": policy.get("name", "draft"),
            "effect": policy.get("effect", "DENY"), "priority": policy.get("priority", 100),
            "combining_algorithm": policy.get("combining_algorithm", "DENY_OVERRIDES"),
            "obligations": policy.get("obligations") or {},
        }
        matched = [MatchedPolicy(policy=p, trace=trace)] if ok else []
        effect, winning = CombiningAlgorithmService.combine(matched, p["combining_algorithm"])
        obligations = ObligationService.build(effect, matched) if matched else []
        explanation, reason = DecisionExplanationService(self.db).build(
            considered=[p], matched=matched, winning_effect=effect, winning=winning,
            decision=effect, missing_attributes=trace.missing_attributes,
        )
        return ABACResult(
            decision=effect,
            allowed=effect in (PolicyEffect.ALLOW.value, PolicyEffect.MASK_FIELDS.value,
                               PolicyEffect.LIMIT_ACTION.value),
            reason=reason,
            matched_policies=[{"policy_id": p["id"], "name": p["name"],
                               "effect": p["effect"], "priority": p["priority"]}] if ok else [],
            obligations=obligations, explanation=explanation,
        )
