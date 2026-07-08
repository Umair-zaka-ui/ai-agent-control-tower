"""PasswordService — hash, verify and enforce password complexity (SRS §9, §11, §14).

The authentication layer's entry point for human-password handling. The policy
itself is defined once in :mod:`app.identity.security.passwords` (which sits
below this package in the import graph); this class is a thin, stable facade so
callers in the auth layer never reach for crypto primitives directly.

Never stores or logs plaintext.
"""

from __future__ import annotations

from app.core.security import needs_rehash, verify_password
from app.identity.security.passwords import (
    COMMON_PASSWORDS,
    MAX_PASSWORD_LENGTH,
    MIN_PASSWORD_LENGTH,
    SPECIAL_CHARS,
    PasswordPolicyError,
    hash_user_password,
    validate_password,
)

# Backwards-compatible aliases for the names this module used to define itself.
MIN_LENGTH = MIN_PASSWORD_LENGTH
MAX_LENGTH = MAX_PASSWORD_LENGTH

__all__ = [
    "COMMON_PASSWORDS",
    "MAX_LENGTH",
    "MIN_LENGTH",
    "SPECIAL_CHARS",
    "PasswordPolicyError",
    "PasswordService",
]


class PasswordService:
    """Stateless helper; instantiate freely or use the classmethods directly."""

    # ----------------------------- hashing ----------------------------- #
    @staticmethod
    def hash(
        password: str,
        *,
        email: str | None = None,
        username: str | None = None,
    ) -> str:
        """Validate complexity, then argon2id-hash."""
        return hash_user_password(password, email=email, username=username)

    @staticmethod
    def verify(plaintext: str, password_hash: str) -> bool:
        return verify_password(plaintext, password_hash)

    @staticmethod
    def needs_upgrade(password_hash: str) -> bool:
        """True when a verified hash should be re-hashed to argon2id."""
        return needs_rehash(password_hash)

    # --------------------------- complexity ----------------------------- #
    @staticmethod
    def validate_complexity(
        password: str,
        *,
        email: str | None = None,
        username: str | None = None,
    ) -> None:
        """Enforce SRS §9. Raises :class:`PasswordPolicyError` on the first failure."""
        validate_password(password, email=email, username=username)
