"""Phase 2.2.3 SRS ACT-INT-FR-140..145 — the storage connector's
declaration model.

A storage connector *instance*'s ``configuration`` declares: the target
backend (``FILESYSTEM``/``S3`` — ``AZURE_BLOB`` is a recognized but
currently backend-pending value, rejected at semantic validation with a
clear message, see ``backends.py``), a credential scheme, a read/write
posture, default/max object-size caps, and one or more **declared
scopes**. Each declared scope names one bucket+prefix (object storage) or
base directory (filesystem), one operation (``READ``/``WRITE``), and
becomes one distinct ``ToolContract`` whose only parameter is a bounded
``path`` string — the remainder of the key/path the model supplies, and
the exact value ``app.integration.connectors.storage.scope.
resolve_and_contain`` validates before any operation runs (never this
module's concern — this module only *declares* the boundary, it never
enforces it).

**Two narrow, justified deviations from the SDK-surface-only discipline**
2.2.1's/2.2.2's own ``declaration.py`` modules kept to (their own module
docstrings explain why *they* needed none beyond the generic SDK
``ConnectorConfigInvalidError``): this build prompt's own §7 explicitly
requires a distinguishable ``STORAGE_SCOPE_INVALID`` code for a
badly-shaped scope declaration — unlike 2.2.2, where no acceptance
criterion demanded a *declaration-time* code beyond the SDK's own
generic one. So ``parse_declaration`` below raises
``StorageScopeInvalidError`` (imported from ``app.integration.errors``,
not the SDK) for its own semantic checks, while ``CONFIG_SCHEMA``'s
*structural* (JSON Schema) validation is still run by the caller
(``connector.py``) through the SDK's own ``validate_configuration_schema``
exactly as every connector's is — a malformed shape still gets the
generic code; a well-formed-but-semantically-wrong scope gets the
specific one. ``mutating`` (here: write) scope detection —
``write_scope_names`` — mirrors 2.2.2's ``mutating_query_names`` exactly:
pure data, never raises; ``connector.py`` is where "one or more write
scopes on a read-only instance" becomes ``StorageWriteNotPermittedError``,
this module's second, separately-justified deviation-adjacent import
(also from ``app.integration.errors``), matching 2.2.2's own split
precisely."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from app.integration.connectors.storage.scope import FILESYSTEM, OBJECT_STORE, ScopeBoundary
from app.integration.errors import StorageScopeInvalidError
from app.integration.sdk import ToolContract

# AZURE_BLOB is a recognized, schema-accepted value -- rejected at semantic
# validation with a specific "backend-pending" message, not a generic
# "invalid enum value" -- mirroring 2.2.2's SQL Server precedent exactly.
# See backends.py for the full rationale.
SUPPORTED_BACKENDS = ("FILESYSTEM", "S3")
_PENDING_BACKENDS = ("AZURE_BLOB",)
_ALL_DECLARABLE_BACKENDS = SUPPORTED_BACKENDS + _PENDING_BACKENDS

_SUPPORTED_AUTH_SCHEMES = ("NONE", "BASIC")
_OPERATIONS = ("READ", "WRITE")

_SCOPE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "name": {"type": "string", "minLength": 1},
        "description": {"type": "string", "minLength": 1},
        "operation": {"type": "string", "enum": list(_OPERATIONS)},
        "bucket": {"type": "string", "minLength": 1},
        "base_directory": {"type": "string", "minLength": 1},
        "prefix": {"type": "string"},
        "max_object_size_bytes": {"type": ["integer", "null"], "minimum": 1},
    },
    "required": ["name", "description", "operation"],
    "additionalProperties": False,
}

CONFIG_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "backend": {"type": "string", "enum": list(_ALL_DECLARABLE_BACKENDS)},
        "auth_scheme": {"type": "string", "enum": list(_SUPPORTED_AUTH_SCHEMES)},
        # S3-compatible connection detail -- an explicit endpoint_url lets one
        # backend serve real AWS S3 *or* an S3-compatible target (e.g. MinIO)
        # by declaration, never a code change.
        "endpoint_url": {"type": ["string", "null"]},
        "region": {"type": ["string", "null"]},
        # ACT-INT-FR-144 -- read-only unless explicitly set false.
        "read_only": {"type": "boolean"},
        # ACT-INT-FR-142 -- default/max object-size caps, both configurable.
        "default_max_object_size_bytes": {"type": "integer", "minimum": 1},
        "max_max_object_size_bytes": {"type": "integer", "minimum": 1},
        "scopes": {"type": "array", "items": _SCOPE_SCHEMA, "minItems": 1},
    },
    "required": ["backend", "scopes"],
    "additionalProperties": False,
}


@dataclass(frozen=True, slots=True)
class DeclaredStorageScope:
    """One declared scope — the ``ACT-INT-FR-140``/``FR-141`` unit that
    becomes one distinct ``ToolContract``. ``root``/``prefix`` are
    already resolved to their enforcement-ready form (see
    ``to_boundary``); nothing about *how* a supplied path is validated
    against them lives here — that is entirely ``scope.py``'s job."""

    name: str
    description: str
    operation: str  # "READ" | "WRITE"
    backend: str  # "FILESYSTEM" | "S3" | "AZURE_BLOB" (rejected before this is constructed)
    root: str  # base_directory (FILESYSTEM) or bucket (S3/AZURE_BLOB)
    prefix: str = ""
    max_object_size_bytes: int | None = None

    def to_boundary(self) -> ScopeBoundary:
        kind = FILESYSTEM if self.backend == "FILESYSTEM" else OBJECT_STORE
        return ScopeBoundary(backend_kind=kind, root=self.root, prefix=self.prefix)


