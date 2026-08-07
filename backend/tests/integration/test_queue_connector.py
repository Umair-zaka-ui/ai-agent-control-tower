"""Phase 2.2.4 tests — Generic Message Queue Connector.

Grouped as the build prompt's §8 groups its acceptance criteria: scoped
publish (AC-01..04, the live-database half of AC-02/AC-04 is in
``test_queue_connector_invocation.py``), bounded consume (AC-05..08),
size/ack/audit (AC-09..12, the live-database half of AC-12 is in the
invocation file), backends/SDK-surface/integrity (AC-13..25).

AMQP and SQS backend-dispatch tests mock ``pika``/``boto3`` (no live
RabbitMQ or SQS/localstack reachable in this environment) — the stated
coverage boundary this phase's own build prompt asks for explicitly
(§6/§9.2); see ``docs/integration/connectors.md`` for the same statement.
The scope-permission check itself (``scope.py``) has full, unmocked
coverage in ``test_queue_scope.py``, since it has no backend dependency
at all."""

from __future__ import annotations

import ast
import inspect
import time
from pathlib import Path
from typing import Any
from unittest import mock

import pytest

from app.integration.connectors.queue import backends, declaration
from app.integration.connectors.queue.connector import CONNECTOR_TYPE, CONNECTOR_VERSION, QueueConnector
from app.integration.connectors.queue.declaration import parse_declaration, tool_contracts_for
from app.integration.mock import MockConnector
from app.integration.sdk import ConnectorConfigInvalidError, ConnectorTestHarness
from app.integration.service import _CONNECTOR_TYPES, ConnectorTypeService

_PACKAGE_ROOT = Path(__file__).resolve().parents[2] / "app" / "integration" / "connectors" / "queue"
_ALL_PACKAGE_FILES = ("__init__.py", "scope.py", "declaration.py", "backends.py", "connector.py", "invoker.py")


def _amqp_config(**overrides: Any) -> dict[str, Any]:
    base = {
        "backend": "AMQP", "host": "localhost", "port": 5672,
        "bindings": [
            {"name": "publish_orders", "description": "Publish an order event.", "operation": "PUBLISH", "queue_name": "orders"},
            {"name": "consume_orders", "description": "Consume order events.", "operation": "CONSUME", "queue_name": "orders",
             "max_batch_size": 3, "wait_timeout_seconds": 0.3},
        ],
    }
    base.update(overrides)
    return base


def _sqs_config(**overrides: Any) -> dict[str, Any]:
    base = {
        "backend": "SQS", "region": "us-east-1",
        "bindings": [
            {"name": "publish_orders", "description": "x", "operation": "PUBLISH",
             "queue_name": "https://sqs.us-east-1.amazonaws.com/123/orders"},
            {"name": "consume_orders", "description": "x", "operation": "CONSUME",
             "queue_name": "https://sqs.us-east-1.amazonaws.com/123/orders", "max_batch_size": 3, "wait_timeout_seconds": 1},
        ],
    }
    base.update(overrides)
    return base


class _FakeAmqpChannel:
    def __init__(self, available_bodies: list[bytes]):
        self._available = list(available_bodies)
        self.published: list[tuple[str, bytes]] = []
        self.get_calls = 0
        self.last_auto_ack: bool | None = None

    def basic_get(self, queue, auto_ack):
        self.get_calls += 1
        self.last_auto_ack = auto_ack
        if self._available:
            return (object(), None, self._available.pop(0))
        return (None, None, None)

    def basic_publish(self, exchange, routing_key, body):
        self.published.append((routing_key, body))


class _FakeAmqpConnection:
    def __init__(self, available_bodies: list[bytes] | None = None):
        self.channel_obj = _FakeAmqpChannel(available_bodies or [])
        self.closed = False

    def channel(self):
        return self.channel_obj

    def close(self):
        self.closed = True


