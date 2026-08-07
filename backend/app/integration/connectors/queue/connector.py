"""Phase 2.2.4 SRS ACT-INT-FR-160..164 — ``QueueConnector``.

Built using names imported from ``app.integration.sdk`` only (plus this
package's own sibling module, ``declaration.py``, and the standard
library) — **zero deviations** from the pure-SDK-surface discipline, the
same shape 2.2.1's REST connector had (see ``declaration.py``'s own
module docstring for why this phase, unlike 2.2.2/2.2.3, needed none)."""

from __future__ import annotations

import socket
from typing import Any, Mapping

from app.integration.connectors.queue.declaration import CONFIG_SCHEMA, parse_declaration
from app.integration.sdk import (
    Connector,
    ConnectorConfigInvalidError,
    ConnectorDescriptor,
    ToolContract,
    validate_configuration_schema,
)

CONNECTOR_TYPE = "QUEUE"
CONNECTOR_VERSION = "1.0.0"

_HEALTH_CHECK_TIMEOUT_SECONDS = 2.0
_DEFAULT_AMQP_PORT = 5672
_DEFAULT_SQS_HOST = "sqs.amazonaws.com"
_DEFAULT_SQS_PORT = 443

_DECLARATION_TOOL_CONTRACT = ToolContract(
    name="_declared_bindings",
    description=(
        "Structural placeholder satisfying connector-type registration completeness "
        "(ACT-INT-FR-064). A configured queue connector instance's real, invocable tool "
        "contracts are derived from its own 'bindings' declaration -- one per declared "
        "binding (ACT-INT-FR-161) -- see app.integration.connectors.queue.declaration."
        "tool_contracts_for(). Publish is scoped to declared queues (the target is fixed "
        "by the tool contract, never a model-supplied value); consume is always bounded "
        "to at most N messages within a bounded wait, never an unbounded stream."
    ),
    parameters={"type": "object", "properties": {}, "additionalProperties": True},
)


class QueueConnector(Connector):
    """Declaration only — like every SDK-authored connector, this class
    never receives a credential, a database session, or another
    tenant's data, and (unlike ``backends.py``) it never publishes or
    consumes a message at all except for its own reachability-only
    ``health_check``. It has no method that accepts a queue name or a
    message payload — there is nothing on this class an author could
    even attempt to route an unscoped publish through."""

    def __init__(self, *, connector_factory=None) -> None:
        # Test-only hook, not part of the ABC -- lets a test supply a fake
        # TCP-connect factory so `health_check` never performs a real
        # socket call, mirroring `DatabaseConnector`/`StorageConnector`'s
        # own injectable-resolver precedent.
        self._connector_factory = connector_factory or socket.create_connection

    def describe(self) -> ConnectorDescriptor:
        return ConnectorDescriptor(
            connector_type=CONNECTOR_TYPE,
            version=CONNECTOR_VERSION,
            capabilities={
                "category": "generic", "supports_publish": True, "supports_consume": True, "declarative": True,
            },
            config_schema=CONFIG_SCHEMA,
            # "NONE" at the type level, deliberately, mirroring every other
            # generic connector: this type serves many broker targets, each
            # with its own instance-declared credential scheme.
            auth_requirements={"scheme": "NONE"},
            tool_contracts=(_DECLARATION_TOOL_CONTRACT,),
        )

    def validate_configuration(self, configuration: Mapping[str, Any]) -> None:
        validate_configuration_schema(configuration, CONFIG_SCHEMA)
        parse_declaration(configuration)  # raises ConnectorConfigInvalidError (semantic)

    def health_check(self, configuration: Mapping[str, Any]) -> bool:
        """Reachability only — never a credential, never a real publish
        or consume. A raw TCP connect to the declared broker
        (AMQP: ``host``/``port``; SQS: the configured/default endpoint
        host) proves network-level reachability without authenticating
        or touching a queue at all — the same "TCP reachability only"
        contract every prior generic connector's ``health_check``
        established."""
        try:
            declaration = parse_declaration(configuration)
        except ConnectorConfigInvalidError:
            return False

        if declaration.backend == "AMQP":
            host, port = declaration.host or "localhost", declaration.port or _DEFAULT_AMQP_PORT
        else:
            if declaration.endpoint_url:
                from urllib.parse import urlsplit

                parts = urlsplit(declaration.endpoint_url)
                host = parts.hostname or _DEFAULT_SQS_HOST
                port = parts.port or (443 if parts.scheme != "http" else 80)
            else:
                host, port = _DEFAULT_SQS_HOST, _DEFAULT_SQS_PORT
        try:
            connection = self._connector_factory((host, port), _HEALTH_CHECK_TIMEOUT_SECONDS)
        except OSError:
            return False
        try:
            connection.close()
        except OSError:
            pass
        return True
