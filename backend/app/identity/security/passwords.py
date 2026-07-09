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
    """Raised when a password fails the complexity policy.

    ``code`` is the stable machine-readable reason (SRS §26); the string message is
    human-facing. The identity error handler maps this to a 422.
    """

    def __init__(self, message: str, *, code: str = "PASSWORD_POLICY_FAILED") -> None:
        super().__init__(message)
        self.code = code


def _is_common(lowered_password: str) -> bool:
    """Reject known-weak passwords even when "decorated" to pass the class checks.

    ``Password123!`` normalizes to ``password123`` (exact match); ``password123!AA``
    normalizes to ``password123aa`` which *begins with* the weak stem, so it is
    rejected too — appending two characters does not make a leaked password safe.

    Prefix matching (not contains-anywhere) is the deliberate line: people decorate
    a weak password by *appending*, and matching anywhere would reject an otherwise
    strong password that merely embeds a stem in the middle (e.g. ``T3st!Passw0rd#Ok``).
    """
    if lowered_password in COMMON_PASSWORDS:
        return True
    alnum = "".join(c for c in lowered_password if c.isalnum())
    if alnum in COMMON_PASSWORDS:
        return True
    return any(alnum.startswith(common) for common in COMMON_PASSWORDS)


# Ordered keyboard rows / common runs. A password should not lean on a straight
# line across the keyboard or a counting sequence — those are the first things a
# guesser tries and add no real entropy (SRS §7).
_SEQUENCES = (
    "abcdefghijklmnopqrstuvwxyz",
    "0123456789",
    "qwertyuiop",
    "asdfghjkl",
    "zxcvbnm",
)


def _has_run(lowered: str, *, length: int = 4) -> bool:
    """True if ``lowered`` contains a forward or reverse run of ``length`` along
    any known sequence — ``1234``, ``qwer``, ``dcba`` — anywhere in the string."""
    for seq in _SEQUENCES:
        reverse = seq[::-1]
        for source in (seq, reverse):
            for start in range(len(source) - length + 1):
                if source[start : start + length] in lowered:
                    return True
    return False


def _has_repeat(lowered: str, *, run: int = 4) -> bool:
    """True if a single character repeats ``run`` times in a row (``aaaa``)."""
    count = 1
    for prev, curr in zip(lowered, lowered[1:]):
        count = count + 1 if curr == prev else 1
        if count >= run:
            return True
    return False


def validate_password(
    password: str,
    *,
    email: str | None = None,
    username: str | None = None,
    name: str | None = None,
    organization_name: str | None = None,
) -> None:
    """Enforce the password policy (SRS §7, §9). Raises on the first failure.

    ``PasswordPolicyError.code`` carries the machine-readable reason so callers can
    map to the right §26 error code and audit event.
    """
    if len(password) < MIN_PASSWORD_LENGTH:
        raise PasswordPolicyError(
            f"Password must be at least {MIN_PASSWORD_LENGTH} characters.",
            code="PASSWORD_TOO_WEAK",
        )
    if len(password) > MAX_PASSWORD_LENGTH:
        raise PasswordPolicyError(
            f"Password must be at most {MAX_PASSWORD_LENGTH} characters."
        )
    if not any(c.isupper() for c in password):
        raise PasswordPolicyError("Password must contain an uppercase letter.", code="PASSWORD_TOO_WEAK")
    if not any(c.islower() for c in password):
        raise PasswordPolicyError("Password must contain a lowercase letter.", code="PASSWORD_TOO_WEAK")
    if not any(c.isdigit() for c in password):
        raise PasswordPolicyError("Password must contain a number.", code="PASSWORD_TOO_WEAK")
    if not any(c in SPECIAL_CHARS for c in password):
        raise PasswordPolicyError("Password must contain a special character.", code="PASSWORD_TOO_WEAK")

    lowered = password.lower()
    if _is_common(lowered):
        raise PasswordPolicyError(
            "Password is too common; choose a stronger password.", code="PASSWORD_TOO_WEAK"
        )
    if _has_run(lowered):
        raise PasswordPolicyError(
            "Password must not contain a keyboard or numeric sequence like '1234' or 'qwer'.",
            code="PASSWORD_TOO_WEAK",
        )
    if _has_repeat(lowered):
        raise PasswordPolicyError(
            "Password must not repeat the same character four or more times.",
            code="PASSWORD_TOO_WEAK",
        )

    # Must not contain the local-part of the email, the username, any part of the
    # person's name, or the organization name (SRS §7).
    identity_tokens: list[str] = []
    if username:
        identity_tokens.append(username)
    if email:
        identity_tokens.append(email.split("@")[0])
    if name:
        identity_tokens.extend(name.split())
    if organization_name:
        identity_tokens.extend(organization_name.split())
    for identity_value in identity_tokens:
        token = identity_value.strip().lower()
        if len(token) >= 3 and token in lowered:
            raise PasswordPolicyError(
                "Password must not contain your name, email, username or organization name.",
                code="PASSWORD_TOO_WEAK",
            )