class _FakeSqsClient:
    def __init__(self, batches: list[list[dict]] | None = None):
        self._batches = list(batches or [])
        self.receive_calls: list[dict] = []
        self.deleted: list[str] = []
        self.sent: list[dict] = []

    def receive_message(self, **kwargs):
        self.receive_calls.append(kwargs)
        if self._batches:
            return {"Messages": self._batches.pop(0)}
        return {"Messages": []}

    def delete_message(self, **kwargs):
        self.deleted.append(kwargs["ReceiptHandle"])

    def send_message(self, **kwargs):
        self.sent.append(kwargs)


# --------------------------------------------------------------------------- #
# Scoped publish (AC-01..04)
# --------------------------------------------------------------------------- #
def test_ac01_publish_to_a_declared_binding_succeeds_amqp():
    """AC-01."""
    decl = parse_declaration(_amqp_config())
    binding = decl.binding_by_name("publish_orders")
    connection = _FakeAmqpConnection()
    with mock.patch("pika.BlockingConnection", return_value=connection):
        backends.publish(decl, binding, b"hello", {})
    assert connection.channel_obj.published == [("orders", b"hello")]
    assert connection.closed is True


def test_ac01_publish_to_a_declared_binding_succeeds_sqs():
    """AC-01."""
    decl = parse_declaration(_sqs_config())
    binding = decl.binding_by_name("publish_orders")
    client = _FakeSqsClient()
    with mock.patch("boto3.client", return_value=client):
        backends.publish(decl, binding, b"hello", {})
    assert client.sent == [{"QueueUrl": binding.queue_name, "MessageBody": "hello"}]


def test_ac03_a_publish_tool_contract_has_no_queue_name_parameter():
    """AC-03 — the target queue is fixed by the tool contract itself;
    the model's only parameter is the message payload."""
    contracts = tool_contracts_for(_amqp_config())
    publish_contract = next(c for c in contracts if c.name == "publish_orders")
    assert set(publish_contract.parameters["properties"]) == {"message"}


def test_ac03_a_consume_tool_contract_has_no_queue_name_parameter():
    """AC-03."""
    contracts = tool_contracts_for(_amqp_config())
    consume_contract = next(c for c in contracts if c.name == "consume_orders")
    assert set(consume_contract.parameters["properties"]) == {"max_messages"}


# --------------------------------------------------------------------------- #
# Bounded consume (AC-05..08)
# --------------------------------------------------------------------------- #
def test_ac05_consume_never_exceeds_the_configured_cap_even_when_more_is_available():
    """AC-05 — the queue holds 5 messages, the binding caps the batch at
    3, and the caller asks for 10; only 3 come back."""
    decl = parse_declaration(_amqp_config())
    binding = decl.binding_by_name("consume_orders")
    connection = _FakeAmqpConnection([b"m1", b"m2", b"m3", b"m4", b"m5"])
    with mock.patch("pika.BlockingConnection", return_value=connection):
        messages = backends.consume(decl, binding, {}, max_messages=10)
    assert len(messages) == 3
    assert [m.body for m in messages] == [b"m1", b"m2", b"m3"]


def test_ac05_a_caller_asking_for_fewer_than_the_cap_gets_at_most_that_many():
    decl = parse_declaration(_amqp_config())
    binding = decl.binding_by_name("consume_orders")
    connection = _FakeAmqpConnection([b"m1", b"m2", b"m3"])
    with mock.patch("pika.BlockingConnection", return_value=connection):
        messages = backends.consume(decl, binding, {}, max_messages=1)
    assert len(messages) == 1


def test_ac06_consume_never_blocks_past_its_bounded_wait_amqp():
    """AC-06 — an empty queue returns within the configured timeout, not
    indefinitely."""
    decl = parse_declaration(_amqp_config())
    binding = decl.binding_by_name("consume_orders")  # wait_timeout_seconds=0.3
    connection = _FakeAmqpConnection([])
    start = time.monotonic()
    with mock.patch("pika.BlockingConnection", return_value=connection):
        messages = backends.consume(decl, binding, {}, max_messages=5)
    elapsed = time.monotonic() - start
    assert messages == []
    assert elapsed < 1.0  # bounded, not indefinite


