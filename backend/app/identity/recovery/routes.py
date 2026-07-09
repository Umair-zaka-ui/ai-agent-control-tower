"""Recovery endpoints (4.2.2.3.3 §21).

    POST /api/v1/auth/forgot-password     request a reset link (uniform response)
    POST /api/v1/auth/reset-password      redeem a reset token, set a new password
    POST /api/v1/auth/change-email        request an email change (re-auth required)
    POST /api/v1/auth/verify-new-email    confirm a new address, swap it in
    GET  /api/v1/security/recovery-events org-wide recovery activity (admin)

Public endpoints are rate limited (§15) and enumeration-safe (§9). ``change-email``
is authenticated. HTTP concerns only; all logic is in the recovery services.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.identity.api.deps import require_permission
from app.identity.auth.authentication_service import AuthenticationService
from app.identity.auth.context import IdentityContext
from app.identity.auth.dependency import authenticate
from app.identity.models.enums import SessionRevocationReason
from app.identity.recovery import RECOVERY_EVENT_TYPES, RecoveryService
from app.identity.recovery.audit import RecoveryContext
from app.identity.recovery.schemas import (
    ChangeEmailRequest,
    ForgotPasswordRequest,
    RecoveryAck,
    RecoveryEventRead,
    ResetPasswordRequest,
    VerifyNewEmailRequest,
)
from app.identity.errors import ErrorCode, IdentityError
from app.identity.ratelimit import rate_limit
from app.identity.repositories.security_event_repository import SecurityEventRepository
from app.models.user import User

router = APIRouter(prefix="/api/v1/auth", tags=["auth:recovery"])
security_router = APIRouter(prefix="/api/v1/security", tags=["security:recovery"])

# The uniform answer a forgot-password / reset request always gives (§9).
_UNIFORM_MESSAGE = "If an account exists, recovery instructions have been sent."


def _context(request: Request) -> RecoveryContext:
    return RecoveryContext(
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        request_id=request.headers.get("x-request-id"),
        correlation_id=request.headers.get("x-correlation-id"),
    )


def _revoker(db: Session, request: Request):
    def revoke_all(user_id: uuid.UUID, _reason: str) -> int:
        return len(
            AuthenticationService(db).logout_all(
                user_id,
                reason=SessionRevocationReason.PASSWORD_RESET,
                request_id=request.headers.get("x-request-id"),
            )
        )

    return revoke_all


# --------------------------------------------------------------------------- #
# Forgot / reset password
# --------------------------------------------------------------------------- #
@router.post(
    "/forgot-password",
    response_model=RecoveryAck,
    dependencies=[Depends(rate_limit("forgot_password"))],
)
def forgot_password(
    payload: ForgotPasswordRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> RecoveryAck:
    """Always returns the same acknowledgement (§9), whether or not the account
    exists — the response and its timing must never be an existence oracle."""
    RecoveryService(db).forgot_password(str(payload.email), context=_context(request))
    return RecoveryAck(message=_UNIFORM_MESSAGE)


@router.post(
    "/reset-password",
    response_model=RecoveryAck,
    dependencies=[Depends(rate_limit("reset_password"))],
)
def reset_password(
    payload: ResetPasswordRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> RecoveryAck:
    """Redeem the single-use token and set the new password. Revokes every session (§13)."""
    service = RecoveryService(db, revoke_sessions=_revoker(db, request))
    service.reset_password(payload.token, payload.new_password, context=_context(request))
    return RecoveryAck(
        message="Your password has been reset. Please sign in with your new password."
    )


# --------------------------------------------------------------------------- #
# Email change (authenticated) + confirmation (public token redeem)
# --------------------------------------------------------------------------- #
@router.post("/change-email", response_model=RecoveryAck)
def change_email(
    payload: ChangeEmailRequest,
    request: Request,
    context: IdentityContext = Depends(authenticate),
    db: Session = Depends(get_db),
) -> RecoveryAck:
    """Request an email change. Re-authenticates, then emails the *new* address a
    confirmation link; the current address stays in effect until it is confirmed."""
    user = db.get(User, uuid.UUID(context.identity_id))
    if user is None:
        raise IdentityError(ErrorCode.USER_NOT_FOUND, "User does not exist.")
    RecoveryService(db).change_email(
        user,
        new_email=str(payload.new_email),
        current_password=payload.current_password,
        context=_context(request),
    )
    return RecoveryAck(
        message="Check your new email address for a link to confirm the change."
    )


@router.post(
    "/verify-new-email",
    response_model=RecoveryAck,
    dependencies=[Depends(rate_limit("verify_new_email"))],
)
def verify_new_email(
    payload: VerifyNewEmailRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> RecoveryAck:
    RecoveryService(db).verify_new_email(payload.token, context=_context(request))
    return RecoveryAck(message="Your email address has been updated.")


# --------------------------------------------------------------------------- #
# Recovery dashboard (admin)
# --------------------------------------------------------------------------- #
@security_router.get("/recovery-events", response_model=list[RecoveryEventRead])
def recovery_events(
    actor: User = Depends(require_permission("recovery.view")),
    db: Session = Depends(get_db),
    limit: int = 100,
) -> list[RecoveryEventRead]:
    """Org-wide recovery activity (§18): reset requests, completions, failures,
    email changes and expiries. Reused from the single security-event stream."""
    events = SecurityEventRepository(db).list_for_organization(
        actor.organization_id,
        event_types=RECOVERY_EVENT_TYPES,
        limit=min(max(limit, 1), 500),
    )
    return [RecoveryEventRead.from_event(e) for e in events]
