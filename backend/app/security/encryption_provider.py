"""Phase M4.11 M4.11-FR-040/041 — the encryption-key provider seam.

This mirrors ``app/runtime/versioning/signing/base.py``'s ``SigningProvider``
deliberately: the code that needs the Fernet key
(``app/runtime/providers/credential_crypto.py``) asks a provider for it and
never reads a path directly, so moving the key into an external KMS/Vault
later is a configuration change (``settings.ENCRYPTION_KEY_PROVIDER``), not a
rewrite of every decrypt consumer.

**What crosses this interface.** Unlike ``SigningProvider`` — where private
key material must *never* cross the boundary because an HSM/Key Vault can
sign server-side — a symmetric Fernet key necessarily enters process memory
to encrypt/decrypt (there is no envelope operation that keeps it out; this
is the same accepted, documented deviation ``credential_crypto.py`` and
``signing/local.py`` already record). So ``get_key()`` returns key bytes.
A future ``VaultEncryptionKeyProvider`` would fetch them from the vault at
startup instead of reading a file; the seam is identical.

**The default provider does not generate a key.** ``LocalEncryptionKey
Provider.get_key()`` raises ``KeyMaterialError`` when no key is configured
or present — it never writes a replacement. Generating fresh key material is
``bootstrap()``, which is only ever called deliberately (see
``app/security/bootstrap.py``), never as a side effect of a missing file.
That inversion is the core M4.11 fix.

**No vendor lock-in.** This module imports no vendor SDK. Vendor adapters
(AWS KMS, HashiCorp Vault, Azure Key Vault) are documented as future work in
``docs/security/key-management.md`` and attach here exactly as a second
``SigningProvider`` would attach to that registry.
"""

from __future__ import annotations

import hashlib
import os
import stat
from abc import ABC, abstractmethod
from pathlib import Path

from cryptography.fernet import Fernet

from app.core.config import settings
from app.security.errors import KeyMaterialError

_FINGERPRINT_DOMAIN = b"act-encryption-key-fingerprint-v1\x00"


class ProviderUnavailableError(RuntimeError):
    """The key provider itself could not be reached (a future KMS/Vault
    outage). Phase M4.11a: this is deliberately **distinct** from "the key
    is missing" — a transient provider outage must fail loud and must never
    be mistaken for a new installation, and must never fall back to
    generating a key (M4.11a-FR-023)."""


def key_fingerprint(key: bytes) -> str:
    """A short, **non-secret** identifier for a key — a domain-separated
    SHA-256 prefix. Safe to print and to store in the clear (it is what an
    operator compares across a backup manifest and a running platform). A
    Fernet key is 32 bytes of CSPRNG output, so this is not a meaningful
    brute-force target regardless."""
    return hashlib.sha256(_FINGERPRINT_DOMAIN + key.strip()).hexdigest()[:16]


def _valid_fernet_key(raw: bytes) -> bytes:
    try:
        Fernet(raw)  # validates the base64 + length
    except (ValueError, TypeError) as exc:
        raise KeyMaterialError(
            "ENCRYPTION_KEY_INVALID",
            "the configured encryption key is not a valid urlsafe-base64 32-byte Fernet key",
            remediation=(
                "restore the correct key from the recovery archive, or set "
                "MODEL_CREDENTIAL_ENCRYPTION_KEY to a valid Fernet key"
            ),
        ) from exc
    return raw


class EncryptionKeyProvider(ABC):
    """Four methods, none of which generate key material as a side effect."""

    name: str = "ABSTRACT"

    def check_available(self) -> None:
        """Phase M4.11a — raise ``ProviderUnavailableError`` if the provider
        backend cannot be reached at all (distinct from "the key is
        missing"). Default: a no-op — a local file provider is always
        reachable. A KMS/Vault adapter overrides this to ping the vault."""
        return None

    @abstractmethod
    def is_present(self) -> bool:
        """True iff a key is configured/available *without* generating one."""

    @abstractmethod
    def get_key(self) -> bytes:
        """The active key used for new encryption. Raises ``KeyMaterialError``
        if none is available — never generates one."""

    @abstractmethod
    def fallback_keys(self) -> list[bytes]:
        """Previously-active keys retained so historical ciphertext still
        decrypts during/after a rotation. Newest-first, excluding the active
        key. Empty when no rotation is in progress."""

    @abstractmethod
    def bootstrap(self) -> bytes:
        """Deliberately provision fresh key material (new install only).
        Returns the new key. Never called implicitly."""

    def all_keys(self) -> list[bytes]:
        """Active key first, then fallbacks — the MultiFernet key ring."""
        return [self.get_key(), *self.fallback_keys()]

    def fingerprint(self) -> str:
        return key_fingerprint(self.get_key())

    def describe(self) -> dict:
        """Non-secret provider status for an operator / a startup log line."""
        present = self.is_present()
        return {
            "provider": self.name,
            "present": present,
            "active_fingerprint": self.fingerprint() if present else None,
            "fallback_fingerprints": [key_fingerprint(k) for k in self.fallback_keys()] if present else [],
        }