def test_ac06_consume_never_blocks_past_its_bounded_wait_sqs():
    """AC-06."""
    decl = parse_declaration(_sqs_config(bindings=[
        {"name": "consume_orders", "description": "x", "operation": "CONSUME", "queue_name": "q",
         "max_batch_size": 3, "wait_timeout_seconds": 0.4},
    ]))
    binding = decl.binding_by_name("consume_orders")
    client = _FakeSqsClient([])
    start = time.monotonic()
    with mock.patch("boto3.client", return_value=client):
        messages = backends.consume(decl, binding, {}, max_messages=5)
    elapsed = time.monotonic() - start
    assert messages == []
    assert elapsed < 2.0


def test_ac07_consume_returns_a_bounded_list_not_a_stream_or_generator():
    """AC-07."""
    decl = parse_declaration(_amqp_config())
    binding = decl.binding_by_name("consume_orders")
    connection = _FakeAmqpConnection([b"m1", b"m2"])
    with mock.patch("pika.BlockingConnection", return_value=connection):
        messages = backends.consume(decl, binding, {}, max_messages=10)
    assert isinstance(messages, list)
    assert len(messages) <= decl.effective_max_batch_size(binding)


def test_ac08_consume_dispatch_is_never_offered_for_a_publish_only_binding():
    """AC-08 (backend-dispatch half — the invocation-level rejection
    with the platform error code is proven in
    ``test_queue_connector_invocation.py``). ``backends.consume`` itself
    has no operation-awareness; the permission boundary lives entirely
    in ``scope.py``/``invoker.py`` — this test documents that
    `backends.py` will happily consume from any binding handed to it, by
    design (mirrors 2.2.2/2.2.3's own "backend module trusts its
    caller" split)."""
    decl = parse_declaration(_amqp_config())
    publish_binding = decl.binding_by_name("publish_orders")
    assert publish_binding.operation == "PUBLISH"
    # backends.py itself does not reject this -- confirming the
    # permission boundary is enforced one layer up, not duplicated here.
    connection = _FakeAmqpConnection([])
    with mock.patch("pika.BlockingConnection", return_value=connection):
        backends.consume(decl, publish_binding, {}, max_messages=1)


# --------------------------------------------------------------------------- #
# Size, ack, audit (AC-09..12, structural half)
# --------------------------------------------------------------------------- #
def test_ac09_an_oversized_publish_is_rejected_before_any_send(monkeypatch):
    """AC-09 — proven by making the backend's own send path fail the
    test if reached."""
    decl = parse_declaration(_amqp_config(default_max_message_size_bytes=5))
    binding = decl.binding_by_name("publish_orders")

    def _fail_if_connected(*args, **kwargs):
        raise AssertionError("no connection should be attempted once the size check has already rejected the message")

    monkeypatch.setattr("pika.BlockingConnection", _fail_if_connected)
    with pytest.raises(backends.MessageTooLargeError):
        backends.publish(decl, binding, b"way too many bytes", {})


def test_ac10_an_oversized_consumed_message_is_truncated_and_flagged_not_silently_passed():
    """AC-10."""
    decl = parse_declaration(_amqp_config(default_max_message_size_bytes=4))
    binding = decl.binding_by_name("consume_orders")
    big_body = b"0123456789"
    connection = _FakeAmqpConnection([big_body])
    with mock.patch("pika.BlockingConnection", return_value=connection):
        messages = backends.consume(decl, binding, {}, max_messages=1)
    assert len(messages) == 1
    assert messages[0].truncated is True
    assert messages[0].body == big_body[:4]
    assert messages[0].size_bytes == len(big_body)  # real size reported, not the truncated length


def test_ac10_a_message_within_the_limit_is_never_flagged_truncated():
    decl = parse_declaration(_amqp_config())
    binding = decl.binding_by_name("consume_orders")
    connection = _FakeAmqpConnection([b"small"])
    with mock.patch("pika.BlockingConnection", return_value=connection):
        messages = backends.consume(decl, binding, {}, max_messages=1)
    assert messages[0].truncated is False
    assert messages[0].body == b"small"


