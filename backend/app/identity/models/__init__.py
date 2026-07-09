"""Identity ORM models.

Importing this package registers every identity table on ``Base.metadata`` so
Alembic and ``create_all`` see them. Existing platform tables (users,
organizations, roles, rbac_permissions) are reused from ``app.models`` — the
identity foundation is additive, not a replacement.
"""

from app.identity.models.agent_identity import AgentIdentity
from app.identity.models.credential import PasswordHistory
from app.identity.models.department import Department, Team
from app.identity.models.protection import (
    AccountLock,
    BlockedIp,
    IdentityProtectionRule,
    IdentityRiskEvent,
)
from app.identity.models.recovery import PasswordResetRequest
from app.identity.models.enums import (
    CredentialType,
    DeviceStatus,
    IdentityStatus,
    IdentityType,
    InvitationStatus,
    RegistrationMode,
    SecurityEventType,
    SessionRevocationReason,
    SessionSecurityBand,
    SessionStatus,
)
from app.identity.models.external_client import ExternalClient
from app.identity.models.login_history import LoginHistory
from app.identity.models.registration import (
    EmailVerification,
    Invitation,
    RateLimitHit,
    UserProfile,
)
from app.identity.models.security_event import SecurityEvent
from app.identity.models.service_account import ServiceAccount
from app.identity.models.session import RefreshToken, UserDevice, UserSession

__all__ = [
    "Department",
    "Team",
    "ServiceAccount",
    "ExternalClient",
    "AgentIdentity",
    "UserSession",
    "RefreshToken",
    "UserDevice",
    "SecurityEvent",
    "LoginHistory",
    "IdentityStatus",
    "IdentityType",
    "CredentialType",
    "SecurityEventType",
    "SessionStatus",
    "SessionRevocationReason",
    "SessionSecurityBand",
    "DeviceStatus",
    "Invitation",
    "EmailVerification",
    "UserProfile",
    "RateLimitHit",
    "InvitationStatus",
    "RegistrationMode",
    "PasswordHistory",
    "PasswordResetRequest",
    "AccountLock",
    "BlockedIp",
    "IdentityProtectionRule",
    "IdentityRiskEvent",
]
