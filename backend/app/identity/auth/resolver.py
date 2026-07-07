"""IdentityContextResolver — validated credentials → IdentityContext (SRS §9, §16)."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.identity.auth.context import IdentityContext
from app.identity.auth.enums import AuthAssuranceLevel, AuthIdentityType, AuthMethod
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
        assurance_level: str = AuthAssuranceLevel.AAL1.value,
        amr: list[str] | None = None,
        mfa_pending: bool = False,
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
            assurance_level=assurance_level,
            amr=list(amr or []),
            mfa_pending=mfa_pending,
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
            # Backward compatible: tokens minted before the assurance seam default
            # to single-factor and no MFA-pending state.
            assurance_level=str(claims.get("assurance_level", AuthAssuranceLevel.AAL1.value)),
            amr=list(claims.get("amr", [])),
            mfa_pending=bool(claims.get("mfa_pending", False)),
            ip_address=ip_address,
            user_agent=user_agent,
            request_id=request_id,
        )