def test_ac11_amqp_ack_policy_is_ack_on_retrieve():
    """AC-11 — `basic_get` is called with `auto_ack=True`, the
    documented ack-on-retrieve policy."""
    decl = parse_declaration(_amqp_config())
    binding = decl.binding_by_name("consume_orders")
    connection = _FakeAmqpConnection([b"m1"])
    with mock.patch("pika.BlockingConnection", return_value=connection):
        backends.consume(decl, binding, {}, max_messages=1)
    assert connection.channel_obj.last_auto_ack is True


def test_ac11_sqs_ack_policy_deletes_each_message_immediately_after_receipt():
    """AC-11 — `delete_message` is called once per retrieved message,
    in the same call that returns the batch, not deferred."""
    decl = parse_declaration(_sqs_config())
    binding = decl.binding_by_name("consume_orders")
    client = _FakeSqsClient([[{"Body": "m1", "ReceiptHandle": "r1"}, {"Body": "m2", "ReceiptHandle": "r2"}]])
    with mock.patch("boto3.client", return_value=client):
        messages = backends.consume(decl, binding, {}, max_messages=5)
    assert len(messages) == 2
    assert client.deleted == ["r1", "r2"]


# --------------------------------------------------------------------------- #
# Backends, SDK-surface, integrity (AC-13..25)
# --------------------------------------------------------------------------- #
def test_ac14_service_bus_is_recognized_but_backend_pending():
    with pytest.raises(ConnectorConfigInvalidError) as excinfo:
        parse_declaration({
            "backend": "SERVICE_BUS",
            "bindings": [{"name": "p", "description": "x", "operation": "PUBLISH", "queue_name": "q"}],
        })
    assert "backend-pending" in str(excinfo.value)
    assert "SERVICE_BUS" in backends.PENDING_BACKENDS
    assert "SERVICE_BUS" not in backends.SUPPORTED_BACKENDS


def test_ac15_declaration_module_never_imports_a_backend_sdk():
    """AC-15 — backend-specific ack/protocol differences are handled
    entirely inside `backends.py`; `declaration.py` never imports
    `pika`/`boto3`."""
    source = (_PACKAGE_ROOT / "declaration.py").read_text(encoding="utf-8")
    assert "pika" not in source
    assert "boto3" not in source


def _app_imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("app."):
            modules.add(node.module)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("app."):
                    modules.add(alias.name)
    return modules


def test_ac16_declaration_py_imports_only_from_the_sdk_surface():
    """AC-16 — this phase needed zero deviations (see declaration.py's
    own module docstring for why, unlike 2.2.2/2.2.3)."""
    for module in _app_imports(_PACKAGE_ROOT / "declaration.py"):
        assert module == "app.integration.sdk" or module.startswith("app.integration.sdk."), (
            f"declaration.py imports {module!r}, reaching past the SDK surface"
        )


def test_ac16_connector_py_imports_only_from_the_sdk_surface():
    """AC-16 — zero deviations, matching declaration.py: the only
    non-SDK import is this package's own sibling `declaration.py`."""
    modules = _app_imports(_PACKAGE_ROOT / "connector.py")
    non_sdk = {m for m in modules if not (m == "app.integration.sdk" or m.startswith("app.integration.sdk."))
               and not m.startswith("app.integration.connectors.queue")}
    assert non_sdk == set()


def test_ac16_scope_py_has_zero_app_dependencies():
    assert _app_imports(_PACKAGE_ROOT / "scope.py") == set()


def test_ac16_backends_py_never_imports_platform_error_types():
    modules = _app_imports(_PACKAGE_ROOT / "backends.py")
    assert not any(m.startswith("app.integration.errors") for m in modules)


def test_ac17_the_connector_never_receives_raw_credential_material():
    """AC-17 — `QueueConnector`'s ABC methods take no db/session/
    credential parameter; its own file never imports the auth
    framework or a broker SDK at all."""
    for method_name in ("describe", "validate_configuration", "health_check"):
        params = list(inspect.signature(getattr(QueueConnector, method_name)).parameters)
        assert all(p in ("self", "configuration") for p in params)
    modules = _app_imports(_PACKAGE_ROOT / "connector.py")
    assert not any(m.startswith("app.integration.auth") for m in modules)
    source = (_PACKAGE_ROOT / "connector.py").read_text(encoding="utf-8")
    assert "import pika" not in source
    assert "import boto3" not in source


