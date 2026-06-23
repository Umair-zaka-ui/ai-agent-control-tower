"""Approval service - creating approval requests and processing reviews."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.enums import (
    ActionStatus,
    ActorType,
    ApprovalDecision,
)
from app.models.agent_action import AgentAction
from app.models.approval import Approval
from app.models.user import User
from app.services import audit_service


def create_pending_approval(db: Session, action: AgentAction) -> Approval:
    """Create a PENDING approval for an action awaiting human review.

    The action keeps status ``CREATED`` until a reviewer acts on it.
    """
    approval = Approval(
        organization_id=action.organization_id,
        agent_action_id=action.id,
        requested_by_agent_id=action.agent_id,
        decision=ApprovalDecision.PENDING,
    )
    db.add(approval)
    db.flush()

    audit_service.log_event(
        db,
        organization_id=action.organization_id,
        actor_type=ActorType.SYSTEM,
        event_type="APPROVAL_REQUESTED",
        entity_type="approval",
        entity_id=approval.id,
        metadata={
            "agent_action_id": str(action.id),
            "agent_id": str(action.agent_id),
            "resource": action.resource,
            "action": action.action,
            "risk_score": action.risk_score,
        },
    )
    return approval


def approve_action(
    db: Session,
    approval: Approval,
    reviewer: User,
    comment: str | None = None,
) -> Approval:
    """Mark an approval (and its action) as APPROVED."""
    approval.decision = ApprovalDecision.APPROVED
    approval.reviewed_by_user_id = reviewer.id
    approval.review_comment = comment
    approval.reviewed_at = datetime.now(timezone.utc)

    action = approval.agent_action
    action.status = ActionStatus.APPROVED

    db.flush()

    audit_service.log_event(
        db,
        organization_id=approval.organization_id,
        actor_type=ActorType.USER,
        actor_id=reviewer.id,
        event_type="APPROVAL_APPROVED",
        entity_type="approval",
        entity_id=approval.id,
        metadata={
            "agent_action_id": str(approval.agent_action_id),
            "review_comment": comment,
        },
    )
    return approval


def reject_action(
    db: Session,
    approval: Approval,
    reviewer: User,
    comment: str | None = None,
) -> Approval:
    """Mark an approval (and its action) as REJECTED."""
    approval.decision = ApprovalDecision.REJECTED
    approval.reviewed_by_user_id = reviewer.id
    approval.review_comment = comment
    approval.reviewed_at = datetime.now(timezone.utc)

    action = approval.agent_action
    action.status = ActionStatus.REJECTED

    db.flush()

    audit_service.log_event(
        db,
        organization_id=approval.organization_id,
        actor_type=ActorType.USER,
        actor_id=reviewer.id,
        event_type="APPROVAL_REJECTED",
        entity_type="approval",
        entity_id=approval.id,
        metadata={
            "agent_action_id": str(approval.agent_action_id),
            "review_comment": comment,
        },
    )
    return approval
