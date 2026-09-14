"""Fixtures for the Phase 5.6 (M5.6) Runtime Threat Detection & Containment
tests. Mirrors ``tests/posture/conftest.py`` -- a new top-level domain gets
its own test directory and its own minimal ``client``/``admin``/``db_session``
fixtures, the established convention for every prior domain in this codebase.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from app.authorization.seeding import seed_authorization
from app.core.database import SessionLocal
from app.main import app

PASSWORD = "T3st!Passw0rd#Ok"


@pytest.fixture(scope="session", autouse=True)
def _seed_authorization_once() -> None:
    db = SessionLocal()
    try:
        seed_authorization(db)
        db.commit()
    finally:
        db.close()


@pytest.fixture()
def db_session():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.rollback()
        db.close()


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


def register_org(client: TestClient, org_name: str) -> dict:
    email = f"threat_{uuid.uuid4().hex[:10]}@example.com"
    reg = client.post(
        "/auth/register",
        json={"organization_name": org_name, "name": "Owner", "email": email, "password": PASSWORD},
    )
    assert reg.status_code == 201, reg.text
    tokens = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD}).json()
    h = {"Authorization": f"Bearer {tokens['access_token']}"}
    me = client.get("/api/v1/auth/me", headers=h).json()
    return {
        "headers": h,
        "user_id": me["user"]["id"],
        "organization_id": me["user"]["organization_id"],
        "email": email,
    }


@pytest.fixture()
def admin(client: TestClient) -> dict:
    return register_org(client, "Threat Org")


@pytest.fixture()
def other_org_admin(client: TestClient) -> dict:
    return register_org(client, "Other Threat Org")
