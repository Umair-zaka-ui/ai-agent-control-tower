"""Password policy + hashing/secret helpers (SRS §9 security).

Thin wrappers over ``app.core.security`` so identity code has a single, policy-
aware entry point and never reaches for crypto primitives directly.
"""

from __future__ import annotations

import secrets

from app.core import security as core_security

MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_LENGTH = 128


class PasswordPolicyError(ValueError):
    """Raised when a password fails the policy."""


def validate_password(password: str) -> None:
    """Enforce the minimum password policy. Raises ``PasswordPolicyError``."""
    if len(password) < MIN_PASSWORD_LENGTH:
        raise PasswordPolicyError(
            f"Password must be at least {MIN_PASSWORD_LENGTH} characters."
        )
    if len(password) > MAX_PASSWORD_LENGTH:
        raise PasswordPolicyError(
            f"Password must be at most {MAX_PASSWORD_LENGTH} characters."
        )
    if password.lower() == password or password.upper() == password:
        raise PasswordPolicyError("Password must mix upper and lower case characters.")
    if not any(c.isdigit() for c in password):
        raise PasswordPolicyError("Password must contain at least one digit.")


def hash_user_password(password: str) -> str:
    """Validate then bcrypt-hash a user password."""
    validate_password(password)
    return core_security.hash_password(password)


def hash_secret(secret: str) -> str:
    """Hash a client secret / API key for storage (SHA-256)."""
    return core_security.hash_api_key(secret)


def verify_secret(secret: str, secret_hash: str) -> bool:
    return core_security.verify_api_key(secret, secret_hash)


def generate_client_secret() -> str:
    """Generate an opaque client secret (shown once)."""
    return f"sk_{secrets.token_urlsafe(32)}"
