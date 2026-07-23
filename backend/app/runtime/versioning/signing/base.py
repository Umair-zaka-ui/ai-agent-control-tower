"""Phase 5.2.4 SRS ACT-VER-FR-060..071 — the signing provider contract.

Local keys are the only implementation today; Azure Key Vault comes at
deployment. The abstraction exists so that swap is a configuration change
(``settings.SIGNING_PROVIDER``, see ``registry.py``), not a rewrite.

**Critical constraint**: private key material must never cross this
interface. ``sign()`` takes bytes and returns a signature — never a key.
Nothing outside ``local.py`` may read a key file; nothing outside a future
Azure implementation may hold a Key Vault credential. If calling code ever
touches raw key material directly, the Azure swap becomes a rewrite, which
is the exact failure this abstraction exists to prevent.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class SignatureResult:
    """What ``sign()`` returns — a signature and the identity of the key
    that produced it. Never the key itself."""

    signature: bytes
    key_id: str
    key_version: int
    algorithm: str


@dataclass(frozen=True)
class KeyRotationResult:
    """What ``rotate()`` returns — the new public key and version numbers.
    Never the new private key."""

    key_id: str
    previous_version: int
    new_version: int
    public_key_pem: bytes


class SigningProvider(ABC):
    """Every concrete provider (local file-based, Azure Key Vault, ...)
    implements exactly this surface — four methods, none of which accept
    or return private key material."""

    @abstractmethod
    def sign(self, payload: bytes, key_id: str) -> SignatureResult:
        """Signs ``payload`` with the current version of ``key_id``.
        Auto-provisions the key (dev convenience) if it doesn't exist yet —
        see ``LocalKeyProvider.ensure_key``."""

    @abstractmethod
    def verify(self, payload: bytes, signature: bytes, key_id: str, key_version: int) -> bool:
        """Verifies ``signature`` over ``payload`` against the *public* key
        for ``key_id``/``key_version`` — must work for a rotated-out
        version too, since old signatures must stay verifiable."""

    @abstractmethod
    def get_public_key(self, key_id: str, key_version: int) -> bytes:
        """Returns the PEM-encoded public key for ``key_id``/``key_version``
        — including retired versions."""

    @abstractmethod
    def rotate(self, key_id: str) -> KeyRotationResult:
        """Generates a new key version for ``key_id`` and makes it current.
        The previous version's public key remains retrievable via
        ``get_public_key`` so signatures made with it still verify."""
