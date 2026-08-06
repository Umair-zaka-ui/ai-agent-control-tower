"""Phase 2.2.3 SRS ACT-INT-FR-140..145 — ``StorageConnector``.

Built using names imported from ``app.integration.sdk`` (plus this
package's own sibling module, ``declaration.py``, and the standard
library) — with **one specific, documented deviation**: this file also
imports ``StorageWriteNotPermittedError`` from ``app.integration.errors``.

**Why, and why it is narrow and justified** — exactly 2.2.2's
``connector.py`` precedent: a read-only instance declaring one or more
write scopes must be rejected at *configuration* time with a
distinguishable, stable, machine-checkable code
(``STORAGE_WRITE_NOT_PERMITTED``, ``ACT-INT-FR-144``), not merely a
message string. ``declaration.py`` already carries its own, separately
justified deviation (``StorageScopeInvalidError``, see that module's
docstring) for shape-level semantic errors; this file's own deviation is
narrower still — one exception type, for one specific, distinguishable
outcome the SDK's generic ``ConnectorConfigInvalidError`` cannot express
without becoming REST/database/storage-specific itself."""

from __future__ import annotations

import socket
from typing import Any, Mapping
from urllib.parse import urlsplit

from app.integration.connectors.storage.declaration import CONFIG_SCHEMA, parse_declaration, write_scope_names
from app.integration.errors import StorageScopeInvalidError, StorageWriteNotPermittedError
from app.integration.sdk import (
    Connector,
    ConnectorDescriptor,
    ToolContract,
    validate_configuration_schema,
)

CONNECTOR_TYPE = "STORAGE"
CONNECTOR_VERSION = "1.0.0"

_HEALTH_CHECK_TIMEOUT_SECONDS = 2.0
_DEFAULT_OBJECT_STORE_HOST = "s3.amazonaws.com"
_DEFAULT_OBJECT_STORE_PORT = 443

_DECLARATION_TOOL_CONTRACT = ToolContract(
    name="_declared_scopes",
    description=(
        "Structural placeholder satisfying connector-type registration completeness "
        "(ACT-INT-FR-064). A configured storage connector instance's real, invocable tool "
        "contracts are derived from its own 'scopes' declaration -- one per declared scope "
        "(ACT-INT-FR-141) -- see app.integration.connectors.storage.declaration.tool_contracts_for(). "
        "A model-supplied path can never escape its declared scope: it is canonicalized and "
        "proven in-bounds before any read or write is attempted."
    ),
    parameters={"type": "object", "properties": {}, "additionalProperties": True},
)


class StorageConnector(Connector):
    """Declaration only — like every SDK-authored connector, this class
    never receives a credential, a database session, or another
    tenant's data, and (unlike ``backends.py``) it never reads or writes
    an object at all except for its own reachability-only
    ``health_check``. It has no method that accepts a resolved
    filesystem/object path — there is nothing on this class an author
    could even attempt to route an unvalidated path through."""

    def __init__(self, *, connector_factory=None) -> None:
        # Test-only hook, not part of the ABC -- lets a test supply a fake
        # TCP-connect factory so `health_check` never performs a real
        # socket call for the object-store path, mirroring
        # `DatabaseConnector`'s own injectable-resolver precedent.
        self._connector_factory = connector_factory or socket.create_connection

    def describe(self) -> ConnectorDescriptor:
        return ConnectorDescriptor(
            connector_type=CONNECTOR_TYPE,
            version=CONNECTOR_VERSION,
            capabilities={"category": "generic", "supports_read": True, "supports_write": False, "declarative": True},
            config_schema=CONFIG_SCHEMA,
            # "NONE" at the type level, deliberately, mirroring RestConnector/
            # DatabaseConnector exactly: this generic type serves many storage
            # targets, each with its own instance-declared credential scheme.
            auth_requirements={"scheme": "NONE"},
            tool_contracts=(_DECLARATION_TOOL_CONTRACT,),
        )

    def validate_configuration(self, configuration: Mapping[str, Any]) -> None:
        validate_configuration_schema(configuration, CONFIG_SCHEMA)
        declaration = parse_declaration(configuration)  # raises StorageScopeInvalidError (semantic)
        if declaration.read_only:
            offenders = write_scope_names(declaration)
            if offenders:
                raise StorageWriteNotPermittedError(offenders)  # ACT-INT-FR-144

    def health_check(self, configuration: Mapping[str, Any]) -> bool:
        """Reachability only — never a credential, never a real object
        read/write. For ``FILESYSTEM``, every declared scope's own base
        directory must exist and be a real directory. For ``S3``, a raw
        TCP connect to the configured (or default AWS) endpoint host
        proves network-level reachability without authenticating or
        listing anything — the same "TCP reachability only" contract
        ``DatabaseConnector.health_check`` established."""
        try:
            declaration = parse_declaration(configuration)
        except StorageScopeInvalidError:
            return False

        if declaration.backend == "FILESYSTEM":
            return self._filesystem_health(declaration)
        return self._object_store_health(declaration)

    def _filesystem_health(self, declaration) -> bool:
        import os

        for scope in declaration.scopes:
            if not os.path.isdir(scope.root):
                return False
        return True

    def _object_store_health(self, declaration) -> bool:
        if declaration.endpoint_url:
            parts = urlsplit(declaration.endpoint_url)
            host = parts.hostname or _DEFAULT_OBJECT_STORE_HOST
            port = parts.port or (443 if parts.scheme != "http" else 80)
        else:
            host, port = _DEFAULT_OBJECT_STORE_HOST, _DEFAULT_OBJECT_STORE_PORT
        try:
            connection = self._connector_factory((host, port), _HEALTH_CHECK_TIMEOUT_SECONDS)
        except OSError:
            return False
        try:
            connection.close()
        except OSError:
            pass
        return True
