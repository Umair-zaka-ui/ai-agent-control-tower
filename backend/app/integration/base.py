"""Phase 2.1.1 SRS ACT-INT-FR-001, FR-006 — the connector contract.

Structural twin of ``app/runtime/providers/base.py``'s ``ModelProvider``:
every connector implementation (``MockConnector`` today; a real generic
REST/database/storage/queue connector in 2.2.x, vendor-specific ones as
fast-follow work after that) satisfies exactly this interface. Nothing
outside a connector's own module may know that connector's specifics —
this is ``ACT-INT-FR-006``, the **runtime-never-knows principle**, the
spine of this whole milestone (§3.3 of the SRS): the runtime, model
gateway and ``ToolGatewayService`` core must never be able to tell a
connector-backed Tool from an echo Tool. Everything crossing this
boundary is expressed in the connector-neutral types in ``types.py``.

``describe()`` and ``validate_configuration()`` are both abstract —
every concrete connector must implement both, or it cannot be
instantiated (AC-01, AC-02). Deliberately **no** ``authenticate()``,
``execute()`` or ``health_check()`` method exists here — those belong to
2.1.2 (authentication framework), 2.1.3 (registry & health) and the
tool-bridge respectively, all explicitly out of scope for this
sub-phase. If expressing ``MockConnector`` ever required adding one of
those, that would be a sign the ABC had drifted ahead of its own
sub-phase's scope; it does not (AC-03)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Mapping

import jsonschema

from app.integration.errors import ConnectorConfigInvalidError
from app.integration.types import ConnectorDescriptor


def validate_configuration_schema(configuration: Mapping[str, Any], config_schema: Mapping[str, Any]) -> None:
    """The one place a connector instance's configuration is checked
    against a JSON Schema — reusing the exact ``jsonschema`` library
    Milestone 1 already validates tool/agent contracts with (see
    ``app/runtime/services.py``'s ``_validate_schema``), not a new
    validator (per the build prompt's own working constraint). Kept here,
    not imported from ``app.runtime.services``, since that module is a
    sibling domain's internal implementation detail, not a published
    shared utility — importing a private helper across domains would be
    a tighter coupling than reusing the one line of standard-library-
    adjacent validation logic it wraps."""
    try:
        jsonschema.validate(instance=dict(configuration), schema=dict(config_schema))
    except jsonschema.ValidationError as exc:
        raise ConnectorConfigInvalidError(exc.message) from exc
    except jsonschema.SchemaError as exc:
        raise ConnectorConfigInvalidError(f"the connector's own config_schema is invalid: {exc.message}") from exc


class Connector(ABC):
    """The contract every connector *type* implementation satisfies."""

    @abstractmethod
    def describe(self) -> ConnectorDescriptor:
        """Returns this connector type's full declaration: identifier,
        contract version, capabilities, configuration schema, declared
        authentication requirements, and the tool contract(s) it exposes
        (``ACT-INT-FR-002``)."""

    @abstractmethod
    def validate_configuration(self, configuration: Mapping[str, Any]) -> None:
        """Validates a prospective instance ``configuration`` for this
        connector type, raising ``ConnectorConfigInvalidError`` on
        failure. Every concrete connector must implement this — the
        expected, sufficient implementation for a connector with no
        validation beyond its declared JSON Schema is exactly
        ``MockConnector``'s (a one-line call to
        ``validate_configuration_schema`` above); the hook exists,
        abstract, so a future connector *can* layer additional checks
        (e.g. cross-field consistency JSON Schema cannot express) without
        this base class needing to change to accommodate it."""
