"""Identity session endpoints (SRS §9 api)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.identity.api.deps import get_current_user, get_db, require_permission
from app.identity.errors import ErrorCode, IdentityError
from app.identity.repositories.user_repository import UserRepository
from app.identity.schemas.identity import SessionRead
from app.identity.sessions.manager import SessionManager
from app.models.user import User

router = APIRouter(prefix="/sessions", tags=["identity:sessions"])


@router.get("", response_model=list[SessionRead])
def list_sessions(
    user_id: uuid.UUID = Query(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("user.view")),
):
    """Active sessions for a user in the caller's organization."""
    target = UserRepository(db).get(user_id)
    if target is None or target.organization_id != current_user.organization_id:
        raise IdentityError(ErrorCode.USER_NOT_FOUND, "User does not exist.")
    return SessionManager(db).list_active(user_id)
