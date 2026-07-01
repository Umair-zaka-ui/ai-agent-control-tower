"""IdentityService — the single entry point for identity operations (SRS §15).

Responsibilities: create / update / suspend / activate / archive / delete /
validate / authenticate identities, and register audit events for every change.
Controllers call this service; the service calls repositories; repositories touch
the database (SRS §13). The service owns the transaction (commit).
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.core.enums import UserRole
from app.identity.audit.events import record_security_event
from app.identity.errors import ErrorCode, IdentityError
from app.identity.models.department import Department
from app.identity.models.enums import (
    IdentityStatus,
    IdentityType,
    SecurityEventType,
    can_transition,
)
from app.identity.repositories.department_repository import DepartmentRepository
from app.identity.repositories.organization_repository import OrganizationRepository
from app.identity.repositories.session_repository import SessionRepository
from app.identity.repositories.user_repository import UserRepository
from app.identity.schemas.identity import DepartmentCreate, UserCreate
from app.identity.security.passwords import PasswordPolicyError, hash_user_password
from app.core.security import verify_password
from app.models.user import User


class IdentityService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.users = UserRepository(db)
        self.departments = DepartmentRepository(db)
        self.organizations = OrganizationRepository(db)
        self.sessions = SessionRepository(db)

    # ----------------------------------------------------------------- #
    # Users
    # ----------------------------------------------------------------- #
    def get_user(self, user_id: uuid.UUID) -> User:
        user = self.users.get(user_id)
        if user is None:
            raise IdentityError(ErrorCode.USER_NOT_FOUND, "User does not exist.")
        return user

    def list_users(self, organization_id: uuid.UUID, *, limit: int = 100, offset: int = 0) -> list[User]:
        return self.users.list_by_organization(organization_id, limit=limit, offset=offset)

    def create_user(
        self,
        data: UserCreate,
        *,
        actor_id: uuid.UUID | None = None,
        request_id: str | None = None,
    ) -> User:
        if self.organizations.get(data.organization_id) is None:
            raise IdentityError(ErrorCode.ORGANIZATION_NOT_FOUND, "Organization does not exist.")
        if self.users.get_by_email(data.email) is not None:
            raise IdentityError(ErrorCode.CONFLICT, "A user with this email already exists.")
        try:
            role = UserRole(data.role)
        except ValueError as exc:
            raise IdentityError(ErrorCode.VALIDATION_ERROR, f"Unknown role '{data.role}'.") from exc
        try:
            password_hash = hash_user_password(data.password)
        except PasswordPolicyError as exc:
            raise IdentityError(ErrorCode.VALIDATION_ERROR, str(exc)) from exc

        user = User(
            organization_id=data.organization_id,
            department_id=data.department_id,
            name=data.display_name,
            email=data.email,
            password_hash=password_hash,
            role=role,
            is_active=True,
        )
        self.users.add(user)
        self._record(
            SecurityEventType.IDENTITY_LIFECYCLE_CHANGED,
            organization_id=user.organization_id,
            actor_id=actor_id,
            target_id=user.id,
            request_id=request_id,
            metadata={"action": "created", "status": IdentityStatus.ACTIVE.value},
        )
        self.db.commit()
        self.db.refresh(user)
        return user

    def set_user_active(
        self,
        user_id: uuid.UUID,
        *,
        active: bool,
        actor_id: uuid.UUID | None = None,
        request_id: str | None = None,
    ) -> User:
        """Activate (True) or suspend (False) a human identity."""
        user = self.get_user(user_id)
        user.is_active = active
        self._record(
            SecurityEventType.IDENTITY_LIFECYCLE_CHANGED,
            organization_id=user.organization_id,
            actor_id=actor_id,
            target_id=user.id,
            request_id=request_id,
            metadata={
                "action": "activated" if active else "suspended",
                "status": IdentityStatus.ACTIVE.value if active else IdentityStatus.SUSPENDED.value,
            },
        )
        self.db.commit()
        self.db.refresh(user)
        return user

    def authenticate(self, email: str, password: str, *, request_id: str | None = None) -> User:
        """Validate credentials and return the user, or raise."""
        user = self.users.get_by_email(email)
        if user is None or not verify_password(password, user.password_hash):
            raise IdentityError(ErrorCode.AUTHENTICATION_FAILED, "Invalid email or password.")
        if not user.is_active:
            raise IdentityError(ErrorCode.AUTHENTICATION_FAILED, "This identity is not active.")
        self._record(
            SecurityEventType.LOGIN_SUCCEEDED,
            organization_id=user.organization_id,
            actor_id=user.id,
            target_id=user.id,
            request_id=request_id,
            metadata={"email": user.email},
        )
        self.db.commit()
        return user

    # ----------------------------------------------------------------- #
    # Generic lifecycle for status-bearing identities
    # ----------------------------------------------------------------- #
    def transition_status(
        self,
        entity: Any,
        target: IdentityStatus,
        *,
        organization_id: uuid.UUID | None = None,
        actor_id: uuid.UUID | None = None,
        request_id: str | None = None,
    ) -> Any:
        """Move an identity with a ``status`` column to a new lifecycle state."""
        current = IdentityStatus(entity.status)
        if not can_transition(current, target):
            raise IdentityError(
                ErrorCode.INVALID_LIFECYCLE_TRANSITION,
                f"Cannot transition from {current.value} to {target.value}.",
            )
        entity.status = target.value
        self._record(
            SecurityEventType.IDENTITY_LIFECYCLE_CHANGED,
            organization_id=organization_id,
            actor_id=actor_id,
            target_id=getattr(entity, "id", None),
            request_id=request_id,
            metadata={"from": current.value, "to": target.value},
        )
        self.db.commit()
        return entity

    # ----------------------------------------------------------------- #
    # Departments
    # ----------------------------------------------------------------- #
    def create_department(
        self, data: DepartmentCreate, *, actor_id: uuid.UUID | None = None, request_id: str | None = None
    ) -> Department:
        if self.organizations.get(data.organization_id) is None:
            raise IdentityError(ErrorCode.ORGANIZATION_NOT_FOUND, "Organization does not exist.")
        dept = Department(
            organization_id=data.organization_id, name=data.name, manager_id=data.manager_id
        )
        self.departments.add(dept)
        self.db.commit()
        self.db.refresh(dept)
        return dept

    def get_department(self, department_id: uuid.UUID) -> Department:
        dept = self.departments.get(department_id)
        if dept is None:
            raise IdentityError(ErrorCode.DEPARTMENT_NOT_FOUND, "Department does not exist.")
        return dept

    def list_departments(self, organization_id: uuid.UUID) -> list[Department]:
        return self.departments.list_by_organization(organization_id)

    # ----------------------------------------------------------------- #
    # Internal
    # ----------------------------------------------------------------- #
    def _record(
        self,
        event_type: SecurityEventType,
        *,
        organization_id: uuid.UUID | None,
        actor_id: uuid.UUID | None,
        target_id: uuid.UUID | None,
        request_id: str | None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        record_security_event(
            self.db,
            event_type=event_type,
            actor_type=IdentityType.HUMAN,
            organization_id=organization_id,
            actor_id=actor_id,
            target_type="user",
            target_id=target_id,
            request_id=request_id,
            metadata=metadata,
        )
