"""Password policy + hashing/secret helpers (SRS §9, §11, §14).

**This module is the single source of truth for the password policy.** It lives
below ``app.identity.auth`` in the import graph (``credential_service`` and
``tokens.service`` import it at module scope), so the policy is defined here and
``app.identity.auth.PasswordService`` is a thin facade over it. Defining it the
other way round would create an import cycle.

Every path that sets a human password must go through :func:`hash_user_password`
so complexity is enforced exactly once, in one place. Never stores or logs
plaintext.
"""

from __future__ import annotations

import secrets

from app.core import security as core_security

MIN_PASSWORD_LENGTH = 12
MAX_PASSWORD_LENGTH = 128
SPECIAL_CHARS = set("!@#$%^&*()-_=+[]{};:,.<>?/|\\`~\"'")

# A small, high-signal blocklist. A production deployment layers a full
# breached-password corpus (e.g. HaveIBeenPwned k-anonymity) on top; the seam is
# ``_is_common`` so that swap is additive.
COMMON_PASSWORDS = frozenset(
    {
        "password",
        "password1",
        "password123",
        "password1234",
        "passw0rd",
        "12345678",
        "123456789",
        "1234567890",
        "welcome123",
        "qwerty123",
        "admin123",
        "letmein123",
        "iloveyou123",
        "changeme123",
        "abc12345",
        "administrator",
    }
)


class PasswordPolicyError(ValueError):
    """Raised when a password fails the complexity policy."""


def _is_common(lowered_password: str) -> bool:
    """Reject known-weak passwords even when "decorated" to pass the class
    checks — e.g. ``Password123!`` normalizes to ``password123``."""
    if lowered_password in COMMON_PASSWORDS:
        return True
    alnum = "".join(c for c in lowered_password if c.isalnum())
    return alnum in COMMON_PASSWORDS


def validate_password(
    password: str,
    *,
    email: str | None = None,
    username: str | None = None,
) -> None:
    """Enforce the password policy (SRS §9). Raises on the first failure."""
    if len(password) < MIN_PASSWORD_LENGTH:
        raise PasswordPolicyError(
            f"Password must be at least {MIN_PASSWORD_LENGTH} characters."
        )
    if len(password) > MAX_PASSWORD_LENGTH:
        raise PasswordPolicyError(
            f"Password must be at most {MAX_PASSWORD_LENGTH} characters."
        )
    if not any(c.isupper() for c in password):
        raise PasswordPolicyError("Password must contain an uppercase letter.")
    if not any(c.islower() for c in password):
        raise PasswordPolicyError("Password must contain a lowercase letter.")
    if not any(c.isdigit() for c in password):
        raise PasswordPolicyError("Password must contain a number.")
    if not any(c in SPECIAL_CHARS for c in password):
        raise PasswordPolicyError("Password must contain a special character.")

    lowered = password.lower()
    if _is_common(lowered):
        raise PasswordPolicyError("Password is too common; choose a stronger password.")

    # Must not contain the local-part of the email or the username.
    for identity_value in (username, (email.split("@")[0] if email else None)):
        if identity_value:
            token = identity_value.strip().lower()
            if len(token) >= 3 and token in lowered:
                raise PasswordPolicyError(
                    "Password must not contain your email or username."
                )


def hash_user_password(
    password: str,
    *,
    email: str | None = None,
    username: str | None = None,
) -> str:
    """Validate complexity, then argon2id-hash. The only sanctioned way to set
    a human password."""
    validate_password(password, email=email, username=username)
    return core_security.hash_password(password)


def needs_password_upgrade(password_hash: str) -> bool:
    """True when a verified hash should be re-hashed to argon2id."""
    return core_security.needs_rehash(password_hash)


def verify_user_password(plaintext: str, password_hash: str) -> bool:
    return core_security.verify_password(plaintext, password_hash)


def hash_secret(secret: str) -> str:
    """Hash a client secret / API key for storage (SHA-256)."""
    return core_security.hash_api_key(secret)


def verify_secret(secret: str, secret_hash: str) -> bool:
    return core_security.verify_api_key(secret, secret_hash)


def generate_client_secret() -> str:
    """Generate an opaque client secret (shown once)."""
    return f"sk_{secrets.token_urlsafe(32)}"
