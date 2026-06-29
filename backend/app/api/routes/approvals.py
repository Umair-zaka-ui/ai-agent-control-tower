"""Approval routes - the Human Review Workbench (Phase 3 Part 3.4).

Exposes the approval queue, statistics, history, escalations, a rich detail
payload and the review actions (approve / reject / escalate / assign) plus a
threaded comment model and an audit-derived review timeline.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_permission
from app.core.enums import ApprovalDecision, ApprovalPriority
from app.models.agent import Agent
from app.models.agent_action import AgentAction
from app.models.approval import Approval, ApprovalComment
from app.models.audit_log import AuditLog
from app.models.user import User
from app.schemas.approval import (
    ApprovalAssignRequest,
    ApprovalCommentCreate,
    ApprovalCommentRead,
    ApprovalDetail,
    ApprovalEscalateRequest,
    ApprovalListItem,
    ApprovalRead,
    ApprovalReviewRequest,
    ApprovalStatistics,
    ApprovalTimelineEvent,
)
from app.schemas.approval import (
    ApprovalActionInfo,
    ApprovalAgentInfo,
    ApprovalPolicyInfo,
    ApprovalRiskAssessment,
)
from app.services import approval_service, notification_service, policy_engine, risk_engine


router = APIRouter(prefix="/approvals", tags=["approvals"])

# Decisions that count as "resolved" for the history view.
_RESOLVED = (
    ApprovalDecision.APPROVED,
    ApprovalDecision.REJECTED,
    ApprovalDecision.EXPIRED,
    ApprovalDecision.ESCALATED,
)


# --------------------------------------------------------------------------- #
# Queue / statistics / history / escalations (static paths first)
# --------------------------------------------------------------------------- #
@router.get("", response_model=list[ApprovalListItem])
def list_approvals(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("approval.view")),
    status_filter: ApprovalDecision | None = Query(default=None, alias="status"),
    priority: ApprovalPriority | None = Query(default=None),
    risk_min: int | None = Query(default=None, ge=0, le=100),
    risk_max: int | None = Query(default=None, ge=0, le=100),
    search: str | None = Query(default=None),
) -> list[ApprovalListItem]:
    """Filterable approval queue for the caller's organization."""
    rows = _query_approvals(
        db,
        current_user,
        statuses=[status_filter] if status_filter else None,
        priority=priority,
        risk_min=risk_min,
        risk_max=risk_max,
    )
    return _assemble_items(db, current_user, rows, search=search)


@router.get("/pending", response_model=list[ApprovalRead])
def list_pending_approvals(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("approval.view")),
) -> list[Approval]:
    """List all pending approvals in the caller's organization (compat endpoint)."""
    stmt = (
        select(Approval)
        .where(
            Approval.organization_id == current_user.organization_id,
            Approval.decision == ApprovalDecision.PENDING,
        )
        .order_by(Approval.created_at)
    )
    return list(db.execute(stmt).scalars().all())


@router.get("/statistics", response_model=ApprovalStatistics)
def approval_statistics(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("approval.view")),
) -> ApprovalStatistics:
    """Headline counts for the approval dashboard statistics cards."""
    org = current_user.organization_id
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

    def _count(decision: ApprovalDecision, *, today: bool = False) -> int:
        stmt = select(func.count(Approval.id)).where(
            Approval.organization_id == org, Approval.decision == decision
        )
        if today:
            stmt = stmt.where(Approval.reviewed_at >= today_start)
        return db.execute(stmt).scalar_one() or 0

    # Average review time over resolved approvals that carry a reviewed_at.
    durations = db.execute(
        select(Approval.created_at, Approval.reviewed_at).where(
            Approval.organization_id == org,
            Approval.reviewed_at.is_not(None),
            Approval.decision.in_((ApprovalDecision.APPROVED, ApprovalDecision.REJECTED)),
        )
    ).all()
    avg_seconds: int | None = None
    if durations:
        total = sum((rv - cr).total_seconds() for cr, rv in durations if rv and cr)
        avg_seconds = int(total / len(durations))

    return ApprovalStatistics(
        pending=_count(ApprovalDecision.PENDING),
        approved_today=_count(ApprovalDecision.APPROVED, today=True),
        rejected_today=_count(ApprovalDecision.REJECTED, today=True),
        escalated=_count(ApprovalDecision.ESCALATED),
        avg_review_seconds=avg_seconds,
    )


