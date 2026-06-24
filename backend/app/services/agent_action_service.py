"""Agent action orchestration.

The end-to-end Phase 2 pipeline:

    permission check -> risk score (v2) -> policy evaluation -> decision
                     -> persist action -> approval queue (if needed) -> audit log

It composes the engines/services so the HTTP route stays thin. The caller owns
the transaction (commit/rollback) and handles notifications.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.core.enums import ActionDecision, ActionStatus, ActorType
from app.models.agent import Agent
from app.models.agent_action import AgentAction
from app.models.approval import Approval
from app.services import (
    approval_service,
    audit_service,
    decision_engine,
    permission_engine,
    policy_engine,
    risk_engine,
)

_DECISION_TO_STATUS: dict[ActionDecision, ActionStatus] = {
    ActionDecision.ALLOW: ActionStatus.EXECUTED,
    ActionDecision.BLOCK: ActionStatus.BLOCKED,
    ActionDecision.PENDING_APPROVAL: ActionStatus.CREATED,
}


@dataclass
class RequestContext:
    """Forensic context captured from the HTTP request for the audit trail."""

    ip_address: str | None = None
    user_agent: str | None = None
    request_id: str | None = None
    trace_id: str | None = None
    submitted_by_user_id: str | None = None


@dataclass
class ProcessResult:
    action: AgentAction
    approval: Approval | None
    decision: decision_engine.DecisionResult


def process_agent_action(
    db: Session,
    agent: Agent,
    resource: str,
    action: str,
    input_payload: dict[str, Any],
    context: RequestContext | None = None,
) -> ProcessResult:
    """Run the full governance pipeline for one attempted agent action."""
    context = context or RequestContext()

    # 1. Permission check.
    permission_result = permission_engine.check_permission(db, agent.id, resource, action)

    # 2. Risk scoring (v2 - transparent breakdown for the audit record).
    risk = risk_engine.calculate_risk_breakdown(resource, action, input_payload)

    # 3. Policy evaluation (only meaningful once permission passes, but cheap).
    policy_result = policy_engine.evaluate_policies(
        db, agent.organization_id, resource, action, input_payload
    )

    # 4. Decision.
    decision = decision_engine.make_decision(
        agent, permission_result, risk.score, policy_result
    )

    # 5. Persist the action with the derived initial status.
    agent_action = AgentAction(
        organization_id=agent.organization_id,
        agent_id=agent.id,
        resource=resource,
        action=action,
        input_payload=input_payload,
        risk_score=decision.risk_score,
        decision=decision.decision,
        decision_reason=decision.decision_reason,
        status=_DECISION_TO_STATUS[decision.decision],
    )
    db.add(agent_action)
    db.flush()

    # 6. Audit the decision (always), with full forensic context.
    audit_service.log_event(
        db,
        organization_id=agent.organization_id,
        actor_type=ActorType.AGENT,
        actor_id=agent.id,
        event_type="AGENT_ACTION_DECISION",
        entity_type="agent_action",
        entity_id=agent_action.id,
        ip_address=context.ip_address,
        user_agent=context.user_agent,
        request_id=context.request_id,
        trace_id=context.trace_id,
        after_state={"status": agent_action.status.value, "decision": decision.decision.value},
        metadata={
            "resource": resource,
            "action": action,
            "risk_score": decision.risk_score,
            "risk_breakdown": {
                "action_score": risk.action_score,
                "resource_score": risk.resource_score,
                "modifiers": risk.modifiers,
            },
            "decision": decision.decision.value,
            "decision_reason": decision.decision_reason,
            "matched_policy": decision.matched_policy_name,
            "submitted_by_user_id": context.submitted_by_user_id,
        },
    )

    # 7. Route to the approval queue when human review is required.
    approval: Approval | None = None
    if decision.decision == ActionDecision.PENDING_APPROVAL:
        approval = approval_service.create_pending_approval(db, agent_action)

    return ProcessResult(action=agent_action, approval=approval, decision=decision)
