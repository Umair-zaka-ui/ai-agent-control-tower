"""IdentityService — the single entry point for identity operations (SRS §15).

Responsibilities: create / update / suspend / activate / archive / delete /
validate / authenticate identities, and register audit events for every change.
Controllers call this service; the service calls repositories; repositories touch
the database (SRS §13). The service owns the transaction (commit).
"""

from __future__ import annotations

import secrets
import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.core.enums import UserRole
from app.core.security import verify_password
from app.identity.audit.events import record_security_event
from app.identity.errors import ErrorCode, IdentityError
from app.identity.models.agent_identity import AgentIdentity
from app.identity.models.department import Department
from app.identity.models.enums import (
    IdentityStatus,
    IdentityType,
    SecurityEventType,
    can_transition,
)
from app.identity.models.external_client import ExternalClient
from app.identity.models.service_account import ServiceAccount
from app.identity.repositories.department_repository import DepartmentRepository
from app.identity.repositories.identity_repositories import (
    AgentIdentityRepository,
    ExternalClientRepository,
    ServiceAccountRepository,
)
from app.identity.repositories.organization_repository import OrganizationRepository
from app.identity.repositories.session_repository import SessionRepository
from app.identity.repositories.user_repository import UserRepository
from app.identity.schemas.identity import (
    AgentIdentityCreate,
    DepartmentCreate,
    ExternalClientCreate,
    ServiceAccountCreate,
    UserCreate,
)
from app.identity.security.passwords import (
    PasswordPolicyError,
    generate_client_secret,
    hash_secret,
    hash_user_password,
)
from app.models.agent import Agent
from app.models.user import User


