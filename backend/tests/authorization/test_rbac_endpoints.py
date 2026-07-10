"""Phase 4.3.1 integration tests: role/permission CRUD, scoped assignment,
hierarchy + inheritance, and audit (§27, §29)."""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient


def _new_role(client: TestClient, admin: dict, **over) -> dict:
    body = {"name": f"role_{uuid.uuid4().hex[:8]}", "category": "CUSTOM",
            "priority": 40, "permissions": ["agent.view"], **over}
    resp = client.post("/api/v1/roles", json=body, headers=admin["headers"])
    assert resp.status_code == 201, resp.text
    return resp.json()


# --- auth gating ----------------------------------------------------------- #
def test_endpoints_require_authentication(client: TestClient) -> None:
    # Missing credentials is denied. HTTPBearer answers a *missing* header with 403
    # (a present-but-invalid token is 401); either way the endpoint is protected.
    assert client.get("/api/v1/roles").status_code in (401, 403)
    assert client.post("/api/v1/roles", json={"name": "x"}).status_code in (401, 403)


# --- roles: list includes built-ins, full CRUD ----------------------------- #
def test_list_roles_includes_builtin_taxonomy(client: TestClient, admin: dict) -> None:
    roles = client.get("/api/v1/roles", headers=admin["headers"]).json()
    names = {r["name"] for r in roles}
    assert "ROLE_PLATFORM_OWNER" in names
    assert "ROLE_VIEWER" in names
    # Built-ins are system + sorted by priority desc (owner first).
    owner = next(r for r in roles if r["name"] == "ROLE_PLATFORM_OWNER")
    assert owner["is_system"] and owner["priority"] == 100
    assert owner["category"] == "SYSTEM"


def test_role_crud_lifecycle(client: TestClient, admin: dict) -> None:
    role = _new_role(client, admin, description="a custom role")
    rid = role["id"]
    assert role["permissions"] == ["agent.view"]
    assert role["is_system"] is False

    # get
    got = client.get(f"/api/v1/roles/{rid}", headers=admin["headers"])
    assert got.status_code == 200
    assert got.json()["assignment_count"] == 0

    # update permissions + status
    upd = client.put(
        f"/api/v1/roles/{rid}",
        json={"display_name": "Renamed", "permissions": ["agent.view", "policy.view"],
              "priority": 42},
        headers=admin["headers"],
    )
    assert upd.status_code == 200
    assert sorted(upd.json()["permissions"]) == ["agent.view", "policy.view"]
    assert upd.json()["display_name"] == "Renamed"

    # delete
    assert client.delete(f"/api/v1/roles/{rid}", headers=admin["headers"]).status_code == 204
    assert client.get(f"/api/v1/roles/{rid}", headers=admin["headers"]).status_code == 404


def test_duplicate_role_name_conflicts(client: TestClient, admin: dict) -> None:
    role = _new_role(client, admin)
    dup = client.post("/api/v1/roles", json={"name": role["name"], "permissions": []},
                      headers=admin["headers"])
    assert dup.status_code == 409
    assert dup.json()["error"]["code"] == "ROLE_ALREADY_EXISTS"


def test_system_role_is_protected(client: TestClient, admin: dict) -> None:
    roles = client.get("/api/v1/roles", headers=admin["headers"]).json()
    viewer = next(r for r in roles if r["name"] == "ROLE_VIEWER")
    resp = client.delete(f"/api/v1/roles/{viewer['id']}", headers=admin["headers"])
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "SYSTEM_ROLE_PROTECTED"


# --- permissions ----------------------------------------------------------- #
def test_permission_create_validation(client: TestClient, admin: dict) -> None:
    ok = client.post("/api/v1/permissions",
                     json={"code": "widget.build", "description": "Build widgets"},
                     headers=admin["headers"])
    assert ok.status_code in (201, 409)  # 409 if a prior run already created it

    bad = client.post("/api/v1/permissions", json={"code": "Widget Build"},
                      headers=admin["headers"])
    assert bad.status_code == 422
    assert bad.json()["error"]["code"] == "INVALID_PERMISSION_NAME"


