"""Phase 2.2.4 tests — the queue connector's tool-invocation bridge
(``app/integration/connectors/queue/invoker.py``), end to end.

This is the file that proves AC-19 ("a queue tool is actually invocable
end to end") and the live-database half of AC-02/AC-04/AC-08/AC-12 —
everything here connects to this platform's own real dev database via
``db_session``/``admin`` (a real, database-backed ``ConnectorInstance``,
a real, stored, encrypted credential), exactly as every prior
connector's own invocation test file does. The broker itself is mocked
(``pika.BlockingConnection``) since no live RabbitMQ is reachable in
this environment — the same, explicitly stated coverage boundary as
``test_queue_connector.py``; only the *database*-backed half of this
bridge is live here, not the broker half."""

from __future__ import annotations

import json
import uuid
from typing import Any
from unittest import mock

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.integration.auth.service import ConnectorCredentialService
from app.integration.connectors.queue.invoker import consume_messages, publish_message
from app.integration.errors import QueueBindingNotDeclaredError, QueueOperationNotPermittedError
from app.integration.service import ConnectorService, ConnectorTypeService
from app.models.integration import ConnectorCredential
from app.models.rbac import AuthorizationAudit
from app.models.user import User


class _FakeAmqpChannel:
    def __init__(self, available_bodies: list[bytes] | None = None):
        self._available = list(available_bodies or [])
        self.published: list[tuple[str, bytes]] = []

    def basic_get(self, queue, auto_ack):
        if self._available:
            return (object(), None, self._available.pop(0))
        return (None, None, None)

    def basic_publish(self, exchange, routing_key, body):
        self.published.append((routing_key, body))


class _FakeAmqpConnection:
    def __init__(self, available_bodies: list[bytes] | None = None):
        self.channel_obj = _FakeAmqpChannel(available_bodies)

    def channel(self):
        return self.channel_obj

    def close(self):
        pass


def _amqp_config(*, auth_scheme: str = "NONE") -> dict[str, Any]:
    return {
        "backend": "AMQP", "host": "localhost", "port": 5672, "auth_scheme": auth_scheme,
        "bindings": [
            {"name": "orders_out", "description": "Publish an order event.", "operation": "PUBLISH", "queue_name": "orders"},
            {"name": "orders_in", "description": "Consume order events.", "operation": "CONSUME", "queue_name": "orders",
             "max_batch_size": 3, "wait_timeout_seconds": 0.3},
        ],
    }


def _admin_user(db_session: Session, admin: dict) -> User:
    return db_session.get(User, uuid.UUID(admin["user_id"]))


def _make_instance(db_session: Session, admin: dict, config: dict):
    ConnectorTypeService(db_session).ensure_seeded()
    actor = _admin_user(db_session, admin)
    org_id = uuid.UUID(admin["organization_id"])
    instance = ConnectorService(db_session).create_instance(
        actor, org_id, connector_type="QUEUE", name=f"Queue {uuid.uuid4().hex[:6]}", configuration=config,
    )
    return instance, actor, org_id


# --------------------------------------------------------------------------- #
# AC-19 — a queue tool is actually invocable end to end
# --------------------------------------------------------------------------- #
def test_ac19_publish_through_the_bridge_end_to_end(admin, db_session: Session):
    instance, actor, org_id = _make_instance(db_session, admin, _amqp_config())
    fake_conn = _FakeAmqpConnection()
    with mock.patch("pika.BlockingConnection", return_value=fake_conn):
        publish_message(db_session, org_id, instance.id, "orders_out", {"message": "hello"})
    assert fake_conn.channel_obj.published == [("orders", b"hello")]


def test_ac19_consume_through_the_bridge_end_to_end(admin, db_session: Session):
    instance, actor, org_id = _make_instance(db_session, admin, _amqp_config())
    fake_conn = _FakeAmqpConnection([b"m1", b"m2"])
    with mock.patch("pika.BlockingConnection", return_value=fake_conn):
        result = consume_messages(db_session, org_id, instance.id, "orders_in", {})
    assert result == [
        {"message": "m1", "size_bytes": 2, "truncated": False},
        {"message": "m2", "size_bytes": 2, "truncated": False},
    ]


