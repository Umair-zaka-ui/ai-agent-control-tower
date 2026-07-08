"""Request/response DTOs for the human-authentication endpoints (SRS §16, §17)."""

from __future__ import annotations

from pydantic import BaseModel, EmailStr, Field

from app.identity.schemas.identity import SessionRead
from app.schemas.user import UserRead

__all__ = [
    "LoginRequestDTO",
    "LoginResponse",
    "MfaVerifyRequestDTO",
    "RefreshRequestDTO",
    "TokenResponse",
    "MeResponse",
    "SessionRead",
]


class LoginRequestDTO(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=1, max_length=128)


class TokenResponse(BaseModel):
    """Issued on a completed login or refresh (SRS §6, §11 step 11)."""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int  # access-token lifetime in seconds
    user: UserRead | None = None


class LoginResponse(TokenResponse):
    """Login can also short-circuit into an MFA challenge (SRS §24)."""

    mfa_required: bool = False
    mfa_challenge_token: str | None = None


class MfaVerifyRequestDTO(BaseModel):
    challenge_token: str
    method: str = "TOTP"
    code: str = Field(..., min_length=1, max_length=16)


class RefreshRequestDTO(BaseModel):
    refresh_token: str = Field(..., min_length=1)


class MeResponse(BaseModel):
    """Current identity projection for GET /auth/me (SRS §16)."""

    user: UserRead
    roles: list[str] = Field(default_factory=list)
    permissions: list[str] = Field(default_factory=list)
    assurance_level: str
    session_id: str | None = None
