"""Account recovery — forgot password, reset, and verified email change (Part 4.2.2.3.3).

Recovery is one of the highest-risk parts of an identity platform, so it reuses the
platform's existing discipline rather than inventing a weaker parallel: opaque hashed
single-use tokens (as invitations/verification do), the credential write path (policy
+ no-reuse + argon2id + history), Postgres-backed rate limiting, uniform
enumeration-safe responses, and the single ``security_events`` audit stream.
"""

from app.identity.recovery.audit import RecoveryAuditService, RecoveryContext
from app.identity.recovery.email_change_service import EmailChangeService
from app.identity.recovery.password_reset_service import PasswordResetService
from app.identity.recovery.repository import PasswordResetRepository
from app.identity.recovery.service import RECOVERY_EVENT_TYPES, RecoveryService

__all__ = [
    "RecoveryService",
    "PasswordResetService",
    "EmailChangeService",
    "RecoveryAuditService",
    "RecoveryContext",
    "PasswordResetRepository",
    "RECOVERY_EVENT_TYPES",
]
