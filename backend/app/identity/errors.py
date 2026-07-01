"""Standard identity error envelope and exception handling (SRS §18).

Every identity API returns, on failure:

    {"success": false, "error": {"code": "...", "message": "..."}, "request_id": "..."}

Handlers are registered only for identity errors, so the rest of the platform's
error format is unchanged.
"""

from __future__ import annotations

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse


class ErrorCode:
    """Stable, machine-readable identity error codes."""

    USER_NOT_FOUND = "USER_NOT_FOUND"
    ROLE_NOT_FOUND = "ROLE_NOT_FOUND"
    ORGANIZATION_NOT_FOUND = "ORGANIZATION_NOT_FOUND"
    DEPARTMENT_NOT_FOUND = "DEPARTMENT_NOT_FOUND"
    SESSION_NOT_FOUND = "SESSION_NOT_FOUND"
    IDENTITY_NOT_FOUND = "IDENTITY_NOT_FOUND"
    INVALID_LIFECYCLE_TRANSITION = "INVALID_LIFECYCLE_TRANSITION"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    AUTHENTICATION_FAILED = "AUTHENTICATION_FAILED"
    CONFLICT = "CONFLICT"
    INTERNAL_ERROR = "INTERNAL_ERROR"


# Map error codes → HTTP status.
_STATUS: dict[str, int] = {
    ErrorCode.USER_NOT_FOUND: status.HTTP_404_NOT_FOUND,
    ErrorCode.ROLE_NOT_FOUND: status.HTTP_404_NOT_FOUND,
    ErrorCode.ORGANIZATION_NOT_FOUND: status.HTTP_404_NOT_FOUND,
    ErrorCode.DEPARTMENT_NOT_FOUND: status.HTTP_404_NOT_FOUND,
    ErrorCode.SESSION_NOT_FOUND: status.HTTP_404_NOT_FOUND,
    ErrorCode.IDENTITY_NOT_FOUND: status.HTTP_404_NOT_FOUND,
    ErrorCode.INVALID_LIFECYCLE_TRANSITION: status.HTTP_409_CONFLICT,
    ErrorCode.CONFLICT: status.HTTP_409_CONFLICT,
    ErrorCode.VALIDATION_ERROR: status.HTTP_422_UNPROCESSABLE_ENTITY,
    ErrorCode.PERMISSION_DENIED: status.HTTP_403_FORBIDDEN,
    ErrorCode.AUTHENTICATION_FAILED: status.HTTP_401_UNAUTHORIZED,
    ErrorCode.INTERNAL_ERROR: status.HTTP_500_INTERNAL_SERVER_ERROR,
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
