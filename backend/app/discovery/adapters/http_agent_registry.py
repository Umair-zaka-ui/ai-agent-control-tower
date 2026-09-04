"""Phase 5.2 (M5.2) - THE REFERENCE ADAPTER (required for the framework
proof). Distinguish this clearly from a future production vendor adapter:
this is a generic, vendor-neutral client for any HTTP endpoint that serves a
paginated JSON list of agents at ``GET {base_url}{path}?offset=&limit=`` in
the shape ``{"items": [{"id": ..., "name": ..., ...}], "next_offset": int|null}``.

**No real vendor's API shape is assumed or hard-coded.** A genuine vendor
adapter (Azure AI Foundry, AWS Bedrock Agents, a LangGraph/CrewAI registry,
Kubernetes CRDs, an MCP server's ``list_agents``, ...) is explicitly deferred
(SRS M5.2 §5) -- this adapter exists to prove the discovery framework end to
end against a real, non-mocked local HTTP server (see
``tests/discovery/test_discovery_framework.py``'s ``local_server`` fixture,
the same real-``http.server`` convention Phase 2.2.1's REST-connector tests
established), not to catalog vendors.

Bounded against a hostile/huge source (SRS M5.2 §10): at most ``max_pages``
pages, each at most ``page_size`` items -- a source that never stops paging
cannot make one sweep run forever.
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any, Mapping
from urllib.parse import urlencode

from app.discovery.adapters.base import (
    DiscoveryAdapter,
    DiscoveryAdapterDescriptor,
    DiscoveryFetchResult,
    NormalizedObservation,
    RawDiscoveryItem,
)
from app.discovery.adapters.registry import register
from app.identity.errors import ErrorCode, IdentityError
from app.integration.base import validate_configuration_schema
from app.integration.sdk import GovernedHttpClient

ADAPTER_KEY = "HTTP_AGENT_REGISTRY"

_CONFIG_SCHEMA: dict = {
    "type": "object",
    "required": ["base_url", "allowed_hosts"],
    "properties": {
        "base_url": {"type": "string", "minLength": 1},
        "allowed_hosts": {"type": "array", "items": {"type": "string"}, "minItems": 1},
        "local_dev_hosts": {"type": "array", "items": {"type": "string"}},
        "allow_plaintext_http": {"type": "boolean"},
        "path": {"type": "string", "default": "/agents"},
        "page_size": {"type": "integer", "minimum": 1, "maximum": 200, "default": 50},
        "max_pages": {"type": "integer", "minimum": 1, "maximum": 100, "default": 20},
        "origin_provider": {"type": "string", "default": ADAPTER_KEY},
    },
    "additionalProperties": True,
}

_MAX_ITEMS_PER_FETCH = 200 * 100  # page_size ceiling * max_pages ceiling - the absolute DoS bound


@register(ADAPTER_KEY)
class HttpAgentRegistryAdapter(DiscoveryAdapter):
    def describe(self) -> DiscoveryAdapterDescriptor:
        return DiscoveryAdapterDescriptor(
            adapter_key=ADAPTER_KEY,
            display_name="Generic HTTP Agent Registry (reference adapter)",
            config_schema=_CONFIG_SCHEMA,
            requires_secret=False,
        )

    def validate_configuration(self, configuration: Mapping[str, Any]) -> None:
        try:
            validate_configuration_schema(configuration, _CONFIG_SCHEMA)
        except Exception as exc:  # noqa: BLE001 - re-raise as this domain's own error code
            raise IdentityError(ErrorCode.DISCOVERY_SOURCE_INVALID_CONFIG, str(exc)) from exc

    def build_client(self, configuration: Mapping[str, Any]) -> GovernedHttpClient:
        return GovernedHttpClient(
            allowed_hosts=frozenset(configuration["allowed_hosts"]),
            allow_plaintext_http=bool(configuration.get("allow_plaintext_http", False)),
            local_dev_hosts=frozenset(configuration.get("local_dev_hosts", ())),
        )

    def fetch(
        self,
        client: GovernedHttpClient,
        configuration: Mapping[str, Any],
        secret: str | None,
        checkpoint: Mapping[str, Any] | None,
    ) -> DiscoveryFetchResult:
        base_url = str(configuration["base_url"]).rstrip("/")
        path = str(configuration.get("path", "/agents"))
        page_size = min(int(configuration.get("page_size", 50)), 200)
        max_pages = min(int(configuration.get("max_pages", 20)), 100)
        headers = {"Authorization": f"Bearer {secret}"} if secret else {}

        offset = int((checkpoint or {}).get("offset", 0))
        items: list[RawDiscoveryItem] = []
        degraded = False
        degraded_reason: str | None = None
        pages_fetched = 0

        while pages_fetched < max_pages:
            query = urlencode({"offset": offset, "limit": page_size})
            result = client.request("GET", f"{base_url}{path}", headers=headers, query=query,
                                    timeout_seconds=10.0)
            pages_fetched += 1
            if not result.success or result.status != 200:
                # A hard failure on the FIRST page means the source is
                # unreachable/rejecting us - that is a genuine run failure.
                # A failure on a LATER page means we degrade with what we
                # already have (SRS M5.2 §11 - fails open, never loses prior
                # evidence for a mid-sweep hiccup).
                if pages_fetched == 1:
                    raise IdentityError(
                        ErrorCode.DISCOVERY_SOURCE_UNREACHABLE,
                        f"HTTP_AGENT_REGISTRY source returned status={result.status} "
                        f"egress={result.egress_decision.reason}.",
                    )
                degraded, degraded_reason = True, f"page {pages_fetched} failed: status={result.status}"
                break

            body = self._parse_body(result.response_body_redacted)
            page_items = body.get("items") or []
            for raw in page_items:
                external_id = str(raw.get("id"))
                items.append(RawDiscoveryItem(external_identifier=external_id, payload=dict(raw)))
                if len(items) >= _MAX_ITEMS_PER_FETCH:
                    return DiscoveryFetchResult(items=tuple(items), next_checkpoint={"offset": offset},
                                                complete=False, degraded=True,
                                                degraded_reason="absolute item bound reached")

            next_offset = body.get("next_offset")
            if next_offset is None or not page_items:
                return DiscoveryFetchResult(items=tuple(items), next_checkpoint={},
                                            complete=True, degraded=degraded, degraded_reason=degraded_reason)
            offset = int(next_offset)

        # max_pages reached with more pages available - a bounded, honest
        # partial fetch, resumable from the checkpoint on the next sweep.
        return DiscoveryFetchResult(items=tuple(items), next_checkpoint={"offset": offset},
                                    complete=False, degraded=True,
                                    degraded_reason=degraded_reason or "max_pages reached")

    @staticmethod
    def _parse_body(raw: bytes | dict | None) -> dict:
        """``GovernedHttpClient``/``execute_http_tool`` never parses JSON for
        the caller -- ``response_body_redacted`` is always raw ``bytes``
        (the ``dict`` union in its own type hint applies to other callers,
        not this path). Malformed JSON is treated as an empty page rather
        than raising -- the caller's own per-page failure handling (hard
        failure on page 1, degrade thereafter) already covers "this source
        sent us garbage"."""
        if isinstance(raw, dict):
            return raw
        if not raw:
            return {}
        try:
            parsed = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return {}
        return parsed if isinstance(parsed, dict) else {}

    def normalize(self, item: RawDiscoveryItem) -> NormalizedObservation:
        raw = item.payload
        return NormalizedObservation(
            external_identifier=item.external_identifier,
            name=str(raw.get("name") or item.external_identifier),
            agent_type=str(raw.get("agent_type") or "ASSISTANT"),
            origin_provider=str(raw.get("origin_provider") or ADAPTER_KEY),
            description=raw.get("description"),
            # The reference source is treated as authoritative for its own
            # inventory - confidence 1.00. A future vendor adapter reporting
            # a heuristic/derived listing would report a lower, still
            # deterministic, source-class-derived number here.
            confidence=Decimal("1.00"),
            raw=raw,
        )