@router.get("/history", response_model=list[ApprovalListItem])
def approval_history(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("approval.view")),
    status_filter: ApprovalDecision | None = Query(default=None, alias="status"),
    search: str | None = Query(default=None),
) -> list[ApprovalListItem]:
    """Resolved approvals (approved / rejected / escalated / expired)."""
    statuses = [status_filter] if status_filter else list(_RESOLVED)
    rows = _query_approvals(db, current_user, statuses=statuses, resolved_order=True)
    return _assemble_items(db, current_user, rows, search=search)


@router.get("/escalations", response_model=list[ApprovalListItem])
def approval_escalations(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("approval.view")),
) -> list[ApprovalListItem]:
    """Currently escalated approvals, ordered by SLA urgency."""
    stmt = (
        select(Approval)
        .where(
            Approval.organization_id == current_user.organization_id,
            Approval.decision == ApprovalDecision.ESCALATED,
        )
        .order_by(Approval.sla_due_at.is_(None), Approval.sla_due_at, Approval.created_at)
    )
    rows = list(db.execute(stmt).scalars().all())
    return _assemble_items(db, current_user, rows)


# --------------------------------------------------------------------------- #
# Detail / timeline / comments
# --------------------------------------------------------------------------- #
@router.get("/{approval_id}", response_model=ApprovalDetail)
def get_approval(
    approval_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("approval.view")),
) -> ApprovalDetail:
    """Full detail payload for one approval (agent, policy, risk, payload, comments)."""
    approval = _get_org_approval(db, approval_id, current_user)
    action = approval.agent_action
    agent = db.get(Agent, approval.requested_by_agent_id)

    names = _user_name_map(db, current_user.organization_id)

    # Policy explanation: re-evaluate the policy engine against the action.
    policy_result = policy_engine.evaluate_policies(
        db,
        current_user.organization_id,
        action.resource,
        action.action,
        action.input_payload,
    )
    policy_info = ApprovalPolicyInfo(
        matched=policy_result.matched,
        policy_name=policy_result.policy_name,
        decision=policy_result.decision.value if policy_result.decision else None,
        conditions=_matched_conditions(db, policy_result.policy_id),
        reason=policy_result.reason,
    )

    risk = _risk_assessment(action)

    agent_info = (
        ApprovalAgentInfo(
            id=agent.id,
            name=agent.name,
            version=agent.version,
            owner=agent.owner,
            department=agent.department,
            status=agent.status.value,
            health=agent.health,
            last_activity=agent.updated_at,
        )
        if agent
        else None
    )

    detail = ApprovalDetail(
        **ApprovalRead.model_validate(approval).model_dump(),
        reviewer_name=names.get(approval.reviewed_by_user_id),
        assigned_to_name=names.get(approval.assigned_to_user_id),
        agent=agent_info,
        action=ApprovalActionInfo(
            id=action.id,
            resource=action.resource,
            action=action.action,
            input_payload=action.input_payload,
            risk_score=action.risk_score,
            decision=action.decision.value,
            decision_reason=action.decision_reason,
            status=action.status.value,
            created_at=action.created_at,
        ),
        policy=policy_info,
        risk=risk,
        comments=[ApprovalCommentRead.model_validate(c) for c in approval.comments],
    )
    return detail


@router.get("/{approval_id}/timeline", response_model=list[ApprovalTimelineEvent])
def approval_timeline(
    approval_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("approval.view")),
) -> list[ApprovalTimelineEvent]:
    """Audit-derived review timeline for an approval (created → assigned → decided)."""
    approval = _get_org_approval(db, approval_id, current_user)
    names = _user_name_map(db, current_user.organization_id)
    stmt = (
        select(AuditLog)
        .where(
            AuditLog.organization_id == current_user.organization_id,
            AuditLog.entity_type == "approval",
            AuditLog.entity_id == approval.id,
        )
        .order_by(AuditLog.created_at)
    )
    logs = db.execute(stmt).scalars().all()
    return [
        ApprovalTimelineEvent(
            id=log.id,
            event_type=log.event_type,
            actor_type=log.actor_type.value,
            actor_id=log.actor_id,
            actor_name=names.get(log.actor_id),
            metadata=log.meta or {},
            created_at=log.created_at,
        )
        for log in logs
    ]


