"""Phase 2.1.4 — the worked example's own tests.

Deliberately kept in a file separate from ``test_connector_sdk.py``: this
file's own imports are the proof for AC-03 ("the example's tests use only
the SDK testing harness") — everything below is exercised through
``ConnectorTestHarness`` alone, and the only non-stdlib imports in this
file are ``app.integration.sdk`` (the harness) and the example connector
itself under test. No database, no service class, no registry, no
internal ``app.integration.*`` module."""

from __future__ import annotations

import ast
from pathlib import Path

from app.integration.sdk import ConnectorTestHarness
from app.integration.sdk.example.webhook_connector import WebhookConnector

_PUBLIC_IP_RESOLVER = lambda host: ["93.184.216.34"]  # noqa: E731 -- test-only, no live DNS/network


def test_this_file_imports_only_the_sdk_harness_and_the_example_under_test():
    tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("app."):
            modules.add(node.module)
    assert modules == {"app.integration.sdk", "app.integration.sdk.example.webhook_connector"}


def test_declaration_is_complete():
    ConnectorTestHarness(WebhookConnector()).assert_declaration_complete()


def test_configuration_validation():
    harness = ConnectorTestHarness(WebhookConnector())
    harness.assert_configuration_valid({"webhook_url": "https://hooks.example.com/notify"})
    message = harness.assert_configuration_invalid({})
    assert "webhook_url" in message


def test_send_notification_tool_contract_shape():
    contract = ConnectorTestHarness(WebhookConnector()).tool_contract("send_notification")
    assert contract.parameters["properties"]["message"]["type"] == "string"
    assert contract.parameters["required"] == ["message"]


def test_health_check_reachable_and_unreachable():
    reachable = ConnectorTestHarness(WebhookConnector(resolver=_PUBLIC_IP_RESOLVER))
    outcome = reachable.run_health_check({"webhook_url": "https://hooks.example.com/notify"})
    assert outcome.reachable is True

    no_host = ConnectorTestHarness(WebhookConnector())
    outcome = no_host.run_health_check({"webhook_url": ""})
    assert outcome.reachable is False
