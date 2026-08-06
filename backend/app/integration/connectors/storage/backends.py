"""Phase 2.2.3 SRS ACT-INT-FR-140, FR-142 — the backend abstraction: one
interface over filesystem and S3-compatible object storage, mirroring
2.2.2's ``drivers.py`` ("one small interface over per-vendor behavior,
built on an already-first-class dependency of this codebase") exactly,
applied to storage I/O instead of SQL dialect connection strings.

**Azure Blob is backend-pending, not implemented.** ``azure-storage-blob``
is a real, heavy dependency this environment cannot exercise live this
phase — the build prompt's own §6 explicitly allows marking a backend
pending with the abstraction ready rather than half-implementing it,
exactly 2.2.2's SQL Server precedent. ``SUPPORTED_BACKENDS`` below lists
only what actually performs I/O today; ``declaration.py``'s
``CONFIG_SCHEMA`` still accepts ``"AZURE_BLOB"`` as a recognized value so
a config-validation error can name it specifically rather than reporting
a bare "invalid enum value" (see that module).

**Size checked before any full transfer (``ACT-INT-FR-142``).** A read
checks the object's size via metadata first — ``os.path.getsize``
(filesystem) or ``head_object`` (S3, a HEAD call, never a GET) — and
rejects before ever touching the object's bytes if it is already too
large. Both reads *also* bound the actual transfer itself
(``read(max_bytes + 1)`` for a local file; ``Body.read(max_bytes + 1)``
for S3) as a second, defense-in-depth check against a size that changes
between the metadata check and the transfer (the storage analogue of
2.2.2's row-limit "reject, never truncate" discipline) — a result larger
than declared is rejected outright, never silently truncated. A write
checks the in-memory payload's length before ever calling the backend.

**Local exceptions only.** Like 2.2.2's ``executor.py``, this module
raises its own exception types (never ``app.integration.errors``) —
translated to platform errors exclusively by ``invoker.py``, the bridge
sitting above this connector, not by this module or ``connector.py``
itself."""

from __future__ import annotations

import os
from typing import Any, Mapping

from app.integration.connectors.storage.declaration import DeclaredStorageScope, StorageDeclaration
from app.integration.connectors.storage.scope import ValidatedTarget

SUPPORTED_BACKENDS = frozenset({"FILESYSTEM", "S3"})
PENDING_BACKENDS = frozenset({"AZURE_BLOB"})


class ObjectNotFoundError(Exception):
    """The declared, validated target does not exist — translated to
    ``StorageObjectNotFoundError`` at the platform boundary."""


class ObjectTooLargeError(Exception):
    """The object (on read) or the supplied payload (on write) exceeds
    its scope's effective size limit — translated to
    ``StorageObjectTooLargeError``."""


class StorageBackendError(Exception):
    """Any other backend-level failure. The message is always a generic,
    safe summary (see ``_safe_message``) — never a raw driver/SDK
    exception's own text, which can embed a path, bucket, or (for some
    SDK error classes) request metadata not safe to surface verbatim."""


def _safe_message(exc: Exception) -> str:
    return f"{type(exc).__name__}: storage operation failed"


# --------------------------------------------------------------------------- #
# Filesystem
# --------------------------------------------------------------------------- #
def _fs_read(target: ValidatedTarget, *, max_bytes: int) -> bytes:
    try:
        size = os.path.getsize(target.resolved_path)
    except FileNotFoundError as exc:
        raise ObjectNotFoundError(target.relative_path) from exc
    except OSError as exc:
        raise StorageBackendError(_safe_message(exc)) from exc
    if size > max_bytes:
        raise ObjectTooLargeError(f"object exceeds the {max_bytes}-byte limit")
    try:
        with open(target.resolved_path, "rb") as handle:
            data = handle.read(max_bytes + 1)
    except FileNotFoundError as exc:
        raise ObjectNotFoundError(target.relative_path) from exc
    except OSError as exc:
        raise StorageBackendError(_safe_message(exc)) from exc
    if len(data) > max_bytes:
        raise ObjectTooLargeError(f"object exceeds the {max_bytes}-byte limit")
    return data


