"""Phase 2.1.1 SRS ACT-INT-FR-001 — MockConnector.

The trivial reference implementation, exactly as ``MockProvider`` was for
5.7a.1 (``app/runtime/providers/mock.py``): proof that ``Connector`` can
express a connector type without distortion, and the fixture every
lifecycle test in this sub-phase runs against. Declares one small
capability set, one config schema (a single required ``endpoint``
string — enough to exercise real pass/fail validation without inventing
a connector-specific concept), no real authentication requirement, and
one trivial tool contract (``ping`` — declaration only; nothing executes
it, since the tool bridge is out of scope this sub-phase)."""

from __future__ import annotations

from typing import Any, Mapping

from app.integration.base import Connector, validate_configuration_schema
from app.integration.types import ConnectorDescriptor, ToolContract

CONNECTOR_TYPE = "MOCK"
CONNECTOR_VERSION = "1.0.0"

_CONFIG_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"endpoint": {"type": "string", "minLength": 1}},
    "required": ["endpoint"],
    "additionalProperties": True,
}


class MockConnector(Connector):
    def describe(self) -> ConnectorDescriptor:
        return ConnectorDescriptor(
            connector_type=CONNECTOR_TYPE,
            version=CONNECTOR_VERSION,
            capabilities={"category": "reference", "supports_read": True, "supports_write": False},
            config_schema=_CONFIG_SCHEMA,
            auth_requirements={"scheme": "NONE"},
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
