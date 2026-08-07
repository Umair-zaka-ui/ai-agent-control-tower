"""Phase 2.2.4 SRS ACT-INT-FR-160..164 — the queue connector's
tool-invocation bridge.

Mirrors ``app/integration/connectors/storage/invoker.py`` in shape
(platform bridge code sitting *above* ``QueueConnector``, not
SDK-surface-restricted; every attempt audited via a ``finally`` block)
but exposes **two** distinct public entry points, ``publish_message``
and ``consume_messages``, rather than one polymorphic ``invoke_tool`` —
because a queue binding's permitted operation is fixed at declaration
time and a caller must state which operation it is attempting, so the
bridge can verify (``app.integration.connectors.queue.scope.
check_operation_permitted``) that the resolved binding actually permits
it *before* touching a broker. This is the queue analogue of
``ACT-INT-FR-164``: the model's own tool-contract shape already makes
attempting the wrong operation against a binding unreachable in
ordinary use (see ``declaration.py::tool_contracts_for``), and this
bridge double-checks it anyway, defense in depth.

**Every publish and consume attempt is recorded in the platform audit
trail** — reusing 2.2.3's ``INTEGRATION_CONNECTOR_OBJECT_ACCESSED``
event rather than adding a new one (a message is, for audit purposes,
exactly the kind of "object accessed" that event already models), never
a credential, carrying the binding name, operation, message count, size,
and outcome."""

from __future__ import annotations

import uuid
from typing import Any, Mapping

from sqlalchemy.orm import Session

from app.authorization.enums import AuthorizationAuditEvent
from app.authorization.services import AuthorizationAuditService
from app.integration.auth.service import ConnectorCredentialService
from app.integration.connectors.queue import backends, declaration, scope as scope_mod
from app.integration.connectors.queue.declaration import DeclaredQueueBinding, QueueDeclaration
from app.integration.errors import (
    QueueBackendFailedError,
    QueueBindingNotDeclaredError,
    QueueMessageTooLargeError,
    QueueOperationNotPermittedError,
)
from app.integration.registry import ConnectorRegistry
from app.models.integration import ConnectorInstance

_NO_AUTH_SCHEME = "NONE"


def _binding_by_name(decl: QueueDeclaration, binding_name: str) -> DeclaredQueueBinding:
    binding = decl.binding_by_name(binding_name)
    if binding is None:
        raise QueueBindingNotDeclaredError(binding_name)
    return binding


def _check_permitted(binding: DeclaredQueueBinding, requested_operation: str) -> None:
    try:
        scope_mod.check_operation_permitted(binding.name, binding.operation, requested_operation)
    except scope_mod.QueueScopeViolationError as exc:
        raise QueueOperationNotPermittedError(str(exc)) from exc


def _record_access(
    db: Session, organization_id: uuid.UUID, instance_id: uuid.UUID, *,
    backend: str, binding_name: str, operation: str, message_count: int | None, size_bytes: int | None, outcome: str,
) -> None:
    AuthorizationAuditService(db).record_change(
        AuthorizationAuditEvent.INTEGRATION_CONNECTOR_OBJECT_ACCESSED,
        organization_id=organization_id, actor_id=None,
        meta={
            "connector_instance_id": str(instance_id), "backend": backend, "scope_name": binding_name,
            "operation": operation, "message_count": message_count, "size_bytes": size_bytes, "outcome": outcome,
        },
    )


def _resolve(db: Session, organization_id: uuid.UUID, instance_id: uuid.UUID, binding_name: str):
    registry = ConnectorRegistry(db)
    resolved = registry.resolve_instance_for_invocation(organization_id, instance_id)
    decl = declaration.parse_declaration(resolved.configuration)
    binding = _binding_by_name(decl, binding_name)

    credential: dict[str, Any] = {}
    if decl.auth_scheme != _NO_AUTH_SCHEME:
        instance_row: ConnectorInstance = registry.instances.get_or_404(organization_id, instance_id)
        credential = ConnectorCredentialService(db).resolve_credential_bundle(instance_row, decl.auth_scheme)
    return decl, binding, credential


def publish_message(
    db: Session, organization_id: uuid.UUID, instance_id: uuid.UUID, binding_name: str, arguments: Mapping[str, Any],
) -> None:
    """Publishes to the queue fixed by ``binding_name``'s own
    declaration — the model supplies only ``arguments["message"]``, the
    payload, never a queue name (``ACT-INT-FR-164``). Fail-fast resolves
    the instance (``ACT-INT-FR-044``, inherited unchanged from the
    registry), resolves its declared credential, verifies the resolved
    binding actually permits ``PUBLISH``, and records the attempt in the
    audit trail regardless of outcome."""
    decl, binding, credential = _resolve(db, organization_id, instance_id, binding_name)
    message = arguments.get("message")
    payload = message.encode("utf-8") if isinstance(message, str) else b""

    outcome = "ERROR"
    size_bytes: int | None = None
    try:
        _check_permitted(binding, scope_mod.PUBLISH)
        size_bytes = len(payload)
        try:
            backends.publish(decl, binding, payload, credential)
        except backends.MessageTooLargeError as exc:
            outcome = "TOO_LARGE"
            raise QueueMessageTooLargeError(str(exc)) from exc
        except backends.QueueBackendError as exc:
            outcome = "ERROR"
            raise QueueBackendFailedError(str(exc)) from exc
        outcome = "SUCCESS"
    except QueueOperationNotPermittedError:
        outcome = "DENIED"
        raise
    finally:
        _record_access(
            db, organization_id, instance_id, backend=decl.backend, binding_name=binding.name,
            operation="PUBLISH", message_count=1, size_bytes=size_bytes, outcome=outcome,
        )


def consume_messages(
    db: Session, organization_id: uuid.UUID, instance_id: uuid.UUID, binding_name: str, arguments: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Consumes up to ``arguments.get("max_messages")`` messages (capped
    regardless by the binding's own effective batch size,
    ``ACT-INT-FR-162``) from the queue fixed by ``binding_name``'s own
    declaration — never an unbounded stream, never a value the model
    could redirect. Fail-fast resolves the instance, resolves its
    credential, verifies the resolved binding actually permits
    ``CONSUME``, and records the attempt regardless of outcome. Returns
    a plain list of ``{"message": <str>, "size_bytes": <int>,
    "truncated": <bool>}`` dicts — never the raw ``ConsumedMessage``
    dataclass, so no backend-internal shape leaks past this bridge."""
    decl, binding, credential = _resolve(db, organization_id, instance_id, binding_name)
    max_messages = arguments.get("max_messages")

    outcome = "ERROR"
    result: list[dict[str, Any]] = []
    total_bytes = 0
    try:
        _check_permitted(binding, scope_mod.CONSUME)
        try:
            consumed = backends.consume(decl, binding, credential, max_messages=max_messages)
        except backends.QueueBackendError as exc:
            outcome = "ERROR"
            raise QueueBackendFailedError(str(exc)) from exc
        for item in consumed:
            total_bytes += item.size_bytes
            result.append({
                "message": item.body.decode("utf-8", errors="replace"),
                "size_bytes": item.size_bytes, "truncated": item.truncated,
            })
        outcome = "SUCCESS"
        return result
    except QueueOperationNotPermittedError:
        outcome = "DENIED"
        raise
    finally:
        _record_access(
            db, organization_id, instance_id, backend=decl.backend, binding_name=binding.name,
            operation="CONSUME", message_count=len(result), size_bytes=total_bytes or None, outcome=outcome,
        )
