"""Phase 2.1.2 SRS ACT-INT-FR-021 — explicit authentication scheme registry.

Mirrors ``app/runtime/providers/registry.py``'s pattern exactly: explicit
registration, not directory-scanning discovery — greppable, and the
mechanical proof behind ``ACT-INT-FR-021`` ("adding a scheme requires no
connector/runtime change"). Every scheme gets registered once, at the
bottom of this module; nothing else in this codebase branches on a
scheme identifier string."""

from __future__ import annotations

from app.integration.auth.base import AuthScheme
from app.integration.auth.schemes.api_key import ApiKeyScheme
from app.integration.auth.schemes.basic import BasicAuthScheme
from app.integration.auth.schemes.bearer import BearerTokenScheme
from app.integration.auth.schemes.mtls import MTLSScheme
from app.integration.auth.schemes.oauth2_authorization_code import OAuth2AuthorizationCodeScheme
from app.integration.auth.schemes.oauth2_client_credentials import OAuth2ClientCredentialsScheme
from app.integration.errors import ConnectorAuthSchemeUnsupportedError

_REGISTRY: dict[str, type[AuthScheme]] = {}

# The two scheme identifiers whose stored credential bundle requires
# token_manager-mediated resolution (a fresh access_token merged in)
# before AuthScheme.apply() runs — every other scheme's stored bundle is
# already everything apply() needs.
OAUTH2_SCHEME_IDENTIFIERS = frozenset({"OAUTH2_CLIENT_CREDENTIALS", "OAUTH2_AUTHORIZATION_CODE"})


def register(identifier: str, scheme_cls: type[AuthScheme]) -> None:
    _REGISTRY[identifier.upper()] = scheme_cls


def resolve(identifier: str) -> AuthScheme:
    scheme_cls = _REGISTRY.get((identifier or "").upper())
    if scheme_cls is None:
        raise ConnectorAuthSchemeUnsupportedError(identifier)
    return scheme_cls()


def registered_identifiers() -> list[str]:
    return sorted(_REGISTRY)


register("API_KEY", ApiKeyScheme)
register("BEARER", BearerTokenScheme)
register("BASIC", BasicAuthScheme)
register("OAUTH2_CLIENT_CREDENTIALS", OAuth2ClientCredentialsScheme)
register("OAUTH2_AUTHORIZATION_CODE", OAuth2AuthorizationCodeScheme)
register("MTLS", MTLSScheme)