# --------------------------------------------------------------------------- #
# AC-02 — an undeclared binding is rejected before reaching any backend
# --------------------------------------------------------------------------- #
def test_ac02_an_undeclared_binding_name_is_rejected_before_reaching_any_backend(admin, db_session: Session):
    instance, actor, org_id = _make_instance(db_session, admin, _amqp_config())
    with mock.patch("pika.BlockingConnection", side_effect=AssertionError("no connection should be attempted")):
        with pytest.raises(QueueBindingNotDeclaredError) as excinfo:
            publish_message(db_session, org_id, instance.id, "not_a_real_binding", {"message": "x"})
    assert excinfo.value.code == "QUEUE_NOT_DECLARED"


# --------------------------------------------------------------------------- #
# AC-08 — an operation mismatch is rejected before reaching any backend
# --------------------------------------------------------------------------- #
def test_ac08_consume_on_a_publish_only_binding_is_rejected(admin, db_session: Session):
    instance, actor, org_id = _make_instance(db_session, admin, _amqp_config())
    with mock.patch("pika.BlockingConnection", side_effect=AssertionError("no connection should be attempted")):
        with pytest.raises(QueueOperationNotPermittedError) as excinfo:
            consume_messages(db_session, org_id, instance.id, "orders_out", {})
    assert excinfo.value.code == "QUEUE_OPERATION_NOT_PERMITTED"


def test_ac08_publish_on_a_consume_only_binding_is_rejected(admin, db_session: Session):
    instance, actor, org_id = _make_instance(db_session, admin, _amqp_config())
    with mock.patch("pika.BlockingConnection", side_effect=AssertionError("no connection should be attempted")):
        with pytest.raises(QueueOperationNotPermittedError):
            publish_message(db_session, org_id, instance.id, "orders_in", {"message": "x"})


# --------------------------------------------------------------------------- #
# AC-04 / AC-12 — every attempt (allowed or denied) is audited, live
# --------------------------------------------------------------------------- #
def _audit_rows(db_session: Session, org_id: uuid.UUID) -> list[AuthorizationAudit]:
    return list(db_session.execute(
        select(AuthorizationAudit).where(
            AuthorizationAudit.event_type == "INTEGRATION_CONNECTOR_OBJECT_ACCESSED",
            AuthorizationAudit.organization_id == org_id,
        )
    ).scalars().all())


def test_ac04_a_denied_operation_is_audited_as_a_probing_signal(admin, db_session: Session):
    instance, actor, org_id = _make_instance(db_session, admin, _amqp_config())
    with mock.patch("pika.BlockingConnection", side_effect=AssertionError("no connection should be attempted")):
        with pytest.raises(QueueOperationNotPermittedError):
            consume_messages(db_session, org_id, instance.id, "orders_out", {})
    audit = _audit_rows(db_session, org_id)
    assert len(audit) == 1
    assert audit[0].meta["outcome"] == "DENIED"
    assert audit[0].meta["scope_name"] == "orders_out"
    assert audit[0].meta["operation"] == "CONSUME"


def test_ac12_a_successful_publish_is_audited(admin, db_session: Session):
    instance, actor, org_id = _make_instance(db_session, admin, _amqp_config())
    fake_conn = _FakeAmqpConnection()
    with mock.patch("pika.BlockingConnection", return_value=fake_conn):
        publish_message(db_session, org_id, instance.id, "orders_out", {"message": "hello"})
    audit = _audit_rows(db_session, org_id)
    assert len(audit) == 1
    meta = audit[0].meta
    assert meta["backend"] == "AMQP"
    assert meta["scope_name"] == "orders_out"
    assert meta["operation"] == "PUBLISH"
    assert meta["message_count"] == 1
    assert meta["size_bytes"] == len(b"hello")
    assert meta["outcome"] == "SUCCESS"


