"""Phase 4.3.5 integration + security tests (§42) — policy lifecycle,
versioning/rollback, validation, evaluation, obligations, engine integration,
explainability/redaction, simulation, exceptions, scoping, cross-tenant
isolation and unauthorized publication."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

PASSWORD = "T3st!Passw0rd#Ok"
BASE = "/api/v1/authorization"


def _register_org(client: TestClient, org: str = "Abac Org") -> dict:
    email = f"abac_{uuid.uuid4().hex[:10]}@example.com"
    assert client.post("/auth/register", json={
        "organization_name": org, "name": "Owner", "email": email, "password": PASSWORD,
    }).status_code == 201
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
    email = f"abacm_{uuid.uuid4().hex[:10]}@example.com"
    r = client.post("/api/v1/identity/users", headers=admin["headers"], json={
        "email": email, "display_name": "Member", "password": PASSWORD, "role": role,
        "organization_id": _org_id(client, admin), "department_id": department_id,
    })
    assert r.status_code in (200, 201), r.text
    tokens = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD}).json()
    h = {"Authorization": f"Bearer {tokens['access_token']}"}
    me = client.get("/api/v1/auth/me", headers=h).json()
    return {"headers": h, "user_id": me["user"]["id"], "email": email}


def _create_policy(client: TestClient, who: dict, **overrides) -> dict:
    body = {
        "name": f"policy_{uuid.uuid4().hex[:8]}",
        "effect": "DENY",
        "target": {"actions": ["dataset.export"]},
        "conditions": {"all": [
            {"attribute": "environment.network_zone", "operator": "NOT_IN",
             "value": ["CORPORATE", "TRUSTED_VPN"]},
        ]},
    }
    body.update(overrides)
    r = client.post(f"{BASE}/abac/policies", json=body, headers=who["headers"])
    assert r.status_code == 201, r.text
    return r.json()


def _publish(client: TestClient, who: dict, policy_id: str) -> dict:
    r = client.post(f"{BASE}/abac/policies/{policy_id}/publish", headers=who["headers"])
    assert r.status_code == 200, r.text
    return r.json()


def _evaluate(client: TestClient, who: dict, action: str, context: dict | None = None) -> dict:
    r = client.post(f"{BASE}/abac/evaluate",
                    json={"action": action, "context": context or {}}, headers=who["headers"])
    assert r.status_code == 200, r.text
    return r.json()


def _iso(**delta) -> str:
    return (datetime.now(timezone.utc) + timedelta(**delta)).isoformat()


# --- Attribute catalog (§20) ------------------------------------------------- #
def test_attribute_catalog_seeded_and_custom_attributes(client: TestClient, admin: dict) -> None:
    attrs = client.get(f"{BASE}/attributes", headers=admin["headers"]).json()
    names = {a["name"] for a in attrs}
    for expected in ("identity.risk_score", "resource.contains_phi", "action.name",
                     "environment.network_zone", "ai.autonomy_level"):
        assert expected in names, f"system attribute {expected} missing"
    phi = client.get(f"{BASE}/attributes/resource.contains_phi", headers=admin["headers"]).json()
    assert phi["data_type"] == "BOOLEAN" and phi["is_system"] is True

    # A custom attribute becomes usable in a policy once registered.
    custom = f"resource.custom_{uuid.uuid4().hex[:6]}"
    r = client.post(f"{BASE}/attributes", headers=admin["headers"], json={
        "name": custom, "category": "RESOURCE", "data_type": "BOOLEAN",
    })
    assert r.status_code == 201, r.text
    p = _create_policy(client, admin, conditions={"all": [
        {"attribute": custom, "operator": "EQUALS", "value": True}]})
    v = client.post(f"{BASE}/abac/policies/{p['id']}/validate", headers=admin["headers"]).json()
    assert v["valid"] is True, v


# --- Validation (§10, §24, §39) -------------------------------------------------- #
def test_validation_rejects_bad_policies(client: TestClient, admin: dict) -> None:
    # Unregistered attribute.
    p = _create_policy(client, admin, conditions={"all": [
        {"attribute": "resource.not_a_thing", "operator": "EQUALS", "value": True}]})
    v = client.post(f"{BASE}/abac/policies/{p['id']}/validate", headers=admin["headers"]).json()
    assert v["valid"] is False
    assert any(e["code"] == "ABAC_ATTRIBUTE_NOT_FOUND" for e in v["errors"])

    # Type mismatch: integer attribute compared to a string (§10).
    p2 = _create_policy(client, admin, conditions={"all": [
        {"attribute": "identity.risk_score", "operator": "GREATER_THAN", "value": "high"}]})
    v2 = client.post(f"{BASE}/abac/policies/{p2['id']}/validate", headers=admin["headers"]).json()
    assert any(e["code"] == "ABAC_ATTRIBUTE_TYPE_MISMATCH" for e in v2["errors"])

    # Unsupported operator for the type.
    p3 = _create_policy(client, admin, conditions={"all": [
        {"attribute": "resource.contains_phi", "operator": "GREATER_THAN", "value": True}]})
    v3 = client.post(f"{BASE}/abac/policies/{p3['id']}/validate", headers=admin["headers"]).json()
    assert any(e["code"] == "ABAC_OPERATOR_NOT_SUPPORTED" for e in v3["errors"])

    # Malicious regex is rejected at validation (§42 security).
    p4 = _create_policy(client, admin, conditions={"all": [
        {"attribute": "ai.model_name", "operator": "MATCHES_REGEX", "value": "(a+)+$"}]})
    v4 = client.post(f"{BASE}/abac/policies/{p4['id']}/validate", headers=admin["headers"]).json()
    assert v4["valid"] is False

    # Publishing an invalid policy fails.
    r = client.post(f"{BASE}/abac/policies/{p['id']}/publish", headers=admin["headers"])
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "ABAC_POLICY_INVALID"

    # Malformed payload (bad condition tree shape).
    p5 = _create_policy(client, admin, conditions={"bogus": "shape"})
    v5 = client.post(f"{BASE}/abac/policies/{p5['id']}/validate", headers=admin["headers"]).json()
    assert any(e["code"] == "ABAC_CONDITION_INVALID" for e in v5["errors"])


# --- Lifecycle + versioning + rollback (§7, §30) ------------------------------------- #
def test_policy_lifecycle_versioning_and_rollback(client: TestClient, admin: dict) -> None:
    p = _create_policy(client, admin)
    assert p["status"] == "DRAFT" and p["version"] == 1

    # Draft policies never affect decisions.
    d = _evaluate(client, admin, "dataset.export", {"environment.network_zone": "PUBLIC"})
    assert d["decision"] == "NOT_APPLICABLE"

    v = client.post(f"{BASE}/abac/policies/{p['id']}/validate", headers=admin["headers"]).json()
    assert v["valid"] is True and v["status"] == "VALIDATED"

    active_v1 = _publish(client, admin, p["id"])
    assert active_v1["status"] == "ACTIVE" and active_v1["published_at"]

    # Editing the active version creates a new draft version — published stays immutable.
    r = client.put(f"{BASE}/abac/policies/{p['id']}", headers=admin["headers"],
                   json={"priority": 250})
    assert r.status_code == 200
    v2 = r.json()
    assert v2["id"] != p["id"] and v2["version"] == 2 and v2["status"] == "DRAFT"
    assert client.get(f"{BASE}/abac/policies/{p['id']}",
                      headers=admin["headers"]).json()["status"] == "ACTIVE"

    # Publishing v2 deprecates v1 — one ACTIVE per family.
    _publish(client, admin, v2["id"])
    assert client.get(f"{BASE}/abac/policies/{p['id']}",
                      headers=admin["headers"]).json()["status"] == "DEPRECATED"

    versions = client.get(f"{BASE}/abac/policies/{v2['id']}/versions",
                          headers=admin["headers"]).json()
    assert [row["version"] for row in versions] == [2, 1]

    # Rollback to v1 publishes a new version with v1's content.
    rb = client.post(f"{BASE}/abac/policies/{v2['id']}/rollback/1", headers=admin["headers"])
    assert rb.status_code == 200, rb.text
    assert rb.json()["version"] == 3 and rb.json()["status"] == "ACTIVE"
    assert rb.json()["priority"] == p["priority"]

    # Published history cannot be deleted (§7); archive instead.
    assert client.delete(f"{BASE}/abac/policies/{p['id']}",
                         headers=admin["headers"]).status_code == 409
    assert client.post(f"{BASE}/abac/policies/{p['id']}/archive",
                       headers=admin["headers"]).json()["status"] == "ARCHIVED"

    # Disable stops an active policy.
    assert client.post(f"{BASE}/abac/policies/{rb.json()['id']}/disable",
                       headers=admin["headers"]).json()["status"] == "DISABLED"
    d = _evaluate(client, admin, "dataset.export", {"environment.network_zone": "PUBLIC"})
    assert d["decision"] == "NOT_APPLICABLE"


# --- Evaluation + effects (§8, §15) ------------------------------------------------ #
def test_deny_policy_and_explainability(client: TestClient, admin: dict) -> None:
    p = _create_policy(client, admin)
    _publish(client, admin, p["id"])

    d = _evaluate(client, admin, "dataset.export", {"environment.network_zone": "PUBLIC"})
    assert d["decision"] == "DENY" and d["allowed"] is False
    assert p["name"] in d["reason"]
    assert d["matched_policies"][0]["policy_id"] == p["id"]
    # §16 — which policies were considered/matched, conditions, winning effect.
    exp = d["explanation"]
    assert exp["winning_effect"] == "DENY"
    assert any(c["attribute"] == "environment.network_zone" and c["result"]
               for c in exp["matched_policies"][0]["conditions"])

    # From a trusted zone the condition fails → baseline applies.
    d = _evaluate(client, admin, "dataset.export", {"environment.network_zone": "CORPORATE"})
    assert d["decision"] == "NOT_APPLICABLE" and d["applicable"] is False


def test_challenge_and_constraint_effects(client: TestClient, admin: dict) -> None:
    action = f"workflow.run{uuid.uuid4().hex[:6]}"
    approval = _create_policy(
        client, admin, effect="REQUIRE_APPROVAL",
        target={"actions": [action]},
        conditions={"all": [{"attribute": "ai.autonomy_level", "operator": "IN",
                             "value": ["AUTONOMOUS", "CRITICAL_AUTONOMOUS"]}]},
        obligations={"priority": "CRITICAL", "reviewer_role": "ROLE_AI_REVIEWER"},
    )
    _publish(client, admin, approval["id"])
    d = _evaluate(client, admin, action, {"ai.autonomy_level": "AUTONOMOUS"})
    assert d["decision"] == "REQUIRE_APPROVAL" and d["allowed"] is False
    ob = next(o for o in d["obligations"] if o["type"] == "CREATE_APPROVAL")
    assert ob["priority"] == "CRITICAL" and ob["reviewer_role"] == "ROLE_AI_REVIEWER"

    # MASK_FIELDS allows but attaches the field list.
    mask_action = f"record.view{uuid.uuid4().hex[:6]}"
    mask = _create_policy(
        client, admin, effect="MASK_FIELDS", target={"actions": [mask_action]},
        conditions=None, obligations={"fields": ["ssn", "medical_record_number"]},
    )
    _publish(client, admin, mask["id"])
    d = _evaluate(client, admin, mask_action)
    assert d["decision"] == "MASK_FIELDS" and d["allowed"] is True
    assert next(o for o in d["obligations"]
                if o["type"] == "MASK_FIELDS")["fields"] == ["ssn", "medical_record_number"]

    # LIMIT_ACTION allows with limits.
    limit_action = f"dataset.pull{uuid.uuid4().hex[:6]}"
    limit = _create_policy(
        client, admin, effect="LIMIT_ACTION", target={"actions": [limit_action]},
        conditions=None, obligations={"maximum_export_rows": 1000},
    )
    _publish(client, admin, limit["id"])
    d = _evaluate(client, admin, limit_action)
    assert d["decision"] == "LIMIT_ACTION" and d["allowed"] is True
    assert next(o for o in d["obligations"]
                if o["type"] == "LIMIT_ACTION")["limits"] == {"maximum_export_rows": 1000}

    # LOG_ONLY records an observation without changing the decision.
    log_action = f"report.view{uuid.uuid4().hex[:6]}"
    log = _create_policy(client, admin, effect="LOG_ONLY",
                         target={"actions": [log_action]}, conditions=None)
    _publish(client, admin, log["id"])
    d = _evaluate(client, admin, log_action)
    assert d["decision"] == "NOT_APPLICABLE", "LOG_ONLY must not change the decision"
    assert any(o["type"] == "LOG_ONLY" for o in d["obligations"]), "observation recorded (§8)"

    # Audit events (§38).
    audit = client.get("/api/v1/authorization/audit?event_type=ABAC_APPROVAL_REQUIRED",
                       headers=admin["headers"]).json()
    assert any(a["meta"] and a["meta"].get("action") == action for a in audit)


# --- Redaction (§16, §40.7) ------------------------------------------------------------ #
def test_sensitive_attribute_values_redacted(client: TestClient, admin: dict) -> None:
    action = f"risky.op{uuid.uuid4().hex[:6]}"
    p = _create_policy(
        client, admin, target={"actions": [action]},
        conditions={"all": [{"attribute": "environment.session_risk",
                             "operator": "GREATER_THAN_OR_EQUAL", "value": 70}]},
    )
    _publish(client, admin, p["id"])
    d = _evaluate(client, admin, action, {"environment.session_risk": 82})
    assert d["decision"] == "DENY"
    cond = d["explanation"]["matched_policies"][0]["conditions"][0]
    assert cond["attribute"] == "environment.session_risk"
    assert cond["expected"] == "[REDACTED]", "RESTRICTED attribute value must be redacted"


# --- Permission Engine integration (§4, §25) ---------------------------------------------- #
def test_abac_layers_over_authorization_check(client: TestClient, admin: dict) -> None:
    member = _invite_member(client, admin)  # VIEWER: has agent.view baseline

    # Baseline allow + no policy → ALLOW.
    check = client.post("/api/v1/authorization/check", headers=member["headers"],
                        json={"permission": "agent.view"}).json()
    assert check["allowed"] is True and check["decision"] == "ALLOW"

    # An ABAC deny on that action flips the same check to DENY.
    p = _create_policy(
        client, admin, target={"actions": ["agent.view"]},
        conditions={"all": [{"attribute": "action.read_only", "operator": "EQUALS",
                             "value": True}]},
    )
    _publish(client, admin, p["id"])
    check = client.post("/api/v1/authorization/check", headers=member["headers"],
                        json={"permission": "agent.view"}).json()
    assert check["allowed"] is False and check["decision"] == "DENY"
    assert p["name"] in check["reason"]
    assert "ABAC_DENY" in check["events"]

    # ABAC never grants what RBAC denied (§4): an ALLOW policy on a permission
    # the member lacks changes nothing.
    grant = _create_policy(client, admin, effect="ALLOW",
                           target={"actions": ["role.manage"]}, conditions=None)
    _publish(client, admin, grant["id"])
    check = client.post("/api/v1/authorization/check", headers=member["headers"],
                        json={"permission": "role.manage"}).json()
    assert check["allowed"] is False and check["decision"] == "DENY"

    # Context flows through: approval above a row threshold (§31).
    big = _create_policy(
        client, admin, effect="REQUIRE_APPROVAL",
        target={"actions": ["audit.export"]},
        conditions={"all": [{"attribute": "action.target_count",
                             "operator": "GREATER_THAN", "value": 10000}]},
        obligations={"priority": "HIGH"},
    )
    _publish(client, admin, big["id"])
    check = client.post("/api/v1/authorization/check", headers=admin["headers"],
                        json={"permission": "audit.export",
                              "context": {"action.target_count": 20000}}).json()
    assert check["decision"] == "REQUIRE_APPROVAL" and check["allowed"] is False
    assert any(o["type"] == "CREATE_APPROVAL" for o in check["obligations"])
    small = client.post("/api/v1/authorization/check", headers=admin["headers"],
                        json={"permission": "audit.export",
                              "context": {"action.target_count": 10}}).json()
    assert small["allowed"] is True and small["decision"] == "ALLOW"


def test_subject_attributes_cannot_be_spoofed(client: TestClient, admin: dict) -> None:
    action = f"secure.op{uuid.uuid4().hex[:6]}"
    p = _create_policy(
        client, admin, target={"actions": [action]},
        conditions={"all": [{"attribute": "identity.risk_score", "operator": "EXISTS"},
                            {"attribute": "identity.risk_score",
                             "operator": "LESS_THAN", "value": 5}]},
        effect="ALLOW",
    )
    _publish(client, admin, p["id"])
    # The caller tries to inject identity.risk_score through the request context.
    d = _evaluate(client, admin, action, {"identity.risk_score": 1})
    assert d["decision"] == "NOT_APPLICABLE", "identity.* overrides must be dropped"


# --- Scoping (§12) --------------------------------------------------------------------------- #
def test_department_scoped_policy(client: TestClient, admin: dict) -> None:
    dept = client.post("/api/v1/departments", json={"name": f"D_{uuid.uuid4().hex[:6]}"},
                       headers=admin["headers"]).json()
    inside = _invite_member(client, admin, department_id=dept["id"])
    outside = _invite_member(client, admin)

    action = f"agent.tune{uuid.uuid4().hex[:6]}"
    p = _create_policy(client, admin, scope_type="DEPARTMENT", scope_id=dept["id"],
                       target={"actions": [action]}, conditions=None)
    _publish(client, admin, p["id"])

    assert _evaluate(client, inside, action)["decision"] == "DENY"
    assert _evaluate(client, outside, action)["decision"] == "NOT_APPLICABLE"


# --- Simulation (§35) -------------------------------------------------------------------------- #
def test_simulator_reports_all_layers_without_enforcing(client: TestClient, admin: dict) -> None:
    member = _invite_member(client, admin)
    p = _create_policy(client, admin, target={"actions": ["dataset.export"]})
    # Simulate the *draft* policy for another identity with attribute overrides.
    r = client.post(f"{BASE}/abac/policies/{p['id']}/simulate", headers=admin["headers"], json={
        "action": "dataset.export", "identity_id": member["user_id"],
        "context": {"environment.network_zone": "PUBLIC"},
    })
    assert r.status_code == 200, r.text
    sim = r.json()
    assert sim["baseline_rbac"]["allowed"] is False  # VIEWER lacks dataset.export
    assert sim["abac"]["decision"] == "DENY"
    assert sim["abac"]["matched_policies"][0]["policy_id"] == p["id"]

    # The generic simulator with an inline draft policy.
    r2 = client.post(f"{BASE}/abac/simulate", headers=admin["headers"], json={
        "action": "anything.run",
        "context": {"environment.network_zone": "CORPORATE"},
        "policy": {"name": "inline", "effect": "DENY", "conditions": {"all": [
            {"attribute": "environment.network_zone", "operator": "EQUALS",
             "value": "CORPORATE"}]}},
    })
    assert r2.status_code == 200
    assert r2.json()["abac"]["decision"] == "DENY"

    # Simulation is read-only: no live ABAC access event was produced for it.
    audit = client.get("/api/v1/authorization/audit?event_type=ABAC_POLICY_SIMULATED",
                       headers=admin["headers"]).json()
    assert len(audit) >= 2


# --- Exceptions (§21, §40.12) --------------------------------------------------------------------- #
def test_policy_exceptions_skip_and_expire(client: TestClient, admin: dict) -> None:
    action = f"except.op{uuid.uuid4().hex[:6]}"
    p = _create_policy(client, admin, target={"actions": [action]}, conditions=None)
    _publish(client, admin, p["id"])
    assert _evaluate(client, admin, action)["decision"] == "DENY"

    # Exceptions must be time-boxed.
    r = client.post(f"{BASE}/exceptions", headers=admin["headers"], json={
        "policy_id": p["id"], "subject_id": admin["user_id"],
    })
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "VALIDATION_ERROR"

    # An approved, in-window exception exempts the subject from the policy.
    exc = client.post(f"{BASE}/exceptions", headers=admin["headers"], json={
        "policy_id": p["id"], "subject_id": admin["user_id"],
        "reason": "incident response", "valid_until": _iso(hours=1),
    })
    assert exc.status_code == 201, exc.text
    assert _evaluate(client, admin, action)["decision"] == "NOT_APPLICABLE"

    # Revoking restores enforcement.
    assert client.delete(f"{BASE}/exceptions/{exc.json()['id']}",
                         headers=admin["headers"]).status_code == 200
    assert _evaluate(client, admin, action)["decision"] == "DENY"

    # An expired exception is ignored (and auto-marked EXPIRED).
    expired = client.post(f"{BASE}/exceptions", headers=admin["headers"], json={
        "policy_id": p["id"], "subject_id": admin["user_id"],
        "valid_until": _iso(minutes=-5),
    }).json()
    assert _evaluate(client, admin, action)["decision"] == "DENY"
    rows = client.get(f"{BASE}/exceptions", headers=admin["headers"]).json()
    assert next(r for r in rows if r["id"] == expired["id"])["status"] == "EXPIRED"


# --- Cross-tenant isolation + authorization (§37, §40, §42) ----------------------------------------- #
def test_cross_tenant_isolation_and_unauthorized_publish(client: TestClient, admin: dict) -> None:
    other = _register_org(client, org="Abac Other Org")
    p = _create_policy(client, admin)
    _publish(client, admin, p["id"])

    # The other org cannot see or affect this policy…
    assert client.get(f"{BASE}/abac/policies/{p['id']}",
                      headers=other["headers"]).status_code == 404
    listing = client.get(f"{BASE}/abac/policies", headers=other["headers"]).json()
    assert all(row["id"] != p["id"] for row in listing)
    # …and is not affected by it.
    d = _evaluate(client, other, "dataset.export", {"environment.network_zone": "PUBLIC"})
    assert d["decision"] == "NOT_APPLICABLE"

    # Members without §37 permissions can neither author nor publish.
    member = _invite_member(client, admin)
    assert client.post(f"{BASE}/abac/policies", headers=member["headers"],
                       json={"name": "nope", "effect": "DENY"}).status_code == 403
    assert client.post(f"{BASE}/abac/policies/{p['id']}/publish",
                       headers=member["headers"]).status_code == 403
    assert client.get(f"{BASE}/abac/evaluations", headers=member["headers"]).status_code == 403

    # Platform-scoped policies require platform administration (§40.6).
    r = client.post(f"{BASE}/abac/policies", headers=admin["headers"],
                    json={"name": "platform-wide", "effect": "DENY", "scope_type": "PLATFORM"})
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "ABAC_POLICY_PUBLISH_DENIED"


# --- Evaluations log + metrics (§36, §43) ------------------------------------------------------------- #
def test_evaluations_are_recorded_and_metrics_exposed(client: TestClient, admin: dict) -> None:
    action = f"metric.op{uuid.uuid4().hex[:6]}"
    p = _create_policy(client, admin, target={"actions": [action]}, conditions=None)
    _publish(client, admin, p["id"])
    _evaluate(client, admin, action)

    rows = client.get(f"{BASE}/abac/evaluations?decision=DENY", headers=admin["headers"]).json()
    row = next(r for r in rows if r["action"] == action)
    assert row["decision"] == "DENY"
    assert row["matched_policy_ids"] == [p["id"]]
    assert row["evaluation_time_ms"] is not None
    detail = client.get(f"{BASE}/abac/evaluations/{row['id']}", headers=admin["headers"]).json()
    assert detail["explanation"]["winning_effect"] == "DENY"

    metrics = client.get(f"{BASE}/abac/metrics", headers=admin["headers"]).json()
    assert metrics["abac_evaluations_total"] >= 1
    assert metrics["abac_denies_total"] >= 1
    assert "abac_evaluation_latency_ms" in metrics and "abac_cache_hit_ratio" in metrics
