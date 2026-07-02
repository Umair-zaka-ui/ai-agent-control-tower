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
