"""Phase 5.7a.1 SRS ACT-MDL-FR-005, FR-009 — provider-layer exceptions.

Both wrap ``IdentityError`` so provider failures surface through the same
error envelope as everything else in the platform
(``{"success": false, "error": {"code", "message"}, "request_id"}``),
while giving the provider abstraction its own specific, catchable
exception types rather than callers matching on error-code strings.
"""

from __future__ import annotations

from app.identity.errors import ErrorCode, IdentityError


class ProviderUnavailableError(IdentityError):
    """Raised when the configured provider identifier has no registered
    implementation — preserves the pre-abstraction
    ``MODEL_PROVIDER_UNAVAILABLE`` fail-closed behavior exactly
    (``ACT-MDL-FR-005``)."""

    def __init__(self, provider: str) -> None:
        super().__init__(ErrorCode.MODEL_PROVIDER_UNAVAILABLE,
                         f"Model provider '{provider}' is not configured in this environment.")


class CapabilityUnsupportedError(IdentityError):
    """Raised when a request asks a provider for something it declared it
    doesn't support — e.g. tool definitions sent to a provider whose
    ``describe()`` reports ``supports_tools=False`` (``ACT-MDL-FR-009``)."""

    def __init__(self, provider: str, capability: str) -> None:
        super().__init__(ErrorCode.MODEL_CAPABILITY_UNSUPPORTED,
                         f"Provider '{provider}' does not support '{capability}'.")
