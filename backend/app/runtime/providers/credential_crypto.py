"""Phase 5.7a.5 SRS ACT-MDL-FR-080 — application-level encryption for
per-organization provider credentials.

Fernet (AES-128-CBC + HMAC-SHA256, authenticated symmetric encryption) via
the ``cryptography`` package already vendored transitively (``python-jose
[cryptography]``, see ``requirements.txt``) — no new dependency added.

**Key provenance (Phase M4.11).** The key comes from an
``EncryptionKeyProvider`` (``app/security/encryption_provider.py``), not
from a path read inline here — the same seam shape as Phase 5.2.4's
``SigningProvider``, so an external KMS/Vault is a config change rather than
a rewrite. The default ``LocalEncryptionKeyProvider`` reads
``settings.MODEL_CREDENTIAL_ENCRYPTION_KEY`` or the local key file at
``settings.MODEL_CREDENTIAL_ENCRYPTION_KEY_PATH``.

**This module no longer generates a key when one is absent.** A missing key
on an established installation is lost key material — it fails loud
(``KeyMaterialError``) rather than silently minting a replacement that
would leave every pre-existing ciphertext undecryptable. Deliberate
provisioning for a genuine new install is ``app/security/bootstrap.py``.
The fail-loud check runs at startup (``app.main`` lifespan) via
``app/security/key_integrity.py``.

**Rotation.** ``_keyring()`` is a ``MultiFernet`` over the active key plus
``settings.MODEL_CREDENTIAL_ENCRYPTION_KEYS`` (retained prior keys) — new
data encrypts under the active key, historical data still decrypts under a
prior one. See ``docs/security/key-management.md``.

**Known deviation (mirrors ACT-VER-NFR-002)**: a platform-held symmetric
key necessarily enters process memory to encrypt/decrypt — unavoidable
without an external KMS/HSM performing the operation server-side. Accepted
pre-production; the provider seam above is what makes that swap a
configuration change.
"""

from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

from app.identity.errors import ErrorCode, IdentityError
from app.security.encryption_provider import get_encryption_key_provider

_cached_keyring: MultiFernet | None = None


def _keyring() -> MultiFernet:
    global _cached_keyring
    if _cached_keyring is None:
        provider = get_encryption_key_provider()
        _cached_keyring = MultiFernet([Fernet(k) for k in provider.all_keys()])
    return _cached_keyring


def reset_cached_key() -> None:
    """Test-only — forces the next ``encrypt_secret``/``decrypt_secret``
    call to re-resolve the key ring, so a test can point the provider's
    settings at a fresh value and actually exercise that path rather than
    reusing whatever this process already cached."""
    global _cached_keyring
    _cached_keyring = None


def encrypt_secret(plaintext: str) -> str:
    """Returns a Fernet token (ASCII, safe to store in a TEXT column) —
    never the plaintext itself. Encrypts under the active key."""
    return _keyring().encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt_secret(ciphertext: str) -> str:
    """The only function in this codebase that turns a stored provider
    credential back into plaintext. Callers must never assign the result
    onto a persisted model or log it — see ``ProviderCredentialService.
    resolve_secret``. Decrypts under the active key or any retained prior
    key (rotation)."""
    try:
        return _keyring().decrypt(ciphertext.encode("ascii")).decode("utf-8")
    except InvalidToken as exc:
        raise IdentityError(
            ErrorCode.INTERNAL_ERROR,
            "Stored provider credential could not be decrypted -- the encryption key may have changed.",
        ) from exc


def mask_hint(plaintext: str) -> str:
    """The last four characters only — enough for a human to recognize
    "yes, that's the key I set," never enough to reconstruct it
    (``ACT-MDL-FR-081``)."""
    return plaintext[-4:] if len(plaintext) >= 4 else "*" * len(plaintext)
