"""Phase 2.1.1 SRS ACT-INT-FR-005, FR-009 — connector-layer exceptions.

Mirrors ``app/runtime/providers/errors.py`` exactly: each wraps
``IdentityError`` so connector failures surface through the same error
envelope as everything else in the platform
(``{"success": false, "error": {"code", "message"}, "request_id"}``),
while giving this layer its own specific, catchable exception types
rather than callers matching on error-code strings."""

from __future__ import annotations

from app.identity.errors import ErrorCode, IdentityError


class ConnectorTypeNotFoundError(IdentityError):
    """Raised when a requested connector *type* identifier has no
    registered implementation."""

    def __init__(self, connector_type: str) -> None:
        super().__init__(
            ErrorCode.CONNECTOR_TYPE_NOT_FOUND,
            f"Connector type '{connector_type}' is not registered.",
        )


class ConnectorNotFoundError(IdentityError):
    """Raised when a requested connector *instance* id does not exist, or
    does not belong to the caller's organization (``ACT-PLT-NFR-001`` —
    cross-org lookups are indistinguishable from not-found, never a 403
    that would confirm another org's instance exists)."""

    def __init__(self, instance_id: object) -> None:
        super().__init__(
            ErrorCode.CONNECTOR_NOT_FOUND,
            f"Connector instance '{instance_id}' was not found.",
        )


class ConnectorConfigInvalidError(IdentityError):
    """Raised when an instance's ``configuration`` fails validation
    against its type's declared ``config_schema`` (``ACT-INT-FR-005``)."""

    def __init__(self, detail: str) -> None:
        super().__init__(
            ErrorCode.CONNECTOR_CONFIG_INVALID,
            f"Connector configuration is invalid: {detail}",
        )


class ConnectorInvalidTransitionError(IdentityError):
    """Raised when a lifecycle transition is attempted that
    ``app/integration/lifecycle.py`` does not allow from the instance's
    current state (``ACT-INT-FR-003``). Named by ``event`` (``configure``/
    ``activate``/``disable``/``mark_failed``), not by a target state —
    an invalid attempt has no valid target to name."""

    def __init__(self, from_state: str, event: str) -> None:
        super().__init__(
            ErrorCode.CONNECTOR_INVALID_TRANSITION,
            f"Cannot '{event}' a connector instance currently in state '{from_state}'.",
        )


class ConnectorCredentialNotFoundError(IdentityError):
    """Raised when a requested connector credential (for a given instance
    + scheme) has not been configured (Phase 2.1.2, ``ACT-INT-FR-022``)."""

    def __init__(self, instance_id: object, auth_scheme: str) -> None:
        super().__init__(
            ErrorCode.CONNECTOR_CREDENTIAL_NOT_FOUND,
            f"No '{auth_scheme}' credential is configured for connector instance '{instance_id}'.",
        )


class ConnectorAuthSchemeUnsupportedError(IdentityError):
    """Raised when a caller names an authentication scheme identifier
    with no registered implementation (Phase 2.1.2, ``ACT-INT-FR-021``)."""

    def __init__(self, auth_scheme: str) -> None:
        super().__init__(
            ErrorCode.CONNECTOR_AUTH_SCHEME_UNSUPPORTED,
            f"Authentication scheme '{auth_scheme}' is not supported.",
        )


class ConnectorCredentialInvalidError(IdentityError):
    """Raised when a credential bundle is missing a field its scheme
    declares required, or otherwise fails validation (Phase 2.1.2)."""

    def __init__(self, detail: str) -> None:
        super().__init__(
            ErrorCode.CONNECTOR_CREDENTIAL_INVALID,
            f"Connector credential is invalid: {detail}",
        )


class ConnectorOAuthRefreshFailedError(IdentityError):
    """Raised when an OAuth2 token acquisition or refresh call fails
    (Phase 2.1.2, ``ACT-INT-FR-024``) — mirrors
    ``ProviderRequestFailedError``'s "upstream call failed" treatment."""

    def __init__(self, detail: str) -> None:
        super().__init__(
            ErrorCode.CONNECTOR_OAUTH_REFRESH_FAILED,
            f"OAuth2 token acquisition/refresh failed: {detail}",
        )
