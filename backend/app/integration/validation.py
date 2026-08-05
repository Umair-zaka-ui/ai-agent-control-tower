"""Phase 2.1.4 SRS ACT-INT-FR-064 — connector declaration completeness.

The one place a connector *type's* declaration (what ``describe()``
returns, plus a live smoke-call of ``health_check()``) is checked for
completeness before it may be registered. This is a different check from
``base.py``'s ``validate_configuration_schema``, which validates a tenant
*instance's* ``configuration`` against an already-registered type's
``config_schema`` — this module runs earlier and checks the type's own
declaration, not any instance's data.

**Single check, two callers, no privileged path** (``ACT-INT-FR-062``
extends to validation too): ``ConnectorTypeService.register`` (the real
registration path every ``_CONNECTOR_TYPES`` entry — first-party and
SDK-authored alike — goes through) and
``app.integration.sdk.testing.ConnectorTestHarness.assert_declaration_complete``
(so an SDK author can prove their connector will pass registration
*before* ever touching a database) both call this exact function. There is
no second, more lenient completeness check anywhere in this codebase.

**Why an actual call to ``health_check({})`` at registration time.** Every
other field on ``ConnectorDescriptor`` is inert data, checkable by
inspection alone. Whether ``health_check`` was *actually implemented* is
not — the ``Connector`` ABC already guarantees the method exists
(``TypeError`` at instantiation otherwise, Phase 2.1.1's own AC-02), but a
lazy/placeholder body satisfies the ABC while still being an incomplete
declaration in the sense this sub-phase's build prompt means ("missing
health-check implementation"). ``HealthCheckNotImplemented`` (below) is
this module's own, dedicated marker for exactly that placeholder case —
deliberately not Python's generic unimplemented-method builtin exception
(this codebase's own convention, enforced by an existing test in
``tests/integration/test_connector_health.py``, treats that builtin
exception's name anywhere under ``app/integration/`` as a leftover stub
marker; a dedicated exception here keeps that check meaningful instead of
colliding with it). A genuine, unexpected exception from a real
implementation being probed against an empty configuration is treated as
normal — that is exactly what ``ConnectorHealthService`` itself calls
``ERROR`` (distinct from ``UNHEALTHY``), not a sign the method was never
written — so only ``HealthCheckNotImplemented`` specifically is treated as
incompleteness here."""

from __future__ import annotations

from app.integration.auth import registry as auth_registry
from app.integration.base import Connector as ConnectorImplementation
from app.integration.errors import ConnectorDeclarationIncompleteError

_NO_AUTH_SCHEME = "NONE"


class HealthCheckNotImplemented(Exception):
    """A connector's own ``health_check()`` raises this — instead of
    leaving a placeholder body — to signal explicitly "this was never
    actually written." The one condition ``validate_declaration_complete``
    treats as an incomplete declaration rather than a legitimate runtime
    failure. Internal to registration/testing, never raised across an HTTP
    boundary — always caught here and translated into
    ``ConnectorDeclarationIncompleteError`` before anything is written."""


def validate_declaration_complete(implementation: ConnectorImplementation) -> None:
    """Raises ``ConnectorDeclarationIncompleteError`` naming every missing
    element at once (``ACT-INT-FR-064``'s "specific, actionable error" —
    AC-09), rather than stopping at the first failure."""
    descriptor = implementation.describe()
    missing: list[str] = []

    if not descriptor.config_schema or "type" not in descriptor.config_schema:
        missing.append("config_schema (must be a non-empty JSON Schema object)")

    if not descriptor.capabilities:
        missing.append("capabilities (must declare at least one)")

    if not descriptor.tool_contracts:
        missing.append("tool_contracts (must declare at least one)")
    else:
        for tool_contract in descriptor.tool_contracts:
            label = tool_contract.name or "<unnamed>"
            if not tool_contract.name or not tool_contract.description:
                missing.append(f"tool_contract '{label}' is missing a name or description")
            if not tool_contract.parameters or "type" not in tool_contract.parameters:
                missing.append(f"tool_contract '{label}' parameters must be a JSON Schema object")

    scheme_id = (descriptor.auth_requirements or {}).get("scheme")
    if not scheme_id:
        missing.append("auth_requirements.scheme")
    elif scheme_id != _NO_AUTH_SCHEME and scheme_id not in auth_registry.registered_identifiers():
        missing.append(f"auth_requirements.scheme '{scheme_id}' is not a registered authentication scheme")

    try:
        probe_result = implementation.health_check({})
    except HealthCheckNotImplemented:
        missing.append("health_check (not implemented)")
    except Exception:  # noqa: BLE001 -- an unexpected probe failure is ERROR-path behavior, not incompleteness
        pass
    else:
        if not isinstance(probe_result, bool):
            missing.append("health_check must return a bool")

    if missing:
        raise ConnectorDeclarationIncompleteError(descriptor.connector_type, missing)
