"""Identity API dependencies."""

from __future__ import annotations

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_permission
from app.core.database import get_db
from app.identity.services.identity_service import IdentityService

__all__ = ["get_db", "get_current_user", "require_permission", "get_identity_service", "get_request_id"]


def get_identity_service(db: Session = Depends(get_db)) -> IdentityService:
    return IdentityService(db)


def get_request_id(request: Request) -> str | None:
    """Correlation/request id from the standard header (SRS §19)."""
    return request.headers.get("x-request-id")
