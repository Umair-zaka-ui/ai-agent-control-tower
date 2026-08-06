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


class RestEndpointNotDeclaredError(IdentityError):
    """Raised at invocation (Phase 2.2.1, ``ACT-INT-FR-102``) when a caller
    names a tool that has no matching entry in a REST connector instance's
    own declared ``endpoints`` — the framework never guesses or falls back
    to a "closest match"; an undeclared endpoint simply cannot be called."""

    def __init__(self, tool_name: str) -> None:
        super().__init__(
            ErrorCode.REST_ENDPOINT_NOT_DECLARED,
            f"No endpoint named '{tool_name}' is declared on this REST connector instance.",
        )


class RestTemplateInvalidError(IdentityError):
    """Raised at invocation (Phase 2.2.1, ``ACT-INT-FR-104``) when a REST
    endpoint's request cannot be safely rendered from the supplied tool
    arguments — a missing required path/query/header/body argument, or a
    value that would otherwise alter the request's structure (an embedded
    path separator, a header-injecting control character). The connector's
    own templating layer (``app/integration/connectors/rest/templating.py``)
    never lets such a value reach a real request; this is the platform
    error a caller sees instead."""

    def __init__(self, detail: str) -> None:
        super().__init__(ErrorCode.REST_TEMPLATE_INVALID, f"REST request templating failed: {detail}")


class RestExtractionFailedError(IdentityError):
    """Raised at invocation (Phase 2.2.1, ``ACT-INT-FR-104``) when a REST
    endpoint's response cannot be extracted or validated per its own
    declared ``response_field``/``output_schema`` — a response that isn't
    valid JSON, a declared field path absent from the body, or an
    extracted value that fails the endpoint's own output schema."""

    def __init__(self, detail: str) -> None:
        super().__init__(ErrorCode.REST_EXTRACTION_FAILED, f"REST response extraction failed: {detail}")


class DbQueryNotDeclaredError(IdentityError):
    """Raised at invocation (Phase 2.2.2, ``ACT-INT-FR-121``) when a caller
    names a query that has no matching entry in a database connector
    instance's own declared ``queries`` — there is no fallback, no partial
    match, and (deliberately) no way to supply SQL instead."""

    def __init__(self, query_name: str) -> None:
        super().__init__(
            ErrorCode.DB_QUERY_NOT_DECLARED,
            f"No query named '{query_name}' is declared on this database connector instance.",
        )


class DbParameterInvalidError(IdentityError):
    """Raised at invocation (Phase 2.2.2, ``ACT-INT-FR-121``) when the
    supplied parameters fail validation against a declared query's own
    parameter schema — a missing required parameter, or one of the wrong
    type. Never raised for "wrong SQL": there is no SQL to supply."""

    def __init__(self, detail: str) -> None:
        super().__init__(ErrorCode.DB_PARAMETER_INVALID, f"Database query parameters are invalid: {detail}")


class DbWriteNotPermittedError(IdentityError):
    """Raised at **configuration** time (Phase 2.2.2, ``ACT-INT-FR-125``)
    when a read-only database connector instance declares one or more
    mutating queries (INSERT/UPDATE/DELETE/DDL/etc., classified by
    inspecting the *declared, trusted* SQL — never model output). A
    connector author fixes this by either removing the mutating query or
    explicitly configuring the instance for write access."""

    def __init__(self, query_names: list[str]) -> None:
        super().__init__(
            ErrorCode.DB_WRITE_NOT_PERMITTED,
            f"Read-only database connector instance declares mutating quer{'y' if len(query_names) == 1 else 'ies'}: "
            f"{', '.join(query_names)}.",
        )


class DbResultLimitExceededError(IdentityError):
    """Raised at invocation (Phase 2.2.2, ``ACT-INT-FR-124``) when a
    declared query's result would exceed its configured row limit — the
    result is rejected outright, never silently truncated (a truncated
    result could mislead a model into acting on partial data)."""

    def __init__(self, query_name: str, row_limit: int) -> None:
        super().__init__(
            ErrorCode.DB_RESULT_LIMIT_EXCEEDED,
            f"Query '{query_name}' returned more than its {row_limit}-row limit; rejected rather than truncated.",
        )


class DbQueryTimeoutError(IdentityError):
    """Raised at invocation (Phase 2.2.2, ``ACT-INT-FR-124``) when a
    declared query exceeds its configured timeout — the database analogue
    of Milestone 1's HTTP tool timeout."""

    def __init__(self, query_name: str, timeout_seconds: float) -> None:
        super().__init__(
            ErrorCode.DB_QUERY_TIMEOUT,
            f"Query '{query_name}' exceeded its {timeout_seconds}s timeout.",
        )


class DbConnectionFailedError(IdentityError):
    """Raised at invocation (Phase 2.2.2, ``ACT-INT-FR-127``) when a
    database connector instance cannot connect or a query otherwise fails
    at the driver level. The message is always a generic, safe summary —
    never the connection string, host, credential, or raw driver
    exception text, any of which could leak topology or secret material
    (``ACT-INT-FR-127``)."""

    def __init__(self, detail: str) -> None:
        super().__init__(ErrorCode.DB_CONNECTION_FAILED, f"Database operation failed: {detail}")
