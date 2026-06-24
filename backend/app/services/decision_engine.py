"""Decision engine.

Combines agent status, permission, **policy** and risk into a final decision.
Evaluation order (first decisive rule wins):

1. Inactive agent                       -> BLOCK
2. Permission missing / denied          -> BLOCK
3. A matching database policy           -> the policy's decision (overrides risk)
4. Risk score thresholds:
     risk <= 40                         -> ALLOW
     41 <= risk <= 80                   -> PENDING_APPROVAL
     risk > 80                          -> BLOCK
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from app.core.enums import ActionDecision, AgentStatus
from app.models.agent import Agent
from app.services.permission_engine import PermissionResult
from app.services.policy_engine import PolicyResult

ALLOW_MAX_RISK = 40
APPROVAL_MAX_RISK = 80


@dataclass(frozen=True)
class DecisionResult:
    decision: ActionDecision
    decision_reason: str
    risk_score: int
    matched_policy_id: uuid.UUID | None = None
    matched_policy_name: str | None = None


def make_decision(
    agent: Agent,
    permission_result: PermissionResult,
    risk_score: int,
    policy_result: PolicyResult | None = None,
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

    # A matching policy is authoritative and overrides the raw risk thresholds.
    if policy_result is not None and policy_result.matched and policy_result.decision:
        return DecisionResult(
            decision=policy_result.decision,
            decision_reason=policy_result.reason or "Decided by policy.",
            risk_score=risk_score,
            matched_policy_id=policy_result.policy_id,
            matched_policy_name=policy_result.policy_name,
        )

    if risk_score <= ALLOW_MAX_RISK:
        return DecisionResult(
            decision=ActionDecision.ALLOW,
            decision_reason=(
                f"Permission granted and risk score ({risk_score}) is low; action allowed."
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
            f"Risk score ({risk_score}) exceeds the maximum allowed threshold; action blocked."
        ),
        risk_score=risk_score,
    )
