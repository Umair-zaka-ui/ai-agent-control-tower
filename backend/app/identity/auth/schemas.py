"""Request/response DTOs for the human-authentication endpoints (SRS §16, §17, §23)."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.schemas.user import UserRead

__all__ = [
    "LoginRequestDTO",
    "LoginResponse",
    "MfaVerifyRequestDTO",
    "RefreshRequestDTO",
    "TokenResponse",
    "MeResponse",
    "SessionRead",
    "SessionDetail",
    "RevokeSessionRequest",
    "LogoutRequest",
    "LogoutResponse",
    "DeviceRead",
    "SecurityEventRead",
    "SecurityEventPage",
]


class LoginRequestDTO(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=1, max_length=128)
    # "Remember me" extends the ABSOLUTE ceiling only; idle timeout still applies.
    remember_me: bool = False


class TokenResponse(BaseModel):
    """Issued on a completed login or refresh (SRS §6)."""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int  # access-token lifetime in seconds
    user: UserRead | None = None


class LoginResponse(TokenResponse):
    """Login can also short-circuit into an MFA challenge (SRS §24)."""

    mfa_required: bool = False
    mfa_challenge_token: str | None = None
    # Session posture surfaced to the client (SRS §15, §25).
    session_id: str | None = None
    security_score: int = 100
    is_new_device: bool = False
    # Idle-warning budget so the client can prompt before expiry (SRS §5).
    idle_timeout_seconds: int | None = None
    idle_warning_seconds: int | None = None
    # Part 4.2.2.3.2 §11/§13: the SPA must send the user to change their password
    # before any feature when true (expired, or an admin-issued temporary password).
    password_change_required: bool = False


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


# --------------------------------------------------------------------------- #
# Sessions (SRS §18, §19, §23)
# --------------------------------------------------------------------------- #
class SessionRead(BaseModel):
    """One row of the session list. ``is_current`` powers the "Current Device"
    badge and the confirm-before-revoke guard (SRS §19)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    status: str
    device_id: uuid.UUID | None = None
    device_name: str | None = None
    device_type: str | None = None
    browser: str | None = None
    browser_version: str | None = None
    operating_system: str | None = None
    ip_address: str | None = None
    country: str | None = None
    city: str | None = None
    login_method: str | None = None
    created_at: datetime
    last_seen_at: datetime | None = None
    last_activity_at: datetime | None = None
    idle_expires_at: datetime
    absolute_expires_at: datetime
    revoked_at: datetime | None = None
    revoked_reason: str | None = None
    security_score: int = 100
    is_trusted: bool = False
    # Derived, not stored.
    is_current: bool = False
    security_band: str | None = None


class SessionDetail(SessionRead):
    """GET /auth/sessions/{id} — adds the refresh-token family for forensics."""

    refresh_token_family_id: uuid.UUID
    user_agent: str | None = None


class RevokeSessionRequest(BaseModel):
    """Optional body for POST /auth/sessions/{id}/revoke."""

    reason: str | None = None


class LogoutRequest(BaseModel):
    """POST /auth/logout. ``all_devices`` implements "Logout all devices" (§24)."""

    all_devices: bool = False


class LogoutResponse(BaseModel):
    revoked_session_ids: list[uuid.UUID] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# Devices (SRS §13, §14, §23)
# --------------------------------------------------------------------------- #
class DeviceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    device_name: str | None = None
    device_type: str | None = None
    browser: str | None = None
    browser_version: str | None = None
    operating_system: str | None = None
    status: str
    last_ip: str | None = None
    last_seen_at: datetime | None = None
    created_at: datetime
    is_current: bool = False


# --------------------------------------------------------------------------- #
# Security-event audit stream (SRS §26; DoD §32 "…and audit user sessions")
# --------------------------------------------------------------------------- #
class SecurityEventRead(BaseModel):
    """One row of the security-event stream.

    ``meta`` is passed through verbatim: it is the forensic payload (revocation
    reason, acting administrator, security band, device id, token id) and the
    reader must see exactly what was recorded, not a lossy projection of it.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    event_type: str
    actor_type: str
    actor_id: uuid.UUID | None = None
    target_type: str | None = None
    target_id: uuid.UUID | None = None
    organization_id: uuid.UUID | None = None
    request_id: str | None = None
    correlation_id: str | None = None
    ip_address: str | None = None
    meta: dict = Field(default_factory=dict)
    created_at: datetime


class SecurityEventPage(BaseModel):
    """Paginated envelope. ``total`` is the count *after* filtering, so a UI can
    page without guessing."""

    items: list[SecurityEventRead] = Field(default_factory=list)
    total: int
    limit: int
    offset: int
