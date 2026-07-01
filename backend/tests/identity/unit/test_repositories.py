"""DB-backed repository + IdentityService unit tests."""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from app.core.database import SessionLocal
from app.identity.errors import IdentityError
from app.identity.models.enums import IdentityStatus
from app.identity.models.service_account import ServiceAccount
from app.identity.repositories.department_repository import DepartmentRepository
from app.identity.repositories.user_repository import UserRepository
from app.identity.schemas.identity import DepartmentCreate, UserCreate
from app.identity.security.passwords import hash_secret
from app.identity.services.identity_service import IdentityService
from app.main import app
from app.models.user import User


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


def _register_org(client: TestClient) -> uuid.UUID:
    """Bootstrap an org + SUPER_ADMIN and return the organization id."""
    email = f"owner_{uuid.uuid4().hex[:10]}@example.com"
    token = client.post(
        "/auth/register",
        json={"organization_name": "Identity Org", "name": "Owner", "email": email, "password": "password123"},
    ).json()["access_token"]
    me = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"}).json()
    return uuid.UUID(me["organization_id"])


def test_user_repository_and_service(client: TestClient) -> None:
    org_id = _register_org(client)
    db = SessionLocal()
    try:
        service = IdentityService(db)
        created = service.create_user(
            UserCreate(
                email=f"u_{uuid.uuid4().hex[:8]}@example.com",
                display_name="Ada Lovelace",
                password="Str0ngPass",
                organization_id=org_id,
                role="REVIEWER",
            )
        )
        assert created.id is not None

        repo = UserRepository(db)
        assert repo.get(created.id) is not None
        assert repo.get_by_email(created.email) is not None
        assert any(u.id == created.id for u in repo.list_by_organization(org_id))

        # Duplicate email is a conflict.
        with pytest.raises(IdentityError):
            service.create_user(
                UserCreate(
                    email=created.email,
                    display_name="Dup",
                    password="Str0ngPass",
                    organization_id=org_id,
                )
            )
    finally:
        db.close()


def test_department_repository(client: TestClient) -> None:
    org_id = _register_org(client)
    db = SessionLocal()
    try:
        service = IdentityService(db)
        dept = service.create_department(DepartmentCreate(organization_id=org_id, name="Billing"))
        assert dept.id is not None
        repo = DepartmentRepository(db)
        assert any(d.id == dept.id for d in repo.list_by_organization(org_id))
    finally:
        db.close()


def test_service_account_lifecycle_transition(client: TestClient) -> None:
    org_id = _register_org(client)
    db = SessionLocal()
    try:
        sa = ServiceAccount(
            organization_id=org_id,
            name="etl-bot",
            client_secret_hash=hash_secret("secret"),
            permissions=["analytics.view"],
            status=IdentityStatus.ACTIVE.value,
        )
        db.add(sa)
        db.commit()

        service = IdentityService(db)
        service.transition_status(sa, IdentityStatus.SUSPENDED, organization_id=org_id)
        assert sa.status == IdentityStatus.SUSPENDED.value

        # Illegal transition (SUSPENDED → CREATED) is rejected.
        with pytest.raises(IdentityError):
            service.transition_status(sa, IdentityStatus.CREATED, organization_id=org_id)
    finally:
        db.close()


def test_authenticate(client: TestClient) -> None:
    org_id = _register_org(client)
    db = SessionLocal()
    try:
        service = IdentityService(db)
        email = f"auth_{uuid.uuid4().hex[:8]}@example.com"
        service.create_user(
            UserCreate(email=email, display_name="Auth User", password="Str0ngPass", organization_id=org_id)
        )
        assert service.authenticate(email, "Str0ngPass").email == email
        with pytest.raises(IdentityError):
            service.authenticate(email, "wrong-password")
    finally:
        db.close()