def test_ac12_a_successful_consume_is_audited_with_the_real_message_count(admin, db_session: Session):
    instance, actor, org_id = _make_instance(db_session, admin, _amqp_config())
    fake_conn = _FakeAmqpConnection([b"m1", b"m2"])
    with mock.patch("pika.BlockingConnection", return_value=fake_conn):
        consume_messages(db_session, org_id, instance.id, "orders_in", {})
    audit = _audit_rows(db_session, org_id)
    assert len(audit) == 1
    meta = audit[0].meta
    assert meta["operation"] == "CONSUME"
    assert meta["message_count"] == 2
    assert meta["outcome"] == "SUCCESS"


# --------------------------------------------------------------------------- #
# Credential resolution and protection (structural half is in
# test_queue_connector.py; this is the live half)
# --------------------------------------------------------------------------- #
def test_the_stored_credential_is_applied_to_the_amqp_connection(admin, db_session: Session):
    instance, actor, org_id = _make_instance(db_session, admin, _amqp_config(auth_scheme="BASIC"))
    ConnectorCredentialService(db_session).store(
        actor, org_id, instance.id, "BASIC", {"username": "queue-user", "password": "queue-secret-9f8e7d"},
    )
    captured: dict[str, Any] = {}

    def _fake_blocking_connection(params):
        captured["username"] = params.credentials.username
        captured["password"] = params.credentials.password
        return _FakeAmqpConnection()

    with mock.patch("pika.BlockingConnection", side_effect=_fake_blocking_connection):
        publish_message(db_session, org_id, instance.id, "orders_out", {"message": "hi"})
    assert captured["username"] == "queue-user"
    assert captured["password"] == "queue-secret-9f8e7d"


def test_the_stored_credential_row_never_holds_the_plaintext_password(admin, db_session: Session):
    instance, actor, org_id = _make_instance(db_session, admin, _amqp_config(auth_scheme="BASIC"))
    secret_password = "another-secret-value"
    ConnectorCredentialService(db_session).store(
        actor, org_id, instance.id, "BASIC", {"username": "u", "password": secret_password},
    )
    row = db_session.execute(
        select(ConnectorCredential).where(ConnectorCredential.connector_instance_id == instance.id)
    ).scalar_one()
    assert secret_password not in row.encrypted_secret
    assert secret_password not in row.secret_hint


def test_ac12_a_credential_never_appears_in_the_audit_trail(admin, db_session: Session):
    instance, actor, org_id = _make_instance(db_session, admin, _amqp_config(auth_scheme="BASIC"))
    secret_password = "s3cr3t-queue-password"
    ConnectorCredentialService(db_session).store(
        actor, org_id, instance.id, "BASIC", {"username": "u", "password": secret_password},
    )
    fake_conn = _FakeAmqpConnection()
    with mock.patch("pika.BlockingConnection", return_value=fake_conn):
        publish_message(db_session, org_id, instance.id, "orders_out", {"message": "hi"})
    audit = _audit_rows(db_session, org_id)
    assert all(secret_password not in json.dumps(a.meta or {}) for a in audit)


def test_none_auth_scheme_never_calls_the_credential_service(admin, db_session: Session, monkeypatch):
    """Mirrors every prior connector's own precedent test exactly: the
    ``"NONE"`` scheme path must never even attempt to resolve a
    credential."""
    instance, actor, org_id = _make_instance(db_session, admin, _amqp_config())  # auth_scheme omitted -> NONE

    def _fail_if_called(*args, **kwargs):
        raise AssertionError("resolve_credential_bundle must not be called for auth_scheme NONE")

    monkeypatch.setattr(ConnectorCredentialService, "resolve_credential_bundle", _fail_if_called)
    fake_conn = _FakeAmqpConnection()
    with mock.patch("pika.BlockingConnection", return_value=fake_conn):
        publish_message(db_session, org_id, instance.id, "orders_out", {"message": "hi"})
