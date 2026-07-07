"""TokenService — create / decode / validate access tokens (SRS §6, §7, §16).

Access tokens are short-lived (15 min) and carry the full identity claim set so
the authorization layer can act without a database round-trip. Signing reuses
the platform JWT secret/algorithm.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from jose import ExpiredSignatureError, JWTError, jwt
from sqlalchemy.orm import Session

from app.core.config import settings
from app.identity.auth.context import IdentityContext
from app.identity.errors import ErrorCode, IdentityError

ACCESS_TOKEN_TYPE = "access"


class TokenService:
    def __init__(self, db: Session | None = None) -> None:
        # db is used for revocation checks once the token_revocations table lands
        # (Part 4.2.2). Kept optional so the service is usable stateless today.
        self.db = db

    def create_access_token(
        self,
        context: IdentityContext,
        *,
        ttl_seconds: int | None = None,
        jti: str | None = None,
    ) -> str:
        now = datetime.now(timezone.utc)
        ttl = ttl_seconds or settings.AUTH_ACCESS_TOKEN_TTL_SECONDS
        payload: dict[str, Any] = {
            "sub": context.identity_id,
            "identity_id": context.identity_id,
            "identity_type": context.identity_type,
            "organization_id": context.organization_id,
            "roles": context.roles,
            "permissions": context.permissions,
            "scopes": context.scopes,
            "session_id": context.session_id,
            "credential_id": context.credential_id,
            "auth_method": context.auth_method,
            "assurance_level": context.assurance_level,
            "amr": context.amr,
            "mfa_pending": context.mfa_pending,
            "token_type": ACCESS_TOKEN_TYPE,
            "iss": settings.JWT_ISSUER,
            "aud": settings.JWT_AUDIENCE,
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(seconds=ttl)).timestamp()),
            "jti": jti or f"tok_{uuid.uuid4().hex}",
        }
        return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)

    def decode(self, token: str) -> dict[str, Any]:
        """Decode + validate signature, expiry, issuer and audience."""
        try:
            return jwt.decode(
                token,
                settings.JWT_SECRET_KEY,
                algorithms=[settings.JWT_ALGORITHM],
                audience=settings.JWT_AUDIENCE,
                issuer=settings.JWT_ISSUER,
            )
        except ExpiredSignatureError as exc:
            raise IdentityError(ErrorCode.TOKEN_EXPIRED, "Access token has expired.") from exc
        except JWTError as exc:
            raise IdentityError(ErrorCode.INVALID_CREDENTIALS, "Invalid access token.") from exc

    def validate_access_token(self, token: str) -> dict[str, Any]:
        """Full validation: claims + token type + revocation."""
        claims = self.decode(token)
        if claims.get("token_type") != ACCESS_TOKEN_TYPE:
            raise IdentityError(ErrorCode.INVALID_CREDENTIALS, "Not an access token.")
        if self.is_revoked(claims.get("jti")):
            raise IdentityError(ErrorCode.TOKEN_REVOKED, "This token has been revoked.")
        return claims

    def is_revoked(self, jti: str | None) -> bool:
        """Revocation check. The ``token_revocations`` table lands in Part 4.2.2;
        until then no access token is individually revoked (sessions/refresh
        tokens are revoked instead)."""
        return False
