"""Identity request/response schemas (SRS §9 schemas, §18 error format)."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.identity.models.enums import IdentityStatus


# --------------------------------------------------------------------------- #
# Error envelope (SRS §18)
# --------------------------------------------------------------------------- #
class ErrorBody(BaseModel):
    code: str
    message: str


class ErrorEnvelope(BaseModel):
    success: bool = False
    error: ErrorBody
    request_id: str | None = None


# --------------------------------------------------------------------------- #
# Lifecycle
# --------------------------------------------------------------------------- #
class LifecycleTransition(BaseModel):
    """Request body to move an identity to a new lifecycle state."""

    target_status: IdentityStatus
    reason: str | None = None


# --------------------------------------------------------------------------- #
# Users
# --------------------------------------------------------------------------- #
class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    display_name: str = Field(validation_alias="name")
    organization_id: uuid.UUID
    department_id: uuid.UUID | None = None
    role: str
    is_active: bool
    status: str
    created_at: datetime
    updated_at: datetime


class UserCreate(BaseModel):
    email: EmailStr
    display_name: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=8, max_length=128)
    organization_id: uuid.UUID
    department_id: uuid.UUID | None = None
    role: str = "VIEWER"


# --------------------------------------------------------------------------- #
# Organizations / hierarchy
# --------------------------------------------------------------------------- #
class OrganizationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    status: str
    created_at: datetime


class DepartmentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    name: str
    manager_id: uuid.UUID | None = None
    created_at: datetime


class DepartmentCreate(BaseModel):
    organization_id: uuid.UUID
    name: str = Field(min_length=1, max_length=255)
    manager_id: uuid.UUID | None = None


class TeamRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    department_id: uuid.UUID
    name: str
    lead_id: uuid.UUID | None = None
    created_at: datetime


# --------------------------------------------------------------------------- #
# Roles
# --------------------------------------------------------------------------- #
class RoleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    description: str | None = None
    is_system: bool
    organization_id: uuid.UUID | None = None


# --------------------------------------------------------------------------- #
# Service accounts / sessions
# --------------------------------------------------------------------------- #
class ServiceAccountRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    name: str
    owner_id: uuid.UUID | None = None
    status: str
    created_at: datetime


class SessionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    ip_address: str | None = None
    user_agent: str | None = None
    created_at: datetime
    expires_at: datetime
    last_seen_at: datetime | None = None
    revoked_at: datetime | None = None


# --------------------------------------------------------------------------- #
# Machine identities: agent identity, service account, external client
# --------------------------------------------------------------------------- #
class AgentIdentityCreate(BaseModel):
    agent_id: uuid.UUID
    credential_type: str = "API_KEY"


class AgentIdentityRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    agent_id: uuid.UUID
    client_id: str
    credential_type: str
    status: str
    last_used_at: datetime | None = None
    expires_at: datetime | None = None
    created_at: datetime


class ServiceAccountCreate(BaseModel):
    organization_id: uuid.UUID
    name: str = Field(min_length=1, max_length=255)
    permissions: list[str] = Field(default_factory=list)
    owner_id: uuid.UUID | None = None


class ServiceAccountCreated(ServiceAccountRead):
    """Returned once on creation — includes the plaintext client secret."""

    client_secret: str


class ExternalClientCreate(BaseModel):
    organization_id: uuid.UUID
    client_name: str = Field(min_length=1, max_length=255)
    redirect_uri: str | None = None
    allowed_scopes: list[str] = Field(default_factory=list)


class ExternalClientRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    client_name: str
    client_id: str
    redirect_uri: str | None = None
    allowed_scopes: list[str] = Field(default_factory=list)
    status: str
    created_at: datetime


class ExternalClientCreated(ExternalClientRead):
    """Returned once on creation — includes the plaintext client secret."""

    client_secret: str
