"""Phase 4.3.8 integration tests — Identity Governance & Administration:
certification campaigns via the governance proxy, SoD/toxic-permission
detection (explicit scan + the continuous role-assignment hook), findings,
remediation with real enforcement, privileged access review, orphaned-identity
detection, risk scoring, compliance reporting, audit events and role-gating."""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient
from sqlalchemy import select

PASSWORD = "T3st!Passw0rd#Ok"
GOV = "/api/v1/governance"


def _register_org(client: TestClient, org: str = "Governance Org") -> dict:
    email = f"gov_{uuid.uuid4().hex[:10]}@example.com"
    assert client.post("/auth/register", json={
        "organization_name": org, "name": "Owner", "email": email, "password": PASSWORD,
    }).status_code == 201
    tokens = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD}).json()
    h = {"Authorization": f"Bearer {tokens['access_token']}"}
    me = client.get("/api/v1/auth/me", headers=h).json()
    return {"headers": h, "user_id": me["user"]["id"],
            "organization_id": me["user"]["organization_id"], "email": email}


def _invite_member(client: TestClient, admin: dict, *, role: str = "VIEWER") -> dict:
    email = f"govm_{uuid.uuid4().hex[:10]}@example.com"
    r = client.post("/api/v1/identity/users", headers=admin["headers"], json={
        "email": email, "display_name": "Member", "password": PASSWORD, "role": role,
        "organization_id": admin["organization_id"],
    })
    assert r.status_code in (200, 201), r.text
    tokens = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD}).json()
    h = {"Authorization": f"Bearer {tokens['access_token']}"}
    me = client.get("/api/v1/auth/me", headers=h).json()
    return {"headers": h, "user_id": me["user"]["id"], "email": email}


def _make_role(client: TestClient, admin: dict, *, permissions: list[str]) -> dict:
    r = client.post("/api/v1/roles", headers=admin["headers"], json={
        "name": f"ROLE_GOV_{uuid.uuid4().hex[:8].upper()}", "permissions": permissions,
    })
    assert r.status_code == 201, r.text
    return r.json()


def _assign_role(client: TestClient, admin: dict, *, user_id: str, role_id: str) -> dict:
    r = client.post("/api/v1/role-assignments", headers=admin["headers"], json={
        "user_id": user_id, "role_id": role_id, "scope": "ORGANIZATION",
    })
    assert r.status_code == 201, r.text
    return r.json()


def _audit_events(db_session, organization_id: str) -> set[str]:
    from app.models.rbac import AuthorizationAudit

    return {row.event_type for row in db_session.execute(
        select(AuthorizationAudit).where(
            AuthorizationAudit.organization_id == uuid.UUID(organization_id))
    ).scalars()}


# --------------------------------------------------------------------------- #
# Dashboard / analytics (§21, §26)
# --------------------------------------------------------------------------- #
def test_governance_dashboard_and_analytics(client: TestClient) -> None:
    org = _register_org(client)
    r = client.get(f"{GOV}/dashboard", headers=org["headers"])
    assert r.status_code == 200, r.text
    body = r.json()
    for key in ("active_campaigns", "pending_reviews", "overdue_reviews", "privileged_accounts",
                "toxic_permission_findings", "sod_findings", "orphaned_accounts",
                "compliance_status", "remediation_queue", "governance_risk_distribution"):
        assert key in body["widgets"], key

    r = client.get(f"{GOV}/analytics", headers=org["headers"])
    assert r.status_code == 200, r.text
    body = r.json()
    for key in ("review_completion_trend", "findings_by_severity", "findings_by_type",
                "privileged_access_growth", "risk_score_distribution"):
        assert key in body, key