class IdentityService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.users = UserRepository(db)
        self.departments = DepartmentRepository(db)
        self.organizations = OrganizationRepository(db)
        self.sessions = SessionRepository(db)
        self.agent_identities = AgentIdentityRepository(db)
        self.service_accounts = ServiceAccountRepository(db)
        self.external_clients = ExternalClientRepository(db)

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
            password_hash = hash_user_password(
                data.password, email=data.email, username=data.display_name
            )
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
        user.status = IdentityStatus.ACTIVE.value if active else IdentityStatus.SUSPENDED.value
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
        actor_type: IdentityType = IdentityType.HUMAN,
        target_type: str = "identity",
        request_id: str | None = None,
    ) -> Any:
        """Move any identity with a ``status`` column to a new lifecycle state.

        Works uniformly across humans, organizations, agent identities, service
        accounts and external clients. For humans, ``is_active`` is kept in sync
        so authentication continues to honour the lifecycle.
        """
        current = IdentityStatus(entity.status)
        if not can_transition(current, target):
            raise IdentityError(
                ErrorCode.INVALID_LIFECYCLE_TRANSITION,
                f"Cannot transition from {current.value} to {target.value}.",
            )
        entity.status = target.value
        if isinstance(entity, User):
            entity.is_active = target == IdentityStatus.ACTIVE
        record_security_event(
            self.db,
            event_type=SecurityEventType.IDENTITY_LIFECYCLE_CHANGED,
            actor_type=actor_type,
            organization_id=organization_id,
            actor_id=actor_id,
            target_type=target_type,
            target_id=getattr(entity, "id", None),
            request_id=request_id,
            metadata={"from": current.value, "to": target.value},
        )
        self.db.commit()
        return entity

    def transition_user(
        self,
        user_id: uuid.UUID,
        target: IdentityStatus,
        *,
        actor_id: uuid.UUID | None = None,
        request_id: str | None = None,
    ) -> User:
        user = self.get_user(user_id)
        return self.transition_status(
            user,
            target,
            organization_id=user.organization_id,
            actor_id=actor_id,
            target_type="user",
            request_id=request_id,
        )

    def transition_organization(
        self,
        organization_id: uuid.UUID,
        target: IdentityStatus,
        *,
        actor_id: uuid.UUID | None = None,
        request_id: str | None = None,
    ) -> Any:
        org = self.organizations.get(organization_id)
        if org is None:
            raise IdentityError(ErrorCode.ORGANIZATION_NOT_FOUND, "Organization does not exist.")
        return self.transition_status(
            org,
            target,
            organization_id=org.id,
            actor_id=actor_id,
            actor_type=IdentityType.ORGANIZATION,
            target_type="organization",
            request_id=request_id,
        )

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
    # AI agent identities
    # ----------------------------------------------------------------- #
    def create_agent_identity(
        self,
        data: AgentIdentityCreate,
        *,
        organization_id: uuid.UUID,
        actor_id: uuid.UUID | None = None,
        request_id: str | None = None,
    ) -> AgentIdentity:
        agent = self.db.get(Agent, data.agent_id)
        if agent is None or agent.organization_id != organization_id:
            raise IdentityError(ErrorCode.IDENTITY_NOT_FOUND, "Agent does not exist.")
        identity = AgentIdentity(
            agent_id=data.agent_id,
            client_id=f"cid_{secrets.token_urlsafe(16)}",
            credential_type=data.credential_type,
            status=IdentityStatus.ACTIVE.value,
        )
        self.agent_identities.add(identity)
        self._record_machine(
            organization_id=organization_id,
            actor_type=IdentityType.AI_AGENT,
            actor_id=actor_id,
            target_type="agent_identity",
            target_id=identity.id,
            request_id=request_id,
            metadata={"action": "created", "agent_id": str(data.agent_id)},
        )
        self.db.commit()
        self.db.refresh(identity)
        return identity

    def list_agent_identities(self, agent_id: uuid.UUID) -> list[AgentIdentity]:
        return self.agent_identities.list_by_agent(agent_id)

    def get_agent_identity(self, identity_id: uuid.UUID) -> AgentIdentity:
        identity = self.agent_identities.get(identity_id)
        if identity is None:
            raise IdentityError(ErrorCode.AGENT_IDENTITY_NOT_FOUND, "Agent identity does not exist.")
        return identity

    # ----------------------------------------------------------------- #
    # Service accounts
    # ----------------------------------------------------------------- #
    def create_service_account(
        self,
        data: ServiceAccountCreate,
        *,
        actor_id: uuid.UUID | None = None,
        request_id: str | None = None,
    ) -> tuple[ServiceAccount, str]:
        if self.organizations.get(data.organization_id) is None:
            raise IdentityError(ErrorCode.ORGANIZATION_NOT_FOUND, "Organization does not exist.")
        secret = generate_client_secret()
        account = ServiceAccount(
            organization_id=data.organization_id,
            name=data.name,
            client_secret_hash=hash_secret(secret),
            permissions=list(data.permissions),
            owner_id=data.owner_id,
            status=IdentityStatus.ACTIVE.value,
        )
        self.service_accounts.add(account)
        self._record_machine(
            organization_id=data.organization_id,
            actor_type=IdentityType.SERVICE_ACCOUNT,
            actor_id=actor_id,
            target_type="service_account",
            target_id=account.id,
            request_id=request_id,
            metadata={"action": "created", "name": data.name},
        )
        self.db.commit()
        self.db.refresh(account)
        return account, secret

    def list_service_accounts(self, organization_id: uuid.UUID) -> list[ServiceAccount]:
        return self.service_accounts.list_by_organization(organization_id)

    def get_service_account(self, account_id: uuid.UUID) -> ServiceAccount:
        account = self.service_accounts.get(account_id)
        if account is None:
            raise IdentityError(ErrorCode.SERVICE_ACCOUNT_NOT_FOUND, "Service account does not exist.")
        return account

    # ----------------------------------------------------------------- #
    # External clients
    # ----------------------------------------------------------------- #
    def create_external_client(
        self,
        data: ExternalClientCreate,
        *,
        actor_id: uuid.UUID | None = None,
        request_id: str | None = None,
    ) -> tuple[ExternalClient, str]:
        if self.organizations.get(data.organization_id) is None:
            raise IdentityError(ErrorCode.ORGANIZATION_NOT_FOUND, "Organization does not exist.")
        secret = generate_client_secret()
        client = ExternalClient(
            organization_id=data.organization_id,
            client_name=data.client_name,
            client_id=f"cid_{secrets.token_urlsafe(16)}",
            redirect_uri=data.redirect_uri,
            secret_hash=hash_secret(secret),
            allowed_scopes=list(data.allowed_scopes),
            status=IdentityStatus.ACTIVE.value,
        )
        self.external_clients.add(client)
        self._record_machine(
            organization_id=data.organization_id,
            actor_type=IdentityType.EXTERNAL_CLIENT,
            actor_id=actor_id,
            target_type="external_client",
            target_id=client.id,
            request_id=request_id,
            metadata={"action": "created", "client_name": data.client_name},
        )
        self.db.commit()
        self.db.refresh(client)
        return client, secret

    def list_external_clients(self, organization_id: uuid.UUID) -> list[ExternalClient]:
        return self.external_clients.list_by_organization(organization_id)

    def get_external_client(self, client_id: uuid.UUID) -> ExternalClient:
        client = self.external_clients.get(client_id)
        if client is None:
            raise IdentityError(ErrorCode.EXTERNAL_CLIENT_NOT_FOUND, "External client does not exist.")
        return client

    # ----------------------------------------------------------------- #
    # Internal
    # ----------------------------------------------------------------- #
    def _record_machine(
        self,
        *,
        organization_id: uuid.UUID | None,
        actor_type: IdentityType,
        actor_id: uuid.UUID | None,
        target_type: str,
        target_id: uuid.UUID | None,
        request_id: str | None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        record_security_event(
            self.db,
            event_type=SecurityEventType.IDENTITY_LIFECYCLE_CHANGED,
            actor_type=actor_type,
            organization_id=organization_id,
            actor_id=actor_id,
            target_type=target_type,
            target_id=target_id,
            request_id=request_id,
            metadata=metadata,
        )

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
