"""IdentityContext — the internal object every authenticated request carries.

Services must depend on this (SRS §9), never on raw tokens/headers. It answers
the core questions of §2: who is calling, what type, how they authenticated,
what they may do, and the request's security metadata.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.identity.auth.enums import AuthAssuranceLevel


@dataclass
class IdentityContext:
    identity_id: str
    identity_type: str  # AuthIdentityType value
    auth_method: str  # AuthMethod value
    organization_id: str | None = None
    roles: list[str] = field(default_factory=list)
    permissions: list[str] = field(default_factory=list)
    scopes: list[str] = field(default_factory=list)
    session_id: str | None = None
    credential_id: str | None = None
    ip_address: str | None = None
    user_agent: str | None = None
    request_id: str | None = None
    # --- Authentication assurance / MFA (SRS §24) --------------------- #
    # assurance_level: AuthAssuranceLevel value. amr: OIDC "authentication
    # methods references", e.g. ["pwd"] or ["pwd", "otp"]. mfa_pending marks the
    # interstitial state where the primary factor is verified but a required
    # second factor has not yet been satisfied — such a context must not pass
    # authorization checks.
    assurance_level: str = AuthAssuranceLevel.AAL1.value
    amr: list[str] = field(default_factory=list)
    mfa_pending: bool = False

    # ------------------------------------------------------------------ #
    # Convenience predicates used by the authorization layer
    # ------------------------------------------------------------------ #
    def is_machine(self) -> bool:
        return self.identity_type in {"AI_AGENT", "SERVICE_ACCOUNT", "EXTERNAL_CLIENT", "SYSTEM"}

    def has_permission(self, code: str) -> bool:
        return code in self.permissions

    def has_scope(self, scope: str) -> bool:
        return scope in self.scopes

    def has_role(self, role: str) -> bool:
        return role in self.roles

    # --- Assurance predicates (SRS §24) ------------------------------- #
    def mfa_satisfied(self) -> bool:
        """True once a second factor has been verified (AAL2)."""
        return self.assurance_level == AuthAssuranceLevel.AAL2.value

    def needs_mfa_challenge(self) -> bool:
        """True while the primary factor is verified but MFA is still required."""
        return self.mfa_pending
