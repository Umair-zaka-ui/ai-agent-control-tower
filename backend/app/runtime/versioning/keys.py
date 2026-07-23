"""Phase 5.2.4 SRS ACT-VER-FR-060..071 — signing key lifecycle.

``SigningKeyService`` is the database record of what a ``SigningProvider``
actually holds (on disk, or later in a vault) — it never touches key
material itself; it calls into the provider (via
``signing/registry.py::get_signing_provider``) for every cryptographic
operation and only tracks metadata here: which key/version is current, when
a version was retired, and revocation status. Direct SQLAlchemy queries, no
repository layer — matching the runtime domain convention (REPO_STATE §7).
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.identity.errors import ErrorCode, IdentityError
from app.models.runtime import AgentVersionSignature, SigningKey, SigningKeyVersion
from app.runtime.versioning.signing.registry import get_signing_provider


def _now() -> datetime:
    return datetime.now(timezone.utc)


class SigningKeyService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.provider = get_signing_provider()

    def get_or_404(self, key_id: str) -> SigningKey:
        key = self.db.execute(select(SigningKey).where(SigningKey.key_id == key_id)).scalar_one_or_none()
        if key is None:
            raise IdentityError(ErrorCode.SIGNING_KEY_NOT_FOUND, f"Signing key '{key_id}' not found.")
        return key

    def ensure_key(self, key_id: str) -> SigningKey:
        """Get-or-create the DB record for ``key_id``, generating the
        underlying keypair via the provider (a no-op if it already exists)
        on first use."""
        key = self.db.execute(select(SigningKey).where(SigningKey.key_id == key_id)).scalar_one_or_none()
        if key is not None:
            return key
        version = self.provider.ensure_key(key_id)
        public_key_pem = self.provider.get_public_key(key_id, version).decode("utf-8")
        key = SigningKey(key_id=key_id, provider="LOCAL", algorithm="ED25519", current_version=version,
                         status="ACTIVE", public_key_pem=public_key_pem)
        self.db.add(key)
        self.db.flush()
        self.db.add(SigningKeyVersion(signing_key_id=key.id, version=version, public_key_pem=public_key_pem))
        self.db.commit()
        self.db.refresh(key)
        return key

    def list(self) -> list[SigningKey]:
        return list(self.db.execute(select(SigningKey).order_by(SigningKey.key_id)).scalars())

    def rotate(self, key_id: str) -> SigningKey:
        """Operates only on a key that already exists — unlike
        ``ensure_key`` (the internal, lazy first-use path ``build_and_sign``
        calls), an explicit admin action against an unrecognized
        ``key_id`` must 404, not silently provision a new key nobody asked
        for."""
        key = self.get_or_404(key_id)
        if key.status == "REVOKED":
            raise IdentityError(ErrorCode.SIGNING_KEY_REVOKED,
                                f"Signing key '{key_id}' is revoked and cannot be rotated.")
        result = self.provider.rotate(key_id)
        previous = self.db.execute(
            select(SigningKeyVersion).where(SigningKeyVersion.signing_key_id == key.id,
                                            SigningKeyVersion.version == result.previous_version)
        ).scalar_one_or_none()
        if previous is not None:
            previous.retired_at = _now()
        self.db.add(SigningKeyVersion(signing_key_id=key.id, version=result.new_version,
                                      public_key_pem=result.public_key_pem.decode("utf-8")))
        key.current_version = result.new_version
        key.public_key_pem = result.public_key_pem.decode("utf-8")
        key.status = "ACTIVE"
        self.db.commit()
        self.db.refresh(key)
        return key

    def revoke(self, key_id: str, *, reason: str | None = None) -> SigningKey:
        """§6 "Key revocation" — marks every affected signature's
        ``verification_status`` as ``KEY_REVOKED`` without altering the
        version record or the signature bytes themselves (``ACT-VER-
        FR-066``): the historical fact that it was signed remains true,
        only its current trust status changes."""
        key = self.get_or_404(key_id)
        key.status = "REVOKED"
        key.revoked_at = _now()
        key.revocation_reason = reason
        signatures = self.db.execute(
            select(AgentVersionSignature).where(AgentVersionSignature.signing_key_id == key.id)
        ).scalars()
        for signature in signatures:
            signature.verification_status = "KEY_REVOKED"
        self.db.commit()
        self.db.refresh(key)
        return key
