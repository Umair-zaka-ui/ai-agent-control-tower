"""Onboarding token generation (4.2.2.3.1 §9, §14).

Requirements, verbatim: cryptographically random · single use · expires · stored
hashed · cannot be reused · never exposes internal IDs.

A note on §9's example link, which shows ``/invite/eyJhbGciOi...`` — a JWT. We use an
**opaque random token**, not a JWT, and the two are not interchangeable here:

- A JWT is self-describing. Anyone holding the link can base64-decode it and read the
  organization id, role id and inviter. §9's own requirement is that the link "must
  never expose internal IDs", which a JWT does by construction.
- A JWT is *stateless*, which is the opposite of "single use". Revoking one before its
  expiry requires exactly the server-side record we are already keeping.

So the token is 32 bytes of ``secrets.token_urlsafe`` behind a short type prefix, and
the database row carries everything the link would otherwise have leaked.
"""

from __future__ import annotations

import secrets

from app.identity.security.passwords import hash_secret

INVITATION_PREFIX = "inv_"
VERIFICATION_PREFIX = "vrf_"
# Password-reset token (4.2.2.3.3). Same 256-bit entropy, distinct prefix so a
# leaked token cannot be replayed on the wrong endpoint.
RESET_PREFIX = "rst_"

# 32 bytes -> 43 url-safe characters. Well past any practical guessing attack, and
# short enough to survive a mail client's line wrapping.
_ENTROPY_BYTES = 32


def _generate(prefix: str) -> str:
    return f"{prefix}{secrets.token_urlsafe(_ENTROPY_BYTES)}"


def generate_invitation_token() -> tuple[str, str]:
    """Return ``(plaintext, hash)``. The plaintext is shown exactly once, in an email."""
    plaintext = _generate(INVITATION_PREFIX)
    return plaintext, hash_secret(plaintext)


def generate_verification_token() -> tuple[str, str]:
    plaintext = _generate(VERIFICATION_PREFIX)
    return plaintext, hash_secret(plaintext)


def generate_reset_token() -> tuple[str, str]:
    """Return ``(plaintext, hash)`` for a password-reset link (4.2.2.3.3 §6, §7)."""
    plaintext = _generate(RESET_PREFIX)
    return plaintext, hash_secret(plaintext)


def token_hash(plaintext: str) -> str:
    """Hash a presented token for lookup. Never compare plaintext in Python."""
    return hash_secret(plaintext)
