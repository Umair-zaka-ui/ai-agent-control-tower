"""Phase 5.7a.5 SRS ACT-MDL-FR-080 — application-level encryption for
per-organization provider credentials.

Fernet (AES-128-CBC + HMAC-SHA256, authenticated symmetric encryption) via
the ``cryptography`` package already vendored transitively (``python-jose
[cryptography]``, see ``requirements.txt``) — no new dependency added.

**Key provenance.** The key is read from ``settings.MODEL_CREDENTIAL_
ENCRYPTION_KEY`` (a base64 urlsafe 32-byte Fernet key) if configured;
otherwise one is auto-generated and persisted to ``settings.MODEL_
CREDENTIAL_ENCRYPTION_KEY_PATH`` (default ``./.keys/model_credentials.
key``, gitignored — same ``.keys/`` directory Phase 5.2.4's
``LocalKeyProvider`` already uses for signing keys). This is the identical
dev-convenience-with-a-loud-warning pattern that module already
established, deliberately reused rather than inventing a second one.

**Known deviation (mirrors ACT-VER-NFR-002, Phase 5.2.4's own recorded
deviation)**: a platform-held symmetric key necessarily enters process
memory to encrypt/decrypt — there is no way to avoid that without an
external KMS/HSM performing the operation server-side. Accepted
pre-production; closes when Milestone 13 lands external KMS/vault
integration, the same closure condition 5.2.4 recorded for its own local
signing provider. Do not build that integration here.
"""

from __future__ import annotations

import logging
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings
from app.identity.errors import ErrorCode, IdentityError

logger = logging.getLogger(__name__)

_cached_fernet: Fernet | None = None


def _load_or_generate_key() -> bytes:
    if settings.MODEL_CREDENTIAL_ENCRYPTION_KEY:
        return settings.MODEL_CREDENTIAL_ENCRYPTION_KEY.encode("utf-8")

    path = Path(settings.MODEL_CREDENTIAL_ENCRYPTION_KEY_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        return path.read_bytes()

    logger.warning(
        "Generating a new local Fernet key for provider-credential encryption at %s -- this is a "
        "development convenience, NOT production-grade key management. Production deployments must "
        "set MODEL_CREDENTIAL_ENCRYPTION_KEY explicitly (and eventually an external KMS/vault -- "
        "see Milestone 13).",
        path,
    )
    key = Fernet.generate_key()
    path.write_bytes(key)
    return key


def _fernet() -> Fernet:
    global _cached_fernet
    if _cached_fernet is None:
        _cached_fernet = Fernet(_load_or_generate_key())
    return _cached_fernet


def reset_cached_key() -> None:
    """Test-only — forces the next ``encrypt_secret``/``decrypt_secret``
    call to re-read (or re-generate) the key, so a test can point
    ``MODEL_CREDENTIAL_ENCRYPTION_KEY``/``_PATH`` at a fresh value and
    actually exercise that path rather than reusing whatever this process
    already cached."""
    global _cached_fernet
    _cached_fernet = None


def encrypt_secret(plaintext: str) -> str:
    """Returns a Fernet token (ASCII, safe to store in a TEXT column) —
    never the plaintext itself."""
    return _fernet().encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt_secret(ciphertext: str) -> str:
    """The only function in this codebase that turns a stored provider
    credential back into plaintext. Callers must never assign the result
    onto a persisted model or log it — see ``ProviderCredentialService.
    resolve_secret``."""
    try:
        return _fernet().decrypt(ciphertext.encode("ascii")).decode("utf-8")
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
