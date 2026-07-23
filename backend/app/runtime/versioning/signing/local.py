"""Phase 5.2.4 SRS ACT-VER-FR-060..071 — local, file-based Ed25519 signing.

Development/pre-production only. Keys live at ``settings.SIGNING_KEY_PATH``
(default ``./.keys/``, gitignored — see the repo-root ``.gitignore``), one
PEM file per key version: ``{key_id}.v{n}.pem`` (private) and
``{key_id}.v{n}.pub.pem`` (public). A keypair is auto-generated on first
use if absent, logging a clear warning that it is not production-grade.

**Known deviation (ACT-VER-NFR-002)**, recorded here and in
``docs/runtime/versioning.md`` under "Known Deviations": NFR-002 requires
private key material never enter process memory. A local file-based
provider cannot satisfy this by construction — signing necessarily reads
the private key bytes from disk into this process's memory for the
duration of the ``sign()`` call. This is accepted pre-production and closes
when Azure Key Vault (which signs server-side and never exposes key
material to the calling process) lands as a second ``SigningProvider``.
"""

from __future__ import annotations

import logging
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.core.config import settings
from app.identity.errors import ErrorCode, IdentityError
from app.runtime.versioning.signing.base import KeyRotationResult, SignatureResult, SigningProvider

logger = logging.getLogger(__name__)


class LocalKeyProvider(SigningProvider):
    def __init__(self, key_dir: str | None = None) -> None:
        self._key_dir = Path(key_dir or settings.SIGNING_KEY_PATH)
        self._key_dir.mkdir(parents=True, exist_ok=True)

    def _private_key_path(self, key_id: str, version: int) -> Path:
        return self._key_dir / f"{key_id}.v{version}.pem"

    def _public_key_path(self, key_id: str, version: int) -> Path:
        return self._key_dir / f"{key_id}.v{version}.pub.pem"

    def _current_version(self, key_id: str) -> int:
        # The glob also matches "{key_id}.v{n}.pub.pem" (public keys), which
        # must be excluded rather than parsed as a version number.
        versions = []
        for path in self._key_dir.glob(f"{key_id}.v*.pem"):
            if path.name.endswith(".pub.pem"):
                continue
            suffix = path.name[len(key_id) + 2:-4]  # "{key_id}.v{n}.pem" -> "{n}"
            if suffix.isdigit():
                versions.append(int(suffix))
        return max(versions) if versions else 0

    def ensure_key(self, key_id: str) -> int:
        """Auto-generates version 1 of ``key_id`` if no version exists yet.
        Returns the current (highest) version number either way."""
        current = self._current_version(key_id)
        if current > 0:
            return current
        logger.warning(
            "Generating a new local Ed25519 signing keypair for '%s' at %s -- this is a "
            "development convenience, NOT production-grade key management. Production "
            "deployments must configure Azure Key Vault (SIGNING_PROVIDER=AZURE_KEY_VAULT).",
            key_id, self._key_dir,
        )
        self._generate(key_id, 1)
        return 1

    def _generate(self, key_id: str, version: int) -> None:
        private_key = Ed25519PrivateKey.generate()
        private_bytes = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
        public_bytes = private_key.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        self._private_key_path(key_id, version).write_bytes(private_bytes)
        self._public_key_path(key_id, version).write_bytes(public_bytes)

    def sign(self, payload: bytes, key_id: str) -> SignatureResult:
        version = self.ensure_key(key_id)
        path = self._private_key_path(key_id, version)
        private_key = serialization.load_pem_private_key(path.read_bytes(), password=None)
        signature = private_key.sign(payload)
        return SignatureResult(signature=signature, key_id=key_id, key_version=version, algorithm="ED25519")

    def verify(self, payload: bytes, signature: bytes, key_id: str, key_version: int) -> bool:
        path = self._public_key_path(key_id, key_version)
        if not path.exists():
            raise IdentityError(ErrorCode.SIGNING_KEY_NOT_FOUND,
                                f"Public key for '{key_id}' version {key_version} not found.")
        public_key = serialization.load_pem_public_key(path.read_bytes())
        try:
            public_key.verify(signature, payload)
            return True
        except Exception:  # noqa: BLE001 — an invalid signature is a normal, expected outcome
            return False

    def get_public_key(self, key_id: str, key_version: int) -> bytes:
        path = self._public_key_path(key_id, key_version)
        if not path.exists():
            raise IdentityError(ErrorCode.SIGNING_KEY_NOT_FOUND,
                                f"Public key for '{key_id}' version {key_version} not found.")
        return path.read_bytes()

    def rotate(self, key_id: str) -> KeyRotationResult:
        previous = self.ensure_key(key_id)
        new_version = previous + 1
        self._generate(key_id, new_version)
        return KeyRotationResult(key_id=key_id, previous_version=previous, new_version=new_version,
                                 public_key_pem=self.get_public_key(key_id, new_version))