class LocalEncryptionKeyProvider(EncryptionKeyProvider):
    """Reads the key from ``settings.MODEL_CREDENTIAL_ENCRYPTION_KEY`` (an
    explicit value — the production-recommended path) or, failing that, from
    the local key file at ``settings.MODEL_CREDENTIAL_ENCRYPTION_KEY_PATH``
    (``./.keys/model_credentials.key`` by default, gitignored).

    Rotation fallbacks come from ``settings.MODEL_CREDENTIAL_ENCRYPTION_KEYS``
    (a list of prior keys). See ``docs/security/key-management.md``.
    """

    name = "LOCAL"

    def __init__(self, *, key_path: str | None = None) -> None:
        self._key_path = Path(key_path or settings.MODEL_CREDENTIAL_ENCRYPTION_KEY_PATH)

    # -- sources ---------------------------------------------------------- #
    def _configured_value(self) -> bytes | None:
        raw = settings.MODEL_CREDENTIAL_ENCRYPTION_KEY
        return raw.encode("utf-8") if raw else None

    def _file_value(self) -> bytes | None:
        if self._key_path.exists():
            return self._key_path.read_bytes().strip()
        return None

    # -- interface ------------------------------------------------------- #
    def check_available(self) -> None:
        """The local provider is reachable unless its configured key path is
        occupied by something that is not a readable file (a directory, a
        broken symlink) — that is a misconfiguration, not a missing key."""
        if self._configured_value() is not None:
            return
        if self._key_path.exists() and not self._key_path.is_file():
            raise ProviderUnavailableError(
                f"the encryption key path {self._key_path} exists but is not a readable file"
            )

    def is_present(self) -> bool:
        return self._configured_value() is not None or self._file_value() is not None

    def get_key(self) -> bytes:
        raw = self._configured_value() or self._file_value()
        if raw is None:
            raise KeyMaterialError(
                "ENCRYPTION_KEY_MISSING",
                (
                    "no provider-credential encryption key is configured and none is present at "
                    f"{self._key_path}"
                ),
                remediation=(
                    "restore backend/.keys/model_credentials.key from the recovery archive (see "
                    "docs/security/key-management.md), or — for a genuinely new installation with no "
                    "encrypted data — run `python -m app.security.keys bootstrap`"
                ),
            )
        return _valid_fernet_key(raw)

    def fallback_keys(self) -> list[bytes]:
        out: list[bytes] = []
        seen = {self.get_key().strip()} if self.is_present() else set()
        for raw in settings.MODEL_CREDENTIAL_ENCRYPTION_KEYS or []:
            b = raw.encode("utf-8").strip()
            if b and b not in seen:
                out.append(_valid_fernet_key(b))
                seen.add(b)
        return out

    def bootstrap(self) -> bytes:
        """Generate + persist a fresh key file with restrictive permissions.
        Refuses to clobber an existing file."""
        if self.is_present():
            raise KeyMaterialError(
                "ENCRYPTION_KEY_ALREADY_PRESENT",
                "an encryption key is already configured or present",
                remediation="bootstrap is for new installations only; the existing key must not be replaced",
            )
        self._key_path.parent.mkdir(parents=True, exist_ok=True)
        key = Fernet.generate_key()
        # Write 0600 where the platform supports it (no-op on plain Windows
        # filesystems, which have no POSIX mode bits — documented).
        fd = os.open(str(self._key_path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, stat.S_IRUSR | stat.S_IWUSR)
        try:
            os.write(fd, key)
        finally:
            os.close(fd)
        try:
            os.chmod(self._key_path, stat.S_IRUSR | stat.S_IWUSR)
        except OSError:  # pragma: no cover - platform dependent (Windows has no POSIX mode bits)
            pass
        return key


_REGISTRY: dict[str, type[EncryptionKeyProvider]] = {
    "LOCAL": LocalEncryptionKeyProvider,
}


def get_encryption_key_provider() -> EncryptionKeyProvider:
    provider_cls = _REGISTRY.get(settings.ENCRYPTION_KEY_PROVIDER)
    if provider_cls is None:
        raise KeyMaterialError(
            "ENCRYPTION_KEY_PROVIDER_UNKNOWN",
            f"encryption key provider '{settings.ENCRYPTION_KEY_PROVIDER}' is not configured in this build",
            remediation=f"set ENCRYPTION_KEY_PROVIDER to one of: {sorted(_REGISTRY)}",
        )
    return provider_cls()
