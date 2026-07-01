"""Audit view service (Phase 3 Part 3.5).

Turns raw ``audit_logs`` rows into the enriched events the Audit & Compliance
Center renders: derived severity / category / decision / status / human status,
resolved actor names, and the related-event graph. Nothing here writes — it only
reads and projects existing audit data.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.agent import Agent
from app.models.audit_log import AuditLog
from app.models.user import User
from app.schemas.audit import (
    AuditEventListItem,
    AuditEventTypeInfo,
    AuditRelatedEvent,
)

# --------------------------------------------------------------------------- #
# Event-type catalog: category + baseline severity
# --------------------------------------------------------------------------- #
AUTHENTICATION = "AUTHENTICATION"
AGENT = "AGENT"
API_KEY = "API_KEY"
POLICY = "POLICY"
APPROVAL = "APPROVAL"
ADMIN = "ADMINISTRATION"
CONFIG = "CONFIGURATION"
SECURITY = "SECURITY"

# event_type -> (category, baseline severity)
EVENT_CATALOG: dict[str, tuple[str, str]] = {
    "AUTH_LOGIN": (AUTHENTICATION, "INFO"),
    "AUTH_LOGOUT": (AUTHENTICATION, "INFO"),
    "AUTH_LOGIN_FAILED": (SECURITY, "HIGH"),
    "USER_REGISTERED": (AUTHENTICATION, "INFO"),
    "AGENT_CREATED": (AGENT, "LOW"),
    "AGENT_UPDATED": (AGENT, "LOW"),
    "AGENT_STATUS_CHANGED": (AGENT, "MEDIUM"),
    "AGENT_DELETED": (AGENT, "HIGH"),
    "AGENT_ACTION_DECISION": (AGENT, "INFO"),
    "API_KEY_ISSUED": (API_KEY, "MEDIUM"),
    "API_KEY_REVOKED": (API_KEY, "MEDIUM"),
    "POLICY_CREATED": (POLICY, "LOW"),
    "POLICY_UPDATED": (POLICY, "LOW"),
    "POLICY_DELETED": (POLICY, "HIGH"),
    "POLICY_TESTED": (POLICY, "INFO"),
    "POLICY_TRIGGERED": (POLICY, "MEDIUM"),
    "APPROVAL_REQUESTED": (APPROVAL, "MEDIUM"),
    "APPROVAL_APPROVED": (APPROVAL, "INFO"),
    "APPROVAL_REJECTED": (APPROVAL, "MEDIUM"),
    "APPROVAL_ESCALATED": (APPROVAL, "HIGH"),
    "APPROVAL_ASSIGNED": (APPROVAL, "INFO"),
    "APPROVAL_COMMENTED": (APPROVAL, "INFO"),
    "USER_CREATED": (ADMIN, "LOW"),
    "USER_UPDATED": (ADMIN, "LOW"),
    "ROLE_ASSIGNED": (ADMIN, "MEDIUM"),
    "ORGANIZATION_CREATED": (CONFIG, "INFO"),
    "SYSTEM_CONFIGURATION": (CONFIG, "MEDIUM"),
    "SECURITY_ALERT": (SECURITY, "CRITICAL"),
}

_SEVERITY_ORDER = {"INFO": 0, "LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}

# Categories that count toward each statistics bucket.
AUTH_EVENTS = {"AUTH_LOGIN", "AUTH_LOGOUT", "AUTH_LOGIN_FAILED", "USER_REGISTERED"}
POLICY_EVAL_EVENTS = {"AGENT_ACTION_DECISION", "POLICY_TRIGGERED", "POLICY_TESTED"}
CONFIG_EVENTS = {
    "SYSTEM_CONFIGURATION",
    "ORGANIZATION_CREATED",
    "AGENT_UPDATED",
    "AGENT_STATUS_CHANGED",
    "POLICY_UPDATED",
    "ROLE_ASSIGNED",
    "USER_UPDATED",
}


def humanize(token: str | None) -> str:
    if not token:
        return ""
    return token.replace("_", " ").title()


def category_of(event_type: str) -> str:
    return EVENT_CATALOG.get(event_type, (CONFIG, "INFO"))[0]


def severity_of(log: AuditLog) -> str:
    """Derive severity from event type, then escalate using decision/risk."""
    base = EVENT_CATALOG.get(log.event_type, (CONFIG, "INFO"))[1]
    meta = log.meta or {}
    decision = _decision_of(log)
    if decision == "BLOCK":
        base = _max_sev(base, "HIGH")
    elif decision == "PENDING_APPROVAL":
        base = _max_sev(base, "MEDIUM")
    risk = meta.get("risk_score")
    if isinstance(risk, (int, float)) and not isinstance(risk, bool):
        if risk >= 90:
            base = _max_sev(base, "HIGH")
        elif risk >= 70:
            base = _max_sev(base, "MEDIUM")
    return base


def _max_sev(a: str, b: str) -> str:
    return a if _SEVERITY_ORDER.get(a, 0) >= _SEVERITY_ORDER.get(b, 0) else b


def _decision_of(log: AuditLog) -> str | None:
    meta = log.meta or {}
    if isinstance(meta.get("decision"), str):
        return meta["decision"]
    after = log.after_state or {}
    if isinstance(after.get("decision"), str):
        return after["decision"]
    return None


def _status_of(log: AuditLog) -> str:
    decision = _decision_of(log)
    if decision == "BLOCK":
        return "Blocked"
    if decision == "PENDING_APPROVAL":
        return "Pending"
    if decision == "ALLOW":
        return "Allowed"
    mapping = {
        "APPROVAL_APPROVED": "Approved",
        "APPROVAL_REJECTED": "Rejected",
        "APPROVAL_ESCALATED": "Escalated",
        "APPROVAL_REQUESTED": "Pending",
        "AUTH_LOGIN_FAILED": "Failed",
        "AGENT_DELETED": "Deleted",
        "API_KEY_REVOKED": "Revoked",
        "SECURITY_ALERT": "Alert",
    }
    return mapping.get(log.event_type, "Recorded")


def is_security_event(log: AuditLog) -> bool:
    if EVENT_CATALOG.get(log.event_type, (CONFIG, "INFO"))[0] == SECURITY:
        return True
    if _decision_of(log) == "BLOCK":
        return True
    return _SEVERITY_ORDER.get(severity_of(log), 0) >= _SEVERITY_ORDER["HIGH"]


# --------------------------------------------------------------------------- #
# Name resolution
# --------------------------------------------------------------------------- #
def name_maps(db: Session, org_id: uuid.UUID) -> tuple[dict, dict]:
    users = {
        uid: name
        for uid, name in db.execute(
            select(User.id, User.name).where(User.organization_id == org_id)
        ).all()
    }
    agents = {
        aid: name
        for aid, name in db.execute(
            select(Agent.id, Agent.name).where(Agent.organization_id == org_id)
        ).all()
    }
    return users, agents


def actor_name(log: AuditLog, users: dict, agents: dict) -> str | None:
    if log.actor_type.value == "SYSTEM":
        return "System"
    if log.actor_type.value == "AGENT":
        return agents.get(log.actor_id)
    return users.get(log.actor_id)


def _resource_of(log: AuditLog) -> str | None:
    meta = log.meta or {}
    return meta.get("resource") or (log.entity_type if log.entity_type else None)


def to_list_item(log: AuditLog, users: dict, agents: dict) -> AuditEventListItem:
    meta = log.meta or {}
    return AuditEventListItem(
        id=log.id,
        created_at=log.created_at,
        event_type=log.event_type,
        category=category_of(log.event_type),
        actor_type=log.actor_type.value,
        actor_id=log.actor_id,
        actor_name=actor_name(log, users, agents),
        resource=_resource_of(log),
        action=meta.get("action"),
        decision=_decision_of(log),
        severity=severity_of(log),
        status=_status_of(log),
        entity_type=log.entity_type,
        entity_id=log.entity_id,
        request_id=log.request_id,
    )


def related_events(
    db: Session, log: AuditLog, users: dict, agents: dict, limit: int = 12
) -> list[AuditRelatedEvent]:
    """Events sharing this event's request/trace id (the same logical flow)."""
    correlation = log.request_id or log.trace_id
    if not correlation:
        return []
    stmt = (
        select(AuditLog)
        .where(
            AuditLog.organization_id == log.organization_id,
            (AuditLog.request_id == correlation) | (AuditLog.trace_id == correlation),
        )
        .order_by(AuditLog.created_at)
        .limit(limit)
    )
    rows = db.execute(stmt).scalars().all()
    return [
        AuditRelatedEvent(
            id=r.id,
            event_type=r.event_type,
            actor_name=actor_name(r, users, agents),
            created_at=r.created_at,
            severity=severity_of(r),
        )
        for r in rows
    ]


def event_catalog() -> list[AuditEventTypeInfo]:
    return [
        AuditEventTypeInfo(value=ev, label=humanize(ev), category=cat, severity=sev)
        for ev, (cat, sev) in EVENT_CATALOG.items()
    ]


def timeline_label(log: AuditLog, users: dict, agents: dict) -> str:
    actor = actor_name(log, users, agents) or "System"
    meta = log.meta or {}
    verb = humanize(log.event_type)
    resource = _resource_of(log)
    if log.event_type == "AGENT_ACTION_DECISION":
        return f"{actor} {humanize(meta.get('action'))} on {resource} → {_decision_of(log)}"
    if resource and log.event_type not in AUTH_EVENTS:
        return f"{actor} · {verb} · {resource}"
    return f"{actor} · {verb}"
