"""Approval service - creating approval requests and processing reviews.

Phase 2 adds approval priority, an SLA deadline derived from priority, and
threaded reviewer comments.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.core.enums import (
    ActionStatus,
    ActorType,
    ApprovalDecision,
    ApprovalPriority,
)
from app.models.agent_action import AgentAction
from app.models.approval import Approval, ApprovalComment
from app.models.user import User
from app.services import audit_service

# SLA window (hours) to review an approval, by priority.
_SLA_HOURS: dict[ApprovalPriority, int] = {
    ApprovalPriority.CRITICAL: 1,
    ApprovalPriority.HIGH: 4,
    ApprovalPriority.MEDIUM: 24,
    ApprovalPriority.LOW: 72,
}


def priority_for_risk(risk_score: int) -> ApprovalPriority:
    """Derive an approval priority from the action's risk score."""
    if risk_score >= 90:
        return ApprovalPriority.CRITICAL
    if risk_score >= 70:
        return ApprovalPriority.HIGH
    if risk_score >= 50:
        return ApprovalPriority.MEDIUM
    return ApprovalPriority.LOW


def create_pending_approval(db: Session, action: AgentAction) -> Approval:
    """Create a PENDING approval for an action awaiting human review."""
    priority = priority_for_risk(action.risk_score)
    sla_due_at = datetime.now(timezone.utc) + timedelta(hours=_SLA_HOURS[priority])

    approval = Approval(
        organization_id=action.organization_id,
        agent_action_id=action.id,
        requested_by_agent_id=action.agent_id,
        decision=ApprovalDecision.PENDING,
        priority=priority,
        sla_due_at=sla_due_at,
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
            "priority": priority.value,
        },
    )
    return approval


def _finalize(
    db: Session,
    approval: Approval,
    reviewer: User,
    decision: ApprovalDecision,
    action_status: ActionStatus,
    comment: str | None,
    event_type: str,
) -> Approval:
    approval.decision = decision
    approval.reviewed_by_user_id = reviewer.id
    approval.review_comment = comment
    approval.reviewed_at = datetime.now(timezone.utc)
    approval.agent_action.status = action_status

    if comment:
        db.add(ApprovalComment(approval_id=approval.id, user_id=reviewer.id, comment=comment))

    db.flush()

    audit_service.log_event(
        db,
        organization_id=approval.organization_id,
        actor_type=ActorType.USER,
        actor_id=reviewer.id,
        event_type=event_type,
        entity_type="approval",
        entity_id=approval.id,
        metadata={
            "agent_action_id": str(approval.agent_action_id),
            "review_comment": comment,
        },
    )
    return approval


def approve_action(db: Session, approval: Approval, reviewer: User, comment: str | None = None) -> Approval:
    return _finalize(
        db, approval, reviewer, ApprovalDecision.APPROVED, ActionStatus.APPROVED,
        comment, "APPROVAL_APPROVED",
    )


def reject_action(db: Session, approval: Approval, reviewer: User, comment: str | None = None) -> Approval:
    return _finalize(
        db, approval, reviewer, ApprovalDecision.REJECTED, ActionStatus.REJECTED,
        comment, "APPROVAL_REJECTED",
    )


def add_comment(db: Session, approval: Approval, user: User, comment: str) -> ApprovalComment:
    record = ApprovalComment(approval_id=approval.id, user_id=user.id, comment=comment)
    db.add(record)
    db.flush()
    return record
