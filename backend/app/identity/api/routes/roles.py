"""Identity role endpoints (SRS §9 api). Reuses the RBAC role engine."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.identity.api.deps import get_current_user, get_db, require_permission
from app.identity.roles.engine import RoleEngine
from app.identity.schemas.identity import RoleRead
from app.models.rbac import Role
from app.models.user import User
from sqlalchemy.orm import Session

router = APIRouter(prefix="/roles", tags=["identity:roles"])


@router.get("", response_model=list[RoleRead])
def list_roles(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("user.view")),
) -> list[Role]:
    """System roles + the caller organization's roles."""
    return RoleEngine(db).list_for_organization(current_user.organization_id)
