"""System routes - operational health of the platform's subsystems."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.user import User
from app.schemas.dashboard import SystemHealth

router = APIRouter(prefix="/system", tags=["system"])

HEALTHY = "healthy"
OFFLINE = "offline"


@router.get("/health", response_model=SystemHealth)
def system_health(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SystemHealth:
    """Report subsystem health for the dashboard's System Health widget.

    The API, policy/approval/audit engines run in-process with this request, so
    if this handler executes they are healthy. The database is probed with a
    lightweight ``SELECT 1``.
    """
    try:
        db.execute(text("SELECT 1"))
        database = HEALTHY
    except Exception:  # pragma: no cover - defensive
        database = OFFLINE

    return SystemHealth(
        api=HEALTHY,
        database=database,
        policy_engine=HEALTHY,
        approval_engine=HEALTHY,
        audit=HEALTHY,
    )
