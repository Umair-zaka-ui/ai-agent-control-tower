"""Authentication service - registration and credential verification."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.enums import ActorType, UserRole
from app.core.security import hash_password, verify_password
from app.models.organization import Organization
from app.models.user import User
from app.services import audit_service, rbac_service


def email_exists(db: Session, email: str) -> bool:
    return db.execute(
        select(User.id).where(User.email == email)
    ).scalar_one_or_none() is not None


def register_organization(
    db: Session,
    *,
    organization_name: str,
    name: str,
    email: str,
    password: str,
) -> User:
    """Create a new organization with its first SUPER_ADMIN user and seed RBAC."""
    organization = Organization(name=organization_name)
    db.add(organization)
    db.flush()

    user = User(
        organization_id=organization.id,
        name=name,
        email=email,
        password_hash=hash_password(password),
        role=UserRole.SUPER_ADMIN,
        is_active=True,
    )
    db.add(user)
    db.flush()

    # Seed the RBAC catalog/roles and link this user to the SUPER_ADMIN role.
    rbac_service.seed_rbac(db, organization)

    audit_service.log_event(
        db,
        organization_id=organization.id,
        actor_type=ActorType.USER,
        actor_id=user.id,
        event_type="USER_REGISTERED",
        entity_type="user",
        entity_id=user.id,
        metadata={"email": user.email, "role": user.role.value},
    )
    return user


def authenticate_user(db: Session, email: str, password: str) -> User | None:
    user = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
    if user is None or not verify_password(password, user.password_hash):
        return None
    return user
