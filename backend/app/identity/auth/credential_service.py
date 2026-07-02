"""CredentialService — verify secrets and credential status (SRS §11, §16).

Single place for password / API-key / client-secret verification, so no other
service reaches for crypto primitives. Never stores or logs plaintext.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.core.security import verify_password
from app.identity.models.enums import IdentityStatus
from app.identity.security.passwords import verify_secret


class CredentialService:
    @staticmethod
    def verify_password(plaintext: str, password_hash: str) -> bool:
        return verify_password(plaintext, password_hash)

    @staticmethod
    def verify_api_key(plaintext: str, key_hash: str) -> bool:
        return verify_secret(plaintext, key_hash)

    @staticmethod
    def verify_client_secret(plaintext: str, secret_hash: str) -> bool:
        return verify_secret(plaintext, secret_hash)

    @staticmethod
    def is_active(status: str) -> bool:
        """Whether a credential/identity status permits authentication."""
        return status == IdentityStatus.ACTIVE.value

    @staticmethod
    def is_expired(expires_at: datetime | None) -> bool:
        if expires_at is None:
            return False
        return expires_at <= datetime.now(timezone.utc)
