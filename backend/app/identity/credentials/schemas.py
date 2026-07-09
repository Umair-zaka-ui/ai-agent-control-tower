"""Request/response DTOs for the credential-management API (SRS §22)."""

from __future__ import annotations

import uuid

from pydantic import BaseModel, Field


# --------------------------------------------------------------------------- #
# Change password (self-service, SRS §15)
# --------------------------------------------------------------------------- #
class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1)
    new_password: str = Field(min_length=1, max_length=128)
    # When false the caller keeps its other sessions; defaults to the policy.
    revoke_other_sessions: bool | None = None


class ChangePasswordResponse(BaseModel):
    success: bool = True
    message: str
    password_expires_at: str | None = None


# --------------------------------------------------------------------------- #
# Admin reset (SRS §16)
# --------------------------------------------------------------------------- #
class AdminResetRequest(BaseModel):
    user_id: uuid.UUID


class AdminResetResponse(BaseModel):
    user_id: uuid.UUID
    # Shown exactly once. The administrator hands it over / it is emailed.
    temporary_password: str
    expires_at: str
    must_change_password: bool = True
    message: str = "A temporary password was issued. The user must change it at next login."


# --------------------------------------------------------------------------- #
# Validate / strength (SRS §8)
# --------------------------------------------------------------------------- #
class ValidatePasswordRequest(BaseModel):
    password: str = Field(max_length=256)


class ValidatePasswordResponse(BaseModel):
    level: str
    score: int
    meets_policy: bool
    entropy_bits: float
    feedback: str | None = None


# --------------------------------------------------------------------------- #
# Policy / expiration (SRS §5, §11)
# --------------------------------------------------------------------------- #
class PasswordPolicyResponse(BaseModel):
    min_length: int
    max_length: int
    require_uppercase: bool
    require_lowercase: bool
    require_number: bool
    require_special: bool
    allow_spaces: bool
    forbid_common: bool
    forbid_sequences: bool
    forbid_repeats: bool
    forbid_identity: bool
    history_depth: int
    max_age_days: int
    min_age_hours: int
    expiry_warning_days: list[int]
    temp_password_ttl_hours: int


class PasswordExpirationResponse(BaseModel):
    expires_at: str | None = None
    changed_at: str | None = None
    days_until_expiry: int | None = None
    is_expired: bool
    in_warning_window: bool
    must_change: bool
    change_required: bool


# --------------------------------------------------------------------------- #
# Security dashboard (SRS §17)
# --------------------------------------------------------------------------- #
class PasswordDashboardUser(BaseModel):
    user_id: uuid.UUID
    name: str
    email: str
    expires_at: str | None = None
    days_until_expiry: int | None = None
    is_expired: bool
    must_change: bool


class PasswordDashboardResponse(BaseModel):
    expired: list[PasswordDashboardUser]
    expiring_soon: list[PasswordDashboardUser]
    temporary: list[PasswordDashboardUser]
    must_change: list[PasswordDashboardUser]
    total_users: int
