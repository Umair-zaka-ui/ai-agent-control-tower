"""Phase 2.2.4 tests — the isolated queue scope-permission check
(``app/integration/connectors/queue/scope.py``), the security core's
first half.

Every test in this file runs with **no live broker of any kind** —
``check_operation_permitted`` is pure, in-process logic with zero
dependency on this platform or any queue backend."""

from __future__ import annotations

import pytest

from app.integration.connectors.queue.scope import (
    CONSUME,
    PUBLISH,
    QueueScopeViolationError,
    check_operation_permitted,
)


# --------------------------------------------------------------------------- #
# AC-08 core -- an operation mismatch is denied
# --------------------------------------------------------------------------- #
def test_consume_on_a_publish_only_binding_is_denied():
    with pytest.raises(QueueScopeViolationError) as excinfo:
        check_operation_permitted("orders_out", "PUBLISH", CONSUME)
    assert "orders_out" in str(excinfo.value)
    assert "PUBLISH" in str(excinfo.value)
    assert "CONSUME" in str(excinfo.value)


def test_publish_on_a_consume_only_binding_is_denied():
    with pytest.raises(QueueScopeViolationError):
        check_operation_permitted("orders_in", "CONSUME", PUBLISH)


# --------------------------------------------------------------------------- #
# A matching operation is always permitted
# --------------------------------------------------------------------------- #
def test_publish_on_a_publish_binding_is_permitted():
    check_operation_permitted("orders_out", "PUBLISH", PUBLISH)  # does not raise


def test_consume_on_a_consume_binding_is_permitted():
    check_operation_permitted("orders_in", "CONSUME", CONSUME)  # does not raise


def test_unknown_requested_operation_is_rejected():
    with pytest.raises(ValueError):
        check_operation_permitted("orders_out", "PUBLISH", "SUBSCRIBE")


# --------------------------------------------------------------------------- #
# AC-13 -- exercised entirely without live storage/broker
# --------------------------------------------------------------------------- #
def test_this_module_has_no_dependency_on_a_live_backend():
    import ast
    from pathlib import Path

    tree = ast.parse(Path(__file__).resolve().parents[2].joinpath(
        "app", "integration", "connectors", "queue", "scope.py"
    ).read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
        elif isinstance(node, ast.Import):
            for alias in node.names:
                imported.add(alias.name.split(".")[0])
    assert imported == {"__future__"}  # no real imports at all -- pure stdlib-free logic


def test_violation_message_never_includes_a_credential_or_payload_shaped_value():
    try:
        check_operation_permitted("orders_out", "PUBLISH", CONSUME)
    except QueueScopeViolationError as exc:
        message = str(exc)
        assert "password" not in message.lower()
        assert "secret" not in message.lower()
