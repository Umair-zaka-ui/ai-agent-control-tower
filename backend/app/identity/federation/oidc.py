"""Phase 2.3.1 SRS ACT-INT-FR-180, FR-181 — OIDC federated authentication:
authorization-code flow, JWKS-based ID-token verification.

**The security core is ``verify_id_token``.** It is pure — no HTTP, no
database — so it is exhaustively unit-testable against every bypass vector
with no live IdP required (discovery/JWKS fetching and the token-endpoint
exchange are separate, thin HTTP functions below it, isolated exactly the
way 2.2.x's connector `scope.py`/`executor.py` modules isolated their own
security-critical cores from their own I/O).

**Library choice: ``python-jose`` (already a platform dependency, used for
the platform's own JWT), used "with care," not hand-rolled.** The build
prompt explicitly names this as an acceptable choice given the caveat is
honored. The caveat, honored here specifically:

- **The accepted algorithm set is fixed by *this organization's own stored
  configuration*, never taken from the token's own ``alg`` header.**
  ``jose.jwt.decode(..., algorithms=[...])`` rejects a token whose header
  ``alg`` is not in that list *before* any cryptographic verification runs
  — this is what closes the classic "algorithm confusion" bypass (an
  attacker crafting an HS256 token and hoping a verifier that reads ``alg``
  from the token itself will use the RSA public key as an HMAC secret).
  Verified directly: ``test_oidc_bypass_prevention.py`` mints exactly that
  attack token and asserts it is rejected.
- **The signing key is resolved from the IdP's own JWKS by ``kid``, never
  trusted from the token.** A token whose ``kid`` matches no fetched key is
  rejected outright — there is no "try every key" fallback that could be
  tricked into matching an attacker-supplied key.
- **Issuer, audience, expiry, and (critically, since OIDC's own spec does
  not make this optional in practice) nonce are all explicitly checked.**
  A verified token whose ``nonce`` claim does not match the nonce this
  login flow itself generated is rejected — this is what defeats a replayed
  ID token from an earlier, unrelated login attempt.

Nothing in this module ever accepts "no signature verification" as an
option — there is no code path that returns claims without a passing
``jwt.decode`` call."""

from __future__ import annotations

import secrets
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

import httpx
from jose import jwt
from jose.exceptions import JOSEError

_DEFAULT_TIMEOUT_SECONDS = 5.0


class OidcVerificationError(Exception):
    """A validly-formed but untrustworthy ID token — bad/missing signature,
    expired, wrong issuer/audience, or a nonce mismatch — or a discovery/
    JWKS/token-endpoint call that failed. The message never includes the
    token itself, a claim value, or a client secret."""


@dataclass(frozen=True, slots=True)
class OidcClaims:
    """The verified, trustworthy identity claims extracted from an ID
    token — never constructed except by ``verify_id_token`` succeeding."""

    subject: str
    email: str | None
    name: str | None
    groups: tuple[str, ...] = field(default_factory=tuple)
    raw: Mapping[str, Any] = field(default_factory=dict)


def generate_state_nonce() -> tuple[str, str]:
    """A fresh, unguessable ``(state, nonce)`` pair for one login attempt.
    ``state`` defends the callback against CSRF; ``nonce`` is embedded in
    the authorization request and must reappear, unchanged, inside the
    ID token's own claims — a token minted for a different login attempt
    (a replay) carries a different, non-matching nonce."""
    return secrets.token_urlsafe(32), secrets.token_urlsafe(32)


def build_authorization_url(
    authorization_endpoint: str, *, client_id: str, redirect_uri: str, state: str, nonce: str,
    scope: str = "openid email profile",
) -> str:
    from urllib.parse import urlencode

    params = {
        "response_type": "code", "client_id": client_id, "redirect_uri": redirect_uri,
        "scope": scope, "state": state, "nonce": nonce,
    }
    return f"{authorization_endpoint}?{urlencode(params)}"


def fetch_discovery_document(issuer: str, *, timeout: float = _DEFAULT_TIMEOUT_SECONDS) -> dict[str, Any]:
    """``GET {issuer}/.well-known/openid-configuration``. Raises
    ``OidcVerificationError`` (never a raw ``httpx`` exception) on any
    network/parse failure, so a caller has one exception type to handle."""
    url = issuer.rstrip("/") + "/.well-known/openid-configuration"
    try:
        response = httpx.get(url, timeout=timeout)
        response.raise_for_status()
        return response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise OidcVerificationError("OIDC discovery document could not be retrieved") from exc


def fetch_jwks(jwks_uri: str, *, timeout: float = _DEFAULT_TIMEOUT_SECONDS) -> dict[str, Any]:
    try:
        response = httpx.get(jwks_uri, timeout=timeout)
        response.raise_for_status()
        return response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise OidcVerificationError("IdP JWKS could not be retrieved") from exc


def exchange_code_for_id_token(
    token_endpoint: str, *, code: str, client_id: str, client_secret: str | None, redirect_uri: str,
    timeout: float = _DEFAULT_TIMEOUT_SECONDS,
) -> str:
    """The authorization-code exchange (SP -> IdP token endpoint, never
    exposed to the browser). Returns the raw, still-unverified
    ``id_token`` string — the caller must still call ``verify_id_token``;
    this function's own success proves nothing about trust, only that the
    IdP issued *something*."""
    data = {
        "grant_type": "authorization_code", "code": code,
        "client_id": client_id, "redirect_uri": redirect_uri,
    }
    if client_secret:
        data["client_secret"] = client_secret
    try:
        response = httpx.post(token_endpoint, data=data, timeout=timeout)
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise OidcVerificationError("OIDC token endpoint exchange failed") from exc
    id_token = payload.get("id_token")
    if not id_token:
        raise OidcVerificationError("token endpoint response carried no id_token")
    return id_token


def _find_jwk(jwks: Mapping[str, Any], kid: str | None) -> dict[str, Any] | None:
    keys = jwks.get("keys") or []
    if kid is not None:
        for key in keys:
            if key.get("kid") == kid:
                return key
        return None
    # No kid in the token header (permitted by the spec when the IdP
    # publishes exactly one key) -- only ever accepted when unambiguous.
    return keys[0] if len(keys) == 1 else None


def verify_id_token(
    id_token: str, jwks: Mapping[str, Any], *, issuer: str, audience: str, nonce: str,
    algorithms: Sequence[str] = ("RS256",),
) -> OidcClaims:
    """The security core (see module docstring). Raises
    ``OidcVerificationError`` for any failure — signature, issuer,
    audience, expiry, or nonce — never returns partially-verified claims."""
    try:
        header = jwt.get_unverified_header(id_token)
    except JOSEError as exc:
        raise OidcVerificationError("malformed token header") from exc

    key = _find_jwk(jwks, header.get("kid"))
    if key is None:
        raise OidcVerificationError("no matching JWKS key for this token")

    try:
        claims = jwt.decode(
            id_token, key, algorithms=list(algorithms), audience=audience, issuer=issuer,
            options={"require_exp": True, "require_iat": True, "require_sub": True},
        )
    except JOSEError as exc:
        raise OidcVerificationError("token signature or claim verification failed") from exc

    if claims.get("nonce") != nonce:
        raise OidcVerificationError("nonce mismatch")

    groups = claims.get("groups") or claims.get("roles") or []
    if isinstance(groups, str):
        groups = [groups]

    return OidcClaims(
        subject=str(claims["sub"]),
        email=claims.get("email"),
        name=claims.get("name"),
        groups=tuple(str(g) for g in groups),
        raw=claims,
    )