@router.get("/{approval_id}/comments", response_model=list[ApprovalCommentRead])
def list_comments(
    approval_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("approval.view")),
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
# Review actions
# --------------------------------------------------------------------------- #
@router.post("/{approval_id}/approve", response_model=ApprovalRead)
def approve(
    approval_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    payload: ApprovalReviewRequest | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("approval.review")),
) -> Approval:
    """Approve a pending (or escalated) action."""
    approval = _get_actionable_approval(db, approval_id, current_user)
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
    """Reject a pending (or escalated) action."""
    approval = _get_actionable_approval(db, approval_id, current_user)
    comment = payload.review_comment if payload else None
    approval_service.reject_action(db, approval, current_user, comment)
    recipients = _notify_targets(db, approval)
    db.commit()
    _schedule_decided_email(background_tasks, recipients, approval, "REJECTED", comment)
    return approval


@router.post("/{approval_id}/escalate", response_model=ApprovalRead)
def escalate(
    approval_id: uuid.UUID,
    payload: ApprovalEscalateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("approval.escalate")),
) -> Approval:
    """Escalate a pending approval to another reviewer or team."""
    approval = _get_actionable_approval(db, approval_id, current_user)
    assignee_id = payload.assigned_to_user_id
    if assignee_id is not None:
        _ensure_org_user(db, assignee_id, current_user)
    approval_service.escalate_action(
        db, approval, current_user, payload.target, payload.reason, assignee_id
    )
    db.commit()
    return approval


@router.post("/{approval_id}/assign", response_model=ApprovalRead)
def assign(
    approval_id: uuid.UUID,
    payload: ApprovalAssignRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("approval.assign")),
) -> Approval:
    """Assign (or reassign) the reviewer responsible for an approval."""
    approval = _get_org_approval(db, approval_id, current_user)
    _ensure_org_user(db, payload.user_id, current_user)
    approval_service.assign_reviewer(db, approval, current_user, payload.user_id)
    db.commit()
    return approval


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _get_org_approval(db: Session, approval_id: uuid.UUID, current_user: User) -> Approval:
    approval = db.get(Approval, approval_id)
    if approval is None or approval.organization_id != current_user.organization_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Approval not found.")
    return approval


def _get_actionable_approval(
    db: Session, approval_id: uuid.UUID, current_user: User
) -> Approval:
    """An approval that can still receive a decision (PENDING or ESCALATED)."""
    approval = _get_org_approval(db, approval_id, current_user)
    if approval.decision not in (ApprovalDecision.PENDING, ApprovalDecision.ESCALATED):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Approval already {approval.decision.value.lower()}.",
        )
    return approval


def _ensure_org_user(db: Session, user_id: uuid.UUID, current_user: User) -> User:
    user = db.get(User, user_id)
    if user is None or user.organization_id != current_user.organization_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Assignee not found."
        )
    return user


def _query_approvals(
    db: Session,
    current_user: User,
    *,
    statuses: list[ApprovalDecision] | None = None,
    priority: ApprovalPriority | None = None,
    risk_min: int | None = None,
    risk_max: int | None = None,
    resolved_order: bool = False,
) -> list[Approval]:
    stmt = select(Approval).where(
        Approval.organization_id == current_user.organization_id
    )
    if statuses:
        stmt = stmt.where(Approval.decision.in_(statuses))
    if priority is not None:
        stmt = stmt.where(Approval.priority == priority)
    if risk_min is not None or risk_max is not None:
        stmt = stmt.join(AgentAction, AgentAction.id == Approval.agent_action_id)
        if risk_min is not None:
            stmt = stmt.where(AgentAction.risk_score >= risk_min)
        if risk_max is not None:
            stmt = stmt.where(AgentAction.risk_score <= risk_max)
    if resolved_order:
        stmt = stmt.order_by(Approval.reviewed_at.desc().nullslast(), Approval.created_at.desc())
    else:
        stmt = stmt.order_by(Approval.created_at)
    return list(db.execute(stmt).scalars().all())


