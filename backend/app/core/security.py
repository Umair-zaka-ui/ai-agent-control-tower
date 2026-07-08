"""Security helpers: password hashing, JWT tokens and API key handling."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import settings

# argon2id is the primary scheme (SRS §11); bcrypt is retained so hashes minted
# before Part 4.2.2.1 still verify. ``deprecated="auto"`` lets us transparently
# re-hash a legacy bcrypt password to argon2id on next successful login.
pwd_context = CryptContext(schemes=["argon2", "bcrypt"], deprecated="auto")


# --------------------------------------------------------------------------- #
# Passwords
# --------------------------------------------------------------------------- #
def hash_password(password: str) -> str:
    """Return an argon2id hash for the given plaintext password."""
    return pwd_context.hash(password)


# An identity that authenticates elsewhere -- SSO, SCIM, or an account whose password
# has been deliberately removed -- still needs a value in the NOT NULL `password_hash`
# column. This sentinel can never be produced by a hash function (no `$` prefix), so no
# password can ever verify against it.
#
# `passlib` raises `UnknownHashError` on any non-hash, which would turn a wrong-password
# attempt against such an account into a 500. The guards below make it fail *closed*.
UNUSABLE_PASSWORD = "!no-password-login"


def is_unusable_password(password_hash: str) -> bool:
    """True when the stored value is a sentinel, not a hash. Such an identity has no
    password credential and must authenticate by some other means."""
    return not password_hash or password_hash.startswith("!")


def verify_password(plain_password: str, password_hash: str) -> bool:
    """Verify a plaintext password against its stored hash (argon2id or bcrypt).

    Returns ``False`` -- never raises -- for an identity with no password credential.
    """
    if is_unusable_password(password_hash):
        return False
    return pwd_context.verify(plain_password, password_hash)


def needs_rehash(password_hash: str) -> bool:
    """True when a stored hash uses a deprecated scheme (e.g. legacy bcrypt) and
    should be upgraded to argon2id after the next successful verification.

    A sentinel is not a hash and must never be "upgraded" into one.
    """
    if is_unusable_password(password_hash):
        return False
    return pwd_context.needs_update(password_hash)


# --------------------------------------------------------------------------- #
# JWT access tokens
# --------------------------------------------------------------------------- #
def create_access_token(
    subject: str,
    expires_minutes: int | None = None,
    extra_claims: dict[str, Any] | None = None,
) -> str:
    """Create a signed JWT access token.

    ``subject`` is stored in the standard ``sub`` claim (the user id).
    """
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=expires_minutes or settings.ACCESS_TOKEN_EXPIRE_MINUTES
    )
    payload: dict[str, Any] = {"sub": str(subject), "exp": expire}
    if extra_claims:
        payload.update(extra_claims)
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_access_token(token: str) -> dict[str, Any] | None:
    """Decode and validate a JWT. Returns the claims dict or ``None``.

    Accepts **both** token shapes the platform issues:

    - the legacy ``/auth/login`` token: ``{sub, exp}``
    - the Part 4.2.1+ ``/api/v1/auth`` token: adds ``iss``, ``aud``, ``token_type``,
      ``session_id``, ``mfa_pending``, …

    The SPA signs in on the new surface and then calls the legacy endpoints with
    that token. Before this accepted ``aud``, python-jose raised ``Invalid audience``
    and *every* dashboard request 401'd for real users.

    ``verify_aud`` is disabled in the decoder and the claim is checked here instead,
    because jose raises for a *missing* audience when one is expected — which would
    reject the legacy token. Absent claims are permitted; **present ones must match**.
    Never blanket-disable the check: a token minted for a different audience must not
    authenticate here.
    """
    try:
        claims = jwt.decode(
            token,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
            options={"verify_aud": False},
        )
    except JWTError:
        return None

    audience = claims.get("aud")
    if audience is not None and audience != settings.JWT_AUDIENCE:
        return None
    issuer = claims.get("iss")
    if issuer is not None and issuer != settings.JWT_ISSUER:
        return None

    # Only an *access* token authenticates a request. A refresh token is opaque and
    # never reaches here; an MFA challenge carries ``mfa_pending`` and proves only
    # the primary factor. Legacy tokens carry neither claim and are accepted.
    if claims.get("token_type") not in (None, "access"):
        return None
    if claims.get("mfa_pending"):
        return None

    return claims


# --------------------------------------------------------------------------- #
# Agent API keys (issued now, used for agent authentication in a later phase)
# --------------------------------------------------------------------------- #
def generate_api_key() -> str:
    """Generate a new opaque API key. The plaintext is shown to the caller once."""
    return f"act_{secrets.token_urlsafe(32)}"


def generate_agent_api_key() -> str:
    """Generate a Phase 2 agent API key, e.g. ``agt_live_xxxxxxxx``."""
    from app.core.config import settings

    return f"{settings.API_KEY_PREFIX}{secrets.token_urlsafe(32)}"


def hash_api_key(api_key: str) -> str:
    """Hash an API key for storage (SHA-256, never reversible)."""
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()


def verify_api_key(api_key: str, api_key_hash: str) -> bool:
    """Constant-time comparison of an API key against its stored hash."""
    return hmac.compare_digest(hash_api_key(api_key), api_key_hash)