def hash_user_password(
    password: str,
    *,
    email: str | None = None,
    username: str | None = None,
    name: str | None = None,
    organization_name: str | None = None,
) -> str:
    """Validate complexity, then argon2id-hash. The only sanctioned way to set
    a human password."""
    validate_password(
        password,
        email=email,
        username=username,
        name=name,
        organization_name=organization_name,
    )
    return core_security.hash_password(password)


# Strength levels, weakest → strongest (SRS §8). ``very_weak`` also covers the
# empty string so the UI has a single vocabulary.
STRENGTH_LEVELS = ("very_weak", "weak", "fair", "strong", "very_strong")


def estimate_strength(
    password: str,
    *,
    email: str | None = None,
    username: str | None = None,
    name: str | None = None,
    organization_name: str | None = None,
) -> dict[str, object]:
    """Score a password for display (SRS §8). Never raises.

    Returns ``{level, score (0-4), meets_policy, entropy_bits, feedback}``. This is
    advisory: :func:`validate_password` remains the only gate. The two share this
    module so the meter and the enforcer can never drift apart.
    """
    try:
        validate_password(
            password,
            email=email,
            username=username,
            name=name,
            organization_name=organization_name,
        )
        meets_policy = True
        feedback: str | None = None
    except PasswordPolicyError as exc:
        meets_policy = False
        feedback = str(exc)

    # Entropy estimate: log2(pool_size) * length. A coarse proxy for character
    # diversity and length combined — enough to rank, not a security claim.
    pool = 0
    if any(c.islower() for c in password):
        pool += 26
    if any(c.isupper() for c in password):
        pool += 26
    if any(c.isdigit() for c in password):
        pool += 10
    if any(c in SPECIAL_CHARS for c in password):
        pool += len(SPECIAL_CHARS)
    from math import log2

    entropy_bits = round(log2(pool) * len(password), 1) if pool and password else 0.0

    if not meets_policy:
        # A password that fails the policy is at best "weak"; a very short or empty
        # one is "very_weak". It can never be advertised as acceptable.
        level = "very_weak" if len(password) < MIN_PASSWORD_LENGTH else "weak"
    elif entropy_bits >= 90 and len(password) >= 16:
        level = "very_strong"
    elif entropy_bits >= 70:
        level = "strong"
    else:
        level = "fair"

    return {
        "level": level,
        "score": STRENGTH_LEVELS.index(level),
        "meets_policy": meets_policy,
        "entropy_bits": entropy_bits,
        "feedback": feedback,
    }


def policy_description() -> dict[str, object]:
    """The active policy, as data, for ``GET /password-policy`` and the UI (SRS §5).

    Sourced from the constants above so the endpoint and the enforcer never
    disagree. Expiration/history counts come from settings at the service layer.
    """
    return {
        "min_length": MIN_PASSWORD_LENGTH,
        "max_length": MAX_PASSWORD_LENGTH,
        "require_uppercase": True,
        "require_lowercase": True,
        "require_number": True,
        "require_special": True,
        "allow_spaces": True,
        "forbid_common": True,
        "forbid_sequences": True,
        "forbid_repeats": True,
        "forbid_identity": True,
    }


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
