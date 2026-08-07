"""Phase 2.2.4 SRS ACT-INT-FR-160..164 — the queue connector's
declaration model.

A queue connector *instance*'s ``configuration`` declares: the target
backend (``AMQP``/``SQS`` — ``SERVICE_BUS`` is a recognized but
currently backend-pending value, rejected at semantic validation with a
clear message, see ``backends.py``), connection detail, a credential
scheme, default/max message-size and batch-size caps, a default/max
consume wait timeout, and one or more **declared bindings**. Each
binding names one physical queue, one operation (``PUBLISH``/
``CONSUME``), and becomes one distinct ``ToolContract`` — see
``tool_contracts_for`` below for exactly why the model never sees a
queue-name parameter at all.

**Zero deviations from the SDK-surface-only discipline this phase —
unlike 2.2.2's one (``DbWriteNotPermittedError``) and 2.2.3's two
(``StorageScopeInvalidError``/``StorageWriteNotPermittedError``).** This
build prompt's own §7 error-code list — ``QUEUE_NOT_DECLARED``,
``QUEUE_MESSAGE_TOO_LARGE``, ``QUEUE_OPERATION_NOT_PERMITTED``,
``QUEUE_CONSUME_TIMEOUT`` — is entirely *invocation*-time vocabulary;
none of it names a *declaration*-time outcome the SDK's own generic
``ConnectorConfigInvalidError`` cannot already express. So
``parse_declaration`` below raises only ``ConnectorConfigInvalidError``
for every structural/semantic problem, exactly as 2.2.1's REST
connector's ``declaration.py`` did — this phase's shape matches that
precedent, not 2.2.2's/2.2.3's write-permission-at-configuration-time
pattern, because there is no instance-level posture flag here for a
per-binding operation to conflict with (each binding is already fully
self-describing: it either permits ``PUBLISH`` or ``CONSUME``, nothing
declares a *default* posture the way storage's ``read_only`` does)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from app.integration.sdk import ConnectorConfigInvalidError, ToolContract

# SERVICE_BUS is a recognized, schema-accepted value -- rejected at semantic
# validation with a specific "backend-pending" message, not a generic
# "invalid enum value" -- mirroring 2.2.2's SQL Server / 2.2.3's Azure Blob
# precedent exactly. See backends.py for the full rationale.
SUPPORTED_BACKENDS = ("AMQP", "SQS")
_PENDING_BACKENDS = ("SERVICE_BUS",)
_ALL_DECLARABLE_BACKENDS = SUPPORTED_BACKENDS + _PENDING_BACKENDS

_SUPPORTED_AUTH_SCHEMES = ("NONE", "BASIC")
_OPERATIONS = ("PUBLISH", "CONSUME")

_BINDING_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "name": {"type": "string", "minLength": 1},
        "description": {"type": "string", "minLength": 1},
        "operation": {"type": "string", "enum": list(_OPERATIONS)},
        # AMQP: a queue name. SQS: a queue URL (or name, backend-specific).
        "queue_name": {"type": "string", "minLength": 1},
        "max_message_size_bytes": {"type": ["integer", "null"], "minimum": 1},
        # CONSUME-only -- validated below, rejected if present on a PUBLISH binding.
        "max_batch_size": {"type": ["integer", "null"], "minimum": 1},
        "wait_timeout_seconds": {"type": ["number", "null"], "exclusiveMinimum": 0},
    },
    "required": ["name", "description", "operation", "queue_name"],
    "additionalProperties": False,
}

CONFIG_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "backend": {"type": "string", "enum": list(_ALL_DECLARABLE_BACKENDS)},
        "auth_scheme": {"type": "string", "enum": list(_SUPPORTED_AUTH_SCHEMES)},
        # AMQP connection detail.
        "host": {"type": ["string", "null"]},
        "port": {"type": ["integer", "null"], "minimum": 1, "maximum": 65535},
        "virtual_host": {"type": ["string", "null"]},
        # SQS connection detail -- endpoint_url also lets one backend serve a
        # local/compatible target (e.g. localstack) by declaration.
        "region": {"type": ["string", "null"]},
        "endpoint_url": {"type": ["string", "null"]},
        # ACT-INT-FR-163 -- default/max message-size caps, both configurable.
        "default_max_message_size_bytes": {"type": "integer", "minimum": 1},
        "max_max_message_size_bytes": {"type": "integer", "minimum": 1},
        # ACT-INT-FR-162 -- default/max consume-batch caps, both configurable.
        "default_max_batch_size": {"type": "integer", "minimum": 1},
        "max_max_batch_size": {"type": "integer", "minimum": 1},
        # ACT-INT-FR-162 -- default/max bounded-wait caps, both configurable.
        "default_wait_timeout_seconds": {"type": "number", "exclusiveMinimum": 0},
        "max_wait_timeout_seconds": {"type": "number", "exclusiveMinimum": 0},
        "bindings": {"type": "array", "items": _BINDING_SCHEMA, "minItems": 1},
    },
    "required": ["backend", "bindings"],
    "additionalProperties": False,
}


@dataclass(frozen=True, slots=True)
class DeclaredQueueBinding:
    """One declared binding — the ``ACT-INT-FR-161`` unit that becomes
    one distinct ``ToolContract``. Exactly one operation per binding; a
    queue reachable both ways is declared twice, under two distinct
    names (mirrors 2.2.3's one-operation-per-scope shape)."""

    name: str
    description: str
    operation: str  # "PUBLISH" | "CONSUME"
    queue_name: str
    max_message_size_bytes: int | None = None
    max_batch_size: int | None = None
    wait_timeout_seconds: float | None = None


@dataclass(frozen=True, slots=True)
class QueueDeclaration:
    """A fully parsed, validated instance declaration."""

    backend: str
    bindings: tuple[DeclaredQueueBinding, ...]
    auth_scheme: str = "NONE"
    host: str | None = None
    port: int | None = None
    virtual_host: str | None = None
    region: str | None = None
    endpoint_url: str | None = None
    default_max_message_size_bytes: int = 262_144
    max_max_message_size_bytes: int = 1_048_576
    default_max_batch_size: int = 10
    max_max_batch_size: int = 100
    default_wait_timeout_seconds: float = 5.0
    max_wait_timeout_seconds: float = 20.0

    def binding_by_name(self, name: str) -> DeclaredQueueBinding | None:
        for binding in self.bindings:
            if binding.name == name:
                return binding
        return None

    def effective_max_message_size_bytes(self, binding: DeclaredQueueBinding) -> int:
        return min(binding.max_message_size_bytes or self.default_max_message_size_bytes, self.max_max_message_size_bytes)

    def effective_max_batch_size(self, binding: DeclaredQueueBinding) -> int:
        return min(binding.max_batch_size or self.default_max_batch_size, self.max_max_batch_size)

    def effective_wait_timeout_seconds(self, binding: DeclaredQueueBinding) -> float:
        return min(binding.wait_timeout_seconds or self.default_wait_timeout_seconds, self.max_wait_timeout_seconds)


def _parse_binding(raw: Mapping[str, Any]) -> DeclaredQueueBinding:
    name = raw["name"]
    operation = raw["operation"]
    if operation == "PUBLISH" and (raw.get("max_batch_size") is not None or raw.get("wait_timeout_seconds") is not None):
        raise ConnectorConfigInvalidError(
            f"binding '{name}' declares 'max_batch_size'/'wait_timeout_seconds', not valid for a PUBLISH binding"
        )
    return DeclaredQueueBinding(
        name=name, description=raw["description"], operation=operation, queue_name=raw["queue_name"],
        max_message_size_bytes=raw.get("max_message_size_bytes"),
        max_batch_size=raw.get("max_batch_size"), wait_timeout_seconds=raw.get("wait_timeout_seconds"),
    )


def parse_declaration(configuration: Mapping[str, Any]) -> QueueDeclaration:
    """Semantic validation, run after ``CONFIG_SCHEMA``'s structural pass
    (``QueueConnector.validate_configuration`` does both, in that
    order). Raises the SDK's own ``ConnectorConfigInvalidError`` for
    every problem — see this module's own docstring for why no
    dedicated exception type was needed this phase."""
    backend = configuration["backend"]
    if backend in _PENDING_BACKENDS:
        raise ConnectorConfigInvalidError(
            f"backend '{backend}' support is backend-pending (no live implementation shipped this phase) "
            f"— supported backends today: {', '.join(SUPPORTED_BACKENDS)}"
        )
    if backend not in SUPPORTED_BACKENDS:
        raise ConnectorConfigInvalidError(f"backend '{backend}' is not a supported queue backend")

    auth_scheme = configuration.get("auth_scheme", "NONE")
    if auth_scheme not in _SUPPORTED_AUTH_SCHEMES:
        raise ConnectorConfigInvalidError(f"auth_scheme '{auth_scheme}' is not supported by the queue connector")

    default_max_message_size_bytes = int(configuration.get("default_max_message_size_bytes", 262_144))
    max_max_message_size_bytes = int(configuration.get("max_max_message_size_bytes", 1_048_576))
    if default_max_message_size_bytes > max_max_message_size_bytes:
        raise ConnectorConfigInvalidError("default_max_message_size_bytes cannot exceed max_max_message_size_bytes")

    default_max_batch_size = int(configuration.get("default_max_batch_size", 10))
    max_max_batch_size = int(configuration.get("max_max_batch_size", 100))
    if default_max_batch_size > max_max_batch_size:
        raise ConnectorConfigInvalidError("default_max_batch_size cannot exceed max_max_batch_size")

    default_wait_timeout_seconds = float(configuration.get("default_wait_timeout_seconds", 5.0))
    max_wait_timeout_seconds = float(configuration.get("max_wait_timeout_seconds", 20.0))
    if default_wait_timeout_seconds > max_wait_timeout_seconds:
        raise ConnectorConfigInvalidError("default_wait_timeout_seconds cannot exceed max_wait_timeout_seconds")

    bindings_raw = configuration.get("bindings") or []
    if not bindings_raw:
        raise ConnectorConfigInvalidError("at least one binding must be declared")

    seen_names: set[str] = set()
    bindings: list[DeclaredQueueBinding] = []
    for raw in bindings_raw:
        binding = _parse_binding(raw)
        if binding.name in seen_names:
            raise ConnectorConfigInvalidError(f"duplicate binding name '{binding.name}'")
        seen_names.add(binding.name)
        if binding.max_message_size_bytes is not None and binding.max_message_size_bytes > max_max_message_size_bytes:
            raise ConnectorConfigInvalidError(f"binding '{binding.name}' max_message_size_bytes exceeds max_max_message_size_bytes")
        if binding.max_batch_size is not None and binding.max_batch_size > max_max_batch_size:
            raise ConnectorConfigInvalidError(f"binding '{binding.name}' max_batch_size exceeds max_max_batch_size")
        if binding.wait_timeout_seconds is not None and binding.wait_timeout_seconds > max_wait_timeout_seconds:
            raise ConnectorConfigInvalidError(f"binding '{binding.name}' wait_timeout_seconds exceeds max_wait_timeout_seconds")
        bindings.append(binding)

    return QueueDeclaration(
        backend=backend, bindings=tuple(bindings), auth_scheme=auth_scheme,
        host=configuration.get("host"), port=configuration.get("port"), virtual_host=configuration.get("virtual_host"),
        region=configuration.get("region"), endpoint_url=configuration.get("endpoint_url"),
        default_max_message_size_bytes=default_max_message_size_bytes,
        max_max_message_size_bytes=max_max_message_size_bytes,
        default_max_batch_size=default_max_batch_size, max_max_batch_size=max_max_batch_size,
        default_wait_timeout_seconds=default_wait_timeout_seconds, max_wait_timeout_seconds=max_wait_timeout_seconds,
    )


def tool_contracts_for(configuration: Mapping[str, Any]) -> tuple[ToolContract, ...]:
    """``ACT-INT-FR-161`` — each declared binding becomes one distinct
    ``ToolContract``. **The model never sees a queue-name parameter**:
    a ``PUBLISH`` binding's only parameter is ``message`` (the payload);
    a ``CONSUME`` binding's only parameter is an optional
    ``max_messages`` cap (itself still bounded by the binding's own
    effective batch cap — a model asking for more never yields more).
    The target queue is fixed by which tool contract is called, never a
    value supplied through one (``ACT-INT-FR-164``)."""
    declaration = parse_declaration(configuration)
    contracts = []
    for binding in declaration.bindings:
        if binding.operation == "PUBLISH":
            parameters = {
                "type": "object",
                "properties": {"message": {"type": "string", "minLength": 1}},
                "required": ["message"], "additionalProperties": False,
            }
        else:
            parameters = {
                "type": "object",
                "properties": {"max_messages": {"type": ["integer", "null"], "minimum": 1}},
                "required": [], "additionalProperties": False,
            }
        contracts.append(ToolContract(name=binding.name, description=binding.description, parameters=parameters))
    return tuple(contracts)
