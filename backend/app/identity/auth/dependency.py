"""Authentication middleware/dependency (SRS §17).

Extracts the credential, validates it, resolves an ``IdentityContext`` and
attaches it to the request. Services depend on the context, never the raw token.

JWT access tokens are fully resolved here. API-key / client-credential
resolution (agents, service accounts, external clients) is wired to the
credential store in Part 4.2.2 — the extraction + dispatch is in place and
returns a clear ``API_KEY_INVALID`` until then, so machine auth cannot silently
succeed.
"""

from __future__ import annotations

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.identity.auth.context import IdentityContext
from app.identity.auth.enums import AuthAssuranceLevel
from app.identity.auth.resolver import IdentityContextResolver
from app.identity.auth.token_service import TokenService
from app.identity.errors import ErrorCode, IdentityError

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
    """Dependency factory: require a minimum assurance level (step-up, SRS §24).

    Gate sensitive routes (billing, key issuance, policy changes) behind
    multi-factor authentication. A challenge token is rejected outright; a
    single-factor token is rejected when AAL2 is demanded.
    """

    def _checker(context: IdentityContext = Depends(authenticate)) -> IdentityContext:
        if context.needs_mfa_challenge():
            raise IdentityError(ErrorCode.MFA_REQUIRED, "Multi-factor authentication required.")
        if minimum == AuthAssuranceLevel.AAL2.value and not context.mfa_satisfied():
            raise IdentityError(
                ErrorCode.MFA_REQUIRED, "Step-up authentication (MFA) required for this resource."
            )
        return context

    return _checker
