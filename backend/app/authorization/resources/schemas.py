"""Resource-based authorization API schemas (Phase 4.3.4 §19)."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


# --- Registry (§3, §6) ------------------------------------------------------ #
class ResourceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    resource_type: str
    resource_id: uuid.UUID
    name: str | None = None
    organization_id: uuid.UUID
    project_id: uuid.UUID | None = None
    owner_id: uuid.UUID
    owner_type: str
    created_by: uuid.UUID | None = None
    visibility: str
    status: str
    policy: list | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class ResourceRegister(BaseModel):
    resource_type: str = Field(min_length=1, max_length=50)
    resource_id: uuid.UUID | None = None
    name: str | None = Field(default=None, max_length=255)
    visibility: str = "PRIVATE"
    owner_id: uuid.UUID | None = None
    owner_type: str = "USER"
    project_id: uuid.UUID | None = None


class ResourceUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=255)
    visibility: str | None = None
    status: str | None = None


# --- Ownership (§6–§8) ------------------------------------------------------ #
class OwnerRead(BaseModel):
    resource_pk: uuid.UUID
    owner_id: uuid.UUID
    owner_type: str
    created_by: uuid.UUID | None = None


class OwnershipTransferRequest(BaseModel):
    new_owner_id: uuid.UUID
    new_owner_type: str = "USER"
    reason: str | None = Field(default=None, max_length=500)


class OwnershipHistoryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    resource_id: uuid.UUID
    previous_owner: uuid.UUID | None = None
    previous_owner_type: str | None = None
    new_owner: uuid.UUID
    new_owner_type: str
    changed_by: uuid.UUID | None = None
    reason: str | None = None
    created_at: datetime | None = None


# --- ACL (§10) --------------------------------------------------------------- #
class ACLEntryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    resource_id: uuid.UUID
    principal_type: str
    principal_id: uuid.UUID
    permission: str
    effect: str
    expires_at: datetime | None = None
    created_by: uuid.UUID | None = None
    created_at: datetime | None = None


class ACLEntryCreate(BaseModel):
    principal_type: str
    principal_id: uuid.UUID
    permission: str = Field(min_length=1, max_length=100)
    effect: str = "ALLOW"
    expires_at: datetime | None = None


class ACLEntryUpdate(BaseModel):
    permission: str | None = Field(default=None, max_length=100)
    effect: str | None = None
    expires_at: datetime | None = None


# --- Sharing (§12) ------------------------------------------------------------ #
class ShareRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    resource_id: uuid.UUID
    shared_with_type: str
    shared_with_id: uuid.UUID
    access_level: str
    expires_at: datetime | None = None
    created_by: uuid.UUID | None = None
    created_at: datetime | None = None


class ShareCreate(BaseModel):
    shared_with_type: str
    shared_with_id: uuid.UUID
    access_level: str = "READ"
    expires_at: datetime | None = None


class ShareUpdate(BaseModel):
    access_level: str | None = None
    expires_at: datetime | None = None


# --- Delegation (§13) ---------------------------------------------------------- #
class ResourceDelegationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    resource_id: uuid.UUID
    delegate_id: uuid.UUID
    permissions: list
    expires_at: datetime | None = None
    status: str
    reason: str | None = None
    approved_by: uuid.UUID | None = None
    created_by: uuid.UUID | None = None
    created_at: datetime | None = None


class ResourceDelegationCreate(BaseModel):
    delegate_id: uuid.UUID
    permissions: list[str] = Field(min_length=1)
    expires_at: datetime | None = None
    reason: str | None = Field(default=None, max_length=500)


# --- Policy (§14) --------------------------------------------------------------- #
class PolicyWrite(BaseModel):
    policy: list[dict] | None = None


# --- Authorize / inspector (§18, §21) ------------------------------------------- #
class AuthorizeRequest(BaseModel):
    permission: str = Field(min_length=1, max_length=100)
    # Inspector simulation (§21): administrators may evaluate another identity.
    identity_id: uuid.UUID | None = None


class AuthorizeResponse(BaseModel):
    allowed: bool
    permission: str
    reason: str
    source: str
    error_code: str | None = None
    resource_pk: uuid.UUID | None = None
    resource_type: str | None = None
    owner_id: uuid.UUID | None = None
    owner_type: str | None = None
    visibility: str | None = None
    scope: str | None = None
    source_role: str | None = None
    matched_rule_id: uuid.UUID | None = None
    steps: list[str] = []
