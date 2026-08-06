"""Phase 2.2.2 SRS ACT-INT-FR-120..127 — ``DatabaseConnector``.

Built using names imported from ``app.integration.sdk`` (plus this
package's own sibling module, ``declaration.py``, the standard library,
and ``socket`` for its reachability probe) — with **one specific,
documented deviation**: this file also imports ``DbWriteNotPermittedError``
from ``app.integration.errors``.

**Why that one deviation, and why it is narrow and justified (AC-20
explicitly allows "a justified, reported surface addition").** 2.2.1's
``RestConnector`` never needed a config-time error beyond the SDK's own
generic ``ConnectorConfigInvalidError``, because nothing in the REST
connector's declaration is rejected at configuration time with its own
distinct, stable error code. This sub-phase's own build prompt requires
exactly that for one specific case: a read-only instance declaring a
mutating query must be rejected with ``DB_WRITE_NOT_PERMITTED``
(``ACT-INT-FR-125``, AC-11) — a distinguishable, documented outcome an
author or a caller needs to be able to detect programmatically, not just
read in a message string. Rather than widen the SDK's own
``ConnectorConfigInvalidError`` (a change affecting every connector type,
for a need only this one has), this file imports one additional, specific
exception type for this one purpose — everything else about this
connector's declaration/parsing/tool-contract-derivation logic
(``declaration.py``) remains exactly as SDK-surface-restricted as 2.2.1's
own equivalent module."""

from __future__ import annotations

import socket
from typing import Any, Mapping

from app.integration.connectors.database.declaration import CONFIG_SCHEMA, mutating_query_names, parse_declaration
from app.integration.errors import DbWriteNotPermittedError
from app.integration.sdk import (
    Connector,
    ConnectorConfigInvalidError,
    ConnectorDescriptor,
    ToolContract,
    validate_configuration_schema,
)

CONNECTOR_TYPE = "DATABASE"
CONNECTOR_VERSION = "1.0.0"

_HEALTH_CHECK_TIMEOUT_SECONDS = 2.0

_DECLARATION_TOOL_CONTRACT = ToolContract(
    name="_declared_queries",
    description=(
        "Structural placeholder satisfying connector-type registration completeness "
        "(ACT-INT-FR-064). A configured database connector instance's real, invocable tool "
        "contracts are derived from its own 'queries' declaration -- one per declared query "
        "(ACT-INT-FR-121) -- see app.integration.connectors.database.declaration.tool_contracts_for(). "
        "The model never authors SQL: it names a declared query and supplies bound parameter values."
    ),
    parameters={"type": "object", "properties": {}, "additionalProperties": True},
)


class DatabaseConnector(Connector):
    """Declaration only — like every SDK-authored connector, this class
    never receives a credential, a database session, or another tenant's
    data, and (unlike ``executor.py``) it never connects to a database at
    all except for its own reachability-only ``health_check``. It has no
    method that accepts SQL, model-supplied or otherwise — there is
    nothing on this class an author could even attempt to route raw SQL
    through."""

    def __init__(self, *, connector_factory=None) -> None:
        # Test-only hook, not part of the ABC -- lets a test supply a fake
        # TCP-connect factory so `health_check` never performs a real
        # socket call, mirroring `RestConnector`'s own injectable-resolver
        # precedent (there, a DNS resolver; here, a connection factory).
        self._connector_factory = connector_factory or socket.create_connection

    def describe(self) -> ConnectorDescriptor:
        return ConnectorDescriptor(
            connector_type=CONNECTOR_TYPE,
            version=CONNECTOR_VERSION,
            capabilities={"category": "generic", "supports_read": True, "supports_write": False, "declarative": True},
            config_schema=CONFIG_SCHEMA,
            # "NONE" at the type level, deliberately, mirroring RestConnector
            # exactly: this generic type serves many database targets, each
            # with its own instance-declared credential scheme
            # (ACT-INT-FR-127), not one scheme fixed for every instance.
            auth_requirements={"scheme": "NONE"},
            tool_contracts=(_DECLARATION_TOOL_CONTRACT,),
        )

    def validate_configuration(self, configuration: Mapping[str, Any]) -> None:
        validate_configuration_schema(configuration, CONFIG_SCHEMA)
        declaration = parse_declaration(configuration)  # raises ConnectorConfigInvalidError (structural/semantic)
        if declaration.read_only:
            offenders = mutating_query_names(declaration)
            if offenders:
                raise DbWriteNotPermittedError(offenders)  # ACT-INT-FR-125, AC-11

    def health_check(self, configuration: Mapping[str, Any]) -> bool:
        """Reachability only, at the **TCP** level — never a credential,
        never a real query. A database connector's ``configuration`` (the
        ABC's own contract) never includes a credential in the first
        place (that is 2.1.2's separate, encrypted ``connector_credentials``
        store), so there is nothing here *to* leak even by accident. A raw
        socket connect proves "the database server is reachable on this
        host/port" without needing valid credentials or a real query."""
        try:
            declaration = parse_declaration(configuration)
        except ConnectorConfigInvalidError:
            return False
        try:
            connection = self._connector_factory((declaration.host, declaration.port), _HEALTH_CHECK_TIMEOUT_SECONDS)
        except OSError:
            return False
        try:
            connection.close()
        except OSError:
            pass
        return True
