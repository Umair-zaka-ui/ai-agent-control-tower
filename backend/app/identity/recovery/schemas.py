"""Request/response DTOs for the recovery API (4.2.2.3.3 §21)."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str = Field(min_length=1)
    new_password: str = Field(min_length=1, max_length=128)


class ChangeEmailRequest(BaseModel):
    new_email: EmailStr
    current_password: str = Field(min_length=1)


class VerifyNewEmailRequest(BaseModel):
    token: str = Field(min_length=1)


class RecoveryAck(BaseModel):
    """Deliberately uniform (§9): says nothing about whether an account exists."""

    success: bool = True
    message: str


class RecoveryEventRead(BaseModel):
    id: uuid.UUID
    event_type: str
    actor_id: uuid.UUID | None = None
    ip_address: str | None = None
    user_agent: str | None = None
    created_at: datetime
    metadata: dict | None = None

    @classmethod
    def from_event(cls, event) -> "RecoveryEventRead":
        meta = dict(event.meta or {})
        return cls(
            id=event.id,
            event_type=event.event_type,
            actor_id=event.actor_id,
            ip_address=event.ip_address,
            user_agent=meta.get("user_agent"),
            created_at=event.created_at,
            metadata=meta,
        )
