"""Phase 2.2.3 tests — the storage connector's tool-invocation bridge
(``app/integration/connectors/storage/invoker.py``), end to end.

This is the file that proves AC-24 ("a storage tool is actually invocable
end to end") and the live-database half of AC-19 (every access recorded
in the audit trail), AC-20 (credential protection), AC-22, AC-23 —
everything here connects to this platform's own real dev database via
``db_session``, and performs real filesystem I/O against ``tmp_path``
(never a mock filesystem)."""

from __future__ import annotations

import json
import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.integration.auth.service import ConnectorCredentialService
from app.integration.connectors.storage.invoker import invoke_tool
from app.integration.errors import (
    StorageObjectNotFoundError,
    StoragePathDeniedError,
)
from app.integration.service import ConnectorService, ConnectorTypeService
from app.models.integration import ConnectorCredential
from app.models.rbac import AuthorizationAudit
from app.models.user import User


def _fs_config(base_directory: str, *, read_only: bool = True, operation: str = "READ", **overrides):
    config = {
        "backend": "FILESYSTEM",
        "read_only": read_only,
        "scopes": [
            {"name": "reports", "description": "Read/write scoped report files.", "operation": operation,
             "base_directory": base_directory},
        ],
    }
    config.update(overrides)
    return config


def _admin_user(db_session: Session, admin: dict) -> User:
    return db_session.get(User, uuid.UUID(admin["user_id"]))


def _make_instance(db_session: Session, admin: dict, config: dict):
    ConnectorTypeService(db_session).ensure_seeded()
    actor = _admin_user(db_session, admin)
    org_id = uuid.UUID(admin["organization_id"])
    instance = ConnectorService(db_session).create_instance(
        actor, org_id, connector_type="STORAGE", name=f"Storage {uuid.uuid4().hex[:6]}", configuration=config,
    )
    return instance, actor, org_id


# --------------------------------------------------------------------------- #
# AC-24 — a storage tool is actually invocable end to end
# --------------------------------------------------------------------------- #
def test_ac24_a_declared_scope_reads_through_the_bridge_end_to_end(tmp_path, admin, db_session: Session):
    (tmp_path / "q1.txt").write_text("quarter one content", encoding="utf-8")
    instance, actor, org_id = _make_instance(db_session, admin, _fs_config(str(tmp_path)))
    data = invoke_tool(db_session, org_id, instance.id, "reports", {"path": "q1.txt"})
    assert data == b"quarter one content"


def test_ac24_a_declared_write_scope_writes_through_the_bridge_end_to_end(tmp_path, admin, db_session: Session):
    instance, actor, org_id = _make_instance(
        db_session, admin, _fs_config(str(tmp_path), read_only=False, operation="WRITE"),
    )
    written = invoke_tool(db_session, org_id, instance.id, "reports", {"path": "out.txt", "content": "hello"})
    assert written == 5
    assert (tmp_path / "out.txt").read_text(encoding="utf-8") == "hello"


def test_ac24_an_undeclared_scope_name_is_rejected_before_reaching_any_backend(tmp_path, admin, db_session: Session):
    from app.integration.connectors.storage.invoker import StorageScopeNotDeclaredError

    instance, actor, org_id = _make_instance(db_session, admin, _fs_config(str(tmp_path)))
    with pytest.raises(StorageScopeNotDeclaredError):
        invoke_tool(db_session, org_id, instance.id, "not_a_real_scope", {"path": "x.txt"})


def test_ac24_a_traversal_attempt_is_denied_before_reaching_any_backend(tmp_path, admin, db_session: Session):
    secret_dir = tmp_path.parent / f"secret_{uuid.uuid4().hex[:6]}"
    secret_dir.mkdir()
    (secret_dir / "secret.txt").write_text("do not read", encoding="utf-8")
    scoped_dir = tmp_path / "scoped"
    scoped_dir.mkdir()

    instance, actor, org_id = _make_instance(db_session, admin, _fs_config(str(scoped_dir)))
    with pytest.raises(StoragePathDeniedError) as excinfo:
        invoke_tool(db_session, org_id, instance.id, "reports", {"path": f"../{secret_dir.name}/secret.txt"})
    assert excinfo.value.code == "STORAGE_PATH_DENIED"


def test_ac24_a_missing_object_is_reported_as_not_found(tmp_path, admin, db_session: Session):
    instance, actor, org_id = _make_instance(db_session, admin, _fs_config(str(tmp_path)))
    with pytest.raises(StorageObjectNotFoundError):
        invoke_tool(db_session, org_id, instance.id, "reports", {"path": "does-not-exist.txt"})