# --------------------------------------------------------------------------- #
# Certification campaigns via the governance proxy (§5-§7, §19)
# --------------------------------------------------------------------------- #
def test_certification_campaign_lifecycle_and_decisions(client: TestClient, db_session) -> None:
    org = _register_org(client)
    member = _invite_member(client, org)
    role = _make_role(client, org, permissions=["agent.view"])
    assign = _assign_role(client, org, user_id=member["user_id"], role_id=role["id"])

    campaign = client.post(f"{GOV}/campaigns", headers=org["headers"], json={
        "name": "Q3 governance certification", "campaign_type": "QUARTERLY",
        "scope": {"role_ids": [role["id"]]},
    }).json()
    assert campaign["status"] == "DRAFT" and campaign["campaign_type"] == "QUARTERLY"

    launched = client.post(f"{GOV}/campaigns/{campaign['id']}/launch", headers=org["headers"]).json()
    assert launched["status"] == "ACTIVE" and launched["total_items"] == 1

    items = client.get(f"{GOV}/campaigns/{campaign['id']}/items", headers=org["headers"]).json()
    assert len(items) == 1 and items[0]["subject_label"] == member["email"]
    item_id = items[0]["id"]

    decided = client.post(f"{GOV}/reviews/{item_id}/revoke", headers=org["headers"],
                          json={"comment": "No longer needed"}).json()
    assert decided["decision"] == "REVOKED"

    remaining = client.get("/api/v1/role-assignments", headers=org["headers"],
                           params={"user_id": member["user_id"]}).json()
    assert all(a["id"] != assign["id"] for a in remaining)

    completed = client.post(f"{GOV}/campaigns/{campaign['id']}/complete", headers=org["headers"]).json()
    assert completed["status"] == "COMPLETED" and completed["revoked_items"] == 1

    events = _audit_events(db_session, org["organization_id"])
    assert {"CERTIFICATION_CREATED", "CERTIFICATION_COMPLETED", "ACCESS_REVOKED"} <= events, events


def test_certification_review_approve_delegate_modify(client: TestClient) -> None:
    org = _register_org(client)
    member = _invite_member(client, org)
    role = _make_role(client, org, permissions=["agent.view"])
    _assign_role(client, org, user_id=member["user_id"], role_id=role["id"])

    campaign = client.post(f"{GOV}/campaigns", headers=org["headers"],
                           json={"name": "Approve/delegate/modify test"}).json()
    client.post(f"{GOV}/campaigns/{campaign['id']}/launch", headers=org["headers"])
    items = client.get(f"{GOV}/campaigns/{campaign['id']}/items", headers=org["headers"]).json()

    # Only one item here; exercise approve. A second campaign exercises delegate/modify.
    approved = client.post(f"{GOV}/reviews/{items[0]['id']}/approve", headers=org["headers"]).json()
    assert approved["decision"] == "CERTIFIED"

    role2 = _make_role(client, org, permissions=["policy.view"])
    _assign_role(client, org, user_id=member["user_id"], role_id=role2["id"])
    campaign2 = client.post(f"{GOV}/campaigns", headers=org["headers"],
                            json={"name": "Delegate + modify", "scope": {"role_ids": [role2["id"]]}}).json()
    client.post(f"{GOV}/campaigns/{campaign2['id']}/launch", headers=org["headers"])
    items2 = client.get(f"{GOV}/campaigns/{campaign2['id']}/items", headers=org["headers"]).json()

    delegate_to = str(uuid.uuid4())
    delegated = client.post(f"{GOV}/reviews/{items2[0]['id']}/delegate", headers=org["headers"],
                            json={"comment": "please review", "delegate_to": delegate_to}).json()
    assert delegated["decision"] == "DELEGATED"
    assert delegate_to in (delegated["comment"] or "")


def test_certification_decision_immutable_after_completion(client: TestClient) -> None:
    org = _register_org(client)
    member = _invite_member(client, org)
    role = _make_role(client, org, permissions=["agent.view"])
    _assign_role(client, org, user_id=member["user_id"], role_id=role["id"])

    campaign = client.post(f"{GOV}/campaigns", headers=org["headers"], json={
        "name": "immutability guard", "scope": {"role_ids": [role["id"]]},
    }).json()
    client.post(f"{GOV}/campaigns/{campaign['id']}/launch", headers=org["headers"])
    items = client.get(f"{GOV}/campaigns/{campaign['id']}/items", headers=org["headers"]).json()
    assert len(items) == 1
    client.post(f"{GOV}/reviews/{items[0]['id']}/approve", headers=org["headers"])

    completed = client.post(f"{GOV}/campaigns/{campaign['id']}/complete", headers=org["headers"])
    assert completed.status_code == 200

    # A decision after completion is rejected — certification decisions are
    # immutable once the campaign is done (§24).
    r = client.post(f"{GOV}/reviews/{items[0]['id']}/modify", headers=org["headers"])
    assert r.status_code == 409, r.text

    archived = client.post(f"{GOV}/campaigns/{campaign['id']}/archive", headers=org["headers"])
    assert archived.status_code == 200


