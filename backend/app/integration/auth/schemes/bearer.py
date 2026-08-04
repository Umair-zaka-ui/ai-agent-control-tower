"""Phase 2.1.2 SRS ACT-INT-FR-020 — static bearer token scheme.

Also the scheme both OAuth2 schemes delegate their final header-
application step to (see ``apply_bearer`` below) — an OAuth2-resolved
access token is applied to a request exactly the same way a static
bearer token is; the only difference is what obtained the token value in
the first place."""

from __future__ import annotations

from typing import Any, Mapping

from app.integration.auth.base import AuthScheme, OutboundRequest


def apply_bearer(request: OutboundRequest, token: str) -> OutboundRequest:
    return request.with_headers(Authorization=f"Bearer {token}")


class BearerTokenScheme(AuthScheme):
    def required_fields(self) -> tuple[str, ...]:
        return ("token",)

    def apply(self, request: OutboundRequest, credential: Mapping[str, Any]) -> OutboundRequest:
        return apply_bearer(request, str(credential["token"]))
