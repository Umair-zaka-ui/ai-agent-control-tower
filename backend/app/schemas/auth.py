"""Authentication schemas: registration, login and tokens."""

from __future__ import annotations

from pydantic import BaseModel, EmailStr, Field


class RegisterRequest(BaseModel):
    """Bootstrap a new organization together with its first SUPER_ADMIN user."""

    organization_name: str = Field(..., min_length=1, max_length=255)
    name: str = Field(..., min_length=1, max_length=255)
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=1, max_length=128)


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
