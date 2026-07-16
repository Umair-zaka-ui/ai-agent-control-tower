"""Standard authorization exceptions (Phase 4.3.6 §25, §26).

Every exception subclasses ``IdentityError``, so the platform's registered
handlers already render the §26 envelope:

    {"success": false, "error": {"code": "...", "message": "..."}, "request_id": "..."}

Messages are deliberately generic — policy internals must never leak to the
caller (§26); the full trace lives in the audit trail.
"""

from __future__ import annotations

from app.identity.errors import ErrorCode, IdentityError


class AuthorizationMiddlewareError(IdentityError):
    """Base class for every middleware-raised authorization failure."""


class AuthenticationFailed(AuthorizationMiddlewareError):
    def __init__(self, message: str = "Could not validate credentials.") -> None:
        super().__init__(ErrorCode.AUTHENTICATION_FAILED, message)


class SessionExpired(AuthorizationMiddlewareError):
    def __init__(self, message: str = "Session has expired.") -> None:
        super().__init__(ErrorCode.SESSION_EXPIRED, message)


class PermissionDenied(AuthorizationMiddlewareError):
    def __init__(self, message: str = "Access denied.") -> None:
        super().__init__(ErrorCode.PERMISSION_DENIED, message)


class ResourceForbidden(AuthorizationMiddlewareError):
    def __init__(self, message: str = "Access to this resource is denied.") -> None:
        super().__init__(ErrorCode.RESOURCE_FORBIDDEN, message)


class ABACDenied(AuthorizationMiddlewareError):
    def __init__(self, message: str = "Access denied by policy.") -> None:
        super().__init__(ErrorCode.ABAC_DENIED, message)


class ApprovalRequired(AuthorizationMiddlewareError):
    def __init__(self, message: str = "This action requires human approval.") -> None:
        super().__init__(ErrorCode.APPROVAL_REQUIRED, message)


class MFARequired(AuthorizationMiddlewareError):
    def __init__(self, message: str = "Stronger authentication is required.") -> None:
        super().__init__(ErrorCode.MFA_REQUIRED, message)


class JustificationRequired(AuthorizationMiddlewareError):
    def __init__(self, message: str = "A justification is required for this action.") -> None:
        super().__init__(ErrorCode.JUSTIFICATION_REQUIRED, message)


class PolicyEvaluationFailed(AuthorizationMiddlewareError):
    def __init__(self, message: str = "Authorization could not be evaluated.") -> None:
        super().__init__(ErrorCode.ABAC_EVALUATION_FAILED, message)


# Decision → exception for enforcement points that must abort on a challenge.
DECISION_EXCEPTIONS: dict[str, type[AuthorizationMiddlewareError]] = {
    "DENY": ABACDenied,
    "REQUIRE_APPROVAL": ApprovalRequired,
    "REQUIRE_MFA": MFARequired,
    "REQUIRE_JUSTIFICATION": JustificationRequired,
}
