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


class SessionStatus(str, enum.Enum):
    """Lifecycle state of an authenticated session (SRS 4.2.2.2 §4).

    Exactly one state at a time. ``TERMINATED`` is final: no refresh, no
    reactivation. ``SUSPICIOUS`` also blocks the session, but records that the
    cause was a security signal rather than a routine logout or timeout.

    ``IDLE``/``EXPIRED`` are *derived* facts — the clock decides them — while
    ``REVOKED``/``SUSPICIOUS``/``TERMINATED`` are *recorded* facts. The lifecycle
    service materialises the derived ones on read, so the stored status never lies.

    Which states are actually persisted:

    - ``ACTIVE``      login, and on resumed activity
    - ``IDLE``        materialised when a session is *observed* inside the idle
                      warning window (listing / reaping) — never by the session
                      making a request, since a request is activity
    - ``EXPIRED``     idle or absolute deadline reached
    - ``REVOKED``     logout, admin force-logout, device block, session limit
    - ``SUSPICIOUS``  refresh-token reuse
    - ``TERMINATED``  the identity was suspended/disabled — final, not replaceable
      by signing in again
    - ``CREATED``     **never persisted.** A session is born ``ACTIVE``; there is no
      moment between creation and the login response in which it could be observed.
      Kept because SRS §4 names it, and because a future pre-MFA "created but not yet
      elevated" session would land here.

    Defined here rather than in ``auth/enums.py`` because ``models/session.py``
    needs it, and importing the auth package from a model would create a cycle
    (``auth/__init__`` → ``authentication_service`` → models). ``auth.enums``
    re-exports these names.
    """

    CREATED = "CREATED"
    ACTIVE = "ACTIVE"
    IDLE = "IDLE"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"
    SUSPICIOUS = "SUSPICIOUS"
    TERMINATED = "TERMINATED"

    def is_terminal(self) -> bool:
        """A terminal session can never authenticate or refresh again."""
        return self in _TERMINAL_SESSION_STATES

    def can_authenticate(self) -> bool:
        return self in {SessionStatus.CREATED, SessionStatus.ACTIVE, SessionStatus.IDLE}


_TERMINAL_SESSION_STATES = frozenset(
    {
        SessionStatus.EXPIRED,
        SessionStatus.REVOKED,
        SessionStatus.SUSPICIOUS,
        SessionStatus.TERMINATED,
    }
)


class SessionRevocationReason(str, enum.Enum):
    """Why a session stopped being usable (SRS 4.2.2.2 §20).

    Always recorded alongside ``revoked_at`` — "when" without "why" is useless in
    an incident review.
    """

    USER_LOGOUT = "USER_LOGOUT"
    ADMIN_REVOKED = "ADMIN_REVOKED"
    PASSWORD_RESET = "PASSWORD_RESET"
    SECURITY_EVENT = "SECURITY_EVENT"
    ACCOUNT_DISABLED = "ACCOUNT_DISABLED"
    TOKEN_REUSE = "TOKEN_REUSE"
    SESSION_LIMIT_EXCEEDED = "SESSION_LIMIT_EXCEEDED"
    IDLE_TIMEOUT = "IDLE_TIMEOUT"
    ABSOLUTE_TIMEOUT = "ABSOLUTE_TIMEOUT"


class DeviceStatus(str, enum.Enum):
    """Trust posture of a device (SRS 4.2.2.2 §14).

    A ``BLOCKED`` device cannot authenticate at all. ``TRUSTED`` is the seam a
    future MFA policy uses to skip step-up on a known device.
    """

    UNKNOWN = "UNKNOWN"
    TRUSTED = "TRUSTED"
    BLOCKED = "BLOCKED"


class SessionSecurityBand(str, enum.Enum):
    """Bucketed view of ``security_score`` (SRS 4.2.2.2 §15)."""

    HEALTHY = "HEALTHY"  # 80-100
    WARNING = "WARNING"  # 50-79
    HIGH_RISK = "HIGH_RISK"  # 0-49

    @classmethod
    def for_score(cls, score: int) -> "SessionSecurityBand":
        if score >= 80:
            return cls.HEALTHY
        if score >= 50:
            return cls.WARNING
        return cls.HIGH_RISK


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