def _user_name_map(db: Session, org_id: uuid.UUID) -> dict[uuid.UUID, str]:
    rows = db.execute(
        select(User.id, User.name).where(User.organization_id == org_id)
    ).all()
    return {uid: name for uid, name in rows}


def _agent_name_map(db: Session, org_id: uuid.UUID) -> dict[uuid.UUID, str]:
    rows = db.execute(
        select(Agent.id, Agent.name).where(Agent.organization_id == org_id)
    ).all()
    return {aid: name for aid, name in rows}


def _assemble_items(
    db: Session,
    current_user: User,
    approvals: list[Approval],
    *,
    search: str | None = None,
) -> list[ApprovalListItem]:
    """Join approvals with their action + agent/reviewer names into table rows."""
    if not approvals:
        return []
    org = current_user.organization_id
    action_ids = [a.agent_action_id for a in approvals]
    actions = {
        ac.id: ac
        for ac in db.execute(
            select(AgentAction).where(AgentAction.id.in_(action_ids))
        ).scalars()
    }
    agent_names = _agent_name_map(db, org)
    user_names = _user_name_map(db, org)

    items: list[ApprovalListItem] = []
    for ap in approvals:
        action = actions.get(ap.agent_action_id)
        item = ApprovalListItem(
            id=ap.id,
            agent_action_id=ap.agent_action_id,
            requested_by_agent_id=ap.requested_by_agent_id,
            agent_name=agent_names.get(ap.requested_by_agent_id),
            resource=action.resource if action else "",
            action=action.action if action else "",
            risk_score=action.risk_score if action else 0,
            decision=ap.decision,
            priority=ap.priority,
            escalation_target=ap.escalation_target,
            reviewer_name=user_names.get(ap.reviewed_by_user_id),
            assigned_to_name=user_names.get(ap.assigned_to_user_id),
            sla_due_at=ap.sla_due_at,
            created_at=ap.created_at,
            reviewed_at=ap.reviewed_at,
        )
        items.append(item)

    if search:
        needle = search.strip().lower()
        items = [it for it in items if _matches(it, needle)]
    return items


def _matches(item: ApprovalListItem, needle: str) -> bool:
    haystack = " ".join(
        str(v).lower()
        for v in (
            item.id,
            item.agent_name or "",
            item.resource,
            item.action,
            item.reviewer_name or "",
            item.assigned_to_name or "",
        )
    )
    return needle in haystack


def _matched_conditions(db: Session, policy_id: uuid.UUID | None) -> dict:
    if policy_id is None:
        return {}
    from app.models.policy import Policy

    policy = db.get(Policy, policy_id)
    return policy.conditions if policy else {}


def _risk_assessment(action: AgentAction) -> ApprovalRiskAssessment:
    breakdown = risk_engine.calculate_risk_breakdown(
        action.resource, action.action, action.input_payload
    )
    label_map = {"PHI_ACCESS": "PHI Exposure", "HIGH_AMOUNT": "Financial"}
    factors: dict[str, int] = {
        "Action": breakdown.action_score,
        "Resource": breakdown.resource_score,
    }
    for key, value in breakdown.modifiers.items():
        factors[label_map.get(key, key.replace("_", " ").title())] = value

    score = action.risk_score
    if score >= 90:
        recommendation = "Human review required — critical risk."
    elif score >= 70:
        recommendation = "Human review recommended — high risk."
    elif score >= 50:
        recommendation = "Review advised — medium risk."
    else:
        recommendation = "Low risk — routine action."

    # Confidence is higher the further the score sits from the ambiguous middle.
    confidence = min(99, round(70 + abs(score - 50) * 0.5))

    return ApprovalRiskAssessment(
        score=score,
        action_score=breakdown.action_score,
        resource_score=breakdown.resource_score,
        factors=factors,
        confidence=confidence,
        recommendation=recommendation,
    )


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