# --------------------------------------------------------------------------- #
# AC-19 — every object accessed is recorded in the audit trail, live
# --------------------------------------------------------------------------- #
def test_ac19_a_successful_read_is_recorded_in_the_audit_trail(tmp_path, admin, db_session: Session):
    (tmp_path / "q1.txt").write_text("quarter one content", encoding="utf-8")
    instance, actor, org_id = _make_instance(db_session, admin, _fs_config(str(tmp_path)))
    invoke_tool(db_session, org_id, instance.id, "reports", {"path": "q1.txt"})

    audit = db_session.execute(
        select(AuthorizationAudit).where(
            AuthorizationAudit.event_type == "INTEGRATION_CONNECTOR_OBJECT_ACCESSED",
            AuthorizationAudit.organization_id == org_id,
        )
    ).scalars().all()
    assert len(audit) == 1
    meta = audit[0].meta
    assert meta["backend"] == "FILESYSTEM"
    assert meta["scope_name"] == "reports"
    assert meta["operation"] == "READ"
    assert meta["path"] == "q1.txt"
    assert meta["size_bytes"] == len(b"quarter one content")
    assert meta["outcome"] == "SUCCESS"


def test_ac19_a_denied_traversal_attempt_is_also_recorded_denied(tmp_path, admin, db_session: Session):
    instance, actor, org_id = _make_instance(db_session, admin, _fs_config(str(tmp_path)))
    with pytest.raises(StoragePathDeniedError):
        invoke_tool(db_session, org_id, instance.id, "reports", {"path": "../../etc/passwd"})

    audit = db_session.execute(
        select(AuthorizationAudit).where(
            AuthorizationAudit.event_type == "INTEGRATION_CONNECTOR_OBJECT_ACCESSED",
            AuthorizationAudit.organization_id == org_id,
        )
    ).scalars().all()
    assert len(audit) == 1
    assert audit[0].meta["outcome"] == "DENIED"
    # a denial never carries a validated path -- there was none to record.
    assert audit[0].meta["path"] is None


def test_ac19_a_not_found_access_is_recorded_with_the_validated_path(tmp_path, admin, db_session: Session):
    instance, actor, org_id = _make_instance(db_session, admin, _fs_config(str(tmp_path)))
    with pytest.raises(StorageObjectNotFoundError):
        invoke_tool(db_session, org_id, instance.id, "reports", {"path": "missing/x.txt"})

    audit = db_session.execute(
        select(AuthorizationAudit).where(
            AuthorizationAudit.event_type == "INTEGRATION_CONNECTOR_OBJECT_ACCESSED",
            AuthorizationAudit.organization_id == org_id,
        )
    ).scalars().all()
    assert len(audit) == 1
    assert audit[0].meta["outcome"] == "NOT_FOUND"
    assert audit[0].meta["path"] == "missing/x.txt"


# --------------------------------------------------------------------------- #
# AC-20 — credentials never appear in output, error, log, or audit (live)
# --------------------------------------------------------------------------- #
def test_ac20_a_stored_credential_is_never_embedded_in_the_audit_trail(tmp_path, admin, db_session: Session):
    instance, actor, org_id = _make_instance(
        db_session, admin, _fs_config(str(tmp_path), auth_scheme="BASIC"),
    )
    secret_password = "s3-secret-value-9f8e7d"
    ConnectorCredentialService(db_session).store(
        actor, org_id, instance.id, "BASIC", {"username": "s3-access-key", "password": secret_password},
    )
    (tmp_path / "q1.txt").write_text("content", encoding="utf-8")
    invoke_tool(db_session, org_id, instance.id, "reports", {"path": "q1.txt"})

    audit = db_session.execute(
        select(AuthorizationAudit).where(AuthorizationAudit.event_type == "INTEGRATION_CONNECTOR_OBJECT_ACCESSED")
    ).scalars().all()
    assert all(secret_password not in json.dumps(a.meta or {}) for a in audit)


def test_ac20_the_stored_credential_row_never_holds_the_plaintext_password(tmp_path, admin, db_session: Session):
    instance, actor, org_id = _make_instance(db_session, admin, _fs_config(str(tmp_path), auth_scheme="BASIC"))
    secret_password = "another-secret-value"
    ConnectorCredentialService(db_session).store(
        actor, org_id, instance.id, "BASIC", {"username": "key", "password": secret_password},
    )
    row = db_session.execute(
        select(ConnectorCredential).where(ConnectorCredential.connector_instance_id == instance.id)
    ).scalar_one()
    assert secret_password not in row.encrypted_secret
    assert secret_password not in row.secret_hint


def test_none_auth_scheme_never_calls_the_credential_service(tmp_path, admin, db_session: Session, monkeypatch):
    """Mirrors 2.2.2's own precedent test exactly: the ``"NONE"`` scheme
    path must never even attempt to resolve a credential."""
    instance, actor, org_id = _make_instance(db_session, admin, _fs_config(str(tmp_path)))  # auth_scheme omitted -> NONE

    def _fail_if_called(*args, **kwargs):
        raise AssertionError("resolve_credential_bundle must not be called for auth_scheme NONE")

    monkeypatch.setattr(ConnectorCredentialService, "resolve_credential_bundle", _fail_if_called)
    (tmp_path / "q1.txt").write_text("content", encoding="utf-8")
    data = invoke_tool(db_session, org_id, instance.id, "reports", {"path": "q1.txt"})
    assert data == b"content"
