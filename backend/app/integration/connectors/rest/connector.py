"""Phase 2.2.1 SRS ACT-INT-FR-100..106 — ``RestConnector``.

Built using **only** names imported from ``app.integration.sdk`` (plus this
package's own sibling modules, ``declaration.py``, and the standard
library) — no import of ``app.integration.base``, ``app.integration.
service``, ``app.integration.auth``, or anything under ``app.runtime``
appears in this file. Exactly the discipline 2.1.4's worked example
(``WebhookConnector``) established, now proven against a connector that
does a real job, not a toy one (see
``tests/integration/test_rest_connector.py``'s AST import-inspection
test).

**Why ``describe()`` carries only a structural placeholder tool contract.**
``Connector.describe()`` is a zero-argument, type-level call —
``ConnectorTypeService.register()``/``ensure_seeded()`` instantiate
``RestConnector()`` with no configuration at all, the same way every other
connector type is registered. But a REST connector's *real* tool
contracts (``ACT-INT-FR-102`` — one per declared endpoint) only exist once
a specific *instance* has been configured with its own ``endpoints``
declaration; there is no way for a zero-argument, type-level ``describe()``
to produce them. Rather than widen the ``Connector`` ABC itself (a change
that would ripple into ``MockConnector``/``WebhookConnector`` too, for no
benefit to either), this connector's type-level ``describe()`` declares one
honest, self-documenting placeholder contract solely to satisfy
registration completeness (``ACT-INT-FR-064``); the real mechanism
``ACT-INT-FR-102`` describes is ``declaration.tool_contracts_for()``,
called per-instance by the platform bridge (``invoker.py``) once a
configuration exists. This is a deliberate, reported design decision, not
an oversight — see ``docs/integration/connectors.md``'s REST section."""

from __future__ import annotations

from typing import Any, Mapping
from urllib.parse import urlsplit

from app.integration.connectors.rest.declaration import CONFIG_SCHEMA, parse_declaration
from app.integration.sdk import (
    Connector,
    ConnectorConfigInvalidError,
    ConnectorDescriptor,
    GovernedHttpClient,
    ToolContract,
    validate_configuration_schema,
)

CONNECTOR_TYPE = "REST"
CONNECTOR_VERSION = "1.0.0"

_DECLARATION_TOOL_CONTRACT = ToolContract(
    name="_declared_endpoints",
    description=(
        "Structural placeholder satisfying connector-type registration completeness "
        "(ACT-INT-FR-064). A configured REST connector instance's real, invocable tool "
        "contracts are derived from its own 'endpoints' declaration -- one per endpoint "
        "(ACT-INT-FR-102) -- see app.integration.connectors.rest.declaration.tool_contracts_for()."
    ),
    parameters={"type": "object", "properties": {}, "additionalProperties": True},
)


class RestConnector(Connector):
    """Declaration only — like every SDK-authored connector, this class
    never receives a credential, a database session, or another tenant's
    data. Authentication for a configured instance is applied entirely
    outside this class (``app.integration.auth``, not imported here) by
    the platform bridge, using the instance's own declared ``auth_scheme``
    (``ACT-INT-FR-101``)."""

    def __init__(self, *, resolver=None) -> None:
        # Test-only hook, not part of the ABC -- lets a test supply a fake
        # DNS resolver so `health_check` never performs a real lookup,
        # mirroring `WebhookConnector`'s own precedent exactly.
        self._resolver = resolver

    def describe(self) -> ConnectorDescriptor:
        return ConnectorDescriptor(
            connector_type=CONNECTOR_TYPE,
            version=CONNECTOR_VERSION,
            capabilities={"category": "generic", "supports_read": True, "supports_write": True, "declarative": True},
            config_schema=CONFIG_SCHEMA,
            # "NONE" at the type level, deliberately: this generic type
            # serves many vendor APIs, each with its own instance-declared
            # scheme (part of `configuration`, ACT-INT-FR-101) -- not one
            # scheme fixed for every instance of this type, unlike every
            # 2.1.x connector type. See invoker.py / docs for how a
            # per-instance scheme is actually applied.
            auth_requirements={"scheme": "NONE"},
            tool_contracts=(_DECLARATION_TOOL_CONTRACT,),
        )

    def validate_configuration(self, configuration: Mapping[str, Any]) -> None:
        validate_configuration_schema(configuration, CONFIG_SCHEMA)
        parse_declaration(configuration)  # raises ConnectorConfigInvalidError on semantic issues (AC-04)

    def health_check(self, configuration: Mapping[str, Any]) -> bool:
        """Pre-flights the declared ``base_url``'s host through a
        ``GovernedHttpClient`` built with exactly that host (plus any
        declared ``additional_allowed_hosts``) as its allowed set --
        reachability only, never a credential, mirroring every other
        connector's ``health_check()`` in this codebase."""
        try:
            declaration = parse_declaration(configuration)
        except ConnectorConfigInvalidError:
            return False
        host = urlsplit(declaration.base_url).hostname
        if not host:
            return False
        allowed_hosts = {host} | declaration.additional_allowed_hosts
        local_dev_hosts = allowed_hosts if declaration.allow_plaintext_http else frozenset()
        client = GovernedHttpClient(
            allowed_hosts=allowed_hosts, allow_plaintext_http=declaration.allow_plaintext_http,
            local_dev_hosts=local_dev_hosts,
        )
        return client.evaluate(declaration.base_url, resolver=self._resolver).allowed
