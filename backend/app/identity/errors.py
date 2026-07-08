"""Standard identity error envelope and exception handling (SRS §18).

Every identity API returns, on failure:

    {"success": false, "error": {"code": "...", "message": "..."}, "request_id": "..."}

Handlers are registered only for identity errors, so the rest of the platform's
error format is unchanged.
"""

from __future__ import annotations

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
}


class IdentityError(Exception):
    """Raised by identity services/repositories; rendered as the error envelope."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        self.http_status = _STATUS.get(code, status.HTTP_400_BAD_REQUEST)
        super().__init__(message)


def error_body(code: str, message: str, request_id: str | None) -> dict[str, object]:
    return {
        "success": False,
        "error": {"code": code, "message": message},
        "request_id": request_id,
    }


def _request_id(request: Request) -> str | None:
    return request.headers.get("x-request-id") or getattr(request.state, "request_id", None)


def register_identity_exception_handlers(app: FastAPI) -> None:
    """Register the identity error handler on the FastAPI app."""

    @app.exception_handler(IdentityError)
    async def _handle_identity_error(request: Request, exc: IdentityError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.http_status,
            content=error_body(exc.code, exc.message, _request_id(request)),
        )

    @app.exception_handler(PasswordPolicyError)
    async def _handle_password_policy_error(
        request: Request, exc: PasswordPolicyError
    ) -> JSONResponse:
        """A password-policy rejection is a client validation error, never a 500.

        Routes that set a password (legacy ``/auth/register``, ``/users``) call
        ``hash_user_password`` directly and let this handler shape the response.
        """
        return JSONResponse(
            status_code=422,
            content=error_body(ErrorCode.VALIDATION_ERROR, str(exc), _request_id(request)),
        )