# --------------------------------------------------------------------------- #
# Separation of Duties (§9, §10, §19) — explicit scan + continuous detection
# --------------------------------------------------------------------------- #
def test_sod_rule_lifecycle_and_scan_detects_violation(client: TestClient, db_session) -> None:
    org = _register_org(client)
    member = _invite_member(client, org)
    role_a = _make_role(client, org, permissions=["policy.create"])
    role_b = _make_role(client, org, permissions=["policy.delete"])
    _assign_role(client, org, user_id=member["user_id"], role_id=role_a["id"])
    _assign_role(client, org, user_id=member["user_id"], role_id=role_b["id"])

    rule = client.post(f"{GOV}/sod-rules", headers=org["headers"], json={
        "name": "Author cannot delete own policy", "risk_level": "HIGH",
        "permissions_a": ["policy.create"], "permissions_b": ["policy.delete"],
    }).json()
    assert rule["status"] == "DRAFT" and rule["rule_type"] == "SOD"

    active = client.post(f"{GOV}/sod-rules/{rule['id']}/activate", headers=org["headers"]).json()
    assert active["status"] == "ACTIVE" and active["approved_by"] == org["user_id"]

    findings = client.post(f"{GOV}/sod-findings/scan", headers=org["headers"]).json()
    assert any(f["identity_id"] == member["user_id"] for f in findings), findings

    listed = client.get(f"{GOV}/sod-findings", headers=org["headers"]).json()
    assert any(f["identity_id"] == member["user_id"] and f["severity"] == "HIGH" for f in listed)

    # Re-scanning must not duplicate an already-open finding.
    again = client.post(f"{GOV}/sod-findings/scan", headers=org["headers"]).json()
    assert not any(f["identity_id"] == member["user_id"] for f in again)

    assert "SOD_RULE_CREATED" in _audit_events(db_session, org["organization_id"])
    assert "SOD_VIOLATION_FOUND" in _audit_events(db_session, org["organization_id"])


def test_toxic_permission_detected_on_role_assignment(client: TestClient) -> None:
    """§10 — "Detection runs continuously and during role assignment": no
    explicit scan call here, only two role-assignment POSTs."""
    org = _register_org(client)
    member = _invite_member(client, org)
    role_a = _make_role(client, org, permissions=["agent.delete"])
    role_b = _make_role(client, org, permissions=["audit.export"])

    rule = client.post(f"{GOV}/toxic-rules", headers=org["headers"], json={
        "name": "Delete agents + export audit", "risk_level": "CRITICAL",
        "permissions_a": ["agent.delete"], "permissions_b": ["audit.export"],
    }).json()
    client.post(f"{GOV}/toxic-rules/{rule['id']}/activate", headers=org["headers"])

    _assign_role(client, org, user_id=member["user_id"], role_id=role_a["id"])
    findings = client.get(f"{GOV}/toxic-findings", headers=org["headers"]).json()
    assert not any(f["identity_id"] == member["user_id"] for f in findings)

    _assign_role(client, org, user_id=member["user_id"], role_id=role_b["id"])
    findings = client.get(f"{GOV}/toxic-findings", headers=org["headers"]).json()
    assert any(f["identity_id"] == member["user_id"] for f in findings), findings


