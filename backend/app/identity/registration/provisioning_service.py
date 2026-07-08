"""UserProvisioningService — turn an accepted invitation into an identity (§7).

The single place a human account comes into existence from onboarding. Deliberately
free of HTTP, email and token concerns so that SSO (§3 mode 4) and SCIM (mode 5) can
provision through exactly this seam later without a redesign: they arrive with an
email, an organization, a role and a department, and **no password at all** --
``password=None`` stores the ``UNUSABLE_PASSWORD`` sentinel, and no password can ever
verify against it.

Assigns *both* role systems, because both are live (see ADR-0005):

- ``users.role``  the legacy coarse enum the dashboard still reads
- ``user_roles``  the RBAC grant the authorization layer actually enforces

Assigning only one leaves a user who looks like an ADMIN and can do nothing, or the
reverse — which is worse.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.core.enums import UserRole as LegacyUserRole
from app.core.security import UNUSABLE_PASSWORD
from app.identity.models.enums import IdentityStatus
from app.identity.models.registration import UserProfile
from app.identity.repositories.registration_repositories import UserProfileRepository
from app.identity.roles.engine import RoleEngine
from app.identity.security.passwords import hash_user_password
from app.models.rbac import Role
from app.models.user import User


@dataclass(frozen=True)
class ProvisionRequest:
    organization_id: uuid.UUID
    email: str
    first_name: str
    last_name: str
    # ``None`` provisions an identity with **no password credential** -- the SSO/SCIM
    # path. A password, when given, is still validated against the full policy.
    password: str | None = None
    role_id: uuid.UUID | None = None
    department_id: uuid.UUID | None = None
    phone: str | None = None
    timezone: str | None = None
    language: str | None = None
    job_title: str | None = None


class UserProvisioningService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.profiles = UserProfileRepository(db)
        self.roles = RoleEngine(db)

    def provision(self, request: ProvisionRequest, *, status: IdentityStatus) -> User:
        """Create the identity + profile and assign role/department. Does not commit.

        The account is born in ``status`` — ``REGISTERED`` for the onboarding flow,
        which is *before* the verification email is dispatched. It cannot authenticate
        until it reaches ``ACTIVE``.
        """
        email = request.email.strip().lower()
        legacy_role, rbac_role = self._resolve_roles(request)

        user = User(
            organization_id=request.organization_id,
            department_id=request.department_id,
            name=f"{request.first_name} {request.last_name}".strip(),
            email=email,
            password_hash=self._credential(request, email),
            role=legacy_role,
            # `is_active` mirrors the lifecycle: an unverified account is not active,
            # and the legacy auth path reads this flag.
            is_active=status is IdentityStatus.ACTIVE,
            status=status.value,
        )
        self.db.add(user)
        self.db.flush()

        self.profiles.add(
            UserProfile(
                user_id=user.id,
                first_name=request.first_name,
                last_name=request.last_name,
                job_title=request.job_title,
                phone=request.phone,
                timezone=request.timezone,
                language=request.language,
            )
        )

        if rbac_role is not None:
            self.roles.assign(user.id, rbac_role.id)

        self.db.flush()
        return user

    def initialize_preferences(self, user: User, *, timezone: str | None, language: str | None) -> None:
        """Defaults for anything the invitee did not supply (§7)."""
        profile = self.profiles.get_for_user(user.id)
        if profile is None:  # pragma: no cover - provision always creates one
            return
        profile.timezone = profile.timezone or timezone or "UTC"
        profile.language = profile.language or language or "en"
        self.db.flush()

    # ------------------------------------------------------------------ #
    # Internal
    # ------------------------------------------------------------------ #
    @staticmethod
    def _credential(request: ProvisionRequest, email: str) -> str:
        """The stored ``password_hash``.

        No password -> the sentinel. Making the password optional must not make it
        *unvalidated*: when one is supplied, ``hash_user_password`` enforces the full
        policy before hashing (ADR-0004), here at the service layer rather than merely
        at the HTTP boundary.
        """
        if request.password is None:
            return UNUSABLE_PASSWORD
        return hash_user_password(
            request.password, email=email, username=f"{request.first_name}{request.last_name}"
        )

    def _resolve_roles(self, request: ProvisionRequest) -> tuple[LegacyUserRole, Role | None]:
        """Map the invitation's RBAC role onto the legacy enum, or fall back to VIEWER.

        VIEWER is the safe default: an invitation with no role must not silently mint
        an administrator.
        """
        if request.role_id is None:
            return LegacyUserRole.VIEWER, None

        role = self.db.get(Role, request.role_id)
        if role is None:
            return LegacyUserRole.VIEWER, None

        try:
            legacy = LegacyUserRole(role.name)
        except ValueError:
            # A custom RBAC role with no legacy counterpart. The RBAC grant is what
            # authorization enforces; the enum only needs to be non-privileged.
            legacy = LegacyUserRole.VIEWER
        return legacy, role
