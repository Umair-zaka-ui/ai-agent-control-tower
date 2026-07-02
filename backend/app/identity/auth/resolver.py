"""IdentityContextResolver — validated credentials → IdentityContext (SRS §9, §16)."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.identity.auth.context import IdentityContext
from app.identity.auth.enums import AuthIdentityType, AuthMethod
from app.identity.roles.engine import RoleEngine
from app.models.user import User
from app.services import rbac_service


class IdentityContextResolver:
    def __init__(self, db: Session) -> None:
        self.db = db

    def from_user(
        self,
        user: User,
        *,
        auth_method: AuthMethod,
        session_id: str | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
        request_id: str | None = None,
    ) -> IdentityContext:
        roles = [r.name for r in RoleEngine(self.db).roles_for_user(user.id)]
        permissions = sorted(rbac_service.get_user_permissions(self.db, user))
        return IdentityContext(
            identity_id=str(user.id),
            identity_type=AuthIdentityType.HUMAN_USER.value,
            auth_method=auth_method.value,
            organization_id=str(user.organization_id),
            roles=roles,
            permissions=permissions,
            session_id=session_id,
            ip_address=ip_address,
            user_agent=user_agent,
            request_id=request_id,
        )

    @staticmethod
    def from_claims(
        claims: dict[str, Any],
        *,
        ip_address: str | None = None,
        user_agent: str | None = None,
        request_id: str | None = None,
    ) -> IdentityContext:
        """Rebuild the context from a validated access-token claim set."""
        return IdentityContext(
            identity_id=str(claims.get("identity_id") or claims.get("sub")),
            identity_type=str(claims.get("identity_type", AuthIdentityType.HUMAN_USER.value)),
            auth_method=str(claims.get("auth_method", AuthMethod.JWT.value)),
            organization_id=claims.get("organization_id"),
            roles=list(claims.get("roles", [])),
            permissions=list(claims.get("permissions", [])),
            scopes=list(claims.get("scopes", [])),
            session_id=claims.get("session_id"),
            credential_id=claims.get("credential_id"),
            ip_address=ip_address,
            user_agent=user_agent,
            request_id=request_id,
        )
