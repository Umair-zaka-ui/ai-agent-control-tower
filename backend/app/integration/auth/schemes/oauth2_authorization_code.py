"""Phase 2.1.2 SRS ACT-INT-FR-024 — OAuth2 authorization-code scheme.

**Built vs stubbed (stated plainly, per the build prompt's own
instruction):**

- **Built**: the stored client configuration
  (``client_id``/``client_secret``/``token_url``/``redirect_uri``), the
  authorization-URL construction helper
  (``ConnectorCredentialService.build_authorization_url``), the code→
  token exchange (``token_manager.exchange_authorization_code``, reached
  via ``GET``/``POST .../oauth/callback``), and — the part this
  sub-phase must actually deliver — refresh-and-apply: given a stored
  refresh token, ``token_manager.get_valid_access_token`` keeps a valid
  access token available and this scheme applies it, transparently, on
  every resolution.
- **Stubbed**: the interactive consent-redirect UI itself. This backend
  builds the authorization URL a browser *would* be sent to and exposes
  the callback that completes the exchange once a user has approved
  access at the external provider — but nothing in this sub-phase
  renders a page or performs the redirect. That is explicitly a
  front-end concern, out of scope here exactly as the build prompt
  allowed.

``required_fields()`` therefore names only what must be stored *before*
any code exchange happens (including ``authorize_url``, the endpoint a
browser would be redirected to for consent — needed only by
``build_authorization_url``, never by ``apply()``); ``refresh_token``
arrives later, via the callback, into ``connector_oauth_tokens`` — never
into this table."""

from __future__ import annotations

from typing import Any, Mapping

from app.integration.auth.base import AuthScheme, OutboundRequest
from app.integration.auth.schemes.bearer import apply_bearer


class OAuth2AuthorizationCodeScheme(AuthScheme):
    def required_fields(self) -> tuple[str, ...]:
        return ("client_id", "client_secret", "authorize_url", "token_url", "redirect_uri")

    def apply(self, request: OutboundRequest, credential: Mapping[str, Any]) -> OutboundRequest:
        return apply_bearer(request, str(credential["access_token"]))
