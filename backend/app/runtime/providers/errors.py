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


class ProviderRequestFailedError(IdentityError):
    """Raised by an adapter (Phase 5.7a.2's ``OpenAICompatibleProvider`` is
    the first) when the HTTP call to a configured provider endpoint fails
    outright (connection error, timeout) or returns something this adapter
    cannot parse into a ``ModelResponse``. Deliberately one coarse
    exception, not a taxonomy — classifying failure modes for retry/backoff
    purposes is Phase 5.7a.4."""

    def __init__(self, provider: str, detail: str) -> None:
        super().__init__(ErrorCode.MODEL_PROVIDER_REQUEST_FAILED,
                         f"Request to model provider '{provider}' failed: {detail}")
