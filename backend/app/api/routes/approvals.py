"""Approval routes - the human review queue with comments and notifications."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_permission
from app.core.database import get_db
from app.core.enums import ApprovalDecision
from app.models.agent import Agent
from app.models.approval import Approval, ApprovalComment
from app.models.user import User
from app.schemas.approval import (
    ApprovalCommentCreate,
    ApprovalCommentRead,
    ApprovalRead,
    ApprovalReviewRequest,
)
from app.services import approval_service, notification_service


router = APIRouter(prefix="/approvals", tags=["approvals"])


@router.get("/pending", response_model=list[ApprovalRead])
def list_pending_approvals(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("approval.review")),
) -> list[Approval]:
    """List all pending approvals in the caller's organization."""
    stmt = (
        select(Approval)
        .where(
            Approval.organization_id == current_user.organization_id,
            Approval.decision == ApprovalDecision.PENDING,
        )
        .order_by(Approval.created_at)
    )
    return list(db.execute(stmt).scalars().all())


@router.post("/{approval_id}/approve", response_model=ApprovalRead)
def approve(
    approval_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    payload: ApprovalReviewRequest | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("approval.review")),
) -> Approval:
    """Approve a pending action."""
    approval = _get_pending_approval(db, approval_id, current_user)
    comment = payload.review_comment if payload else None
    approval_service.approve_action(db, approval, current_user, comment)
    recipients = _notify_targets(db, approval)
    db.commit()
    _schedule_decided_email(background_tasks, recipients, approval, "APPROVED", comment)
    return approval


@router.post("/{approval_id}/reject", response_model=ApprovalRead)
def reject(
    approval_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    payload: ApprovalReviewRequest | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("approval.review")),
) -> Approval:
    """Reject a pending action."""
    approval = _get_pending_approval(db, approval_id, current_user)
    comment = payload.review_comment if payload else None
    approval_service.reject_action(db, approval, current_user, comment)
    recipients = _notify_targets(db, approval)
    db.commit()
    _schedule_decided_email(background_tasks, recipients, approval, "REJECTED", comment)
    return approval


@router.get("/{approval_id}/comments", response_model=list[ApprovalCommentRead])
def list_comments(
    approval_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("approval.review")),
) -> list[ApprovalComment]:
    """List the comment thread on an approval."""
    approval = _get_org_approval(db, approval_id, current_user)
    return list(approval.comments)


@router.post(
    "/{approval_id}/comments",
    response_model=ApprovalCommentRead,
    status_code=status.HTTP_201_CREATED,
)
def add_comment(
    approval_id: uuid.UUID,
    payload: ApprovalCommentCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("approval.review")),
) -> ApprovalComment:
    """Add a comment to an approval (does not change its decision)."""
    approval = _get_org_approval(db, approval_id, current_user)
    record = approval_service.add_comment(db, approval, current_user, payload.comment)
    db.commit()
    return record


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _get_org_approval(db: Session, approval_id: uuid.UUID, current_user: User) -> Approval:
    approval = db.get(Approval, approval_id)
    if approval is None or approval.organization_id != current_user.organization_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Approval not found.")
    return approval


def _get_pending_approval(db: Session, approval_id: uuid.UUID, current_user: User) -> Approval:
    approval = _get_org_approval(db, approval_id, current_user)
    if approval.decision != ApprovalDecision.PENDING:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Approval already {approval.decision.value.lower()}.",
        )
    return approval


def _notify_targets(db: Session, approval: Approval) -> list[str]:
    """Email the agent's org owner(s) about the decision (admins/super-admins)."""
    agent = db.get(Agent, approval.requested_by_agent_id)
    if agent is None:
        return []
    from app.core.enums import UserRole

    stmt = select(User.email).where(
        User.organization_id == approval.organization_id,
        User.is_active.is_(True),
        User.role.in_([UserRole.SUPER_ADMIN, UserRole.ADMIN]),
    )
    return [e for (e,) in db.execute(stmt).all()]


def _schedule_decided_email(
    background_tasks: BackgroundTasks,
    recipients: list[str],
    approval: Approval,
    decision: str,
    comment: str | None,
) -> None:
    if not recipients:
        return
    action = approval.agent_action
    background_tasks.add_task(
        notification_service.notify_approval_decided,
        recipients,
        decision=decision,
        resource=action.resource,
        action=action.action,
        comment=comment,
    )
