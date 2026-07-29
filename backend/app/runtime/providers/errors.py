"""Phase 5.7a.1 SRS ACT-MDL-FR-005, FR-009 — provider-layer exceptions.

Both wrap ``IdentityError`` so provider failures surface through the same
error envelope as everything else in the platform
(``{"success": false, "error": {"code", "message"}, "request_id"}``),
while giving the provider abstraction its own specific, catchable
exception types rather than callers matching on error-code strings.
"""

from __future__ import annotations

from app.identity.errors import ErrorCode, IdentityError
from app.runtime.providers.types import ProviderErrorClass


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
    cannot parse into a ``ModelResponse``.

    Phase 5.7a.4 (``ACT-MDL-FR-060``) attaches a classification: every
    instance now carries ``error_class`` (a ``ProviderErrorClass``,
    defaulting to ``UNKNOWN`` for any call site that doesn't classify —
    "we don't know," never a guessed neighbor) and, when the provider sent
    one, ``retry_after_seconds`` (from a ``Retry-After`` header — honored
    in preference to computed backoff, ``ACT-MDL-FR-064``). ``.code``
    itself stays the single ``MODEL_PROVIDER_REQUEST_FAILED`` (HTTP 502)
    it always was — nothing catches this exception at the HTTP-response
    layer (it's always caught inside ``ExecutionWorkerService._execute``
    first), so the taxonomy lives on this new attribute rather than
    forcing a matching explosion of ``ErrorCode``/HTTP-status entries.
    Retry/backoff/circuit-breaking on ``error_class`` is the service
    layer's job (``ModelGatewayService``), not the adapter's — see
    docs/runtime/providers.md."""

    def __init__(self, provider: str, detail: str, *, error_class: ProviderErrorClass = ProviderErrorClass.UNKNOWN,
                retry_after_seconds: float | None = None) -> None:
        self.error_class = error_class
        self.retry_after_seconds = retry_after_seconds
        super().__init__(ErrorCode.MODEL_PROVIDER_REQUEST_FAILED,
                         f"Request to model provider '{provider}' failed: {detail}")
