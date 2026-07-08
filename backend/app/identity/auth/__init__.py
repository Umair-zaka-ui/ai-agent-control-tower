"""Authentication architecture & trust model (Phase 4 Part 4.2.1).

A design-first, additive authentication layer for every identity type — human
users, AI agents, service accounts, external clients and system events. This
part establishes the architecture, the IdentityContext, the core services and
the middleware dependency; token-table persistence and the /api/v1/auth
endpoints are expanded in Parts 4.2.2 / 4.2.3 (see docs/identity/).

The existing password login continues to work unchanged — nothing here replaces
it yet; it is the foundation the migration builds on.
"""

from app.identity.auth.authentication_service import (
    AuthenticationService,
    LoginResult,
    RefreshResult,
)
from app.identity.auth.context import IdentityContext
from app.identity.auth.credential_service import CredentialService
from app.identity.auth.dependency import (
    authenticate,
    extract_credential,
    require_assurance,
    require_scope,
)
from app.identity.auth.enums import (
    AuthAssuranceLevel,
    AuthEventType,
    AuthIdentityType,
    AuthMethod,
    MfaMethod,
)
from app.identity.auth.login_history_service import LoginHistoryService
from app.identity.auth.password_service import PasswordPolicyError, PasswordService
from app.identity.auth.refresh_token_service import RefreshTokenService
from app.identity.auth.resolver import IdentityContextResolver
from app.identity.auth.security_event_service import SecurityEventService
from app.identity.auth.session_service import SessionService
from app.identity.auth.token_service import TokenService

__all__ = [
    "IdentityContext",
    "AuthMethod",
    "AuthEventType",
    "AuthIdentityType",
    "AuthAssuranceLevel",
    "MfaMethod",
    "AuthenticationService",
    "LoginResult",
    "RefreshResult",
    "TokenService",
    "RefreshTokenService",
    "CredentialService",
    "SessionService",
    "SecurityEventService",
    "LoginHistoryService",
    "PasswordService",
    "PasswordPolicyError",
    "IdentityContextResolver",
    "authenticate",
    "extract_credential",
    "require_scope",
    "require_assurance",
]
