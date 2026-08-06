"""Phase 2.2.2 SRS ACT-INT-FR-120..127 — the database connector's
tool-invocation bridge.

Mirrors ``app/integration/connectors/rest/invoker.py`` exactly: platform
bridge code sitting *above* ``DatabaseConnector``, not SDK-surface-
restricted, making a database connector instance's declared queries
genuinely invocable end to end. Resolves the instance (fail-fast, the
unchanged 2.1.3 registry), resolves its credential bundle via the
2.2.1-established ``ConnectorCredentialService`` extension, gets or
creates its per-instance connection pool (``drivers.py``), validates the
caller's parameters against the named query's own declared schema, and
executes through ``executor.py`` — the one, only module in this codebase
that ever turns a declared query + bound parameters into a real database
call.

**The model's entire surface through this bridge is a query name (which
must match a declaration) and parameter values (validated, then bound).**
Nothing here, or in anything this module calls, accepts a SQL string from
``invoke_tool``'s caller."""

from __future__ import annotations

import uuid
from typing import Any, Mapping

import jsonschema
from sqlalchemy.orm import Session

from app.integration.auth.service import ConnectorCredentialService
from app.integration.connectors.database import declaration, drivers, executor
from app.integration.connectors.database.declaration import DatabaseDeclaration, DeclaredQuery
from app.integration.connectors.database.executor import (
    QueryExecutionError,
    QueryTimeoutError,
    ResultLimitExceededError,
)
from app.integration.errors import (
    DbConnectionFailedError,
    DbParameterInvalidError,
    DbQueryNotDeclaredError,
    DbQueryTimeoutError,
    DbResultLimitExceededError,
)
from app.integration.registry import ConnectorRegistry

_NO_AUTH_SCHEME = "NONE"


def _query_by_name(decl: DatabaseDeclaration, query_name: str) -> DeclaredQuery:
    query = decl.query_by_name(query_name)
    if query is None:
        raise DbQueryNotDeclaredError(query_name)
    return query


def _validate_parameters(query: DeclaredQuery, params: Mapping[str, Any]) -> None:
    try:
        jsonschema.validate(instance=dict(params), schema=dict(query.parameters))
    except jsonschema.ValidationError as exc:
        raise DbParameterInvalidError(exc.message) from exc
    except jsonschema.SchemaError as exc:
        raise DbParameterInvalidError(f"the query's own parameter schema is invalid: {exc.message}") from exc


def run_query(
    decl: DatabaseDeclaration, engine, query_name: str, params: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Runs one declared query against an already-built engine — no
    database, no credential resolution; split out from ``invoke_tool``
    below so a caller that already has a resolved declaration and a live
    engine (this module's own tests) doesn't need a real connector
    instance row at all."""
    query = _query_by_name(decl, query_name)
    _validate_parameters(query, params)
    row_limit = decl.effective_row_limit(query)
    timeout_seconds = decl.effective_timeout_seconds(query)
    try:
        return executor.execute_declared_query(
            engine, decl.dialect, query, params, row_limit=row_limit, timeout_seconds=timeout_seconds,
        )
    except QueryTimeoutError as exc:
        raise DbQueryTimeoutError(query.name, timeout_seconds) from exc
    except ResultLimitExceededError as exc:
        raise DbResultLimitExceededError(query.name, row_limit) from exc
    except QueryExecutionError as exc:
        raise DbConnectionFailedError(str(exc)) from exc


def invoke_tool(
    db: Session, organization_id: uuid.UUID, instance_id: uuid.UUID, query_name: str, params: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """The full, database-backed path: fail-fast resolve the instance
    (``ACT-INT-FR-044``, inherited unchanged from the registry), parse its
    declaration, resolve its declared credential (never inside
    ``DatabaseConnector`` itself), get or create its per-instance
    connection pool, and run the named declared query. This is what makes
    a database connector's declared queries genuinely callable end to end
    (AC-23)."""
    registry = ConnectorRegistry(db)
    resolved = registry.resolve_instance_for_invocation(organization_id, instance_id)
    decl = declaration.parse_declaration(resolved.configuration)

    username: str | None = None
    password: str | None = None
    if decl.auth_scheme != _NO_AUTH_SCHEME:
        instance_row = registry.instances.get_or_404(organization_id, instance_id)
        bundle = ConnectorCredentialService(db).resolve_credential_bundle(instance_row, decl.auth_scheme)
        username = bundle.get("username")
        password = bundle.get("password")

    engine = drivers.get_or_create_engine(
        instance_id, decl.dialect, decl.host, decl.port, decl.database,
        username=username, password=password, pool_size=decl.pool_size, max_overflow=decl.max_overflow,
    )
    return run_query(decl, engine, query_name, params)
