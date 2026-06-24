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

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


# --------------------------------------------------------------------------- #
# Passwords
# --------------------------------------------------------------------------- #
def hash_password(password: str) -> str:
    """Return a bcrypt hash for the given plaintext password."""
    return pwd_context.hash(password)


def verify_password(plain_password: str, password_hash: str) -> bool:
    """Verify a plaintext password against its stored bcrypt hash."""
    return pwd_context.verify(plain_password, password_hash)


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
    """Decode and validate a JWT. Returns the claims dict or ``None``."""
    try:
        return jwt.decode(
            token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM]
        )
    except JWTError:
        return None


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
