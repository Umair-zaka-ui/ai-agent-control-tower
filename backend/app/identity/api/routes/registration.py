"""Public registration & email-verification endpoints (4.2.2.3.1 §15).

    POST /api/v1/auth/register             accept an invitation, or self-register
    POST /api/v1/auth/verify-email         redeem a verification token
    POST /api/v1/auth/resend-verification  ask for a new verification link

All three are unauthenticated and therefore rate limited (§19): 5 requests / minute
/ IP. All three refuse to behave as an account-existence oracle (§14).

**Registration never signs you in.** No token is returned. §12 requires the email to
be verified before activation, and handing back a session here would make verification
optional in practice — the user would already be inside.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.identity.ratelimit import rate_limit
from app.identity.registration import RegistrationService, RequestContext
from app.identity.registration.schemas import (
    GenericAcknowledgement,
    RegisterFromInvitationRequest,
    RegistrationResponse,
    ResendVerificationRequest,
    SelfRegisterRequest,
    VerifyEmailRequest,
)

router = APIRouter(prefix="/api/v1/auth", tags=["auth:registration"])


def _context(request: Request) -> RequestContext:
    """Forensic context every registration action records (§20)."""
    return RequestContext(
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        request_id=request.headers.get("x-request-id"),
        correlation_id=request.headers.get("x-correlation-id"),
    )


def _response(result, *, verified_hint: str) -> RegistrationResponse:
    if result.requires_approval:
        message = (
            "Check your email to confirm your address. "
            "An administrator must then approve your account."
        )
    elif result.email_sent:
        message = verified_hint
    else:
        # Honest: the account exists, the link does not. Do not claim we emailed them.
        message = (
            "Your account was created, but we could not send the confirmation email. "
            "Request a new link, or contact your administrator."
        )
    return RegistrationResponse(
        email=result.user.email,
        status=result.status.value,
        email_sent=result.email_sent,
        requires_approval=result.requires_approval,
        message=message,
    )


@router.post(
    "/register",
    response_model=RegistrationResponse,
    status_code=201,
    dependencies=[Depends(rate_limit("register"))],
)
def register_from_invitation(
    payload: RegisterFromInvitationRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> RegistrationResponse:
    """Mode 1 (§3): accept an invitation and set a password.

    The email address comes from the invitation, never from the request body (§11).
    """
    result = RegistrationService(db).register_from_invitation(
        token=payload.token,
        first_name=payload.first_name,
        last_name=payload.last_name,
        password=payload.password,
        phone=payload.phone,
        timezone=payload.timezone,
        language=payload.language,
        job_title=payload.job_title,
        context=_context(request),
    )
    return _response(result, verified_hint="Check your email to confirm your address.")


@router.post(
    "/register/self",
    response_model=RegistrationResponse,
    status_code=201,
    dependencies=[Depends(rate_limit("register"))],
)
def self_register(
    payload: SelfRegisterRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> RegistrationResponse:
    """Mode 3 (§3). Refused with ``REGISTRATION_DISABLED`` unless the organization has
    opted in. Email verification *and* administrator approval are still required."""
    result = RegistrationService(db).register_self_service(
        organization_id=payload.organization_id,
        email=payload.email,
        first_name=payload.first_name,
        last_name=payload.last_name,
        password=payload.password,
        phone=payload.phone,
        timezone=payload.timezone,
        language=payload.language,
        context=_context(request),
    )
    return _response(result, verified_hint="Check your email to confirm your address.")


@router.post(
    "/verify-email",
    response_model=RegistrationResponse,
    dependencies=[Depends(rate_limit("verify_email"))],
)
def verify_email(
    payload: VerifyEmailRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> RegistrationResponse:
    """Redeem a single-use verification token, activating the account (§12).

    In ``SELF_SERVICE`` mode the account stops at ``EMAIL_VERIFIED`` and waits for an
    administrator; the response says so rather than pretending the user can sign in.
    """
    result = RegistrationService(db).verify_email(payload.token, context=_context(request))
    return _response(result, verified_hint="Your email is confirmed. You can now sign in.")


@router.post(
    "/resend-verification",
    response_model=GenericAcknowledgement,
    dependencies=[Depends(rate_limit("resend_verification"))],
)
def resend_verification(
    payload: ResendVerificationRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> GenericAcknowledgement:
    """Always returns the same acknowledgement (§14).

    Unknown address, already-verified address and freshly-resent address are
    indistinguishable to the caller. Rate limiting slows enumeration; only a uniform
    response prevents it.
    """
    RegistrationService(db).resend_verification(payload.email, context=_context(request))
    return GenericAcknowledgement()
