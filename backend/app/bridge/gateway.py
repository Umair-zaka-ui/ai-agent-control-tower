"""Phase 5.7 (M5.7) - ``CapabilityBoundary``: the one place an agent ACT does
not run can reach an enterprise capability, and the one place ACT decides
whether it may.

**This is a boundary, not a second authorizer.** It asks the existing
``AuthorizationGateway`` (``authorize_agent``, the AGENT-principal path the
native runtime already uses), reads the existing Phase 4.3 policies through
``GovernancePolicyService``, and prices the call with the existing Phase 4.4
``BudgetService``. It contains no permission logic, no policy evaluation and
no budget arithmetic of its own -- ``test_ac11_*`` asserts that structurally.
What it adds is a *bound*: the grant's scope, checked before any of the
above, which can only ever narrow what the gateway would allow.

**Transaction discipline -- commit-before-dispatch (the permanent rule).**
The downstream capability here performs real outbound network I/O
(``execute_http_tool``), so this is not a theoretical concern as it was in
Phase 5.6, where no authority did I/O. The sequence is exact:

    1. rate limit          (RateLimiter.check -- commits its own bucket work)
    2. verify + nonce      (commits; a replay loses here, before any work)
    3. decide              (scope -> authz -> policy -> cost; no locks taken)
    4. record the decision and **COMMIT**
    5. dispatch            -- the transaction is closed; no lock is held
    6. reopen, record what the dispatch did, commit

No statement in this package takes ``FOR UPDATE``/``FOR NO KEY UPDATE``, and
``test_ac08_*`` asserts that over the AST *and* proves behaviourally, against
a second real connection, that the row is readable and writable while a
dispatch is in flight. The M1 deadlock needed a lock held across dispatch;
there is no code path here that can produce one.

**Fail semantics (§9 plane rule, §11).** A governed capability fails
**closed**: if the scope check, the gateway, the policy resolution or the cost
evaluation cannot be completed, the call is DENIED, the denial is recorded
with ``fail_mode='FAIL_CLOSED'``, and it is audited. There is no branch that
converts an unevaluable governance decision into an allow. An *observability*
ingest never runs through this class at all -- see ``app/bridge/observed.py``.

**Truthful reach.** The boundary refuses to act for an agent whose effective
mode does not reach boundary calls, and says so in those words. It never
represents a boundary decision as control over the agent: a denied call is a
denied *call*, and ``docs/bridge/enforcement-modes.md`` plus every API
response carry the limit alongside the claim.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.authorization.enums import AuthorizationAuditEvent
from app.authorization.middleware.gateway import AuthorizationGateway
from app.authorization.services import AuthorizationAuditService
from app.bridge import capabilities as caps
from app.bridge.identity import ExternalIdentity
from app.bridge.modes import effective_mode, enforces_boundary_calls, reach_of
from app.identity.errors import ErrorCode, IdentityError
from app.models.bridge import ExternalGatewayCall

MAX_DISPATCH_SUMMARY_BYTES = 2048


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class BoundaryDecision:
    """What the boundary decided, before anything was dispatched."""

    allowed: bool
    record_id: uuid.UUID
    capability: caps.CapabilitySpec
    denial_reason: str | None = None
    fail_mode: str = "FAIL_CLOSED"
    target_ref: str | None = None
    dispatch_plan: dict[str, Any] = field(default_factory=dict)


class CapabilityBoundary:
    def __init__(self, db: Session) -> None:
        self.db = db

    # ------------------------------------------------------------------ #
    def decide(self, identity: ExternalIdentity, *, capability_key: str,
               target_ref: str | None, params: dict | None,
               ip_address: str | None = None, request_id: str | None = None,
               idempotency_key: str | None = None) -> BoundaryDecision:
        """Steps 3 and 4 above: decide, record, commit. Takes no lock."""
        agent = identity.agent
        mode = effective_mode(agent)
        spec = caps.get(capability_key)

        if spec is None or spec.plane != "GOVERNANCE":
            raise IdentityError(
                ErrorCode.EXTERNAL_CAPABILITY_UNKNOWN,
                f"{capability_key!r} is not a governed capability at ACT's boundary. ACT "
                f"governs {list(caps.GOVERNED_CAPABILITIES)} and does not proxy other traffic.",
            )

        # Truthful reach, checked before anything else is attempted. A mode
        # that does not enforce boundary calls has no boundary to call through,
        # and saying so is the honest answer -- not a denial dressed up as
        # enforcement ACT would not actually have performed.
        if not enforces_boundary_calls(agent):
            raise IdentityError(
                ErrorCode.EXTERNAL_MODE_DOES_NOT_ENFORCE,
                f"This agent is at enforcement mode {mode!r}. {reach_of(agent).limits} "
                "ACT therefore has no boundary decision to make for it.",
            )

        outcome = "DENIED"
        denial: str | None = None
        authz_decision, authz_reason, authz_req = "DENY", None, None
        policy_outcome, policy_detail = "UNEVALUABLE", None
        cost_outcome, cost_detail = "UNEVALUABLE", None
        dispatch_plan: dict[str, Any] = {}

        try:
            # --- the bound: scope. Narrows; never grants. ---
            if not identity.scoped_for(capability_key, target_ref):
                denial = ("This grant is not scoped for that capability and target.")
                authz_decision, authz_reason = "DENY", "outside grant scope"
                policy_outcome, cost_outcome = "NOT_APPLICABLE", "NOT_MEASURABLE"
            else:
                # --- the authority: the real AuthorizationGateway ---
                decision = AuthorizationGateway(self.db).authorize_agent(
                    agent, spec.authz_action,
                    # Only ``ai.*``/``environment.*`` keys are accepted here and
                    # the subject attributes are built server-side from the
                    # agent row, so an external caller cannot spoof its own
                    # identity any more than a native one can (§29).
                    # ``ai.tool_name`` is deliberately the platform's own
                    # registered attribute rather than a new one: a real ABAC
                    # policy can be written against it today ("deny external
                    # agents this tool") without extending the 4.3.6 attribute
                    # catalog. The rest is context for the decision trace.
                    ai_context={
                        "ai.tool_name": target_ref,
                        "ai.capability": capability_key,
                        "ai.enforcement_mode": mode,
                        "ai.external_grant_id": str(identity.grant.id),
                    },
                    ip_address=ip_address, request_id=request_id,
                )
                authz_decision = decision.decision
                authz_reason = decision.reason
                authz_req = decision.request_id
                if not decision.allowed:
                    denial = decision.reason or "Authorization denied."
                    policy_outcome, cost_outcome = "NOT_APPLICABLE", "NOT_MEASURABLE"
                else:
                    policy_outcome, policy_detail, policy_denial = self._policy(agent)
                    if policy_denial is not None:
                        denial = policy_denial
                        cost_outcome, cost_detail = "NOT_MEASURABLE", None
                    else:
                        cost_outcome, cost_detail, cost_denial = self._cost(agent, spec)
                        if cost_denial is not None:
                            denial = cost_denial
                        else:
                            outcome = "ALLOWED"
                            dispatch_plan = {"target_ref": target_ref, "params": params or {}}
        except IdentityError:
            raise
        except Exception as exc:  # noqa: BLE001
            # §11: a governance decision that cannot be evaluated DENIES. It is
            # recorded as such -- never silently allowed, never a fake success.
            self.db.rollback()
            outcome, denial = "DENIED", (
                "ACT could not complete the governance decision for this call, so it was "
                f"denied (fail-closed): {type(exc).__name__}.")
            authz_decision = authz_decision or "DENY"
            policy_outcome, cost_outcome = "UNEVALUABLE", "UNEVALUABLE"

        record = ExternalGatewayCall(
            organization_id=agent.organization_id, agent_id=agent.id,
            grant_id=identity.grant.id, capability_key=capability_key,
            target_ref=target_ref, enforcement_mode_at_time=mode,
            authz_decision=authz_decision, authz_permission=spec.authz_action,
            authz_reason=authz_reason, authz_request_id=authz_req,
            policy_outcome=policy_outcome, policy_detail=policy_detail,
            cost_outcome=cost_outcome, cost_detail=cost_detail,
            outcome=outcome, denial_reason=denial, fail_mode=spec.fail_mode,
            dispatch_status="NOT_DISPATCHED", idempotency_key=idempotency_key,
        )
        self.db.add(record)
        identity.grant.last_used_at = _now()
        self._audit(record, agent_id=agent.id)
        # Step 4 -- COMMIT. Everything the decision needed to persist is
        # persisted; nothing is held open across the dispatch that follows.
        self.db.commit()
        self.db.refresh(record)

        return BoundaryDecision(
            allowed=outcome == "ALLOWED", record_id=record.id, capability=spec,
            denial_reason=denial, fail_mode=spec.fail_mode, target_ref=target_ref,
            dispatch_plan=dispatch_plan,
        )

    # ------------------------------------------------------------------ #
    def _policy(self, agent) -> tuple[str, dict | None, str | None]:
        """Read the **existing** Phase 4.3 policies for this agent.

        These are the same ``runtime_governance_policies`` rows the 4.3
        engine's own checkpoints read -- including the ones Phase 5.6's
        ``REQUIRE_APPROVAL`` containment writes. The engine itself is not
        invoked: it decides for an ``AgentExecution``, and a boundary call is
        not one. Fabricating an execution row to borrow it would put a lie in
        the execution ledger.
        """
        from app.runtime.governance.policies import GovernancePolicyService

        policies = GovernancePolicyService(self.db).resolve(
            agent.organization_id, environment_id=None, agent_id=agent.id)
        if not policies:
            return "NOT_APPLICABLE", None, None
        for policy in policies:
            constraints = policy.constraints or {}
            if constraints.get("requires_approval") is True:
                return ("APPROVAL_REQUIRED",
                        {"policy_id": str(policy.id), "policy_name": policy.name},
                        (f"Policy {policy.name!r} requires human approval for this agent. ACT's "
                         "boundary does not auto-approve; the call is denied until an operator "
                         "approves it."))
        return "SATISFIED", {"policies_considered": len(policies)}, None

    def _cost(self, agent, spec: caps.CapabilitySpec) -> tuple[str, dict | None, str | None]:
        """Price the call against the **existing** Phase 4.4 budgets.

        ``BudgetService.resolve`` + ``utilization`` answer "is there headroom"
        without an ``AgentExecution``. A *reservation* is deliberately not
        taken: ``ReservationService.reserve`` is keyed to an execution this
        call does not have, and inventing one would corrupt the 4.4 ledger. So
        ACT enforces the ceiling it can genuinely read and records
        ``NOT_MEASURABLE`` where no budget applies -- rather than reporting a
        number it made up.
        """
        if not spec.cost_measurable:
            return "NOT_MEASURABLE", None, None
        from app.finops.budgets import BudgetService, ExecutionScope

        service = BudgetService(self.db)
        budgets = service.resolve(ExecutionScope(
            organization_id=agent.organization_id, agent_id=agent.id))
        if not budgets:
            return "NOT_MEASURABLE", {"budgets_considered": 0}, None
        for budget in budgets:
            state = service.utilization(budget)
            if budget.mode == "HARD_LIMIT" and state.remaining <= 0:
                return ("EXCEEDED",
                        {"budget_id": str(budget.id), "budget_name": budget.name,
                         "remaining": float(state.remaining)},
                        (f"Budget {budget.name!r} has no remaining headroom and is a hard "
                         "limit; the call is denied at the boundary."))
        return ("WITHIN_BUDGET",
                {"budgets_considered": len(budgets),
                 "remaining": float(service.utilization(budgets[0]).remaining)}, None)

    # ------------------------------------------------------------------ #
    def record_dispatch(self, record_id: uuid.UUID, *, status: str,
                        detail: dict | None) -> None:
        """Step 6: what the downstream call actually did.

        A separate, short transaction opened *after* the dispatch returned.
        Deliberately tolerant: the dispatch already happened, and failing to
        annotate it must not turn a completed call into an error the caller
        sees as a failure that did not occur.
        """
        try:
            record = self.db.get(ExternalGatewayCall, record_id)
            if record is None:
                return
            record.dispatch_status = status
            record.dispatch_detail = _bounded(detail)
            self.db.commit()
        except Exception:  # noqa: BLE001
            self.db.rollback()

    def _audit(self, record: ExternalGatewayCall, *, agent_id: uuid.UUID) -> None:
        event = (AuthorizationAuditEvent.EXTERNAL_GATEWAY_CALL_ALLOWED
                 if record.outcome == "ALLOWED"
                 else AuthorizationAuditEvent.EXTERNAL_GATEWAY_CALL_DENIED)
        AuthorizationAuditService(self.db).record_change(
            event, organization_id=record.organization_id, actor_id=None,
            identity_id=agent_id, permission=record.authz_permission,
            meta={
                "capability": record.capability_key,
                "target_ref": record.target_ref,
                "enforcement_mode": record.enforcement_mode_at_time,
                "authz_decision": record.authz_decision,
                "policy_outcome": record.policy_outcome,
                "cost_outcome": record.cost_outcome,
                "outcome": record.outcome,
                "fail_mode": record.fail_mode,
                "denial_reason": record.denial_reason,
                # The grant is named by its public key_id only. The secret,
                # its ciphertext and its hint never appear here.
                "grant_id": str(record.grant_id) if record.grant_id else None,
            },
        )


def _bounded(detail: dict | None) -> dict | None:
    """Keep a dispatch summary small and free of payload. The downstream
    response body is never stored -- it is the external system's data, it may
    contain anything, and the gateway record is a governance artefact, not a
    response cache."""
    if not detail:
        return None
    import json as jsonlib

    trimmed = {k: v for k, v in detail.items() if k in
               ("status", "success", "error", "egress_reason", "elapsed_ms", "bytes")}
    if len(jsonlib.dumps(trimmed, default=str)) > MAX_DISPATCH_SUMMARY_BYTES:
        return {"truncated": True}
    return trimmed


__all__ = ["CapabilityBoundary", "BoundaryDecision", "MAX_DISPATCH_SUMMARY_BYTES"]
