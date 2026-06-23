"""Agent action orchestration.

This is the end-to-end pipeline described in the product spec:

    permission check -> risk score -> decision -> persist action
                     -> approval queue (if needed) -> audit log

It composes the individual engines and services so the HTTP route stays thin.
The caller owns the transaction (commit/rollback).
"""

from __future__ import annotations

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
    risk_engine,
)

# Maps a decision to the lifecycle status the stored action should start in.
_DECISION_TO_STATUS: dict[ActionDecision, ActionStatus] = {
    ActionDecision.ALLOW: ActionStatus.EXECUTED,
    ActionDecision.BLOCK: ActionStatus.BLOCKED,
    ActionDecision.PENDING_APPROVAL: ActionStatus.CREATED,
}


def process_agent_action(
    db: Session,
    agent: Agent,
    resource: str,
    action: str,
    input_payload: dict[str, Any],
) -> tuple[AgentAction, Approval | None]:
    """Run the full governance pipeline for one attempted agent action."""
    # 1. Permission check.
    permission_result = permission_engine.check_permission(
        db, agent.id, resource, action
    )

    # 2. Risk scoring.
    risk_score = risk_engine.calculate_risk_score(resource, action, input_payload)

    # 3. Decision.
    decision = decision_engine.make_decision(agent, permission_result, risk_score)

    # 4. Persist the action with the derived initial status.
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

    # 5. Audit the decision itself (always).
    audit_service.log_event(
        db,
        organization_id=agent.organization_id,
        actor_type=ActorType.AGENT,
        actor_id=agent.id,
        event_type="AGENT_ACTION_DECISION",
        entity_type="agent_action",
        entity_id=agent_action.id,
        metadata={
            "resource": resource,
            "action": action,
            "risk_score": decision.risk_score,
            "decision": decision.decision.value,
            "decision_reason": decision.decision_reason,
        },
    )

    # 6. Route to the approval queue when human review is required.
    approval: Approval | None = None
    if decision.decision == ActionDecision.PENDING_APPROVAL:
        approval = approval_service.create_pending_approval(db, agent_action)

    return agent_action, approval
