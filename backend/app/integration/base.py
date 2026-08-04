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

``describe()``, ``validate_configuration()``, and — as of Phase 2.1.3 —
``health_check()`` are all abstract: every concrete connector must
implement all three, or it cannot be instantiated (AC-01, AC-02).
Deliberately **still no** ``authenticate()`` or ``execute()`` method
here — authentication is 2.1.2's `AuthScheme` framework (applied
*outside* a connector's own code, never inside it), and actually
invoking a connector is the tool-bridge's job, still out of scope until
2.2.x. Adding `health_check()` now is expected and additive — unlike the
auth-related methods 2.1.1 deliberately withheld, this sub-phase's own
job is exactly to drive health monitoring, so the ABC grows the one
capability it actually needs. If expressing ``MockConnector`` ever
required adding `authenticate()`/`execute()`, that would be a sign the
ABC had drifted ahead of its own sub-phase's scope; it does not (AC-21)."""

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

    @abstractmethod
    def health_check(self, configuration: Mapping[str, Any]) -> bool:
        """Phase 2.1.3, ``ACT-INT-FR-042`` — returns whether this
        connector's declared endpoint is *reachable*, given a live
        instance's ``configuration``. Deliberately narrow: this method
        answers reachability only, never authentication validity —
        credential/token validity is checked separately by
        ``ConnectorCredentialService.validate()`` (reusing all of 2.1.2's
        own machinery), so a connector's ``health_check()`` is never
        handed a decrypted credential at all (``ACT-INT-FR-047`` is
        easier to guarantee when the method that could leak one never
        receives it in the first place). May raise on an unexpected
        failure (a bug, a malformed configuration) — ``ConnectorHealthService``
        treats a raised exception as ``ERROR``, distinct from a clean
        ``False`` return (``UNHEALTHY``); an implementation should reserve
        raising for genuinely unexpected conditions, not ordinary
        "the endpoint is down" outcomes, which are exactly what
        returning ``False`` means."""
