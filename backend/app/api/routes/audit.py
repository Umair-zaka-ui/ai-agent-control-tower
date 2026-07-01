"""Audit & Compliance Center routes (Phase 3 Part 3.5).

Read-only, RBAC-gated views over the immutable ``audit_logs`` trail: an enriched
filterable table, statistics, a recent-activity timeline, the event-type catalog,
a security dashboard, a compliance summary, per-event detail (with forensic
payloads) and an export feed.

``audit.view`` gates the dashboard / table / detail. The sensitive surfaces —
security & compliance dashboards, export, and raw request/response payloads —
additionally require ``audit.export``.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_permission
from app.core.enums import AgentStatus
from app.models.agent import Agent
from app.models.approval import Approval
from app.models.audit_log import AuditLog
from app.models.policy import Policy
from app.models.user import User
from app.schemas.audit import (
    AuditComplianceSummary,
    AuditEventDetail,
    AuditEventListItem,
    AuditEventTypeInfo,
    AuditSecuritySummary,
    AuditStatistics,
    AuditTimelineItem,
    ComplianceMetric,
)
from app.services import audit_view, rbac_service

router = APIRouter(prefix="/audit", tags=["audit"])

# How many rows to scan before applying derived (Python-side) filters.
_SCAN_CAP = 2000


# --------------------------------------------------------------------------- #
# Table / list
# --------------------------------------------------------------------------- #
@router.get("", response_model=list[AuditEventListItem])
def list_audit(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("audit.view")),
    search: str | None = Query(default=None),
    event_type: str | None = Query(default=None),
    category: str | None = Query(default=None),
    actor_type: str | None = Query(default=None),
    severity: str | None = Query(default=None),
    decision: str | None = Query(default=None),
    event_status: str | None = Query(default=None, alias="status"),
    resource: str | None = Query(default=None),
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[AuditEventListItem]:
    """Enriched, filterable audit table (server-side paginated)."""
    items = _filtered_items(
        db,
        current_user,
        search=search,
        event_type=event_type,
        category=category,
        actor_type=actor_type,
        severity=severity,
        decision=decision,
        event_status=event_status,
        resource=resource,
        date_from=date_from,
        date_to=date_to,
    )
    return items[offset : offset + limit]


@router.get("/statistics", response_model=AuditStatistics)
def audit_statistics(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("audit.view")),
) -> AuditStatistics:
    """Headline counts for the audit dashboard cards."""
    org = current_user.organization_id
    rows = db.execute(
        select(AuditLog.event_type, func.count(AuditLog.id))
        .where(AuditLog.organization_id == org)
        .group_by(AuditLog.event_type)
    ).all()
    counts = {et: n for et, n in rows}
    total = sum(counts.values())

    def _sum(predicate) -> int:
        return sum(n for et, n in counts.items() if predicate(et))

    blocked = _count_blocked(db, org)
    security = (
        _sum(
            lambda et: audit_view.EVENT_CATALOG.get(et, ("", "INFO"))[1] in ("HIGH", "CRITICAL")
            or audit_view.category_of(et) == audit_view.SECURITY
        )
        + blocked
    )
    return AuditStatistics(
        total_events=total,
        security_events=security,
        policy_evaluations=_sum(lambda et: et in audit_view.POLICY_EVAL_EVENTS),
        approval_events=_sum(lambda et: et.startswith("APPROVAL_")),
        authentication_events=_sum(lambda et: et in audit_view.AUTH_EVENTS),
        configuration_changes=_sum(lambda et: et in audit_view.CONFIG_EVENTS),
    )


@router.get("/timeline", response_model=list[AuditTimelineItem])
def audit_timeline(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("audit.view")),
    limit: int = Query(default=15, ge=1, le=100),
) -> list[AuditTimelineItem]:
    """Most recent activity, newest first, with a human-readable label."""
    org = current_user.organization_id
    users, agents = audit_view.name_maps(db, org)
    rows = db.execute(
        select(AuditLog)
        .where(AuditLog.organization_id == org)
        .order_by(AuditLog.created_at.desc())
        .limit(limit)
    ).scalars().all()
    return [
        AuditTimelineItem(
            id=r.id,
            created_at=r.created_at,
            event_type=r.event_type,
            severity=audit_view.severity_of(r),
            actor_name=audit_view.actor_name(r, users, agents),
            label=audit_view.timeline_label(r, users, agents),
        )
        for r in rows
    ]


@router.get("/events", response_model=list[AuditEventTypeInfo])
def audit_event_catalog(
    current_user: User = Depends(require_permission("audit.view")),
) -> list[AuditEventTypeInfo]:
    """The supported event-type catalog (for filter dropdowns / reference)."""
    return audit_view.event_catalog()


@router.get("/security", response_model=AuditSecuritySummary)
def audit_security(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("audit.export")),
) -> AuditSecuritySummary:
    """Security-focused aggregation (failed logins, blocked agents, alerts...)."""
    org = current_user.organization_id
    users, agents = audit_view.name_maps(db, org)

    failed_logins = _count_type(db, org, "AUTH_LOGIN_FAILED")
    disabled_api_keys = _count_type(db, org, "API_KEY_REVOKED")
    critical_alerts = _count_type(db, org, "SECURITY_ALERT")
    blocked_actions = _count_blocked(db, org)
    permission_violations = _count_permission_violations(db, org)
    blocked_agents = db.execute(
        select(func.count(Agent.id)).where(
            Agent.organization_id == org,
            Agent.status.in_([AgentStatus.SUSPENDED, AgentStatus.BLOCKED]),
        )
    ).scalar_one() or 0

    # Recent security-relevant events (scan a recent window, derive, filter).
    recent_logs = db.execute(
        select(AuditLog)
        .where(AuditLog.organization_id == org)
        .order_by(AuditLog.created_at.desc())
        .limit(300)
    ).scalars().all()
    recent = [
        audit_view.to_list_item(r, users, agents)
        for r in recent_logs
        if audit_view.is_security_event(r)
    ][:25]

    return AuditSecuritySummary(
        failed_logins=failed_logins,
        blocked_agents=blocked_agents,
        disabled_api_keys=disabled_api_keys,
        permission_violations=permission_violations,
        suspicious_activity=blocked_actions,
        critical_alerts=critical_alerts,
        recent=recent,
    )


@router.get("/compliance", response_model=AuditComplianceSummary)
def audit_compliance(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("audit.export")),
) -> AuditComplianceSummary:
    """Informational compliance posture derived from current configuration."""
    org = current_user.organization_id

    def _count(model, *where) -> int:
        return db.execute(select(func.count(model.id)).where(*where)).scalar_one() or 0

    total_policies = _count(Policy, Policy.organization_id == org)
    enabled_policies = _count(Policy, Policy.organization_id == org, Policy.enabled.is_(True))
    approvals = _count(Approval, Approval.organization_id == org)
    audit_total = _count(AuditLog, AuditLog.organization_id == org)

    policy_pct = round((enabled_policies / total_policies) * 100) if total_policies else 0
    approval_pct = 100 if approvals else 0
    audit_pct = 100 if audit_total else 0
    # Posture frameworks: heuristic blend of the controls we can observe.
    base = round((policy_pct + approval_pct + audit_pct) / 3)

    def metric(label: str, score: int, detail: str) -> ComplianceMetric:
        status_label = "Ready" if score >= 80 else "In progress" if score >= 50 else "Attention"
        return ComplianceMetric(label=label, score=score, status=status_label, detail=detail)

    return AuditComplianceSummary(
        hipaa_readiness=metric(
            "HIPAA Readiness", min(100, base), "PHI access governed by policy + audited."
        ),
        soc2_readiness=metric(
            "SOC 2 Readiness", min(100, base), "Access control, change mgmt and monitoring in place."
        ),
        iso27001_controls=metric(
            "ISO 27001 Controls", min(100, max(0, base - 5)), "Information-security controls coverage."
        ),
        policy_coverage=metric(
            "Policy Coverage", policy_pct, f"{enabled_policies} of {total_policies} policies enabled."
        ),
        approval_coverage=metric(
            "Approval Coverage", approval_pct, f"{approvals} approvals tracked."
        ),
        audit_completeness=metric(
            "Audit Completeness", audit_pct, f"{audit_total} events recorded immutably."
        ),
    )


@router.get("/export", response_model=list[AuditEventListItem])
def audit_export(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("audit.export")),
    search: str | None = Query(default=None),
    event_type: str | None = Query(default=None),
    category: str | None = Query(default=None),
    actor_type: str | None = Query(default=None),
    severity: str | None = Query(default=None),
    decision: str | None = Query(default=None),
    event_status: str | None = Query(default=None, alias="status"),
    resource: str | None = Query(default=None),
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
) -> list[AuditEventListItem]:
    """The full filtered event set for CSV/JSON export (no pagination cap)."""
    return _filtered_items(
        db,
        current_user,
        search=search,
        event_type=event_type,
        category=category,
        actor_type=actor_type,
        severity=severity,
        decision=decision,
        event_status=event_status,
        resource=resource,
        date_from=date_from,
        date_to=date_to,
    )


@router.get("/{event_id}", response_model=AuditEventDetail)
def get_audit_event(
    event_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("audit.view")),
) -> AuditEventDetail:
    """Full forensic detail for a single event, plus the related-event flow."""
    log = db.get(AuditLog, event_id)
    if log is None or log.organization_id != current_user.organization_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Audit event not found.")

    users, agents = audit_view.name_maps(db, current_user.organization_id)
    base = audit_view.to_list_item(log, users, agents)
    meta = log.meta or {}

    can_export = rbac_service.user_has_permission(db, current_user, "audit.export")
    approval_id = None
    if log.entity_type == "approval" and log.entity_id:
        approval_id = log.entity_id
    elif isinstance(meta.get("approval_id"), str):
        try:
            approval_id = uuid.UUID(meta["approval_id"])
        except ValueError:
            approval_id = None

    risk = meta.get("risk_score")
    return AuditEventDetail(
        **base.model_dump(),
        correlation_id=log.trace_id,
        session_id=log.request_id,
        ip_address=log.ip_address,
        user_agent=log.user_agent,
        reason=meta.get("decision_reason") or meta.get("reason"),
        policy=meta.get("matched_policy"),
        approval_id=approval_id,
        risk_score=risk if isinstance(risk, int) else None,
        metadata=meta,
        request_payload=(log.before_state if can_export else None),
        response_payload=(log.after_state if can_export else None),
        related_events=audit_view.related_events(db, log, users, agents),
    )


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _filtered_items(
    db: Session,
    current_user: User,
    *,
    search: str | None,
    event_type: str | None,
    category: str | None,
    actor_type: str | None,
    severity: str | None,
    decision: str | None,
    event_status: str | None,
    resource: str | None,
    date_from: datetime | None,
    date_to: datetime | None,
) -> list[AuditEventListItem]:
    org = current_user.organization_id
    stmt = select(AuditLog).where(AuditLog.organization_id == org)
    if event_type:
        stmt = stmt.where(AuditLog.event_type == event_type)
    if actor_type:
        stmt = stmt.where(AuditLog.actor_type == actor_type.upper())
    if date_from:
        stmt = stmt.where(AuditLog.created_at >= _aware(date_from))
    if date_to:
        stmt = stmt.where(AuditLog.created_at <= _aware(date_to))
    stmt = stmt.order_by(AuditLog.created_at.desc()).limit(_SCAN_CAP)
    logs = db.execute(stmt).scalars().all()

    users, agents = audit_view.name_maps(db, org)
    items = [audit_view.to_list_item(log, users, agents) for log in logs]

    if category:
        items = [it for it in items if it.category == category]
    if severity:
        items = [it for it in items if it.severity == severity.upper()]
    if decision:
        items = [it for it in items if (it.decision or "") == decision]
    if event_status:
        items = [it for it in items if it.status.lower() == event_status.lower()]
    if resource:
        items = [it for it in items if (it.resource or "").upper() == resource.upper()]
    if search:
        needle = search.strip().lower()
        items = [it for it in items if _matches(it, needle)]
    return items


def _matches(item: AuditEventListItem, needle: str) -> bool:
    hay = " ".join(
        str(v).lower()
        for v in (
            item.id,
            item.event_type,
            item.actor_name or "",
            item.resource or "",
            item.action or "",
            item.entity_id or "",
            item.request_id or "",
        )
    )
    return needle in hay


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _count_type(db: Session, org: uuid.UUID, event_type: str) -> int:
    return db.execute(
        select(func.count(AuditLog.id)).where(
            AuditLog.organization_id == org, AuditLog.event_type == event_type
        )
    ).scalar_one() or 0


def _count_blocked(db: Session, org: uuid.UUID) -> int:
    return db.execute(
        select(func.count(AuditLog.id)).where(
            AuditLog.organization_id == org,
            AuditLog.event_type == "AGENT_ACTION_DECISION",
            AuditLog.after_state["decision"].astext == "BLOCK",
        )
    ).scalar_one() or 0


def _count_permission_violations(db: Session, org: uuid.UUID) -> int:
    return db.execute(
        select(func.count(AuditLog.id)).where(
            AuditLog.organization_id == org,
            AuditLog.event_type == "AGENT_ACTION_DECISION",
            AuditLog.after_state["decision"].astext == "BLOCK",
            AuditLog.meta["decision_reason"].astext.ilike("%permission%"),
        )
    ).scalar_one() or 0
