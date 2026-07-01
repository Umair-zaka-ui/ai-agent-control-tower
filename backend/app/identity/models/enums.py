"""Identity domain enumerations (Phase 4 Part 4.1)."""

from __future__ import annotations

import enum


class IdentityType(str, enum.Enum):
    """Everything is an identity (SRS §4)."""

    HUMAN = "HUMAN"
    AI_AGENT = "AI_AGENT"
    SERVICE_ACCOUNT = "SERVICE_ACCOUNT"
    EXTERNAL_CLIENT = "EXTERNAL_CLIENT"
    ORGANIZATION = "ORGANIZATION"


class IdentityStatus(str, enum.Enum):
    """Canonical identity lifecycle (SRS §8).

    Created → Pending Verification → Active → Suspended → Disabled → Archived →
    Deleted. Every transition emits an audit event.
    """

    CREATED = "CREATED"
    PENDING_VERIFICATION = "PENDING_VERIFICATION"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    DISABLED = "DISABLED"
    ARCHIVED = "ARCHIVED"
    DELETED = "DELETED"


# Allowed forward/again transitions between lifecycle states. Kept permissive
# but explicit so the service layer can reject nonsensical jumps.
IDENTITY_TRANSITIONS: dict[IdentityStatus, set[IdentityStatus]] = {
    IdentityStatus.CREATED: {IdentityStatus.PENDING_VERIFICATION, IdentityStatus.ACTIVE},
    IdentityStatus.PENDING_VERIFICATION: {IdentityStatus.ACTIVE, IdentityStatus.DISABLED},
    IdentityStatus.ACTIVE: {IdentityStatus.SUSPENDED, IdentityStatus.DISABLED, IdentityStatus.ARCHIVED},
    IdentityStatus.SUSPENDED: {IdentityStatus.ACTIVE, IdentityStatus.DISABLED, IdentityStatus.ARCHIVED},
    IdentityStatus.DISABLED: {IdentityStatus.ACTIVE, IdentityStatus.ARCHIVED},
    IdentityStatus.ARCHIVED: {IdentityStatus.DELETED, IdentityStatus.ACTIVE},
    IdentityStatus.DELETED: set(),
}


def can_transition(current: IdentityStatus, target: IdentityStatus) -> bool:
    """Whether ``current → target`` is an allowed lifecycle transition."""
    if current == target:
        return False
    return target in IDENTITY_TRANSITIONS.get(current, set())


class CredentialType(str, enum.Enum):
    PASSWORD = "PASSWORD"
    API_KEY = "API_KEY"
    CLIENT_SECRET = "CLIENT_SECRET"
    OAUTH = "OAUTH"
    MTLS = "MTLS"


class SecurityEventType(str, enum.Enum):
    LOGIN_SUCCEEDED = "LOGIN_SUCCEEDED"
    LOGIN_FAILED = "LOGIN_FAILED"
    MFA_CHALLENGED = "MFA_CHALLENGED"
    SESSION_CREATED = "SESSION_CREATED"
    SESSION_REVOKED = "SESSION_REVOKED"
    CREDENTIAL_ROTATED = "CREDENTIAL_ROTATED"
    IDENTITY_LIFECYCLE_CHANGED = "IDENTITY_LIFECYCLE_CHANGED"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    SUSPICIOUS_ACTIVITY = "SUSPICIOUS_ACTIVITY"
