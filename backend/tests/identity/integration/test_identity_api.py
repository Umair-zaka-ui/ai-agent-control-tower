"""Identity API integration tests (versioning, RBAC, error envelope)."""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from app.main import app

BASE = "/api/v1/identity"


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


def _register(client: TestClient) -> tuple[str, uuid.UUID]:
    email = f"owner_{uuid.uuid4().hex[:10]}@example.com"
    token = client.post(
        "/auth/register",
        json={"organization_name": "Identity API Org", "name": "Owner", "email": email, "password": "T3st!Passw0rd#Ok"},
    ).json()["access_token"]
    me = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"}).json()
    return token, uuid.UUID(me["organization_id"])


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_versioned_user_endpoints(client: TestClient) -> None:
    token, org_id = _register(client)
    admin = _auth(token)

    # Create a user under the versioned identity API.
    email = f"member_{uuid.uuid4().hex[:8]}@example.com"
    r = client.post(
        f"{BASE}/users",
        headers=admin,
        json={
            "email": email,
            "display_name": "New Member",
            "password": "Str0ngPass!x2",
            "organization_id": str(org_id),
            "role": "VIEWER",
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["email"] == email and body["display_name"] == "New Member"
    user_id = body["id"]

    # List + get.
    listed = client.get(f"{BASE}/users", headers=admin).json()
    assert any(u["id"] == user_id for u in listed)
    assert client.get(f"{BASE}/users/{user_id}", headers=admin).json()["id"] == user_id

    # Lifecycle: suspend then activate.
    assert client.post(f"{BASE}/users/{user_id}/suspend", headers=admin).json()["is_active"] is False
    assert client.post(f"{BASE}/users/{user_id}/activate", headers=admin).json()["is_active"] is True


def test_error_envelope_and_request_id(client: TestClient) -> None:
    token, _ = _register(client)
    admin = _auth(token)
    missing = uuid.uuid4()
    r = client.get(f"{BASE}/users/{missing}", headers={**admin, "x-request-id": "req-123"})
    assert r.status_code == 404
    body = r.json()
    # Standard envelope (SRS §18): success/error{code,message}/request_id.
    assert body["success"] is False
    assert body["error"]["code"] == "USER_NOT_FOUND"
    assert "message" in body["error"]
    assert body["request_id"] == "req-123"


def test_organizations_departments_roles(client: TestClient) -> None:
    token, org_id = _register(client)
    admin = _auth(token)

    orgs = client.get(f"{BASE}/organizations", headers=admin).json()
    assert len(orgs) == 1 and orgs[0]["id"] == str(org_id)

    dept = client.post(
        f"{BASE}/departments",
        headers=admin,
        json={"organization_id": str(org_id), "name": "Compliance"},
    )
    assert dept.status_code == 201, dept.text
    assert any(d["name"] == "Compliance" for d in client.get(f"{BASE}/departments", headers=admin).json())

    roles = client.get(f"{BASE}/roles", headers=admin).json()
    assert any(r["name"] == "SUPER_ADMIN" for r in roles)


def test_rbac_viewer_cannot_create_users(client: TestClient) -> None:
    token, org_id = _register(client)
    admin = _auth(token)
    # A VIEWER lacks user.create.
    viewer_email = f"viewer_{uuid.uuid4().hex[:8]}@example.com"
    client.post(
        "/users",
        headers=admin,
        json={"name": "Vic", "email": viewer_email, "password": "T3st!Passw0rd#Ok", "role": "VIEWER"},
    )
    vtoken = client.post("/auth/login", json={"email": viewer_email, "password": "T3st!Passw0rd#Ok"}).json()["access_token"]
    r = client.post(
        f"{BASE}/users",
        headers=_auth(vtoken),
        json={
            "email": f"x_{uuid.uuid4().hex[:8]}@example.com",
            "display_name": "X",
            "password": "Str0ngPass!x2",
            "organization_id": str(org_id),
        },
    )
    assert r.status_code == 403


def test_unauthenticated_is_rejected(client: TestClient) -> None:
    # The platform's bearer scheme rejects missing credentials with 403.
    assert client.get(f"{BASE}/users").status_code in (401, 403)


# --------------------------------------------------------------------------- #
# Part 4.1a: unified lifecycle + machine identities
# --------------------------------------------------------------------------- #
def _agent_id(client: TestClient, admin: dict[str, str]) -> str:
    return client.post(
        "/agents", headers=admin, json={"name": "AuditBot", "agent_type": "billing"}
    ).json()["id"]


def test_user_lifecycle_status_endpoint(client: TestClient) -> None:
    token, org_id = _register(client)
    admin = _auth(token)
    email = f"m_{uuid.uuid4().hex[:8]}@example.com"
    user = client.post(
        f"{BASE}/users",
        headers=admin,
        json={"email": email, "display_name": "M", "password": "Str0ngPass!x2", "organization_id": str(org_id)},
    ).json()
    assert user["status"] == "ACTIVE"
    uid = user["id"]

    # ACTIVE → SUSPENDED → ARCHIVED via the generic lifecycle endpoint.
    r = client.post(f"{BASE}/users/{uid}/status", headers=admin, json={"target_status": "SUSPENDED"})
    assert r.status_code == 200 and r.json()["status"] == "SUSPENDED"
    assert r.json()["is_active"] is False  # kept in sync

    r = client.post(f"{BASE}/users/{uid}/status", headers=admin, json={"target_status": "ARCHIVED"})
    assert r.json()["status"] == "ARCHIVED"

    # Illegal jump ARCHIVED → SUSPENDED is rejected with the envelope.
    bad = client.post(f"{BASE}/users/{uid}/status", headers=admin, json={"target_status": "SUSPENDED"})
    assert bad.status_code == 409
    assert bad.json()["error"]["code"] == "INVALID_LIFECYCLE_TRANSITION"


def test_organization_lifecycle(client: TestClient) -> None:
    token, org_id = _register(client)
    admin = _auth(token)
    assert client.get(f"{BASE}/organizations", headers=admin).json()[0]["status"] == "ACTIVE"
    r = client.post(f"{BASE}/organizations/{org_id}/status", headers=admin, json={"target_status": "SUSPENDED"})
    assert r.status_code == 200 and r.json()["status"] == "SUSPENDED"


def test_agent_identity_crud_and_lifecycle(client: TestClient) -> None:
    token, _ = _register(client)
    admin = _auth(token)
    agent_id = _agent_id(client, admin)

    created = client.post(f"{BASE}/agent-identities", headers=admin, json={"agent_id": agent_id})
    assert created.status_code == 201, created.text
    ident = created.json()
    assert ident["status"] == "ACTIVE" and ident["client_id"].startswith("cid_")

    listed = client.get(f"{BASE}/agent-identities", headers=admin, params={"agent_id": agent_id}).json()
    assert any(i["id"] == ident["id"] for i in listed)

    r = client.post(f"{BASE}/agent-identities/{ident['id']}/status", headers=admin, json={"target_status": "SUSPENDED"})
    assert r.json()["status"] == "SUSPENDED"


def test_service_account_and_external_client(client: TestClient) -> None:
    token, org_id = _register(client)
    admin = _auth(token)

    # Service account — secret returned once.
    sa = client.post(
        f"{BASE}/service-accounts",
        headers=admin,
        json={"organization_id": str(org_id), "name": "etl-bot", "permissions": ["analytics.view"]},
    )
    assert sa.status_code == 201, sa.text
    assert sa.json()["client_secret"].startswith("sk_")
    sa_id = sa.json()["id"]
    assert any(a["id"] == sa_id for a in client.get(f"{BASE}/service-accounts", headers=admin).json())
    # List view must never expose the secret.
    assert "client_secret" not in client.get(f"{BASE}/service-accounts", headers=admin).json()[0]
    assert client.post(
        f"{BASE}/service-accounts/{sa_id}/status", headers=admin, json={"target_status": "DISABLED"}
    ).json()["status"] == "DISABLED"

    # External client — secret returned once.
    ec = client.post(
        f"{BASE}/external-clients",
        headers=admin,
        json={"organization_id": str(org_id), "client_name": "Power BI", "allowed_scopes": ["analytics.view"]},
    )
    assert ec.status_code == 201, ec.text
    assert ec.json()["client_secret"].startswith("sk_") and ec.json()["client_id"].startswith("cid_")
    assert any(c["client_name"] == "Power BI" for c in client.get(f"{BASE}/external-clients", headers=admin).json())
