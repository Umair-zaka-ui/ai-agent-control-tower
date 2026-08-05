"""Phase 2.1.4 SRS ACT-INT-FR-060..066 — the worked example connector.

``WebhookConnector`` is built using **only** names imported from
``app.integration.sdk`` (plus the standard library) — no import of
``app.integration.base``, ``app.integration.types``, ``app.integration.auth``,
``app.integration.service``, or anything under ``app.runtime`` appears in
this file. That is not a style preference; it is the proof the build
prompt asks for (AC-02): if expressing a real, if minimal, connector ever
required reaching past ``app.integration.sdk``, the surface would be
incomplete. It did not.

A minimal outbound-webhook connector: one declared tool
(``send_notification``), bearer-token authentication, and a health check
that pre-flights its own declared webhook host through the SDK's
``GovernedHttpClient`` — the *only* network primitive this connector's code
has any access to (``ACT-INT-FR-066``, AC-10). An optional constructor-only
``resolver`` lets tests exercise ``health_check`` deterministically, with
no live DNS or network call, the same way ``MockConnector``'s config-flag
approach avoids one — see ``tests/integration/test_connector_sdk.py``."""

from __future__ import annotations

from typing import Any, Callable, Mapping
from urllib.parse import urlsplit

from app.integration.sdk import (
    Connector,
    ConnectorDescriptor,
    GovernedHttpClient,
    ToolContract,
    validate_configuration_schema,
)

CONNECTOR_TYPE = "SDK_EXAMPLE_WEBHOOK"
CONNECTOR_VERSION = "1.0.0"

_CONFIG_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"webhook_url": {"type": "string", "minLength": 1}},
    "required": ["webhook_url"],
    "additionalProperties": True,
}

_SEND_NOTIFICATION_PARAMETERS: dict[str, Any] = {
    "type": "object",
    "properties": {"message": {"type": "string", "minLength": 1}},
    "required": ["message"],
    "additionalProperties": False,
}


class WebhookConnector(Connector):
    """Declaration only — this class never receives a credential, a
    database session, or another tenant's data; the platform resolves and
    applies the ``BEARER`` credential this type declares outside this
    class entirely (``app.integration.auth``, not imported here)."""

    def __init__(self, *, resolver: Callable[[str], list[str]] | None = None) -> None:
        # Test-only hook, not part of the ABC: lets a test supply a fake
        # resolver so `health_check` never performs a real DNS lookup.
        # `ConnectorTypeService.implementation_for` still instantiates this
        # class with no arguments, which is why `resolver` is optional.
        self._resolver = resolver

    def describe(self) -> ConnectorDescriptor:
        return ConnectorDescriptor(
            connector_type=CONNECTOR_TYPE,
            version=CONNECTOR_VERSION,
            capabilities={"category": "example", "supports_read": False, "supports_write": True},
            config_schema=_CONFIG_SCHEMA,
            auth_requirements={"scheme": "BEARER"},
            tool_contracts=(
                ToolContract(
                    name="send_notification",
                    description="Sends a short text notification to the connector's declared webhook URL.",
                    parameters=_SEND_NOTIFICATION_PARAMETERS,
                ),
            ),
        )

    def validate_configuration(self, configuration: Mapping[str, Any]) -> None:
        validate_configuration_schema(configuration, self.describe().config_schema)

    def health_check(self, configuration: Mapping[str, Any]) -> bool:
        """Reachability only (never a credential, per the ABC's own
        contract) — pre-flights the instance's own declared
        ``webhook_url`` through a ``GovernedHttpClient`` constructed with
        *exactly that host* as its allowed set. There is no way for this
        method to reach any other host: the client is built fresh, here,
        from the same configuration the platform already validated."""
        webhook_url = configuration.get("webhook_url", "")
        host = urlsplit(webhook_url).hostname
        if not host:
            return False
        client = GovernedHttpClient(allowed_hosts={host})
        decision = client.evaluate(webhook_url, resolver=self._resolver)
        return decision.allowed
