"""Authentication middleware/dependency (SRS §17; 4.2.2.2 §5, §16, §28).

Extracts the credential, validates it, resolves an ``IdentityContext`` and
attaches it to the request. Services depend on the context, never the raw token.

**The session is the source of truth.** As of Part 4.2.2.2 a JWT is no longer
sufficient on its own: if the token carries a ``session_id``, the session is
loaded and revalidated on every request. This is what makes logout, admin
force-logout, idle timeout, absolute timeout and token-reuse termination take
effect *immediately* rather than whenever the access token happens to expire.

Cost: one primary-key lookup per authenticated request (SRS §28 budget: <20ms),
plus at most one throttled UPDATE to slide the idle deadline. See
ADR-0007, which supersedes the stateless-hot-path decision in ADR-0003.

Tokens with **no** ``session_id`` (the legacy ``/auth/login`` surface, and MFA
challenge tokens, which intentionally precede any session) skip the session
check. They remain non-revocable — that is a property of the legacy surface, not
of this dependency, and it disappears when the legacy surface is retired.
"""

from __future__ import annotations

import uuid

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.identity.auth.context import IdentityContext
from app.identity.auth.enums import AuthAssuranceLevel
from app.identity.auth.resolver import IdentityContextResolver
from app.identity.auth.session_lifecycle_service import SessionLifecycleService
from app.identity.auth.token_service import TokenService
from app.identity.errors import ErrorCode, IdentityError
from app.identity.models.session import UserSession

_MACHINE_KEY_PREFIXES = ("agt_live_", "svc_live_", "sk_")


def extract_credential(request: Request) -> tuple[str, str]:
    """Return ``(kind, value)`` where kind is ``"jwt"`` or ``"api_key"``."""
    api_key = request.headers.get("x-api-key")
    if api_key:
        return "api_key", api_key
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        token = header[7:].strip()
        if token.startswith(_MACHINE_KEY_PREFIXES):
            return "api_key", token
        return "jwt", token
    raise IdentityError(ErrorCode.INVALID_CREDENTIALS, "Missing or malformed Authorization header.")


def _validate_session(db: Session, context: IdentityContext) -> None:
    """Load and revalidate the session behind a JWT (SRS §5, §16).

    Raises the specific reason the session is unusable — the client needs to tell
    "you were logged out" apart from "you idled out" apart from "we think your
    token was stolen", because each demands a different UX.
    """
    if context.session_id is None:
        # Legacy token or MFA challenge: no session to check.
        return
    try:
        session_id = uuid.UUID(context.session_id)
    except ValueError as exc:  # malformed claim → treat as a bad credential
        raise IdentityError(ErrorCode.TOKEN_INVALID, "Malformed session claim.") from exc

    session = db.get(UserSession, session_id)
    if session is None:
        raise IdentityError(ErrorCode.SESSION_NOT_FOUND, "Session does not exist.")

    lifecycle = SessionLifecycleService(db)
    lifecycle.assert_usable(session)  # raises on revoked/suspicious/expired/idle

    # Sliding idle window. The write is throttled inside ``touch`` so a busy
    # client does not turn a read-mostly path into a write-mostly one.
    if lifecycle.touch(session):
        db.commit()


def authenticate(
    request: Request,
    db: Session = Depends(get_db),
) -> IdentityContext:
    """FastAPI dependency: resolve the caller's IdentityContext or reject."""
    kind, value = extract_credential(request)
    request_id = request.headers.get("x-request-id")
    ip = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")

    if kind == "jwt":
        claims = TokenService(db).validate_access_token(value)
        context = IdentityContextResolver.from_claims(
            claims, ip_address=ip, user_agent=user_agent, request_id=request_id
        )
        _validate_session(db, context)
        request.state.identity_context = context
        return context

    # Machine credential (API key / client secret) — resolved in Part 4.2.2.
    raise IdentityError(
        ErrorCode.API_KEY_INVALID,
        "API-key authentication is not yet enabled (Part 4.2.2).",
    )


def require_scope(scope: str):
    """Dependency factory: require a scope on the resolved context (SRS §4)."""

    def _checker(context: IdentityContext = Depends(authenticate)) -> IdentityContext:
        # An MFA-pending (challenge) token must never satisfy a protected route;
        # it may only be exchanged at the MFA-verify endpoint (SRS §24).
        if context.needs_mfa_challenge():
            raise IdentityError(ErrorCode.MFA_REQUIRED, "Multi-factor authentication required.")
        if not context.has_scope(scope) and not context.has_permission(scope):
            raise IdentityError(ErrorCode.INSUFFICIENT_SCOPE, f"Missing required scope: {scope}")
        return context

    return _checker


def require_assurance(minimum: str = AuthAssuranceLevel.AAL2.value):
    """Dependency factory: require a minimum assurance level (step-up, SRS §24)."""

    def _checker(context: IdentityContext = Depends(authenticate)) -> IdentityContext:
        if context.needs_mfa_challenge():
            raise IdentityError(ErrorCode.MFA_REQUIRED, "Multi-factor authentication required.")
        if minimum == AuthAssuranceLevel.AAL2.value and not context.mfa_satisfied():
            raise IdentityError(
                ErrorCode.MFA_REQUIRED, "Step-up authentication (MFA) required for this resource."
            )
        return context

    return _checker