def test_ac18_registration_parity_with_prior_connectors(db_session):
    """AC-18."""
    assert _CONNECTOR_TYPES["QUEUE"] is QueueConnector
    service = ConnectorTypeService(db_session)
    service.ensure_seeded()
    from sqlalchemy import select

    from app.models.integration import Connector as ConnectorRow
    row = db_session.execute(
        select(ConnectorRow).where(ConnectorRow.connector_type == CONNECTOR_TYPE, ConnectorRow.version == CONNECTOR_VERSION)
    ).scalar_one()
    assert row.connector_type == "QUEUE"


def test_ac20_prior_connectors_still_describe_and_validate_unchanged():
    """AC-20."""
    assert MockConnector().describe().auth_requirements == {"scheme": "NONE"}
    from app.integration.connectors.database.connector import DatabaseConnector
    from app.integration.connectors.rest.connector import RestConnector
    from app.integration.connectors.storage.connector import StorageConnector
    assert RestConnector().describe().connector_type == "REST"
    assert DatabaseConnector().describe().connector_type == "DATABASE"
    assert StorageConnector().describe().connector_type == "STORAGE"


def test_ac22_migration_head_unchanged_no_new_migration_needed():
    """AC-22 — every table this connector touches already exists
    (`connectors`/`connector_instances`/`connector_credentials`/
    `authorization_audit`)."""
    migrations_dir = Path(__file__).resolve().parents[2] / "migrations" / "versions"
    versions = sorted(p.name for p in migrations_dir.glob("00*.py"))
    assert versions[-1] == "0035_connector_health.py"


def test_ac25_no_stub_markers_in_this_phases_new_files():
    """AC-25."""
    forbidden = ("TODO", "FIXME", "XXX", "HACK", "NotImplementedError", "pytest.skip", "xfail")
    for filename in _ALL_PACKAGE_FILES:
        text_content = (_PACKAGE_ROOT / filename).read_text(encoding="utf-8")
        for marker in forbidden:
            assert marker not in text_content, f"{filename} contains forbidden marker {marker!r}"


def test_queue_config_harness_roundtrip():
    """Standard 2.1.4-harness usage, mirroring every prior generic
    connector's own proof that the SDK testing utilities work here too."""
    harness = ConnectorTestHarness(QueueConnector())
    harness.assert_configuration_valid(_amqp_config())
    message = harness.assert_configuration_invalid({"backend": "AMQP"})  # missing required 'bindings'
    assert message


def test_a_publish_binding_declaring_consume_only_fields_is_rejected():
    with pytest.raises(ConnectorConfigInvalidError):
        parse_declaration(_amqp_config(bindings=[
            {"name": "p", "description": "x", "operation": "PUBLISH", "queue_name": "q", "max_batch_size": 5},
        ]))


def test_duplicate_binding_names_are_rejected():
    with pytest.raises(ConnectorConfigInvalidError):
        parse_declaration(_amqp_config(bindings=[
            {"name": "dup", "description": "a", "operation": "PUBLISH", "queue_name": "q1"},
            {"name": "dup", "description": "b", "operation": "PUBLISH", "queue_name": "q2"},
        ]))


def test_health_check_amqp_uses_injected_connector_factory():
    calls = []

    class _FakeConn:
        def close(self):
            pass

    def _factory(address, timeout):
        calls.append(address)
        return _FakeConn()

    connector = QueueConnector(connector_factory=_factory)
    assert connector.health_check(_amqp_config()) is True
    assert calls == [("localhost", 5672)]


def test_health_check_sqs_uses_injected_connector_factory():
    calls = []

    class _FakeConn:
        def close(self):
            pass

    def _factory(address, timeout):
        calls.append(address)
        return _FakeConn()

    connector = QueueConnector(connector_factory=_factory)
    assert connector.health_check(_sqs_config()) is True
    assert calls == [("sqs.amazonaws.com", 443)]
