"""Standard identity error envelope and exception handling (SRS §18).

Every identity API returns, on failure:

    {"success": false, "error": {"code": "...", "message": "..."}, "request_id": "..."}

Handlers are registered only for identity errors, so the rest of the platform's
error format is unchanged.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from app.identity.security.passwords import PasswordPolicyError


class ErrorCode:
    """Stable, machine-readable identity error codes."""

    USER_NOT_FOUND = "USER_NOT_FOUND"
    ROLE_NOT_FOUND = "ROLE_NOT_FOUND"
    ORGANIZATION_NOT_FOUND = "ORGANIZATION_NOT_FOUND"
    DEPARTMENT_NOT_FOUND = "DEPARTMENT_NOT_FOUND"
    SESSION_NOT_FOUND = "SESSION_NOT_FOUND"
    IDENTITY_NOT_FOUND = "IDENTITY_NOT_FOUND"
    AGENT_IDENTITY_NOT_FOUND = "AGENT_IDENTITY_NOT_FOUND"
    SERVICE_ACCOUNT_NOT_FOUND = "SERVICE_ACCOUNT_NOT_FOUND"
    EXTERNAL_CLIENT_NOT_FOUND = "EXTERNAL_CLIENT_NOT_FOUND"
    INVALID_LIFECYCLE_TRANSITION = "INVALID_LIFECYCLE_TRANSITION"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    AUTHENTICATION_FAILED = "AUTHENTICATION_FAILED"
    CONFLICT = "CONFLICT"
    INTERNAL_ERROR = "INTERNAL_ERROR"
    # Phase 4.2.1 authentication error codes (SRS §25).
    INVALID_CREDENTIALS = "INVALID_CREDENTIALS"
    TOKEN_EXPIRED = "TOKEN_EXPIRED"
    TOKEN_REVOKED = "TOKEN_REVOKED"
    REFRESH_TOKEN_REUSED = "REFRESH_TOKEN_REUSED"
    IDENTITY_DISABLED = "IDENTITY_DISABLED"
    IDENTITY_SUSPENDED = "IDENTITY_SUSPENDED"
    SESSION_REVOKED = "SESSION_REVOKED"
    API_KEY_INVALID = "API_KEY_INVALID"
    API_KEY_EXPIRED = "API_KEY_EXPIRED"
    MFA_REQUIRED = "MFA_REQUIRED"
    INSUFFICIENT_SCOPE = "INSUFFICIENT_SCOPE"
    # Human authentication (SRS 4.2.2.1 §21).
    ACCOUNT_LOCKED = "ACCOUNT_LOCKED"
    ACCOUNT_DISABLED = "ACCOUNT_DISABLED"
    PASSWORD_EXPIRED = "PASSWORD_EXPIRED"
    TOKEN_INVALID = "TOKEN_INVALID"
    REFRESH_FAILED = "REFRESH_FAILED"
    # Session lifecycle (SRS 4.2.2.2 §27).
    SESSION_EXPIRED = "SESSION_EXPIRED"
    SESSION_IDLE_TIMEOUT = "SESSION_IDLE_TIMEOUT"
    SESSION_SUSPICIOUS = "SESSION_SUSPICIOUS"
    DEVICE_BLOCKED = "DEVICE_BLOCKED"
    DEVICE_NOT_FOUND = "DEVICE_NOT_FOUND"
    TOKEN_REUSE = "TOKEN_REUSE"
    TOO_MANY_SESSIONS = "TOO_MANY_SESSIONS"
    INVALID_REFRESH_TOKEN = "INVALID_REFRESH_TOKEN"
    # Registration & invitations (4.2.2.3.1 §18).
    INVITATION_NOT_FOUND = "INVITATION_NOT_FOUND"
    INVITATION_EXPIRED = "INVITATION_EXPIRED"
    INVITATION_ALREADY_USED = "INVITATION_ALREADY_USED"
    INVITATION_CANCELLED = "INVITATION_CANCELLED"
    EMAIL_ALREADY_VERIFIED = "EMAIL_ALREADY_VERIFIED"
    INVALID_VERIFICATION_TOKEN = "INVALID_VERIFICATION_TOKEN"
    VERIFICATION_TOKEN_EXPIRED = "VERIFICATION_TOKEN_EXPIRED"
    REGISTRATION_DISABLED = "REGISTRATION_DISABLED"
    USER_ALREADY_EXISTS = "USER_ALREADY_EXISTS"
    EMAIL_NOT_VERIFIED = "EMAIL_NOT_VERIFIED"
    ACCOUNT_PENDING_APPROVAL = "ACCOUNT_PENDING_APPROVAL"
    RATE_LIMIT_EXCEEDED = "RATE_LIMIT_EXCEEDED"
    # Credential management (4.2.2.3.2 §26). PASSWORD_EXPIRED already exists above.
    PASSWORD_TOO_WEAK = "PASSWORD_TOO_WEAK"
    PASSWORD_REUSED = "PASSWORD_REUSED"
    PASSWORD_HISTORY_VIOLATION = "PASSWORD_HISTORY_VIOLATION"
    INVALID_CURRENT_PASSWORD = "INVALID_CURRENT_PASSWORD"
    TEMP_PASSWORD_EXPIRED = "TEMP_PASSWORD_EXPIRED"
    PASSWORD_POLICY_FAILED = "PASSWORD_POLICY_FAILED"
    FIRST_LOGIN_CHANGE_REQUIRED = "FIRST_LOGIN_CHANGE_REQUIRED"
    PASSWORD_MIN_AGE = "PASSWORD_MIN_AGE"
    # Password reset & recovery (4.2.2.3.3 §25).
    RESET_TOKEN_INVALID = "RESET_TOKEN_INVALID"
    RESET_TOKEN_EXPIRED = "RESET_TOKEN_EXPIRED"
    RESET_TOKEN_USED = "RESET_TOKEN_USED"
    EMAIL_VERIFICATION_EXPIRED = "EMAIL_VERIFICATION_EXPIRED"
    PASSWORD_RESET_DISABLED = "PASSWORD_RESET_DISABLED"
    INVALID_RECOVERY_REQUEST = "INVALID_RECOVERY_REQUEST"
    EMAIL_ALREADY_IN_USE = "EMAIL_ALREADY_IN_USE"
    # Account protection & risk-based authentication (4.2.2.3.4 §32).
    # ACCOUNT_LOCKED already exists above (4.2.2.1). These are new.
    LOGIN_BLOCKED = "LOGIN_BLOCKED"
    RISK_CHALLENGE_REQUIRED = "RISK_CHALLENGE_REQUIRED"
    CAPTCHA_REQUIRED = "CAPTCHA_REQUIRED"
    IP_BLOCKED = "IP_BLOCKED"
    SECURITY_REVIEW_REQUIRED = "SECURITY_REVIEW_REQUIRED"
    TOO_MANY_ATTEMPTS = "TOO_MANY_ATTEMPTS"
    PROTECTION_RULE_DENIED = "PROTECTION_RULE_DENIED"
    ACCOUNT_LOCK_NOT_FOUND = "ACCOUNT_LOCK_NOT_FOUND"
    PROTECTION_RULE_NOT_FOUND = "PROTECTION_RULE_NOT_FOUND"
    BLOCKED_IP_NOT_FOUND = "BLOCKED_IP_NOT_FOUND"
    # Enterprise RBAC foundation (Phase 4.3.1 §24). ROLE_NOT_FOUND already exists above.
    ROLE_ALREADY_EXISTS = "ROLE_ALREADY_EXISTS"
    PERMISSION_NOT_FOUND = "PERMISSION_NOT_FOUND"
    PERMISSION_ALREADY_EXISTS = "PERMISSION_ALREADY_EXISTS"
    INVALID_PERMISSION_NAME = "INVALID_PERMISSION_NAME"
    ROLE_HAS_ASSIGNMENTS = "ROLE_HAS_ASSIGNMENTS"
    CIRCULAR_ROLE_HIERARCHY = "CIRCULAR_ROLE_HIERARCHY"
    INVALID_SCOPE = "INVALID_SCOPE"
    SYSTEM_ROLE_PROTECTED = "SYSTEM_ROLE_PROTECTED"
    ROLE_ASSIGNMENT_NOT_FOUND = "ROLE_ASSIGNMENT_NOT_FOUND"
    PERMISSION_GROUP_NOT_FOUND = "PERMISSION_GROUP_NOT_FOUND"
    ROLE_HIERARCHY_EDGE_NOT_FOUND = "ROLE_HIERARCHY_EDGE_NOT_FOUND"
    # Permission engine (Phase 4.3.2 §28). PERMISSION_DENIED already exists above.
    ROLE_NOT_ASSIGNED = "ROLE_NOT_ASSIGNED"
    RESOURCE_FORBIDDEN = "RESOURCE_FORBIDDEN"
    EXPLICIT_DENY = "EXPLICIT_DENY"
    AUTHORIZATION_FAILED = "AUTHORIZATION_FAILED"
    PERMISSION_CACHE_MISS = "PERMISSION_CACHE_MISS"
    # Organization hierarchy (Phase 4.3.3 §19). ORGANIZATION_NOT_FOUND /
    # DEPARTMENT_NOT_FOUND already exist above.
    BUSINESS_UNIT_NOT_FOUND = "BUSINESS_UNIT_NOT_FOUND"
    TEAM_NOT_FOUND = "TEAM_NOT_FOUND"
    PROJECT_NOT_FOUND = "PROJECT_NOT_FOUND"
    RESOURCE_OWNERSHIP_NOT_FOUND = "RESOURCE_OWNERSHIP_NOT_FOUND"
    CROSS_ORG_FORBIDDEN = "CROSS_ORG_FORBIDDEN"
    ENTITY_HAS_CHILDREN = "ENTITY_HAS_CHILDREN"
    DELEGATION_EXCEEDS_AUTHORITY = "DELEGATION_EXCEEDS_AUTHORITY"
    DELEGATION_NOT_FOUND = "DELEGATION_NOT_FOUND"
    HIERARCHY_INTEGRITY_ERROR = "HIERARCHY_INTEGRITY_ERROR"
    # Resource-based authorization (Phase 4.3.4 §24).
    RESOURCE_NOT_FOUND = "RESOURCE_NOT_FOUND"
    RESOURCE_OWNER_REQUIRED = "RESOURCE_OWNER_REQUIRED"
    ACL_ENTRY_NOT_FOUND = "ACL_ENTRY_NOT_FOUND"
    RESOURCE_NOT_SHARED = "RESOURCE_NOT_SHARED"
    DELEGATION_EXPIRED = "DELEGATION_EXPIRED"
    OWNER_TRANSFER_NOT_ALLOWED = "OWNER_TRANSFER_NOT_ALLOWED"
    RESOURCE_POLICY_DENIED = "RESOURCE_POLICY_DENIED"
    CROSS_ORGANIZATION_ACCESS_DENIED = "CROSS_ORGANIZATION_ACCESS_DENIED"
    RESOURCE_ACCESS_DENIED = "RESOURCE_ACCESS_DENIED"


# Map error codes → HTTP status.
_STATUS: dict[str, int] = {
    ErrorCode.USER_NOT_FOUND: status.HTTP_404_NOT_FOUND,
    ErrorCode.ROLE_NOT_FOUND: status.HTTP_404_NOT_FOUND,
    ErrorCode.ORGANIZATION_NOT_FOUND: status.HTTP_404_NOT_FOUND,
    ErrorCode.DEPARTMENT_NOT_FOUND: status.HTTP_404_NOT_FOUND,
    ErrorCode.SESSION_NOT_FOUND: status.HTTP_404_NOT_FOUND,
    ErrorCode.IDENTITY_NOT_FOUND: status.HTTP_404_NOT_FOUND,
    ErrorCode.AGENT_IDENTITY_NOT_FOUND: status.HTTP_404_NOT_FOUND,
    ErrorCode.SERVICE_ACCOUNT_NOT_FOUND: status.HTTP_404_NOT_FOUND,
    ErrorCode.EXTERNAL_CLIENT_NOT_FOUND: status.HTTP_404_NOT_FOUND,
    ErrorCode.INVALID_LIFECYCLE_TRANSITION: status.HTTP_409_CONFLICT,
    ErrorCode.CONFLICT: status.HTTP_409_CONFLICT,
    ErrorCode.VALIDATION_ERROR: status.HTTP_422_UNPROCESSABLE_ENTITY,
    ErrorCode.PERMISSION_DENIED: status.HTTP_403_FORBIDDEN,
    ErrorCode.AUTHENTICATION_FAILED: status.HTTP_401_UNAUTHORIZED,
    ErrorCode.INTERNAL_ERROR: status.HTTP_500_INTERNAL_SERVER_ERROR,
    # Authentication (SRS §25).
    ErrorCode.INVALID_CREDENTIALS: status.HTTP_401_UNAUTHORIZED,
    ErrorCode.TOKEN_EXPIRED: status.HTTP_401_UNAUTHORIZED,
    ErrorCode.TOKEN_REVOKED: status.HTTP_401_UNAUTHORIZED,
    ErrorCode.REFRESH_TOKEN_REUSED: status.HTTP_401_UNAUTHORIZED,
    ErrorCode.IDENTITY_DISABLED: status.HTTP_403_FORBIDDEN,
    ErrorCode.IDENTITY_SUSPENDED: status.HTTP_403_FORBIDDEN,
    ErrorCode.SESSION_REVOKED: status.HTTP_401_UNAUTHORIZED,
    ErrorCode.API_KEY_INVALID: status.HTTP_401_UNAUTHORIZED,
    ErrorCode.API_KEY_EXPIRED: status.HTTP_401_UNAUTHORIZED,
    ErrorCode.MFA_REQUIRED: status.HTTP_401_UNAUTHORIZED,
    ErrorCode.INSUFFICIENT_SCOPE: status.HTTP_403_FORBIDDEN,
    # Human authentication (SRS 4.2.2.1 §21).
    ErrorCode.ACCOUNT_LOCKED: status.HTTP_423_LOCKED,
    ErrorCode.ACCOUNT_DISABLED: status.HTTP_403_FORBIDDEN,
    ErrorCode.PASSWORD_EXPIRED: status.HTTP_401_UNAUTHORIZED,
    ErrorCode.TOKEN_INVALID: status.HTTP_401_UNAUTHORIZED,
    ErrorCode.REFRESH_FAILED: status.HTTP_401_UNAUTHORIZED,
    # Session lifecycle (SRS 4.2.2.2 §27).
    ErrorCode.SESSION_EXPIRED: status.HTTP_401_UNAUTHORIZED,
    ErrorCode.SESSION_IDLE_TIMEOUT: status.HTTP_401_UNAUTHORIZED,
    ErrorCode.SESSION_SUSPICIOUS: status.HTTP_401_UNAUTHORIZED,
    # A blocked device is an authorization decision about the *device*, not the
    # credential — the password was correct. 403, not 401.
    ErrorCode.DEVICE_BLOCKED: status.HTTP_403_FORBIDDEN,
    ErrorCode.DEVICE_NOT_FOUND: status.HTTP_404_NOT_FOUND,
    ErrorCode.TOKEN_REUSE: status.HTTP_401_UNAUTHORIZED,
    ErrorCode.TOO_MANY_SESSIONS: status.HTTP_409_CONFLICT,
    ErrorCode.INVALID_REFRESH_TOKEN: status.HTTP_401_UNAUTHORIZED,
    # Registration & invitations (4.2.2.3.1 §18).
    ErrorCode.INVITATION_NOT_FOUND: status.HTTP_404_NOT_FOUND,
    # 410 Gone, not 404: the link *was* valid. The user needs to be told to ask for
    # a new one, not that they mistyped a URL.
    ErrorCode.INVITATION_EXPIRED: status.HTTP_410_GONE,
    ErrorCode.INVITATION_ALREADY_USED: status.HTTP_410_GONE,
    ErrorCode.INVITATION_CANCELLED: status.HTTP_410_GONE,
    ErrorCode.EMAIL_ALREADY_VERIFIED: status.HTTP_409_CONFLICT,
    ErrorCode.INVALID_VERIFICATION_TOKEN: status.HTTP_400_BAD_REQUEST,
    ErrorCode.VERIFICATION_TOKEN_EXPIRED: status.HTTP_410_GONE,
    ErrorCode.REGISTRATION_DISABLED: status.HTTP_403_FORBIDDEN,
    ErrorCode.USER_ALREADY_EXISTS: status.HTTP_409_CONFLICT,
    # The credential was correct; the account is simply not usable yet. 403, not
    # 401 — re-entering the password cannot help.
    ErrorCode.EMAIL_NOT_VERIFIED: status.HTTP_403_FORBIDDEN,
    ErrorCode.ACCOUNT_PENDING_APPROVAL: status.HTTP_403_FORBIDDEN,
    ErrorCode.RATE_LIMIT_EXCEEDED: status.HTTP_429_TOO_MANY_REQUESTS,
    # Credential management (4.2.2.3.2 §26). Policy failures are client input
    # errors (422); a wrong current password is an auth failure (401).
    ErrorCode.PASSWORD_TOO_WEAK: status.HTTP_422_UNPROCESSABLE_ENTITY,
    ErrorCode.PASSWORD_REUSED: status.HTTP_422_UNPROCESSABLE_ENTITY,
    ErrorCode.PASSWORD_HISTORY_VIOLATION: status.HTTP_422_UNPROCESSABLE_ENTITY,
    ErrorCode.INVALID_CURRENT_PASSWORD: status.HTTP_401_UNAUTHORIZED,
    ErrorCode.TEMP_PASSWORD_EXPIRED: status.HTTP_401_UNAUTHORIZED,
    ErrorCode.PASSWORD_POLICY_FAILED: status.HTTP_422_UNPROCESSABLE_ENTITY,
    ErrorCode.FIRST_LOGIN_CHANGE_REQUIRED: status.HTTP_403_FORBIDDEN,
    ErrorCode.PASSWORD_MIN_AGE: status.HTTP_409_CONFLICT,
    # Password reset & recovery (4.2.2.3.3 §25).
    # A dead reset link *was* valid: 410 Gone, not 404 — tell the user to request a
    # new one, the same discipline as invitation/verification links.
    ErrorCode.RESET_TOKEN_INVALID: status.HTTP_400_BAD_REQUEST,
    ErrorCode.RESET_TOKEN_EXPIRED: status.HTTP_410_GONE,
    ErrorCode.RESET_TOKEN_USED: status.HTTP_410_GONE,
    ErrorCode.EMAIL_VERIFICATION_EXPIRED: status.HTTP_410_GONE,
    ErrorCode.PASSWORD_RESET_DISABLED: status.HTTP_403_FORBIDDEN,
    ErrorCode.INVALID_RECOVERY_REQUEST: status.HTTP_400_BAD_REQUEST,
    ErrorCode.EMAIL_ALREADY_IN_USE: status.HTTP_409_CONFLICT,
    # Account protection (4.2.2.3.4 §32). A blocked/too-many/challenge verdict is a
    # 429 or 403 — never a detailed leak of *why* (§33).
    ErrorCode.LOGIN_BLOCKED: status.HTTP_403_FORBIDDEN,
    ErrorCode.RISK_CHALLENGE_REQUIRED: status.HTTP_401_UNAUTHORIZED,
    ErrorCode.CAPTCHA_REQUIRED: status.HTTP_401_UNAUTHORIZED,
    ErrorCode.IP_BLOCKED: status.HTTP_403_FORBIDDEN,
    ErrorCode.SECURITY_REVIEW_REQUIRED: status.HTTP_403_FORBIDDEN,
    ErrorCode.TOO_MANY_ATTEMPTS: status.HTTP_429_TOO_MANY_REQUESTS,
    ErrorCode.PROTECTION_RULE_DENIED: status.HTTP_403_FORBIDDEN,
    ErrorCode.ACCOUNT_LOCK_NOT_FOUND: status.HTTP_404_NOT_FOUND,
    ErrorCode.PROTECTION_RULE_NOT_FOUND: status.HTTP_404_NOT_FOUND,
    ErrorCode.BLOCKED_IP_NOT_FOUND: status.HTTP_404_NOT_FOUND,
    # Enterprise RBAC foundation (Phase 4.3.1 §24).
    ErrorCode.ROLE_ALREADY_EXISTS: status.HTTP_409_CONFLICT,
    ErrorCode.PERMISSION_NOT_FOUND: status.HTTP_404_NOT_FOUND,
    ErrorCode.PERMISSION_ALREADY_EXISTS: status.HTTP_409_CONFLICT,
    ErrorCode.INVALID_PERMISSION_NAME: status.HTTP_422_UNPROCESSABLE_ENTITY,
    # A role with live assignments cannot be deleted (§8, §25): 409, not 403.
    ErrorCode.ROLE_HAS_ASSIGNMENTS: status.HTTP_409_CONFLICT,
    ErrorCode.CIRCULAR_ROLE_HIERARCHY: status.HTTP_409_CONFLICT,
    ErrorCode.INVALID_SCOPE: status.HTTP_422_UNPROCESSABLE_ENTITY,
    # System roles are protected from edit/delete (§25): 403.
    ErrorCode.SYSTEM_ROLE_PROTECTED: status.HTTP_403_FORBIDDEN,
    ErrorCode.ROLE_ASSIGNMENT_NOT_FOUND: status.HTTP_404_NOT_FOUND,
    ErrorCode.PERMISSION_GROUP_NOT_FOUND: status.HTTP_404_NOT_FOUND,
    ErrorCode.ROLE_HIERARCHY_EDGE_NOT_FOUND: status.HTTP_404_NOT_FOUND,
    # Permission engine (Phase 4.3.2 §28) — all authorization denials are 403.
    ErrorCode.ROLE_NOT_ASSIGNED: status.HTTP_403_FORBIDDEN,
    ErrorCode.RESOURCE_FORBIDDEN: status.HTTP_403_FORBIDDEN,
    ErrorCode.EXPLICIT_DENY: status.HTTP_403_FORBIDDEN,
    ErrorCode.AUTHORIZATION_FAILED: status.HTTP_403_FORBIDDEN,
    ErrorCode.PERMISSION_CACHE_MISS: status.HTTP_500_INTERNAL_SERVER_ERROR,
    # Organization hierarchy (Phase 4.3.3 §19).
    ErrorCode.BUSINESS_UNIT_NOT_FOUND: status.HTTP_404_NOT_FOUND,
    ErrorCode.TEAM_NOT_FOUND: status.HTTP_404_NOT_FOUND,
    ErrorCode.PROJECT_NOT_FOUND: status.HTTP_404_NOT_FOUND,
    ErrorCode.RESOURCE_OWNERSHIP_NOT_FOUND: status.HTTP_404_NOT_FOUND,
    ErrorCode.CROSS_ORG_FORBIDDEN: status.HTTP_403_FORBIDDEN,
    # A parent with children cannot be deleted until they are handled/reassigned (§19).
    ErrorCode.ENTITY_HAS_CHILDREN: status.HTTP_409_CONFLICT,
    ErrorCode.DELEGATION_EXCEEDS_AUTHORITY: status.HTTP_403_FORBIDDEN,
    ErrorCode.DELEGATION_NOT_FOUND: status.HTTP_404_NOT_FOUND,
    ErrorCode.HIERARCHY_INTEGRITY_ERROR: status.HTTP_409_CONFLICT,
    # Resource-based authorization (Phase 4.3.4 §24).
    ErrorCode.RESOURCE_NOT_FOUND: status.HTTP_404_NOT_FOUND,
    ErrorCode.RESOURCE_OWNER_REQUIRED: status.HTTP_403_FORBIDDEN,
    ErrorCode.ACL_ENTRY_NOT_FOUND: status.HTTP_404_NOT_FOUND,
    ErrorCode.RESOURCE_NOT_SHARED: status.HTTP_404_NOT_FOUND,
    ErrorCode.DELEGATION_EXPIRED: status.HTTP_410_GONE,
    ErrorCode.OWNER_TRANSFER_NOT_ALLOWED: status.HTTP_403_FORBIDDEN,
    ErrorCode.RESOURCE_POLICY_DENIED: status.HTTP_403_FORBIDDEN,
    ErrorCode.CROSS_ORGANIZATION_ACCESS_DENIED: status.HTTP_403_FORBIDDEN,
    ErrorCode.RESOURCE_ACCESS_DENIED: status.HTTP_403_FORBIDDEN,
}


class IdentityError(Exception):
    """Raised by identity services/repositories; rendered as the error envelope.

    ``headers`` carries response headers the *error itself* demands — currently only
    ``Retry-After`` on a 429, which a client cannot behave correctly without.
    """

    def __init__(self, code: str, message: str, *, headers: dict[str, str] | None = None) -> None:
        self.code = code
        self.message = message
        self.headers = headers or {}
        self.http_status = _STATUS.get(code, status.HTTP_400_BAD_REQUEST)
        super().__init__(message)


def error_body(code: str, message: str, request_id: str | None) -> dict[str, object]:
    """The standard error envelope (SRS §5).

    ``meta`` mirrors the success envelope so both carry ``request_id`` + ``timestamp``.
    ``request_id`` is also kept at the top level for backward compatibility with the
    clients and tests that read it there.
    """
    return {
        "success": False,
        "error": {"code": code, "message": message},
        "request_id": request_id,
        "meta": {
            "request_id": request_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
    }


def _request_id(request: Request) -> str | None:
    # ``RequestContextMiddleware`` (app.core.middleware) sets ``state.request_id`` to
    # the supplied-or-generated id for every request, honouring the configured header
    # name. Prefer it; fall back to the raw header for any request that somehow
    # bypassed the middleware (e.g. a directly-constructed test request).
    return getattr(request.state, "request_id", None) or request.headers.get("x-request-id")


def register_identity_exception_handlers(app: FastAPI) -> None:
    """Register the identity error handler on the FastAPI app."""

    @app.exception_handler(IdentityError)
    async def _handle_identity_error(request: Request, exc: IdentityError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.http_status,
            content=error_body(exc.code, exc.message, _request_id(request)),
            headers=exc.headers or None,
        )

    @app.exception_handler(PasswordPolicyError)
    async def _handle_password_policy_error(
        request: Request, exc: PasswordPolicyError
    ) -> JSONResponse:
        """A password-policy rejection is a client validation error, never a 500.

        Routes that set a password (legacy ``/auth/register``, ``/users``) call
        ``hash_user_password`` directly and let this handler shape the response.

        The exception carries a specific ``code`` (``PASSWORD_TOO_WEAK`` /
        ``PASSWORD_POLICY_FAILED``) so the client can react precisely (SRS §26).
        """
        code = getattr(exc, "code", None) or ErrorCode.PASSWORD_POLICY_FAILED
        return JSONResponse(
            status_code=422,
            content=error_body(code, str(exc), _request_id(request)),
        )