def _fs_write(target: ValidatedTarget, data: bytes, *, max_bytes: int) -> int:
    if len(data) > max_bytes:
        raise ObjectTooLargeError(f"payload exceeds the {max_bytes}-byte limit")
    try:
        parent = os.path.dirname(target.resolved_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(target.resolved_path, "wb") as handle:
            handle.write(data)
    except OSError as exc:
        raise StorageBackendError(_safe_message(exc)) from exc
    return len(data)


# --------------------------------------------------------------------------- #
# S3-compatible object storage
# --------------------------------------------------------------------------- #
def _s3_client(declaration: StorageDeclaration, credential: Mapping[str, Any]):
    import boto3

    kwargs: dict[str, Any] = {}
    if declaration.endpoint_url:
        kwargs["endpoint_url"] = declaration.endpoint_url
    if declaration.region:
        kwargs["region_name"] = declaration.region
    # The BASIC auth scheme's generic username/password fields carry an S3
    # access key id / secret access key -- a deliberate, documented reuse
    # (no S3-specific field forcing a new AuthScheme), the same
    # generalization 2.2.2's `resolve_credential_bundle` established for a
    # non-HTTP-shaped credential.
    if credential.get("username"):
        kwargs["aws_access_key_id"] = credential["username"]
        kwargs["aws_secret_access_key"] = credential.get("password", "")
    return boto3.client("s3", **kwargs)


def _s3_read(client, bucket: str, target: ValidatedTarget, *, max_bytes: int) -> bytes:
    from botocore.exceptions import ClientError, EndpointConnectionError

    key = target.resolved_path
    try:
        head = client.head_object(Bucket=bucket, Key=key)
    except ClientError as exc:
        code = str(exc.response.get("Error", {}).get("Code", ""))
        if code in ("404", "NoSuchKey", "NotFound"):
            raise ObjectNotFoundError(target.relative_path) from exc
        raise StorageBackendError(_safe_message(exc)) from exc
    except EndpointConnectionError as exc:
        raise StorageBackendError(_safe_message(exc)) from exc

    size = int(head.get("ContentLength", 0))
    if size > max_bytes:
        raise ObjectTooLargeError(f"object exceeds the {max_bytes}-byte limit")

    try:
        obj = client.get_object(Bucket=bucket, Key=key)
        data = obj["Body"].read(max_bytes + 1)
    except ClientError as exc:
        code = str(exc.response.get("Error", {}).get("Code", ""))
        if code in ("404", "NoSuchKey", "NotFound"):
            raise ObjectNotFoundError(target.relative_path) from exc
        raise StorageBackendError(_safe_message(exc)) from exc
    except EndpointConnectionError as exc:
        raise StorageBackendError(_safe_message(exc)) from exc
    if len(data) > max_bytes:
        raise ObjectTooLargeError(f"object exceeds the {max_bytes}-byte limit")
    return data


def _s3_write(client, bucket: str, target: ValidatedTarget, data: bytes, *, max_bytes: int) -> int:
    from botocore.exceptions import ClientError, EndpointConnectionError

    if len(data) > max_bytes:
        raise ObjectTooLargeError(f"payload exceeds the {max_bytes}-byte limit")
    try:
        client.put_object(Bucket=bucket, Key=target.resolved_path, Body=data)
    except (ClientError, EndpointConnectionError) as exc:
        raise StorageBackendError(_safe_message(exc)) from exc
    return len(data)


# --------------------------------------------------------------------------- #
# Dispatch
# --------------------------------------------------------------------------- #
def read_object(
    declaration: StorageDeclaration, scope: DeclaredStorageScope, target: ValidatedTarget,
    credential: Mapping[str, Any],
) -> bytes:
    max_bytes = declaration.effective_max_object_size_bytes(scope)
    if declaration.backend == "FILESYSTEM":
        return _fs_read(target, max_bytes=max_bytes)
    if declaration.backend == "S3":
        client = _s3_client(declaration, credential)
        return _s3_read(client, scope.root, target, max_bytes=max_bytes)
    raise StorageBackendError(f"backend '{declaration.backend}' has no live implementation")


def write_object(
    declaration: StorageDeclaration, scope: DeclaredStorageScope, target: ValidatedTarget, data: bytes,
    credential: Mapping[str, Any],
) -> int:
    max_bytes = declaration.effective_max_object_size_bytes(scope)
    if declaration.backend == "FILESYSTEM":
        return _fs_write(target, data, max_bytes=max_bytes)
    if declaration.backend == "S3":
        client = _s3_client(declaration, credential)
        return _s3_write(client, scope.root, target, data, max_bytes=max_bytes)
    raise StorageBackendError(f"backend '{declaration.backend}' has no live implementation")
