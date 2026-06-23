"""Decision engine.

Combines agent status, the permission result and the risk score into a final
governance decision, following the Phase 1 decision rules:

* Inactive agent                      -> BLOCK
* Permission missing / denied         -> BLOCK
* Permission granted, risk <= 40      -> ALLOW
* Permission granted, 41 <= risk <= 80 -> PENDING_APPROVAL
* Permission granted, risk > 80       -> BLOCK
"""

from __future__ import annotations

from dataclasses import dataclass

from app.core.enums import ActionDecision, AgentStatus
from app.models.agent import Agent
from app.services.permission_engine import PermissionResult

# Risk thresholds.
ALLOW_MAX_RISK = 40
APPROVAL_MAX_RISK = 80


@dataclass(frozen=True)
class DecisionResult:
    decision: ActionDecision
    decision_reason: str
    risk_score: int


def make_decision(
    agent: Agent,
    permission_result: PermissionResult,
    risk_score: int,
) -> DecisionResult:
    """Apply the decision rules and return the outcome plus a human reason."""
    if agent.status != AgentStatus.ACTIVE:
        return DecisionResult(
            decision=ActionDecision.BLOCK,
            decision_reason=f"Agent is not active (status: {agent.status.value}).",
            risk_score=risk_score,
        )

    if not permission_result.allowed:
        return DecisionResult(
            decision=ActionDecision.BLOCK,
            decision_reason=permission_result.reason,
            risk_score=risk_score,
        )

    if risk_score <= ALLOW_MAX_RISK:
        return DecisionResult(
            decision=ActionDecision.ALLOW,
            decision_reason=(
                f"Permission granted and risk score ({risk_score}) is low; "
                "action allowed."
            ),
            risk_score=risk_score,
        )

    if risk_score <= APPROVAL_MAX_RISK:
        return DecisionResult(
            decision=ActionDecision.PENDING_APPROVAL,
            decision_reason=(
                "Permission exists but action requires human approval due to "
                f"medium/high risk (risk score: {risk_score})."
            ),
            risk_score=risk_score,
        )

    return DecisionResult(
        decision=ActionDecision.BLOCK,
        decision_reason=(
            f"Risk score ({risk_score}) exceeds the maximum allowed threshold; "
            "action blocked."
        ),
        risk_score=risk_score,
    )
