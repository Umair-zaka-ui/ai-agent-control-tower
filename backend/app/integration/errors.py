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


class ConnectorUnavailableError(IdentityError):
    """Raised at the registry's invocation-resolution boundary when an
    instance is ``failed`` or ``disabled`` (Phase 2.1.3, ``ACT-INT-FR-044``)
    — the fail-fast contract: raised immediately, before anything ever
    attempts a real call, so a broken connector's tools reject instantly
    instead of timing out. `app/integration/registry.py::
    ConnectorRegistry.resolve_instance_for_invocation` is the one place
    this is raised; 2.2.x's tool bridge inherits it for free by calling
    that method first."""

    def __init__(self, instance_id: object, lifecycle_state: str) -> None:
        super().__init__(
            ErrorCode.CONNECTOR_UNAVAILABLE,
            f"Connector instance '{instance_id}' is '{lifecycle_state}' and cannot be invoked.",
        )


class ConnectorHealthCheckFailedError(IdentityError):
    """Raised by the ``POST .../health/check`` route (never stored — the
    row itself always records ``result='ERROR'`` regardless of how the
    caller learns about it) when the check itself could not complete,
    distinct from a completed check reporting ``UNHEALTHY`` (Phase 2.1.3,
    ``ACT-INT-FR-042``). The message is the same safe, truncated reason
    stored on the ``connector_health_checks`` row — never credential or
    token material (``ACT-INT-FR-047``)."""

    def __init__(self, detail: str) -> None:
        super().__init__(
            ErrorCode.CONNECTOR_HEALTH_CHECK_FAILED,
            f"Connector health check failed to complete: {detail}",
        )


class ConnectorDeclarationIncompleteError(IdentityError):
    """Raised at registration (Phase 2.1.4, ``ACT-INT-FR-064``) when a
    connector type's own ``describe()`` declaration is missing something
    required to be safely registered — no config schema, no capabilities,
    no tool contracts, a malformed tool contract, an undeclared or
    unregistered auth scheme, or a ``health_check()`` that was never really
    implemented (signals so via
    ``app.integration.validation.HealthCheckNotImplemented``). Raised by
    ``app/integration/validation.py::validate_declaration_complete``, the
    single completeness check both ``ConnectorTypeService.register`` (the
    real registration path) and the SDK test harness's
    ``assert_declaration_complete`` call — no separate, weaker check exists
    for SDK-authored connectors (``ACT-INT-FR-062``'s parity extends here
    too)."""

    def __init__(self, connector_type: str, missing: list[str]) -> None:
        super().__init__(
            ErrorCode.CONNECTOR_DECLARATION_INCOMPLETE,
            f"Connector type '{connector_type}' declaration is incomplete: {'; '.join(missing)}.",
        )
