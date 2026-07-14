"""Phase 4.3.4 tests — resource registry, ownership + transfer, ACL evaluation
(explicit deny precedence, expiry), sharing, delegation lifecycle, visibility,
resource policy, cross-tenant isolation and the authorization inspector (§26)."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

PASSWORD = "T3st!Passw0rd#Ok"


def _register_org(client: TestClient, org: str = "Res Org") -> dict:
    email = f"res_{uuid.uuid4().hex[:10]}@example.com"
    assert client.post("/auth/register", json={
        "organization_name": org, "name": "Owner", "email": email, "password": PASSWORD,
    }).status_code == 201, "registration failed"
    tokens = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD}).json()
    h = {"Authorization": f"Bearer {tokens['access_token']}"}
    me = client.get("/api/v1/auth/me", headers=h).json()
    return {"headers": h, "user_id": me["user"]["id"],
            "organization_id": me["user"]["organization_id"], "email": email}


def _org_id(client: TestClient, who: dict) -> str:
    if "organization_id" not in who:
        me = client.get("/api/v1/auth/me", headers=who["headers"]).json()
        who["organization_id"] = me["user"]["organization_id"]
    return who["organization_id"]


def _invite_member(client: TestClient, admin: dict, *, role: str = "VIEWER",
                   department_id: str | None = None) -> dict:
    """A second identity in the same org (legacy role VIEWER — no resource powers)."""
    email = f"member_{uuid.uuid4().hex[:10]}@example.com"
    r = client.post("/api/v1/identity/users", headers=admin["headers"], json={
        "email": email, "display_name": "Member", "password": PASSWORD, "role": role,
        "organization_id": _org_id(client, admin), "department_id": department_id,
    })
    assert r.status_code in (200, 201), r.text
    tokens = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD}).json()
    assert "access_token" in tokens, tokens
    h = {"Authorization": f"Bearer {tokens['access_token']}"}
    me = client.get("/api/v1/auth/me", headers=h).json()
    return {"headers": h, "user_id": me["user"]["id"], "email": email}


def _register_resource(client: TestClient, who: dict, **overrides) -> dict:
    body = {"resource_type": "ai_agent", "name": "Agent X", "visibility": "PRIVATE"}
    body.update(overrides)
    r = client.post("/api/v1/resources", json=body, headers=who["headers"])
    assert r.status_code == 201, r.text
    return r.json()


def _authorize(client: TestClient, who: dict, resource_pk: str, permission: str,
               identity_id: str | None = None) -> dict:
    body: dict = {"permission": permission}
    if identity_id:
        body["identity_id"] = identity_id
    r = client.post(f"/api/v1/resources/{resource_pk}/authorize", json=body, headers=who["headers"])
    assert r.status_code == 200, r.text
    return r.json()


def _iso(**delta) -> str:
    return (datetime.now(timezone.utc) + timedelta(**delta)).isoformat()


# --- Registry + ownership (§6, §7) ------------------------------------------ #
def test_register_and_owner_full_access(client: TestClient, admin: dict) -> None:
    res = _register_resource(client, admin)
    assert res["owner_type"] == "USER"
    owner = client.get(f"/api/v1/resources/{res['id']}/owner", headers=admin["headers"]).json()
    assert owner["owner_id"] == admin["user_id"]

    # The owner may do everything on their resource (§7).
    for perm in ("ai_agent.view", "ai_agent.update", "ai_agent.delete", "ai_agent.share"):
        d = _authorize(client, admin, res["id"], perm)
        assert d["allowed"] is True, f"{perm}: {d}"
        assert d["source"] == "OWNER"


def test_non_owner_default_deny(client: TestClient, admin: dict) -> None:
    member = _invite_member(client, admin)
    res = _register_resource(client, admin)
    d = _authorize(client, member, res["id"], "ai_agent.update")
    assert d["allowed"] is False
    assert d["source"] == "DEFAULT_DENY"


# --- Ownership transfer (§8, §22) -------------------------------------------- #
def test_ownership_transfer_audited_with_history(client: TestClient, admin: dict) -> None:
    member = _invite_member(client, admin)
    res = _register_resource(client, admin)

    r = client.post(f"/api/v1/resources/{res['id']}/transfer-ownership",
                    json={"new_owner_id": member["user_id"], "new_owner_type": "USER",
                          "reason": "handover"},
                    headers=admin["headers"])
    assert r.status_code == 200, r.text
    assert r.json()["owner_id"] == member["user_id"]

    # History preserved (§8).
    hist = client.get(f"/api/v1/resources/{res['id']}/ownership-history",
                      headers=admin["headers"]).json()
    assert len(hist) == 1
    assert hist[0]["previous_owner"] == admin["user_id"]
    assert hist[0]["new_owner"] == member["user_id"]
    assert hist[0]["reason"] == "handover"

    # Audit event generated (§23).
    audit = client.get("/api/v1/authorization/audit?event_type=RESOURCE_OWNER_CHANGED",
                       headers=admin["headers"]).json()
    assert any(a["meta"] and a["meta"].get("resource_pk") == res["id"] for a in audit)

    # The new owner now holds full access; the old owner falls back to RBAC only.
    assert _authorize(client, member, res["id"], "ai_agent.update")["source"] == "OWNER"


def test_unauthorized_ownership_transfer_denied(client: TestClient, admin: dict) -> None:
    member = _invite_member(client, admin)
    res = _register_resource(client, admin)
    r = client.post(f"/api/v1/resources/{res['id']}/transfer-ownership",
                    json={"new_owner_id": member["user_id"], "new_owner_type": "USER"},
                    headers=member["headers"])
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "OWNER_TRANSFER_NOT_ALLOWED"


# --- ACL (§10, §11, §22) ------------------------------------------------------ #
def test_acl_allow_grants_and_deny_overrides(client: TestClient, admin: dict) -> None:
    member = _invite_member(client, admin)
    res = _register_resource(client, admin)

    # ALLOW grants a non-owner the action (§11 explicit allow).
    allow = client.post(f"/api/v1/resources/{res['id']}/acl", headers=admin["headers"], json={
        "principal_type": "USER", "principal_id": member["user_id"],
        "permission": "ai_agent.update", "effect": "ALLOW",
    })
    assert allow.status_code == 201, allow.text
    d = _authorize(client, member, res["id"], "ai_agent.update")
    assert d["allowed"] is True and d["source"] == "ACL"
    assert d["matched_rule_id"] == allow.json()["id"]

    # Explicit DENY always overrides allow (§11).
    deny = client.post(f"/api/v1/resources/{res['id']}/acl", headers=admin["headers"], json={
        "principal_type": "USER", "principal_id": member["user_id"],
        "permission": "ai_agent.update", "effect": "DENY",
    })
    assert deny.status_code == 201
    d = _authorize(client, member, res["id"], "ai_agent.update")
    assert d["allowed"] is False and d["source"] == "ACL_DENY"

    # Removing the deny restores the allow; removal is audited.
    assert client.delete(f"/api/v1/resources/{res['id']}/acl/{deny.json()['id']}",
                         headers=admin["headers"]).status_code == 204
    assert _authorize(client, member, res["id"], "ai_agent.update")["allowed"] is True


def test_expired_acl_entries_are_ignored(client: TestClient, admin: dict) -> None:
    member = _invite_member(client, admin)
    res = _register_resource(client, admin)
    r = client.post(f"/api/v1/resources/{res['id']}/acl", headers=admin["headers"], json={
        "principal_type": "USER", "principal_id": member["user_id"],
        "permission": "*", "effect": "ALLOW", "expires_at": _iso(minutes=-5),
    })
    assert r.status_code == 201
    assert _authorize(client, member, res["id"], "ai_agent.view")["allowed"] is False


def test_acl_modification_requires_authorization(client: TestClient, admin: dict) -> None:
    member = _invite_member(client, admin)
    res = _register_resource(client, admin)
    r = client.post(f"/api/v1/resources/{res['id']}/acl", headers=member["headers"], json={
        "principal_type": "USER", "principal_id": member["user_id"],
        "permission": "*", "effect": "ALLOW",
    })
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "RESOURCE_OWNER_REQUIRED"


# --- Sharing (§12) -------------------------------------------------------------- #
def test_share_with_user_maps_access_levels(client: TestClient, admin: dict) -> None:
    member = _invite_member(client, admin)
    res = _register_resource(client, admin)

    share = client.post(f"/api/v1/resources/{res['id']}/share", headers=admin["headers"], json={
        "shared_with_type": "USER", "shared_with_id": member["user_id"], "access_level": "READ",
    })
    assert share.status_code == 201, share.text

    assert _authorize(client, member, res["id"], "ai_agent.view")["source"] == "SHARE"
    assert _authorize(client, member, res["id"], "ai_agent.update")["allowed"] is False

    # Upgrade to EDIT → update allowed, delete still denied.
    up = client.put(f"/api/v1/resources/{res['id']}/share/{share.json()['id']}",
                    headers=admin["headers"], json={"access_level": "EDIT"})
    assert up.status_code == 200
    assert _authorize(client, member, res["id"], "ai_agent.update")["allowed"] is True
    assert _authorize(client, member, res["id"], "ai_agent.delete")["allowed"] is False

    # Revoke → back to default deny (audited as RESOURCE_UNSHARED).
    assert client.delete(f"/api/v1/resources/{res['id']}/share/{share.json()['id']}",
                         headers=admin["headers"]).status_code == 204
    assert _authorize(client, member, res["id"], "ai_agent.view")["allowed"] is False


def test_share_with_team_and_department(client: TestClient, admin: dict) -> None:
    dept = client.post("/api/v1/departments", json={"name": f"D_{uuid.uuid4().hex[:6]}"},
                       headers=admin["headers"]).json()
    team = client.post("/api/v1/teams", json={"name": "T", "department_id": dept["id"]},
                       headers=admin["headers"]).json()
    # Department share: the member is placed in the department at creation.
    member = _invite_member(client, admin, department_id=dept["id"])

    res = _register_resource(client, admin)
    assert client.post(f"/api/v1/resources/{res['id']}/share", headers=admin["headers"], json={
        "shared_with_type": "DEPARTMENT", "shared_with_id": dept["id"], "access_level": "READ",
    }).status_code == 201
    assert _authorize(client, member, res["id"], "ai_agent.view")["allowed"] is True

    # Team share: a team the member does NOT belong to stays denied.
    res2 = _register_resource(client, admin, name="Agent Y")
    assert client.post(f"/api/v1/resources/{res2['id']}/share", headers=admin["headers"], json={
        "shared_with_type": "TEAM", "shared_with_id": team["id"], "access_level": "EDIT",
    }).status_code == 201
    assert _authorize(client, member, res2["id"], "ai_agent.update")["allowed"] is False


def test_expired_share_ignored(client: TestClient, admin: dict) -> None:
    member = _invite_member(client, admin)
    res = _register_resource(client, admin)
    assert client.post(f"/api/v1/resources/{res['id']}/share", headers=admin["headers"], json={
        "shared_with_type": "USER", "shared_with_id": member["user_id"],
        "access_level": "MANAGE", "expires_at": _iso(minutes=-1),
    }).status_code == 201
    assert _authorize(client, member, res["id"], "ai_agent.view")["allowed"] is False


# --- Delegation (§13, §22) -------------------------------------------------------- #
def test_delegation_lifecycle(client: TestClient, admin: dict) -> None:
    member = _invite_member(client, admin)
    res = _register_resource(client, admin)

    d = client.post(f"/api/v1/resources/{res['id']}/delegate", headers=admin["headers"], json={
        "delegate_id": member["user_id"], "permissions": ["manage"],
        "expires_at": _iso(days=30), "reason": "vacation cover",
    })
    assert d.status_code == 201, d.text
    assert _authorize(client, member, res["id"], "ai_agent.update")["source"] == "DELEGATION"

    # A manage delegation also lets the delegate administer the ACL (§13).
    assert client.post(f"/api/v1/resources/{res['id']}/acl", headers=member["headers"], json={
        "principal_type": "USER", "principal_id": member["user_id"],
        "permission": "ai_agent.view", "effect": "ALLOW",
    }).status_code == 201

    # Revoke → denied again (audited).
    assert client.delete(f"/api/v1/resources/{res['id']}/delegate/{d.json()['id']}",
                         headers=admin["headers"]).status_code == 200
    assert _authorize(client, member, res["id"], "ai_agent.update")["allowed"] is False


def test_expired_delegation_ignored_and_past_expiry_rejected(client: TestClient, admin: dict) -> None:
    member = _invite_member(client, admin)
    res = _register_resource(client, admin)
    r = client.post(f"/api/v1/resources/{res['id']}/delegate", headers=admin["headers"], json={
        "delegate_id": member["user_id"], "permissions": ["*"], "expires_at": _iso(minutes=-1),
    })
    assert r.status_code == 410
    assert r.json()["error"]["code"] == "DELEGATION_EXPIRED"


# --- Visibility (§9) ---------------------------------------------------------------- #
def test_visibility_levels(client: TestClient, admin: dict) -> None:
    member = _invite_member(client, admin)

    private = _register_resource(client, admin, visibility="PRIVATE")
    assert _authorize(client, member, private["id"], "ai_agent.view")["allowed"] is False

    org_vis = _register_resource(client, admin, name="OrgWide", visibility="ORGANIZATION")
    d = _authorize(client, member, org_vis["id"], "ai_agent.view")
    assert d["allowed"] is True and d["source"] == "VISIBILITY"
    # Visibility grants reads only — writes stay denied.
    assert _authorize(client, member, org_vis["id"], "ai_agent.update")["allowed"] is False


def test_department_visibility(client: TestClient, admin: dict) -> None:
    dept = client.post("/api/v1/departments", json={"name": f"D_{uuid.uuid4().hex[:6]}"},
                       headers=admin["headers"]).json()
    team = client.post("/api/v1/teams", json={"name": "T", "department_id": dept["id"]},
                       headers=admin["headers"]).json()
    project = client.post("/api/v1/projects", json={"name": "P", "team_id": team["id"]},
                          headers=admin["headers"]).json()
    member = _invite_member(client, admin, department_id=dept["id"])
    outsider = _invite_member(client, admin)

    rid = str(uuid.uuid4())
    res = _register_resource(client, admin, resource_id=rid, visibility="DEPARTMENT")
    # Attach the resource's hierarchy path (4.3.3) so DEPARTMENT visibility resolves.
    assert client.post("/api/v1/resource-ownership", headers=admin["headers"], json={
        "resource_type": "ai_agent", "resource_id": rid, "project_id": project["id"],
    }).status_code == 201

    assert _authorize(client, member, res["id"], "ai_agent.view")["allowed"] is True
    assert _authorize(client, outsider, res["id"], "ai_agent.view")["allowed"] is False


# --- Resource policy (§14) ------------------------------------------------------------ #
def test_resource_policy_restricts_even_role_holders(client: TestClient, admin: dict) -> None:
    member = _invite_member(client, admin)
    res = _register_resource(client, admin, visibility="ORGANIZATION")

    # Only `member` may publish — even the owner is bound by the policy (§14).
    r = client.put(f"/api/v1/resources/{res['id']}/policy", headers=admin["headers"], json={
        "policy": [{"permission": "ai_agent.publish", "principal_type": "USER",
                    "principal_id": member["user_id"]}],
    })
    assert r.status_code == 200, r.text

    d = _authorize(client, admin, res["id"], "ai_agent.publish")
    assert d["allowed"] is False and d["source"] == "POLICY_DENY"
    assert d["error_code"] == "RESOURCE_POLICY_DENIED"
    # Unrelated actions on the resource are untouched.
    assert _authorize(client, admin, res["id"], "ai_agent.update")["allowed"] is True


# --- Cross-tenant isolation (§22) ------------------------------------------------------ #
def test_cross_tenant_isolation(client: TestClient, admin: dict) -> None:
    other = _register_org(client, org="Other Org")
    res = _register_resource(client, admin)

    # Lookup answers 404 across the tenant boundary — existence is not revealed.
    assert client.get(f"/api/v1/resources/{res['id']}",
                      headers=other["headers"]).status_code == 404

    # Cross-organization sharing is denied by default (§22.4).
    r = client.post(f"/api/v1/resources/{res['id']}/share", headers=admin["headers"], json={
        "shared_with_type": "USER", "shared_with_id": other["user_id"], "access_level": "READ",
    })
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "CROSS_ORGANIZATION_ACCESS_DENIED"

    # PUBLIC_INTERNAL is view-visible platform-wide, but never writable (§9).
    pub = _register_resource(client, admin, name="Pub", visibility="PUBLIC_INTERNAL")
    d = _authorize(client, other, pub["id"], "ai_agent.view")
    assert d["allowed"] is True and d["source"] == "VISIBILITY"
    d = _authorize(client, other, pub["id"], "ai_agent.update")
    assert d["allowed"] is False and d["source"] == "CROSS_ORG_DENY"


# --- Engine integration (§18) ------------------------------------------------------------ #
def test_authorization_check_uses_resource_chain_for_registered_resources(
    client: TestClient, admin: dict,
) -> None:
    member = _invite_member(client, admin)
    rid = str(uuid.uuid4())
    res = _register_resource(client, admin, resource_id=rid)
    assert client.post(f"/api/v1/resources/{res['id']}/acl", headers=admin["headers"], json={
        "principal_type": "USER", "principal_id": member["user_id"],
        "permission": "ai_agent.execute", "effect": "ALLOW",
    }).status_code == 201

    # The central /authorization/check endpoint now resolves the ACL for
    # registered resources — same-role users get different answers (§29 DoD).
    check = client.post("/api/v1/authorization/check", headers=member["headers"], json={
        "permission": "ai_agent.execute", "resource_type": "ai_agent", "resource_id": rid,
    }).json()
    assert check["allowed"] is True
    assert check["reason"] == "Granted via ACL"

    other_member = _invite_member(client, admin)
    check2 = client.post("/api/v1/authorization/check", headers=other_member["headers"], json={
        "permission": "ai_agent.execute", "resource_type": "ai_agent", "resource_id": rid,
    }).json()
    assert check2["allowed"] is False


# --- Authorization inspector (§21) ---------------------------------------------------------- #
def test_authorization_inspector_simulates_identity(client: TestClient, admin: dict) -> None:
    member = _invite_member(client, admin)
    res = _register_resource(client, admin)
    assert client.post(f"/api/v1/resources/{res['id']}/share", headers=admin["headers"], json={
        "shared_with_type": "USER", "shared_with_id": member["user_id"], "access_level": "READ",
    }).status_code == 201

    # An admin simulates the member's access (resource.manage).
    d = _authorize(client, admin, res["id"], "ai_agent.view", identity_id=member["user_id"])
    assert d["allowed"] is True and d["source"] == "SHARE"
    assert d["owner_id"] == admin["user_id"]
    assert d["visibility"] == "PRIVATE"
    assert "IDENTITY_VERIFIED" in d["steps"]

    # A non-admin may not simulate others.
    r = client.post(f"/api/v1/resources/{res['id']}/authorize", headers=member["headers"],
                    json={"permission": "ai_agent.view", "identity_id": admin["user_id"]})
    assert r.status_code == 403


# --- Audit events (§23) ------------------------------------------------------------------ #
def test_access_decisions_and_mutations_are_audited(client: TestClient, admin: dict) -> None:
    member = _invite_member(client, admin)
    res = _register_resource(client, admin)
    _authorize(client, admin, res["id"], "ai_agent.view")          # granted
    _authorize(client, member, res["id"], "ai_agent.delete")       # denied
    client.post(f"/api/v1/resources/{res['id']}/share", headers=admin["headers"], json={
        "shared_with_type": "USER", "shared_with_id": member["user_id"], "access_level": "READ",
    })

    for event in ("RESOURCE_ACCESS_GRANTED", "RESOURCE_ACCESS_DENIED",
                  "RESOURCE_SHARED", "RESOURCE_REGISTERED"):
        rows = client.get(f"/api/v1/authorization/audit?event_type={event}",
                          headers=admin["headers"]).json()
        assert any(r["meta"] and r["meta"].get("resource_pk") == res["id"] for r in rows), event
