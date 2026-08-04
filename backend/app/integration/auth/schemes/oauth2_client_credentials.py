"""Phase 2.1.2 SRS ACT-INT-FR-024 — OAuth2 client-credentials scheme.

``required_fields()`` names the *stored* client configuration
(``client_id``/``client_secret``/``token_url``) — what
``ConnectorCredentialService.store()`` persists, encrypted. ``apply()``
itself does none of the token acquisition: by the time this method runs,
``ConnectorCredentialService.resolve_and_apply()`` has already called
``token_manager.get_valid_access_token()`` and merged a fresh
``access_token`` into the credential mapping passed in here — this
method just attaches it, identically to ``BearerTokenScheme``."""

from __future__ import annotations

from typing import Any, Mapping

from app.integration.auth.base import AuthScheme, OutboundRequest
from app.integration.auth.schemes.bearer import apply_bearer


class OAuth2ClientCredentialsScheme(AuthScheme):
    def required_fields(self) -> tuple[str, ...]:
        return ("client_id", "client_secret", "token_url")

    def apply(self, request: OutboundRequest, credential: Mapping[str, Any]) -> OutboundRequest:
        return apply_bearer(request, str(credential["access_token"]))
