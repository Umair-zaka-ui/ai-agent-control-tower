"""Enterprise password policy & credential management (Phase 4 Part 4.2.2.3.2).

The single write path for human passwords (:class:`CredentialService`), the
lifecycle/expiration rules (:class:`PasswordPolicyService`), reuse prevention
(:class:`PasswordHistoryService`), administrative reset + temporary passwords
(:class:`PasswordResetService`), and their shared audit facade.
"""

from app.identity.credentials.audit import CredentialAuditService, CredentialContext
from app.identity.credentials.history_service import PasswordHistoryService
from app.identity.credentials.policy_service import PasswordPolicyService
from app.identity.credentials.reset_service import PasswordResetService, TemporaryCredential
from app.identity.credentials.service import (
    CredentialService,
    generate_temporary_password,
)

__all__ = [
    "CredentialService",
    "CredentialAuditService",
    "CredentialContext",
    "PasswordHistoryService",
    "PasswordPolicyService",
    "PasswordResetService",
    "TemporaryCredential",
    "generate_temporary_password",
]