@dataclass(frozen=True, slots=True)
class StorageDeclaration:
    """A fully parsed, validated instance declaration."""

    backend: str
    scopes: tuple[DeclaredStorageScope, ...]
    auth_scheme: str = "NONE"
    read_only: bool = True
    endpoint_url: str | None = None
    region: str | None = None
    default_max_object_size_bytes: int = 10_000_000
    max_max_object_size_bytes: int = 100_000_000

    def scope_by_name(self, name: str) -> DeclaredStorageScope | None:
        for scope in self.scopes:
            if scope.name == name:
                return scope
        return None

    def effective_max_object_size_bytes(self, scope: DeclaredStorageScope) -> int:
        return min(scope.max_object_size_bytes or self.default_max_object_size_bytes, self.max_max_object_size_bytes)


def write_scope_names(declaration: StorageDeclaration) -> list[str]:
    """The declared scope names with ``operation == "WRITE"`` — empty if
    none. Pure data, never raises; ``connector.py`` decides what a
    non-empty result means for a read-only instance (``ACT-INT-FR-144``)."""
    return [scope.name for scope in declaration.scopes if scope.operation == "WRITE"]


def _parse_scope(raw: Mapping[str, Any], *, backend: str) -> DeclaredStorageScope:
    name = raw["name"]
    if backend == "FILESYSTEM":
        base_directory = raw.get("base_directory")
        if not base_directory:
            raise StorageScopeInvalidError(f"scope '{name}' requires 'base_directory' for the FILESYSTEM backend")
        if raw.get("bucket") or raw.get("prefix"):
            raise StorageScopeInvalidError(f"scope '{name}' declares 'bucket'/'prefix', not valid for FILESYSTEM")
        root, prefix = base_directory, ""
    else:
        bucket = raw.get("bucket")
        if not bucket:
            raise StorageScopeInvalidError(f"scope '{name}' requires 'bucket' for the '{backend}' backend")
        if raw.get("base_directory"):
            raise StorageScopeInvalidError(f"scope '{name}' declares 'base_directory', not valid for '{backend}'")
        root, prefix = bucket, (raw.get("prefix") or "")

    max_object_size_bytes = raw.get("max_object_size_bytes")
    return DeclaredStorageScope(
        name=name, description=raw["description"], operation=raw["operation"], backend=backend,
        root=root, prefix=prefix, max_object_size_bytes=max_object_size_bytes,
    )


