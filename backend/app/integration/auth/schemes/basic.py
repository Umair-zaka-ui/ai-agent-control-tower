"""Phase 2.1.2 SRS ACT-INT-FR-020 — HTTP basic authentication scheme."""

from __future__ import annotations

import base64
from typing import Any, Mapping

from app.integration.auth.base import AuthScheme, OutboundRequest


class BasicAuthScheme(AuthScheme):
    def required_fields(self) -> tuple[str, ...]:
        return ("username", "password")

    def apply(self, request: OutboundRequest, credential: Mapping[str, Any]) -> OutboundRequest:
        raw = f"{credential['username']}:{credential['password']}".encode("utf-8")
        encoded = base64.b64encode(raw).decode("ascii")
        return request.with_headers(Authorization=f"Basic {encoded}")
