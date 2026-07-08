"""Enterprise registration, invitations & email verification (Phase 4 Part 4.2.2.3.1).

Authentication is only half of identity. This package answers the other half: how a
human *becomes* a trusted identity. The enterprise default is invitation-only —
unrestricted public registration is the exception, not the rule.
"""

from app.identity.registration.audit import RegistrationAuditService, RequestContext
from app.identity.registration.invitation_service import (
    InvitationService,
    IssuedInvitation,
)
from app.identity.registration.provisioning_service import (
    ProvisionRequest,
    UserProvisioningService,
)
from app.identity.registration.registration_service import (
    RegistrationResult,
    RegistrationService,
)
from app.identity.registration.tokens import (
    generate_invitation_token,
    generate_verification_token,
    token_hash,
)
from app.identity.registration.verification_service import (
    EmailVerificationService,
    IssuedVerification,
)

__all__ = [
    "RegistrationService",
    "RegistrationResult",
    "InvitationService",
    "IssuedInvitation",
    "EmailVerificationService",
    "IssuedVerification",
    "UserProvisioningService",
    "ProvisionRequest",
    "RegistrationAuditService",
    "RequestContext",
    "generate_invitation_token",
    "generate_verification_token",
    "token_hash",
]
