"""Phase 4.3.3 integration tests — hierarchy CRUD, inheritance via resource
ownership, cross-organization isolation, and delegation (§21)."""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient

PASSWORD = "T3st!Passw0rd#Ok"


def _register(client: TestClient) -> dict:
    email = f"hier_{uuid.uuid4().hex[:10]}@example.com"
    assert client.post("/auth/register", json={
        "organization_name": "Hier Org", "name": "Owner", "email": email, "password": PASSWORD,
    }).status_code == 201
    tokens = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD}).json()
    h = {"Authorization": f"Bearer {tokens['access_token']}"}
    me = client.get("/api/v1/auth/me", headers=h).json()
    return {"headers": h, "user_id": me["user"]["id"]}


def _post(client, admin, path, body, expect=201):
    r = client.post(path, json=body, headers=admin["headers"])
    assert r.status_code == expect, r.text
    return r.json()


# --- CRUD chain + tree ----------------------------------------------------- #
def test_full_hierarchy_crud_and_tree(client: TestClient, admin: dict) -> None:
    bu = _post(client, admin, "/api/v1/business-units", {"name": "Healthcare"})
    dept = _post(client, admin, "/api/v1/departments",
                 {"name": "Radiology", "business_unit_id": bu["id"]})
    team = _post(client, admin, "/api/v1/teams", {"name": "AI Ops", "department_id": dept["id"]})
    project = _post(client, admin, "/api/v1/projects", {"name": "Medical AI", "team_id": team["id"]})

    # read back
    assert client.get(f"/api/v1/departments/{dept['id']}", headers=admin["headers"]).json()["business_unit_id"] == bu["id"]

    # tree contains the whole chain
    tree = client.get("/api/v1/hierarchy/tree", headers=admin["headers"]).json()
    assert tree["level"] == "ORGANIZATION"
    bu_node = next(n for n in tree["children"] if n["id"] == bu["id"])
    dept_node = next(n for n in bu_node["children"] if n["id"] == dept["id"])
    team_node = next(n for n in dept_node["children"] if n["id"] == team["id"])
    assert any(p["id"] == project["id"] for p in team_node["children"])


def test_cannot_delete_entity_with_children(client: TestClient, admin: dict) -> None:
    dept = _post(client, admin, "/api/v1/departments", {"name": f"D_{uuid.uuid4().hex[:6]}"})
    _post(client, admin, "/api/v1/teams", {"name": "T", "department_id": dept["id"]})
    resp = client.delete(f"/api/v1/departments/{dept['id']}", headers=admin["headers"])
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "ENTITY_HAS_CHILDREN"


# --- Inheritance via resource ownership (§7, §14) -------------------------- #
def test_department_scoped_grant_inherits_to_resources_below(client: TestClient, admin: dict) -> None:
    # A permission the org owner does NOT hold globally (not in the legacy catalog).
    # Unique per run so the shared test DB stays idempotent across runs.
    perm = f"widget.u{uuid.uuid4().hex[:8]}"
    _post(client, admin, "/api/v1/permissions", {"code": perm}, expect=201)
    role = _post(client, admin, "/api/v1/roles",
                 {"name": f"w_{uuid.uuid4().hex[:6]}", "permissions": [perm]})

    dept = _post(client, admin, "/api/v1/departments", {"name": f"Dpt_{uuid.uuid4().hex[:6]}"})
    team = _post(client, admin, "/api/v1/teams", {"name": "T", "department_id": dept["id"]})
    project = _post(client, admin, "/api/v1/projects", {"name": "P", "team_id": team["id"]})

    # Scope the role to the department.
    _post(client, admin, "/api/v1/role-assignments", {
        "user_id": admin["user_id"], "role_id": role["id"],
        "scope": "DEPARTMENT", "department_id": dept["id"],
    })

    inside = str(uuid.uuid4())
    outside = str(uuid.uuid4())
    # inside: an agent owned under the project (path includes the department).
    _post(client, admin, "/api/v1/resource-ownership",
          {"resource_type": "agent", "resource_id": inside, "project_id": project["id"]})
    # outside: an agent with no department path (org-level only).
    _post(client, admin, "/api/v1/resource-ownership",
          {"resource_type": "agent", "resource_id": outside})

    def check(rid):
        return client.post("/api/v1/authorization/check", headers=admin["headers"], json={
            "permission": perm, "resource_type": "agent", "resource_id": rid,
        }).json()

    assert check(inside)["allowed"] is True, "department grant should inherit to a resource below it"
    assert check(outside)["allowed"] is False, "department grant must not apply outside the department"
    # A resource-less check is not satisfied by a department-scoped grant.
    assert client.post("/api/v1/authorization/check", headers=admin["headers"],
                       json={"permission": perm}).json()["allowed"] is False


# --- Cross-organization isolation (§9) ------------------------------------- #
def test_cross_org_isolation_on_lookup_and_check(client: TestClient, admin: dict) -> None:
    other = _register(client)
    # `admin` creates a department; `other` (different org) cannot see it.
    dept = _post(client, admin, "/api/v1/departments", {"name": "Secret"})
    assert client.get(f"/api/v1/departments/{dept['id']}", headers=other["headers"]).status_code == 404

    # A resource owned by `admin`'s org: `other` is denied at authorization time.
    rid = str(uuid.uuid4())
    _post(client, admin, "/api/v1/resource-ownership", {"resource_type": "agent", "resource_id": rid})
    result = client.post("/api/v1/authorization/check", headers=other["headers"], json={
        "permission": "agent.view", "resource_type": "agent", "resource_id": rid,
    }).json()
    assert result["allowed"] is False
    assert "cross-organization" in result["reason"].lower()


# --- Delegation (§10, §19) ------------------------------------------------- #
def test_delegation_lifecycle_and_boundary(client: TestClient, admin: dict) -> None:
    # Delegate ORGANIZATION-scope admin to the same owner (valid within own org).
    deleg = _post(client, admin, "/api/v1/delegations", {
        "delegatee_id": admin["user_id"], "scope_type": "ORGANIZATION",
    })
    assert deleg["revoked_at"] is None
    listing = client.get("/api/v1/delegations", headers=admin["headers"]).json()
    assert any(d["id"] == deleg["id"] for d in listing)

    # Cannot delegate a department in another org.
    other = _register(client)
    other_dept = _post(client, other, "/api/v1/departments", {"name": "Theirs"})
    bad = client.post("/api/v1/delegations", headers=admin["headers"], json={
        "delegatee_id": admin["user_id"], "scope_type": "DEPARTMENT", "scope_id": other_dept["id"],
    })
    assert bad.status_code == 403
    assert bad.json()["error"]["code"] == "DELEGATION_EXCEEDS_AUTHORITY"

    # Revoke.
    revoked = client.delete(f"/api/v1/delegations/{deleg['id']}", headers=admin["headers"]).json()
    assert revoked["revoked_at"] is not None


def test_hierarchy_endpoints_require_auth(client: TestClient) -> None:
    assert client.get("/api/v1/departments").status_code in (401, 403)
    assert client.get("/api/v1/hierarchy/tree").status_code in (401, 403)