def parse_declaration(configuration: Mapping[str, Any]) -> StorageDeclaration:
    """Semantic validation, run after ``CONFIG_SCHEMA``'s structural pass
    (``StorageConnector.validate_configuration`` does both, in that
    order). Raises ``StorageScopeInvalidError`` naming the specific
    problem — see this module's own docstring for why that is a
    dedicated type rather than the SDK's generic
    ``ConnectorConfigInvalidError``. Deliberately does **not** reject a
    read-only instance's write scope here — that is
    ``ACT-INT-FR-144``'s own, differently-coded rejection
    (``StorageWriteNotPermittedError``), raised by ``connector.py`` using
    ``write_scope_names`` above."""
    backend = configuration["backend"]
    if backend in _PENDING_BACKENDS:
        raise StorageScopeInvalidError(
            f"backend '{backend}' support is backend-pending (no live implementation shipped this phase) "
            f"— supported backends today: {', '.join(SUPPORTED_BACKENDS)}"
        )
    if backend not in SUPPORTED_BACKENDS:
        raise StorageScopeInvalidError(f"backend '{backend}' is not a supported storage backend")

    auth_scheme = configuration.get("auth_scheme", "NONE")
    if auth_scheme not in _SUPPORTED_AUTH_SCHEMES:
        raise StorageScopeInvalidError(f"auth_scheme '{auth_scheme}' is not supported by the storage connector")

    default_max_object_size_bytes = int(configuration.get("default_max_object_size_bytes", 10_000_000))
    max_max_object_size_bytes = int(configuration.get("max_max_object_size_bytes", 100_000_000))
    if default_max_object_size_bytes > max_max_object_size_bytes:
        raise StorageScopeInvalidError("default_max_object_size_bytes cannot exceed max_max_object_size_bytes")

    scopes_raw = configuration.get("scopes") or []
    if not scopes_raw:
        raise StorageScopeInvalidError("at least one scope must be declared")

    seen_names: set[str] = set()
    scopes: list[DeclaredStorageScope] = []
    for raw in scopes_raw:
        scope = _parse_scope(raw, backend=backend)
        if scope.name in seen_names:
            raise StorageScopeInvalidError(f"duplicate scope name '{scope.name}'")
        seen_names.add(scope.name)
        if scope.max_object_size_bytes is not None and scope.max_object_size_bytes > max_max_object_size_bytes:
            raise StorageScopeInvalidError(f"scope '{scope.name}' max_object_size_bytes exceeds max_max_object_size_bytes")
        scopes.append(scope)

    return StorageDeclaration(
        backend=backend, scopes=tuple(scopes), auth_scheme=auth_scheme,
        read_only=bool(configuration.get("read_only", True)),
        endpoint_url=configuration.get("endpoint_url"), region=configuration.get("region"),
        default_max_object_size_bytes=default_max_object_size_bytes,
        max_max_object_size_bytes=max_max_object_size_bytes,
    )


def tool_contracts_for(configuration: Mapping[str, Any]) -> tuple[ToolContract, ...]:
    """``ACT-INT-FR-141`` — each declared scope becomes one distinct
    ``ToolContract`` whose only parameter is ``path``: the bounded
    remainder of the key/path a model supplies, validated by
    ``scope.resolve_and_contain`` before any operation runs. Mirrors
    2.2.1/2.2.2's own ``tool_contracts_for`` exactly — instance-derived,
    not something ``StorageConnector.describe()`` (a type-level,
    zero-argument call) can produce."""
    declaration = parse_declaration(configuration)
    return tuple(
        ToolContract(
            name=scope.name, description=scope.description,
            parameters={
                "type": "object",
                "properties": {"path": {"type": "string", "minLength": 1}},
                "required": ["path"],
                "additionalProperties": False,
            },
        )
        for scope in declaration.scopes
    )
