"""Phase 2.2.3 SRS ACT-INT-FR-140..145 — the storage connector's
tool-invocation bridge.

Mirrors ``app/integration/connectors/database/invoker.py`` exactly:
platform bridge code sitting *above* ``StorageConnector``, not
SDK-surface-restricted. Resolves the instance (fail-fast, the unchanged
2.1.3 registry), resolves its credential bundle via the 2.2.1-established
``ConnectorCredentialService`` extension, and — **before any backend
call** — validates the caller's supplied ``path`` against the named
scope's own declared boundary via ``scope.resolve_and_contain``. Nothing
here, or in anything this module calls, ever performs a read or write
against a path/key that has not first been proven to resolve inside its
declared scope.

**Every access attempt is recorded in the platform audit trail
(``ACT-INT-FR-145``)** — allowed or denied, read or write — carrying the
*validated* path (never the raw supplied string, and never a credential),
via a ``finally`` block so a denial is audited exactly as reliably as a
success."""

from __future__ import annotations

import uuid
from typing import Any, Mapping

from sqlalchemy.orm import Session

from app.authorization.enums import AuthorizationAuditEvent
from app.authorization.services import AuthorizationAuditService
from app.integration.auth.service import ConnectorCredentialService
from app.integration.connectors.storage import backends, declaration, scope as scope_mod
from app.integration.connectors.storage.declaration import DeclaredStorageScope, StorageDeclaration
from app.integration.errors import (
    StorageBackendFailedError,
    StorageObjectNotFoundError,
    StorageObjectTooLargeError,
    StoragePathDeniedError,
)
from app.integration.registry import ConnectorRegistry
from app.models.integration import ConnectorInstance

_NO_AUTH_SCHEME = "NONE"


class StorageScopeNotDeclaredError(Exception):
    """Local, translated immediately in ``invoke_tool`` — kept as a
    distinct local type only so ``run_access`` (used directly by this
    module's own tests) doesn't need a live registry/instance row to
    exercise "unknown scope name"."""


def _scope_by_name(decl: StorageDeclaration, scope_name: str) -> DeclaredStorageScope:
    scope = decl.scope_by_name(scope_name)
    if scope is None:
        raise StorageScopeNotDeclaredError(scope_name)
    return scope


def _record_access(
    db: Session, organization_id: uuid.UUID, instance_id: uuid.UUID, *,
    backend: str, scope_name: str, operation: str, path: str | None, size_bytes: int | None, outcome: str,
) -> None:
    AuthorizationAuditService(db).record_change(
        AuthorizationAuditEvent.INTEGRATION_CONNECTOR_OBJECT_ACCESSED,
        organization_id=organization_id, actor_id=None,
        meta={
            "connector_instance_id": str(instance_id), "backend": backend, "scope_name": scope_name,
            "operation": operation, "path": path, "size_bytes": size_bytes, "outcome": outcome,
        },
    )


def _validate(storage_scope: DeclaredStorageScope, supplied_path: str) -> scope_mod.ValidatedTarget:
    try:
        return scope_mod.resolve_and_contain(storage_scope.to_boundary(), supplied_path)
    except scope_mod.ScopeViolationError as exc:
        raise StoragePathDeniedError(str(exc)) from exc


def _perform(
    decl: StorageDeclaration, storage_scope: DeclaredStorageScope, target: scope_mod.ValidatedTarget,
    credential: Mapping[str, Any], *, content: bytes | None,
) -> bytes | int:
    try:
        if storage_scope.operation == "READ":
            return backends.read_object(decl, storage_scope, target, credential)
        if content is None:
            raise StoragePathDeniedError("a write operation requires 'content'")
        return backends.write_object(decl, storage_scope, target, content, credential)
    except backends.ObjectNotFoundError as exc:
        raise StorageObjectNotFoundError(str(exc)) from exc
    except backends.ObjectTooLargeError as exc:
        raise StorageObjectTooLargeError(str(exc)) from exc
    except backends.StorageBackendError as exc:
        raise StorageBackendFailedError(str(exc)) from exc


def run_access(
    decl: StorageDeclaration, storage_scope: DeclaredStorageScope, supplied_path: str,
    credential: Mapping[str, Any], *, content: bytes | None = None,
) -> bytes | int:
    """Validates ``supplied_path`` against ``storage_scope``'s own
    declared boundary and performs the one operation the scope declares
    (``READ`` returns the object's bytes; ``WRITE`` writes ``content``
    and returns the byte count written) — no database, no credential
    resolution, no audit; split out from ``invoke_tool`` below so a
    caller that already has a resolved declaration and credential (this
    module's own tests) doesn't need a real connector instance row at
    all."""
    target = _validate(storage_scope, supplied_path)
    return _perform(decl, storage_scope, target, credential, content=content)


def invoke_tool(
    db: Session, organization_id: uuid.UUID, instance_id: uuid.UUID, scope_name: str, arguments: Mapping[str, Any],
) -> bytes | int:
    """The full, database-backed path: fail-fast resolve the instance
    (``ACT-INT-FR-044``, inherited unchanged from the registry), parse
    its declaration, resolve its declared credential (never inside
    ``StorageConnector`` itself), validate the supplied path against the
    named scope's declared boundary, perform the one operation the
    scope declares, and record the attempt in the audit trail regardless
    of outcome. This is what makes a storage connector's declared
    scopes genuinely callable end to end (AC-24)."""
    registry = ConnectorRegistry(db)
    resolved = registry.resolve_instance_for_invocation(organization_id, instance_id)
    decl = declaration.parse_declaration(resolved.configuration)
    storage_scope = _scope_by_name(decl, scope_name)

    credential: dict[str, Any] = {}
    if decl.auth_scheme != _NO_AUTH_SCHEME:
        instance_row: ConnectorInstance = registry.instances.get_or_404(organization_id, instance_id)
        credential = ConnectorCredentialService(db).resolve_credential_bundle(instance_row, decl.auth_scheme)

    content = arguments.get("content")
    if isinstance(content, str):
        content = content.encode("utf-8")

    outcome = "ERROR"
    validated_path: str | None = None
    size_bytes: int | None = None
    try:
        try:
            target = _validate(storage_scope, arguments.get("path"))
        except StoragePathDeniedError:
            outcome = "DENIED"
            raise
        validated_path = target.relative_path

        try:
            result = _perform(decl, storage_scope, target, credential, content=content)
        except StorageObjectNotFoundError:
            outcome = "NOT_FOUND"
            raise
        except StorageObjectTooLargeError:
            outcome = "TOO_LARGE"
            raise
        except StoragePathDeniedError:
            outcome = "DENIED"
            raise
        except StorageBackendFailedError:
            outcome = "ERROR"
            raise
        size_bytes = len(result) if isinstance(result, (bytes, bytearray)) else result
        outcome = "SUCCESS"
        return result
    finally:
        _record_access(
            db, organization_id, instance_id, backend=decl.backend, scope_name=storage_scope.name,
            operation=storage_scope.operation, path=validated_path, size_bytes=size_bytes, outcome=outcome,
        )
