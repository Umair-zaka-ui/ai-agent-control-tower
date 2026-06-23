"""Approval routes - the human review queue."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import require_roles
from app.core.database import get_db
from app.core.enums import ApprovalDecision, UserRole
from app.models.approval import Approval
from app.models.user import User
from app.schemas.approval import ApprovalRead, ApprovalReviewRequest
from app.services import approval_service

router = APIRouter(prefix="/approvals", tags=["approvals"])

# Reviewers and admins may action the approval queue.
_REVIEWER_ROLES = (UserRole.SUPER_ADMIN, UserRole.ADMIN, UserRole.REVIEWER)


@router.get("/pending", response_model=list[ApprovalRead])
def list_pending_approvals(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(*_REVIEWER_ROLES)),
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
    payload: ApprovalReviewRequest | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(*_REVIEWER_ROLES)),
) -> Approval:
    """Approve a pending action."""
    approval = _get_pending_approval(db, approval_id, current_user)
    comment = payload.review_comment if payload else None
    approval_service.approve_action(db, approval, current_user, comment)
    db.commit()
    return approval


@router.post("/{approval_id}/reject", response_model=ApprovalRead)
def reject(
    approval_id: uuid.UUID,
    payload: ApprovalReviewRequest | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(*_REVIEWER_ROLES)),
) -> Approval:
    """Reject a pending action."""
    approval = _get_pending_approval(db, approval_id, current_user)
    comment = payload.review_comment if payload else None
    approval_service.reject_action(db, approval, current_user, comment)
    db.commit()
    return approval


def _get_pending_approval(
    db: Session, approval_id: uuid.UUID, current_user: User
) -> Approval:
    """Load a PENDING approval scoped to the caller's organization."""
    approval = db.get(Approval, approval_id)
    if approval is None or approval.organization_id != current_user.organization_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Approval not found."
        )
    if approval.decision != ApprovalDecision.PENDING:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Approval already {approval.decision.value.lower()}.",
        )
    return approval
