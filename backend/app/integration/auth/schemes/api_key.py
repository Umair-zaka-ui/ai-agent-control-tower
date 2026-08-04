"""Phase 2.1.2 SRS ACT-INT-FR-020 — static API key scheme.

The credential bundle carries the key value and, optionally, which
header it goes in (``header_name``, defaulting to ``X-API-Key``) — a
connector author who needs a differently-named header declares it in
the stored bundle, not in a new scheme subclass."""

from __future__ import annotations

from typing import Any, Mapping

from app.integration.auth.base import AuthScheme, OutboundRequest

DEFAULT_HEADER_NAME = "X-API-Key"


class ApiKeyScheme(AuthScheme):
    def required_fields(self) -> tuple[str, ...]:
        return ("api_key",)

    def apply(self, request: OutboundRequest, credential: Mapping[str, Any]) -> OutboundRequest:
        header_name = str(credential.get("header_name") or DEFAULT_HEADER_NAME)
        return request.with_headers(**{header_name: str(credential["api_key"])})
