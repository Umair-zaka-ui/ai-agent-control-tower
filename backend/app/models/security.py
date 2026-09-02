"""Phase M4.11 — key-material integrity; Phase M4.11a — the durable
bootstrap marker.

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

from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, String, Text, UniqueConstraint, func
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


class InstallationBootstrap(Base, UUIDPrimaryKeyMixin):
    """Phase M4.11a — the durable, positively-recorded fact that this
    installation has completed key bootstrap.

    Its **presence** is the authoritative EXISTING signal for
    ``detect_install_mode`` (M4.11a-FR-001). Absence of encrypted state is
    *not* a NEW signal — an established install can legitimately hold zero
    encrypted credential rows — so classification no longer infers NEW from
    "no ciphertext"; it requires this marker to be absent *and* no
    encrypted/signed state present.

    Platform-scoped, singular — this is the installation's identity, not
    tenant data. Exactly one row is possible: ``singleton`` is pinned true
    by a CHECK and made unique.

    Holds **only non-secret provenance** — a timestamp, the active key's
    non-secret fingerprint, the provider name, and a keyring schema tag.
    Never a key or a secret.
    """

    __tablename__ = "installation_bootstrap"
    __table_args__ = (
        CheckConstraint("singleton IS TRUE", name="ck_installation_bootstrap_singleton_true"),
        UniqueConstraint("singleton", name="uq_installation_bootstrap_singleton"),
    )

    singleton: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    bootstrapped_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    #: non-secret domain-separated hash prefix of the active encryption key at bootstrap time
    active_key_fingerprint: Mapped[str] = mapped_column(String(32), nullable=False)
    key_provider: Mapped[str] = mapped_column(String(32), nullable=False, default="LOCAL")
    keyring_schema_version: Mapped[str] = mapped_column(String(32), nullable=False, default="m4.11a/1")
    #: "bootstrap" (deliberate provision) | "backfill" (recorded at startup after verifying an existing key)
    recorded_via: Mapped[str] = mapped_column(String(16), nullable=False, default="bootstrap")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    def __repr__(self) -> str:  # pragma: no cover - structural safety net
        return (
            f"<InstallationBootstrap bootstrapped_at={self.bootstrapped_at} "
            f"fingerprint={self.active_key_fingerprint} via={self.recorded_via}>"
        )
