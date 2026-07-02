"""IdentityContext — the internal object every authenticated request carries.

Services must depend on this (SRS §9), never on raw tokens/headers. It answers
the core questions of §2: who is calling, what type, how they authenticated,
what they may do, and the request's security metadata.
"""

from __future__ import annotations

from dataclasses import dataclass, field


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