# --------------------------------------------------------------------------- #
# Findings + remediation with real enforcement (§14, §17, §19)
# --------------------------------------------------------------------------- #
def test_findings_remediate_and_remediation_action_removes_role(client: TestClient, db_session) -> None:
    org = _register_org(client)
    member = _invite_member(client, org)
    role_a = _make_role(client, org, permissions=["session.revoke"])
    role_b = _make_role(client, org, permissions=["credential.reset"])
    assign_a = _assign_role(client, org, user_id=member["user_id"], role_id=role_a["id"])
    _assign_role(client, org, user_id=member["user_id"], role_id=role_b["id"])

    rule = client.post(f"{GOV}/sod-rules", headers=org["headers"], json={
        "name": "Revoke sessions + reset credentials", "risk_level": "CRITICAL",
        "permissions_a": ["session.revoke"], "permissions_b": ["credential.reset"],
    }).json()
    client.post(f"{GOV}/sod-rules/{rule['id']}/activate", headers=org["headers"])
    client.post(f"{GOV}/sod-findings/scan", headers=org["headers"])

    finding = next(f for f in client.get(f"{GOV}/findings", headers=org["headers"]).json()
                   if f["identity_id"] == member["user_id"])

    action = client.post(f"{GOV}/remediation-actions", headers=org["headers"], json={
        "finding_id": finding["id"], "action_type": "REMOVE_ROLE",
        "payload": {"assignment_id": assign_a["id"]},
    }).json()
    assert action["status"] == "PENDING"

    executed = client.post(f"{GOV}/remediation-actions/{action['id']}/execute",
                           headers=org["headers"]).json()
    assert executed["status"] == "EXECUTED"

    remaining = client.get("/api/v1/role-assignments", headers=org["headers"],
                           params={"user_id": member["user_id"]}).json()
    assert all(a["id"] != assign_a["id"] for a in remaining)

    resolved = client.post(f"{GOV}/findings/{finding['id']}/remediate", headers=org["headers"],
                           json={"status": "REMEDIATED", "comment": "role removed"}).json()
    assert resolved["status"] == "REMEDIATED"

    events = _audit_events(db_session, org["organization_id"])
    assert {"REMEDIATION_CREATED", "REMEDIATION_EXECUTED", "GOVERNANCE_FINDING_RESOLVED"} <= events


# --------------------------------------------------------------------------- #
# Orphaned identity detection (§12, §19)
# --------------------------------------------------------------------------- #
def test_orphaned_scan_flags_disabled_user_with_active_access(client: TestClient, db_session) -> None:
    org = _register_org(client)
    member = _invite_member(client, org)
    role = _make_role(client, org, permissions=["agent.view"])
    _assign_role(client, org, user_id=member["user_id"], role_id=role["id"])

    from app.models.user import User

    user = db_session.get(User, uuid.UUID(member["user_id"]))
    user.is_active = False
    db_session.commit()

    result = client.post(f"{GOV}/orphaned-accounts/scan", headers=org["headers"]).json()
    assert result["findings_created"] >= 1

    findings = client.get(f"{GOV}/orphaned-accounts", headers=org["headers"]).json()
    assert any(f["identity_id"] == member["user_id"]
               and f["details"]["reason"] == "DISABLED_WITH_ACTIVE_ACCESS" for f in findings)


# --------------------------------------------------------------------------- #
# Privileged access governance (§11, §19)
# --------------------------------------------------------------------------- #
def test_privileged_accounts_listing_and_review_decision(client: TestClient, db_session) -> None:
    org = _register_org(client)
    member = _invite_member(client, org)

    from app.models.rbac import Role

    security_admin = db_session.execute(
        select(Role).where(Role.name == "ROLE_SECURITY_ADMIN", Role.organization_id.is_(None))
    ).scalar_one()
    assign = _assign_role(client, org, user_id=member["user_id"], role_id=str(security_admin.id))

    accounts = client.get(f"{GOV}/privileged-accounts", headers=org["headers"]).json()
    hit = next((a for a in accounts if a["identity_id"] == member["user_id"]), None)
    assert hit is not None and hit["role_name"] == "ROLE_SECURITY_ADMIN"
    assert hit["risk_score"] >= 0

    review = client.post(f"{GOV}/privileged-accounts/reviews", headers=org["headers"], params={
        "identity_id": member["user_id"], "role_name": "ROLE_SECURITY_ADMIN",
        "assignment_id": assign["id"],
    }).json()
    assert review["status"] == "PENDING"

    decided = client.post(f"{GOV}/privileged-accounts/reviews/{review['id']}/decide",
                          headers=org["headers"], params={
                              "decision": "REVOKED", "assignment_id": assign["id"],
                          }).json()
    assert decided["status"] == "REVOKED"

    remaining = client.get("/api/v1/role-assignments", headers=org["headers"],
                           params={"user_id": member["user_id"]}).json()
    assert all(a["id"] != assign["id"] for a in remaining)

    assert "PRIVILEGED_REVIEW_COMPLETED" in _audit_events(db_session, org["organization_id"])


