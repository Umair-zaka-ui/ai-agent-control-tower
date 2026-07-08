"""DTOs for registration, invitations and email verification (§10, §11, §15, §17)."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

__all__ = [
    "InvitationCreateRequest",
    "InvitationActionRequest",
    "InvitationRead",
    "InvitationPreview",
    "RegisterFromInvitationRequest",
    "SelfRegisterRequest",
    "RegistrationResponse",
    "VerifyEmailRequest",
    "ResendVerificationRequest",
    "GenericAcknowledgement",
    "UserProfileRead",
]

# §11: names are required, max 100 characters. Trimmed, and rejected if the trim
# leaves nothing — "   " is not a first name.
_NAME = Field(..., min_length=1, max_length=100)


class _TrimmedNames(BaseModel):
    first_name: str = _NAME
    last_name: str = _NAME

    @field_validator("first_name", "last_name")
    @classmethod
    def _strip(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("must not be blank")
        return stripped


# --------------------------------------------------------------------------- #
# Invitations (admin)
# --------------------------------------------------------------------------- #
class InvitationCreateRequest(BaseModel):
    email: EmailStr
    role_id: uuid.UUID | None = None
    department_id: uuid.UUID | None = None
    team_id: uuid.UUID | None = None


class InvitationActionRequest(BaseModel):
    """Body for resend / cancel. The invitation is addressed by id, never by token —
    an administrator has no business holding the invitee's single-use token."""

    invitation_id: uuid.UUID


class InvitationRead(BaseModel):
    """Admin view. Deliberately carries **no token**, not even a prefix."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    email: str
    role_id: uuid.UUID | None = None
    department_id: uuid.UUID | None = None
    team_id: uuid.UUID | None = None
    invited_by: uuid.UUID | None = None
    status: str
    expires_at: datetime
    accepted_at: datetime | None = None
    cancelled_at: datetime | None = None
    resent_count: int = 0
    last_sent_at: datetime | None = None
    created_at: datetime
    # Derived for the UI.
    is_expired: bool = False


class InvitationPreview(BaseModel):
    """Public view returned by ``GET /invitations/{token}`` (§17).

    Shows the invitee what they are accepting — organization, role, department,
    expiry — and the email they must register with. It exposes **no internal ids**
    beyond what the invitee already implicitly knows, and never the inviter's email.
    """

    email: str
    organization_name: str
    role_name: str | None = None
    department_name: str | None = None
    invited_by_name: str | None = None
    expires_at: datetime


# --------------------------------------------------------------------------- #
# Registration (public)
# --------------------------------------------------------------------------- #
class RegisterFromInvitationRequest(_TrimmedNames):
    """§10: email is read-only (it comes from the invitation) and is not accepted here."""

    token: str = Field(..., min_length=8, max_length=200)
    password: str = Field(..., min_length=12, max_length=128)
    confirm_password: str = Field(..., min_length=12, max_length=128)
    phone: str | None = Field(default=None, max_length=40)
    timezone: str | None = Field(default=None, max_length=64)
    language: str | None = Field(default=None, max_length=16)
    job_title: str | None = Field(default=None, max_length=150)

    @field_validator("confirm_password")
    @classmethod
    def _match(cls, value: str, info) -> str:
        if info.data.get("password") and value != info.data["password"]:
            raise ValueError("Passwords do not match")
        return value


class SelfRegisterRequest(_TrimmedNames):
    """Mode 3. Requires the organization to have ``registration_mode=SELF_SERVICE``."""

    organization_id: uuid.UUID
    email: EmailStr
    password: str = Field(..., min_length=12, max_length=128)
    confirm_password: str = Field(..., min_length=12, max_length=128)
    phone: str | None = Field(default=None, max_length=40)
    timezone: str | None = Field(default=None, max_length=64)
    language: str | None = Field(default=None, max_length=16)

    @field_validator("confirm_password")
    @classmethod
    def _match(cls, value: str, info) -> str:
        if info.data.get("password") and value != info.data["password"]:
            raise ValueError("Passwords do not match")
        return value


class RegistrationResponse(BaseModel):
    """No tokens are returned. Registration does not sign you in — §12 requires the
    email to be verified first, and returning a session here would make the
    verification step optional in practice."""

    email: str
    status: str
    email_sent: bool
    requires_approval: bool
    message: str


class VerifyEmailRequest(BaseModel):
    token: str = Field(..., min_length=8, max_length=200)


class ResendVerificationRequest(BaseModel):
    email: EmailStr


class GenericAcknowledgement(BaseModel):
    """Identical for every input (§14). Never reveals whether an account exists."""

    message: str = "If that address needs verification, we have sent a new link."


# --------------------------------------------------------------------------- #
# Profile
# --------------------------------------------------------------------------- #
class UserProfileRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user_id: uuid.UUID
    first_name: str | None = None
    last_name: str | None = None
    job_title: str | None = None
    department: str | None = None
    phone: str | None = None
    timezone: str | None = None
    language: str | None = None
    avatar_url: str | None = None
