"""Phase M4.11 — key-material integrity.

One tiny table, ``key_material_canary``. Each row is a **verifier**: a known
constant plaintext encrypted with a specific key. On startup the platform
decrypts the row for the active key's fingerprint; if it does not come back
equal to the constant, the key is wrong — and the platform fails loud
instead of encrypting new data under a key that cannot read the old data
(M4.11-FR-004, AC-02).

Why a dedicated table rather than an existing config store: there is no
key/value platform-settings table in this schema, and a verifier ciphertext
does not belong on any domain table. The table is additive and reversible
(migration ``0052``), and it changes no decrypt behaviour for any existing
row — an install that never writes a canary simply falls back to
trial-decrypting real ciphertext (see ``app/security/canary.py``).

The row holds **no key and no secret** — only a ciphertext of a public
constant and a non-secret fingerprint.
"""

from __future__ import annotations

from sqlalchemy import String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class KeyMaterialCanary(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "key_material_canary"
    __table_args__ = (
        UniqueConstraint("purpose", "key_fingerprint", name="uq_key_material_canary_purpose_fp"),
    )

    #: which key this verifies — e.g. "MODEL_CREDENTIAL_ENCRYPTION"
    purpose: Mapped[str] = mapped_column(String(64), nullable=False)
    #: non-secret domain-separated hash prefix of the key (see encryption_provider.key_fingerprint)
    key_fingerprint: Mapped[str] = mapped_column(String(32), nullable=False)
    #: Fernet token over the public constant KEY_CANARY_PLAINTEXT
    verifier: Mapped[str] = mapped_column(Text, nullable=False)
    #: informational — which provider produced/holds the key
    key_provider: Mapped[str] = mapped_column(String(32), nullable=False, default="LOCAL")

    def __repr__(self) -> str:  # pragma: no cover - structural safety net
        return (
            f"<KeyMaterialCanary purpose={self.purpose} fingerprint={self.key_fingerprint} "
            f"provider={self.key_provider}>"
        )