def test_permission_groups_seeded(client: TestClient, admin: dict) -> None:
    groups = client.get("/api/v1/permission-groups", headers=admin["headers"]).json()
    names = {g["name"] for g in groups}
    assert {"agents", "security", "authorization"}.issubset(names)


# --- assignments + scope --------------------------------------------------- #
def test_scoped_role_assignment_lifecycle(client: TestClient, admin: dict) -> None:
    role = _new_role(client, admin)
    # ORGANIZATION-scoped assignment onto the admin themselves.
    resp = client.post(
        "/api/v1/role-assignments",
        json={"user_id": admin["user_id"], "role_id": role["id"], "scope": "ORGANIZATION"},
        headers=admin["headers"],
    )
    assert resp.status_code == 201, resp.text
    assignment_id = resp.json()["id"]
    assert resp.json()["scope"] == "ORGANIZATION"

    # the role now has an assignment → cannot be deleted
    del_resp = client.delete(f"/api/v1/roles/{role['id']}", headers=admin["headers"])
    assert del_resp.status_code == 409
    assert del_resp.json()["error"]["code"] == "ROLE_HAS_ASSIGNMENTS"

    # list + remove
    listing = client.get(f"/api/v1/role-assignments?user_id={admin['user_id']}",
                         headers=admin["headers"]).json()
    assert any(a["id"] == assignment_id for a in listing)
    assert client.delete(f"/api/v1/role-assignments/{assignment_id}",
                        headers=admin["headers"]).status_code == 204


def test_invalid_scope_missing_target(client: TestClient, admin: dict) -> None:
    role = _new_role(client, admin)
    resp = client.post(
        "/api/v1/role-assignments",
        json={"user_id": admin["user_id"], "role_id": role["id"], "scope": "DEPARTMENT"},
        headers=admin["headers"],
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "INVALID_SCOPE"


# --- hierarchy + inheritance ----------------------------------------------- #
def test_hierarchy_edge_and_effective_permissions(client: TestClient, admin: dict) -> None:
    parent = _new_role(client, admin, permissions=["policy.view"])
    child = _new_role(client, admin, permissions=["agent.view", "dashboard.view"])

    edge = client.post("/api/v1/role-hierarchy",
                       json={"parent_role_id": parent["id"], "child_role_id": child["id"]},
                       headers=admin["headers"])
    assert edge.status_code == 201, edge.text

    eff = client.get(f"/api/v1/roles/{parent['id']}/effective-permissions",
                     headers=admin["headers"]).json()
    # parent inherits child's permissions (§17)
    assert set(eff["permissions"]) == {"policy.view", "agent.view", "dashboard.view"}


def test_hierarchy_cycle_rejected(client: TestClient, admin: dict) -> None:
    a = _new_role(client, admin)
    b = _new_role(client, admin)
    assert client.post("/api/v1/role-hierarchy",
                       json={"parent_role_id": a["id"], "child_role_id": b["id"]},
                       headers=admin["headers"]).status_code == 201
    cyc = client.post("/api/v1/role-hierarchy",
                      json={"parent_role_id": b["id"], "child_role_id": a["id"]},
                      headers=admin["headers"])
    assert cyc.status_code == 409
    assert cyc.json()["error"]["code"] == "CIRCULAR_ROLE_HIERARCHY"


# --- audit (§23) ----------------------------------------------------------- #
def test_authorization_audit_records_role_changes(client: TestClient, admin: dict) -> None:
    role = _new_role(client, admin)
    audit = client.get("/api/v1/authorization/audit?event_type=ROLE_CREATED",
                       headers=admin["headers"]).json()
    assert any(
        (row.get("meta") or {}).get("role_id") == role["id"] for row in audit
    ), "ROLE_CREATED not recorded in the authorization audit"
