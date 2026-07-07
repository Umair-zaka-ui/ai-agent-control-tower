"""Authentication enumerations (SRS §3, §10, §13)."""

from __future__ import annotations

import enum


class AuthIdentityType(str, enum.Enum):
    """Identity types the auth platform authenticates (SRS §3).

    Distinct from the domain ``IdentityType`` (which models organizations too):
    these are the caller kinds a *token* can represent.
    """

    HUMAN_USER = "HUMAN_USER"
    AI_AGENT = "AI_AGENT"
    SERVICE_ACCOUNT = "SERVICE_ACCOUNT"
    EXTERNAL_CLIENT = "EXTERNAL_CLIENT"
    SYSTEM = "SYSTEM"


class AuthMethod(str, enum.Enum):
    """How a request was authenticated (SRS §10). Stored on audit/security events."""

    PASSWORD = "PASSWORD"
    JWT = "JWT"
    REFRESH_TOKEN = "REFRESH_TOKEN"
    API_KEY = "API_KEY"
    OAUTH2 = "OAUTH2"
    OIDC = "OIDC"
    SAML = "SAML"
    CLIENT_CREDENTIALS = "CLIENT_CREDENTIALS"
    SYSTEM_INTERNAL = "SYSTEM_INTERNAL"


class AuthAssuranceLevel(str, enum.Enum):
    """Authenticator Assurance Level (NIST SP 800-63B, SRS §24).

    Carried on every ``IdentityContext`` and access token so the authorization
    layer and future enterprise policies can require step-up authentication
    without redesigning the auth flow.
    """

    AAL0 = "AAL0"  # partial: primary factor verified, second factor still pending
    AAL1 = "AAL1"  # single factor (password / API key / client secret)
    AAL2 = "AAL2"  # multi-factor (primary + OTP / WebAuthn / recovery code)


class MfaMethod(str, enum.Enum):
    """Second-factor methods (SRS §24).

    Enrollment, secret storage and verification land in a later subpart; the
    enum exists now so the assurance seam is complete and typed.
    """

    TOTP = "TOTP"
    WEBAUTHN = "WEBAUTHN"
    SMS = "SMS"
    EMAIL = "EMAIL"
    RECOVERY_CODE = "RECOVERY_CODE"


class AuthEventType(str, enum.Enum):
    """Security events every authentication action emits (SRS §13)."""

    AUTH_LOGIN_SUCCESS = "AUTH_LOGIN_SUCCESS"
    AUTH_LOGIN_FAILED = "AUTH_LOGIN_FAILED"
    AUTH_LOGOUT = "AUTH_LOGOUT"
    TOKEN_REFRESHED = "TOKEN_REFRESHED"
    REFRESH_TOKEN_REUSED = "REFRESH_TOKEN_REUSED"
    TOKEN_REVOKED = "TOKEN_REVOKED"
    API_KEY_USED = "API_KEY_USED"
    API_KEY_REVOKED = "API_KEY_REVOKED"
    SERVICE_ACCOUNT_AUTHENTICATED = "SERVICE_ACCOUNT_AUTHENTICATED"
    EXTERNAL_CLIENT_AUTHENTICATED = "EXTERNAL_CLIENT_AUTHENTICATED"
    SUSPICIOUS_LOGIN = "SUSPICIOUS_LOGIN"
    SESSION_EXPIRED = "SESSION_EXPIRED"
    SESSION_REVOKED = "SESSION_REVOKED"
    # MFA / step-up authentication (SRS §24).
    MFA_CHALLENGE_ISSUED = "MFA_CHALLENGE_ISSUED"
    MFA_SUCCEEDED = "MFA_SUCCEEDED"
    MFA_FAILED = "MFA_FAILED"
    MFA_ENROLLED = "MFA_ENROLLED"
    MFA_DISABLED = "MFA_DISABLED"
