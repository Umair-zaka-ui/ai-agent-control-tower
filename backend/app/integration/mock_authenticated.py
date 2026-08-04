"""Phase 2.1.2 — MockAuthenticatedConnector.

A second reference connector, added alongside 2.1.1's ``MockConnector``
rather than modifying it (2.1.1's own tests assert
``MockConnector().describe().auth_requirements == {"scheme": "NONE"}`` —
changing that would break an already-shipped, already-tested contract).
Declares a real authentication requirement (``API_KEY``) so this
sub-phase's framework is exercised end to end against a mock, per the
build prompt's own instruction ("extend `MockConnector` (or add a second
mock)")."""

from __future__ import annotations

from typing import Any, Mapping

from app.integration.base import Connector, validate_configuration_schema
from app.integration.types import ConnectorDescriptor, ToolContract

CONNECTOR_TYPE = "MOCK_AUTH"
CONNECTOR_VERSION = "1.0.0"

_CONFIG_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"endpoint": {"type": "string", "minLength": 1}},
    "required": ["endpoint"],
    "additionalProperties": True,
}


class MockAuthenticatedConnector(Connector):
    def describe(self) -> ConnectorDescriptor:
        return ConnectorDescriptor(
            connector_type=CONNECTOR_TYPE,
            version=CONNECTOR_VERSION,
            capabilities={"category": "reference", "supports_read": True, "supports_write": False},
            config_schema=_CONFIG_SCHEMA,
            auth_requirements={"scheme": "API_KEY"},
            tool_contracts=(
                ToolContract(
                    name="ping",
                    description="Trivial reference tool contract — declaration only, never invoked.",
                    parameters={"type": "object", "properties": {}, "additionalProperties": False},
                ),
            ),
        )

    def validate_configuration(self, configuration: Mapping[str, Any]) -> None:
        validate_configuration_schema(configuration, self.describe().config_schema)

    def health_check(self, configuration: Mapping[str, Any]) -> bool:
        """Phase 2.1.3 — same configurable simulation as ``MockConnector``;
        this type's `API_KEY` `auth_requirements` is what actually lets a
        health check exercise the credential-validity half too (see
        ``app/integration/health.py``)."""
        if configuration.get("simulate_error"):
            raise RuntimeError("MockAuthenticatedConnector simulated a health-check execution error")
        return not configuration.get("simulate_unreachable", False)
