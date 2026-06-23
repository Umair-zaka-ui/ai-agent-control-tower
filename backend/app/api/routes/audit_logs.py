"""Audit log routes - read-only access to the event trail."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.audit_log import AuditLog
from app.models.user import User
from app.schemas.audit_log import AuditLogRead

router = APIRouter(prefix="/audit-logs", tags=["audit-logs"])


@router.get("", response_model=list[AuditLogRead])
def list_audit_logs(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    event_type: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[AuditLog]:
    """List audit logs in the caller's organization (newest first)."""
    stmt = select(AuditLog).where(
        AuditLog.organization_id == current_user.organization_id
    )
    if event_type is not None:
        stmt = stmt.where(AuditLog.event_type == event_type)
    stmt = stmt.order_by(AuditLog.created_at.desc()).limit(limit).offset(offset)
    return list(db.execute(stmt).scalars().all())


@router.get("/entity/{entity_type}/{entity_id}", response_model=list[AuditLogRead])
def list_entity_audit_logs(
    entity_type: str,
    entity_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[AuditLog]:
    """List all audit logs recorded for a specific entity."""
    stmt = (
        select(AuditLog)
        .where(
            AuditLog.organization_id == current_user.organization_id,
            AuditLog.entity_type == entity_type,
            AuditLog.entity_id == entity_id,
        )
        .order_by(AuditLog.created_at.desc())
    )
    return list(db.execute(stmt).scalars().all())
