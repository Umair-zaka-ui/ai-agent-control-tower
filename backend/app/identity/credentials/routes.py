"""Credential-management endpoints (SRS §22).

    POST /api/v1/auth/change-password        change your own password
    POST /api/v1/auth/admin/reset-password   admin: issue a temporary password
    POST /api/v1/auth/validate-password      strength/validity, no side effects
    GET  /api/v1/auth/password-policy        the active policy, as data
    GET  /api/v1/auth/password-expiration    your own expiry status
    GET  /api/v1/security/password-dashboard org-wide credential posture (admin)

HTTP concerns only; all logic lives in the credential services. Self-service
routes authenticate with the session-backed ``authenticate`` dependency (so a
password change can revoke the caller's *other* sessions while keeping this one);
admin routes additionally require an RBAC permission.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.identity.api.deps import require_permission
from app.identity.auth.authentication_service import AuthenticationService
from app.identity.auth.context import IdentityContext
from app.identity.auth.dependency import authenticate
from app.identity.credentials.audit import CredentialContext
from app.identity.credentials.policy_service import PasswordPolicyService
from app.identity.credentials.reset_service import PasswordResetService
from app.identity.credentials.service import CredentialService
from app.identity.credentials.schemas import (
    AdminResetRequest,
    AdminResetResponse,
    ChangePasswordRequest,
    ChangePasswordResponse,
    PasswordDashboardResponse,
    PasswordDashboardUser,
    PasswordExpirationResponse,
    PasswordPolicyResponse,
    ValidatePasswordRequest,
    ValidatePasswordResponse,
)
from app.identity.errors import ErrorCode, IdentityError
from app.identity.models.enums import SessionRevocationReason
from app.identity.ratelimit import rate_limit
from app.models.user import User

router = APIRouter(prefix="/api/v1/auth", tags=["auth:credentials"])
security_router = APIRouter(prefix="/api/v1/security", tags=["security:credentials"])


def _context(request: Request) -> CredentialContext:
    return CredentialContext(
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        request_id=request.headers.get("x-request-id"),
        correlation_id=request.headers.get("x-correlation-id"),
    )


def _load_user(db: Session, identity_id: str) -> User:
    user = db.get(User, uuid.UUID(identity_id))
    if user is None:
        raise IdentityError(ErrorCode.USER_NOT_FOUND, "User does not exist.")
    return user


# --------------------------------------------------------------------------- #
# Change password (self-service)
# --------------------------------------------------------------------------- #
@router.post("/change-password", response_model=ChangePasswordResponse)
def change_password(
    payload: ChangePasswordRequest,
    request: Request,
    context: IdentityContext = Depends(authenticate),
    db: Session = Depends(get_db),
) -> ChangePasswordResponse:
    user = _load_user(db, context.identity_id)
    current_session_id = (
        uuid.UUID(context.session_id) if context.session_id else None
    )

    def revoke_others(user_id: uuid.UUID, _reason: str) -> int:
        auth = AuthenticationService(db)
        return len(
            auth.logout_all(
                user_id,
                except_session_id=current_session_id,
                reason=SessionRevocationReason.SECURITY_EVENT,
                request_id=request.headers.get("x-request-id"),
            )
        )

    service = CredentialService(db, revoke_sessions=revoke_others)
    service.change_password(
        user,
        current_password=payload.current_password,
        new_password=payload.new_password,
        context=_context(request),
        revoke_other_sessions=payload.revoke_other_sessions,
    )
    return ChangePasswordResponse(
        message="Your password has been changed.",
        password_expires_at=(
            user.password_expires_at.isoformat() if user.password_expires_at else None
        ),
    )


# --------------------------------------------------------------------------- #
# Admin reset
# --------------------------------------------------------------------------- #
@router.post("/admin/reset-password", response_model=AdminResetResponse)
def admin_reset_password(
    payload: AdminResetRequest,
    request: Request,
    actor: User = Depends(require_permission("credential.reset")),
    db: Session = Depends(get_db),
) -> AdminResetResponse:
    target = db.get(User, payload.user_id)
    # An administrator may only reset within their own organization (SRS §16).
    if target is None or target.organization_id != actor.organization_id:
        raise IdentityError(ErrorCode.USER_NOT_FOUND, "User does not exist.")

    def revoke_all(user_id: uuid.UUID, _reason: str) -> int:
        auth = AuthenticationService(db)
        return len(
            auth.logout_all(
                user_id,
                reason=SessionRevocationReason.PASSWORD_RESET,
                request_id=request.headers.get("x-request-id"),
            )
        )

    service = PasswordResetService(db, revoke_sessions=revoke_all)
    result = service.admin_reset(target, actor=actor, context=_context(request))
    return AdminResetResponse(
        user_id=target.id,
        temporary_password=result.password,
        expires_at=result.expires_at.isoformat(),
    )


# --------------------------------------------------------------------------- #
# Validate / strength (rate limited — SRS §25)
# --------------------------------------------------------------------------- #
@router.post(
    "/validate-password",
    response_model=ValidatePasswordResponse,
    dependencies=[Depends(rate_limit("validate_password", limit=20))],
)
def validate_password(
    payload: ValidatePasswordRequest,
    context: IdentityContext = Depends(authenticate),
    db: Session = Depends(get_db),
) -> ValidatePasswordResponse:
    user = _load_user(db, context.identity_id)
    result = PasswordPolicyService.strength(payload.password, user=user)
    return ValidatePasswordResponse(**result)


# --------------------------------------------------------------------------- #
# Policy (readable by any authenticated user; it is not a secret)
# --------------------------------------------------------------------------- #
@router.get("/password-policy", response_model=PasswordPolicyResponse)
def password_policy(
    _context: IdentityContext = Depends(authenticate),
) -> PasswordPolicyResponse:
    return PasswordPolicyResponse(**PasswordPolicyService.describe())


@router.get("/password-expiration", response_model=PasswordExpirationResponse)
def password_expiration(
    context: IdentityContext = Depends(authenticate),
    db: Session = Depends(get_db),
) -> PasswordExpirationResponse:
    user = _load_user(db, context.identity_id)
    return PasswordExpirationResponse(**PasswordPolicyService.expiration_status(user))


# --------------------------------------------------------------------------- #
# Security dashboard (admin)
# --------------------------------------------------------------------------- #
def _dashboard_user(user: User) -> PasswordDashboardUser:
    return PasswordDashboardUser(
        user_id=user.id,
        name=user.name,
        email=user.email,
        expires_at=user.password_expires_at.isoformat() if user.password_expires_at else None,
        days_until_expiry=PasswordPolicyService.days_until_expiry(user),
        is_expired=PasswordPolicyService.is_expired(user),
        must_change=bool(user.must_change_password),
    )


@security_router.get("/password-dashboard", response_model=PasswordDashboardResponse)
def password_dashboard(
    actor: User = Depends(require_permission("credential.dashboard")),
    db: Session = Depends(get_db),
) -> PasswordDashboardResponse:
    """Org-wide credential posture (SRS §17): who is expired, expiring, on a
    temporary password, or otherwise required to change."""
    users = list(
        db.scalars(select(User).where(User.organization_id == actor.organization_id))
    )
    expired, expiring, temporary, must_change = [], [], [], []
    for user in users:
        if PasswordPolicyService.is_expired(user):
            expired.append(_dashboard_user(user))
        elif PasswordPolicyService.is_in_warning_window(user):
            expiring.append(_dashboard_user(user))
        if user.must_change_password:
            temporary.append(_dashboard_user(user))
            must_change.append(_dashboard_user(user))
    return PasswordDashboardResponse(
        expired=expired,
        expiring_soon=expiring,
        temporary=temporary,
        must_change=must_change,
        total_users=len(users),
    )
