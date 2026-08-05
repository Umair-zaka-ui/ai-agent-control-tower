"""Phase 2.1.4 SRS ACT-INT-FR-063 — fixture-based connector testing, no live
external system required.

Formalizes the pattern ``MockConnector``'s and ``MockAuthenticatedConnector``'s
own test suites (2.1.1–2.1.3) already established: exercise ``describe()``,
``validate_configuration()`` and ``health_check()`` directly, in-process,
against synthetic configurations — never a real database, real credential,
or real network call. ``ConnectorTestHarness`` packages that pattern into a
small, reusable object so an SDK author writes connector tests the exact
way this platform's own connectors are tested, per the build prompt's own
§4.5.

Every method here is pure and makes no I/O of its own. A connector's own
``health_check()`` may choose to reach out through ``GovernedHttpClient``
(``app.integration.sdk.http``) — this harness neither requires nor
prevents that; it simply calls the connector's declared methods and
reports what happened."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from app.integration.base import Connector
from app.integration.errors import ConnectorConfigInvalidError
from app.integration.types import ToolContract
from app.integration.validation import validate_declaration_complete


@dataclass(frozen=True, slots=True)
class HealthCheckOutcome:
    """The result of exercising ``health_check()`` against a synthetic
    configuration. ``reachable`` is ``None`` when the call raised — mirrors
    ``ConnectorHealthService``'s own ``ERROR`` (raised) vs. ``UNHEALTHY``
    (cleanly returned ``False``) distinction (``ACT-INT-FR-042``), so a
    harness caller can assert either outcome without writing its own
    ``try``/``except``."""

    reachable: bool | None
    error: str | None = None


class ConnectorTestHarness:
    """Wraps one connector implementation instance under test."""

    def __init__(self, connector: Connector) -> None:
        self.connector = connector

    def describe(self):
        return self.connector.describe()

    def assert_declaration_complete(self) -> None:
        """``ACT-INT-FR-064``'s own check, runnable standalone — an author
        proves their connector will pass registration before ever touching
        a database. Raises ``ConnectorDeclarationIncompleteError`` (the
        same, single check ``ConnectorTypeService.register`` itself runs)
        if it would not."""
        validate_declaration_complete(self.connector)

    def assert_configuration_valid(self, configuration: Mapping[str, Any]) -> None:
        """Raises whatever ``validate_configuration`` itself raises on
        failure — typically ``ConnectorConfigInvalidError``."""
        self.connector.validate_configuration(configuration)

    def assert_configuration_invalid(self, configuration: Mapping[str, Any]) -> str:
        """Returns the rejection message. Raises ``AssertionError`` — not
        the connector's own exception — if ``configuration`` was
        unexpectedly *accepted*, so a misbehaving connector fails the test
        loudly rather than the assertion silently passing for the wrong
        reason."""
        try:
            self.connector.validate_configuration(configuration)
        except ConnectorConfigInvalidError as exc:
            return str(exc)
        raise AssertionError(f"expected configuration {configuration!r} to be rejected, but it was accepted")

    def run_health_check(self, configuration: Mapping[str, Any]) -> HealthCheckOutcome:
        """Calls ``health_check(configuration)`` once, against whatever
        synthetic configuration the caller supplies — no live external
        system, no network call this harness performs itself."""
        try:
            result = self.connector.health_check(configuration)
        except Exception as exc:  # noqa: BLE001 -- mirrors ConnectorHealthService's own ERROR handling
            return HealthCheckOutcome(reachable=None, error=str(exc))
        return HealthCheckOutcome(reachable=bool(result), error=None)

    def tool_contract(self, name: str) -> ToolContract:
        """Returns the declared ``ToolContract`` by name — exercises its
        shape (parameters JSON Schema, description) without any live
        invocation, since no invocation mechanism exists yet (2.2.x's
        tool bridge)."""
        for contract in self.connector.describe().tool_contracts:
            if contract.name == name:
                return contract
        raise AssertionError(f"connector declares no tool contract named {name!r}")