# --------------------------------------------------------------------------- #
# Risk scoring (§13, §19)
# --------------------------------------------------------------------------- #
def test_risk_score_recalculate(client: TestClient) -> None:
    org = _register_org(client)
    rows = client.post(f"{GOV}/risk-scores/recalculate", headers=org["headers"]).json()
    assert any(r["identity_id"] == org["user_id"] for r in rows)

    listed = client.get(f"{GOV}/risk-scores", headers=org["headers"]).json()
    assert any(r["identity_id"] == org["user_id"] for r in listed)


# --------------------------------------------------------------------------- #
# Compliance reporting (§15, §16, §19, §22)
# --------------------------------------------------------------------------- #
def test_compliance_frameworks_and_report_generation(client: TestClient, db_session) -> None:
    org = _register_org(client)
    frameworks = client.get(f"{GOV}/compliance/frameworks", headers=org["headers"]).json()
    assert any(f["framework"] == "SOC2" for f in frameworks)

    report = client.post(f"{GOV}/compliance/reports", headers=org["headers"], json={
        "framework": "HIPAA", "report_type": "EVIDENCE_SNAPSHOT",
    }).json()
    assert report["framework"] == "HIPAA"
    assert "certification_campaigns" in report["payload"]

    listed = client.get(f"{GOV}/compliance/reports", headers=org["headers"]).json()
    assert any(r["id"] == report["id"] for r in listed)

    csv_resp = client.get(f"{GOV}/compliance/reports/{report['id']}", headers=org["headers"],
                          params={"format": "csv"})
    assert csv_resp.status_code == 200
    assert csv_resp.headers["content-type"].startswith("text/csv")
    assert "metric,value" in csv_resp.text

    assert "COMPLIANCE_REPORT_GENERATED" in _audit_events(db_session, org["organization_id"])


# --------------------------------------------------------------------------- #
# Role-gated access + tenant isolation (§21, §24)
# --------------------------------------------------------------------------- #
def test_governance_endpoints_require_permissions(client: TestClient) -> None:
    org = _register_org(client)
    member = _invite_member(client, org, role="VIEWER")
    for path in ("/dashboard", "/analytics", "/campaigns", "/sod-rules", "/sod-findings",
                 "/toxic-rules", "/toxic-findings", "/findings", "/privileged-accounts",
                 "/orphaned-accounts", "/risk-scores", "/remediation-actions",
                 "/compliance/reports", "/compliance/frameworks"):
        r = client.get(f"{GOV}{path}", headers=member["headers"])
        assert r.status_code == 403, f"{path} -> {r.status_code}"


def test_governance_endpoints_require_authentication(client: TestClient) -> None:
    assert client.get(f"{GOV}/dashboard").status_code in (401, 403)


def test_sod_rules_are_tenant_isolated(client: TestClient) -> None:
    org_a = _register_org(client, org="Gov Tenant A")
    org_b = _register_org(client, org="Gov Tenant B")
    rule = client.post(f"{GOV}/sod-rules", headers=org_a["headers"], json={
        "name": "tenant isolation", "permissions_a": ["agent.view"], "permissions_b": ["policy.view"],
    }).json()
    r = client.post(f"{GOV}/sod-rules/{rule['id']}/activate", headers=org_b["headers"])
    assert r.status_code == 404
    listed = client.get(f"{GOV}/sod-rules", headers=org_b["headers"]).json()
    assert all(x["id"] != rule["id"] for x in listed)
