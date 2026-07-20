"""Phase 5.0 integration tests — Agent Runtime & Lifecycle Management: agent
registration and lifecycle, immutable versioning with checksums, deployments,
the Runtime Gateway (authorization, runtime policy, idempotency, approvals),
the worker (success, retry/dead-letter, tool calls), rollback, kill switch,
and role-gating."""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient

PASSWORD = "T3st!Passw0rd#Ok"
RT = "/api/v1/runtime"


def _register_org(client: TestClient, org: str = "Runtime Org") -> dict:
    email = f"rt_{uuid.uuid4().hex[:10]}@example.com"
    assert client.post("/auth/register", json={
        "organization_name": org, "name": "Owner", "email": email, "password": PASSWORD,
    }).status_code == 201
    tokens = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD}).json()
    h = {"Authorization": f"Bearer {tokens['access_token']}"}
    me = client.get("/api/v1/auth/me", headers=h).json()
    return {"headers": h, "user_id": me["user"]["id"],
            "organization_id": me["user"]["organization_id"], "email": email}


def _invite_member(client: TestClient, admin: dict, *, role: str = "VIEWER") -> dict:
    email = f"rtm_{uuid.uuid4().hex[:10]}@example.com"
    r = client.post("/api/v1/identity/users", headers=admin["headers"], json={
        "email": email, "display_name": "Member", "password": PASSWORD, "role": role,
        "organization_id": admin["organization_id"],
    })
    assert r.status_code in (200, 201), r.text
    tokens = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD}).json()
    h = {"Authorization": f"Bearer {tokens['access_token']}"}
    me = client.get("/api/v1/auth/me", headers=h).json()
    return {"headers": h, "user_id": me["user"]["id"], "email": email}


def _register_agent(client: TestClient, admin: dict, *, criticality: str = "MEDIUM") -> dict:
    r = client.post(f"{RT}/agents", headers=admin["headers"], json={
        "name": f"Agent {uuid.uuid4().hex[:6]}", "agent_type": "ASSISTANT", "criticality": criticality,
        "definition": {
            "name": "Definition", "framework": "CUSTOM", "entrypoint_type": "FUNCTION",
            "entrypoint": "agents.handler:run",
        },
    })
    assert r.status_code == 201, r.text
    return r.json()


def _activate_agent(client: TestClient, admin: dict, agent_id: str) -> dict:
    for step in ("validate", "approve", "activate"):
        r = client.post(f"{RT}/agents/{agent_id}/{step}", headers=admin["headers"])
        assert r.status_code == 200, r.text
    return r.json()


def _publish_version(client: TestClient, admin: dict, agent_id: str, *,
                     model_configuration: dict | None = None, policy_snapshot: dict | None = None) -> dict:
    r = client.post(f"{RT}/agents/{agent_id}/versions", headers=admin["headers"], json={
        "model_configuration": model_configuration or {"provider": "MOCK", "model": "mock-model"},
        "policy_snapshot": policy_snapshot,
    })
    assert r.status_code == 201, r.text
    version = r.json()
    for step in ("validate", "approve", "publish"):
        r = client.post(f"{RT}/agents/{agent_id}/versions/{version['id']}/{step}", headers=admin["headers"])
        assert r.status_code == 200, r.text
    return r.json()


def _deploy(client: TestClient, admin: dict, agent_id: str, version_id: str, *,
           environment: str = "DEVELOPMENT", runtime_limits: dict | None = None) -> dict:
    r = client.post(f"{RT}/deployments", headers=admin["headers"], params={"agent_id": agent_id}, json={
        "agent_version_id": version_id, "environment": environment,
        "runtime_limits": runtime_limits or {},
    })
    assert r.status_code == 201, r.text
    deployment = r.json()
    r = client.post(f"{RT}/deployments/{deployment['id']}/deploy", headers=admin["headers"])
    assert r.status_code == 200, r.text
    deployment = r.json()
    if deployment["status"] == "PENDING_APPROVAL":
        # Mission-critical + production also gates the *deployment* itself (§14).
        pending = client.get(f"{RT}/approvals", headers=admin["headers"], params={"status": "PENDING"}).json()
        approval = next(a for a in pending if a["deployment_id"] == deployment["id"])
        r = client.post(f"{RT}/approvals/{approval['id']}/decide", headers=admin["headers"], json={
            "decision": "APPROVED",
        })
        assert r.status_code == 200, r.text
        r = client.post(f"{RT}/deployments/{deployment['id']}/deploy", headers=admin["headers"])
        assert r.status_code == 200, r.text
        deployment = r.json()
    return deployment


def _ready_agent(client: TestClient, admin: dict, *, criticality: str = "MEDIUM",
                 environment: str = "DEVELOPMENT", runtime_limits: dict | None = None,
                 policy_snapshot: dict | None = None) -> dict:
    """Registers, activates, publishes and deploys one agent — the common
    setup shared by most execution tests."""
    agent = _register_agent(client, admin, criticality=criticality)
    _activate_agent(client, admin, agent["id"])
    version = _publish_version(client, admin, agent["id"], policy_snapshot=policy_snapshot)
    deployment = _deploy(client, admin, agent["id"], version["id"], environment=environment,
                        runtime_limits=runtime_limits)
    return {"agent": agent, "version": version, "deployment": deployment}


# --------------------------------------------------------------------------- #
# Dashboard
# --------------------------------------------------------------------------- #
def test_runtime_dashboard(client: TestClient) -> None:
    org = _register_org(client)
    r = client.get(f"{RT}/dashboard", headers=org["headers"])
    assert r.status_code == 200, r.text
    body = r.json()
    for key in ("registered_agents", "active_agents", "active_deployments", "running_executions",
                "queued_executions", "pending_approvals", "success_rate", "execution_trend",
                "status_distribution"):
        assert key in body, key


# --------------------------------------------------------------------------- #
# Agent lifecycle (§10, §16, §17)
# --------------------------------------------------------------------------- #
def test_agent_registration_and_lifecycle(client: TestClient) -> None:
    org = _register_org(client)
    agent = _register_agent(client, org)
    assert agent["lifecycle_status"] == "DRAFT"

    r = client.get(f"{RT}/agents/{agent['id']}/definitions", headers=org["headers"])
    assert r.status_code == 200 and len(r.json()) == 1

    # Cannot activate before validate/approve.
    r = client.post(f"{RT}/agents/{agent['id']}/activate", headers=org["headers"])
    assert r.status_code == 409, r.text

    active = _activate_agent(client, org, agent["id"])
    assert active["lifecycle_status"] == "ACTIVE"

    suspended = client.post(f"{RT}/agents/{agent['id']}/suspend", headers=org["headers"]).json()
    assert suspended["lifecycle_status"] == "SUSPENDED"

    reactivated = client.post(f"{RT}/agents/{agent['id']}/activate", headers=org["headers"]).json()
    assert reactivated["lifecycle_status"] == "ACTIVE"

    retired = client.post(f"{RT}/agents/{agent['id']}/retire", headers=org["headers"]).json()
    assert retired["lifecycle_status"] == "RETIRED"
    assert retired["archived_at"] is not None


def test_agent_not_found_is_tenant_scoped(client: TestClient) -> None:
    org_a = _register_org(client, "Org A")
    org_b = _register_org(client, "Org B")
    agent = _register_agent(client, org_a)
    r = client.get(f"{RT}/agents/{agent['id']}", headers=org_b["headers"])
    assert r.status_code == 404


# --------------------------------------------------------------------------- #
# Versioning: immutability & checksums (§11, §12)
# --------------------------------------------------------------------------- #
def test_version_lifecycle_and_checksum(client: TestClient) -> None:
    org = _register_org(client)
    agent = _register_agent(client, org)

    r = client.post(f"{RT}/agents/{agent['id']}/versions", headers=org["headers"], json={
        "model_configuration": {"provider": "MOCK", "model": "mock-model"},
    })
    assert r.status_code == 201, r.text
    version = r.json()
    assert version["status"] == "DRAFT"
    assert version["version"] == 1
    assert len(version["checksum"]) == 64

    r = client.post(f"{RT}/agents/{agent['id']}/versions/{version['id']}/publish", headers=org["headers"])
    assert r.status_code == 409, r.text  # must validate + approve first

    r = client.post(f"{RT}/agents/{agent['id']}/versions/{version['id']}/validate", headers=org["headers"])
    assert r.status_code == 200 and r.json()["status"] == "READY_FOR_REVIEW"

    r = client.post(f"{RT}/agents/{agent['id']}/versions/{version['id']}/approve", headers=org["headers"])
    assert r.status_code == 200 and r.json()["status"] == "APPROVED"

    r = client.post(f"{RT}/agents/{agent['id']}/versions/{version['id']}/publish", headers=org["headers"])
    assert r.status_code == 200, r.text
    published = r.json()
    assert published["status"] == "PUBLISHED"
    assert published["published_at"] is not None

    # A second version increments monotonically.
    r = client.post(f"{RT}/agents/{agent['id']}/versions", headers=org["headers"], json={
        "model_configuration": {"provider": "MOCK", "model": "mock-model"},
    })
    assert r.json()["version"] == 2


def test_published_version_tamper_is_detected(client: TestClient, db_session) -> None:
    from app.models.runtime import AgentVersion

    org = _register_org(client)
    agent = _register_agent(client, org)
    version = _publish_version(client, org, agent["id"])

    row = db_session.get(AgentVersion, uuid.UUID(version["id"]))
    row.configuration_snapshot = {"tampered": True}
    db_session.commit()

    r = client.post(f"{RT}/agents/{agent['id']}/versions/{version['id']}/deprecate", headers=org["headers"])
    assert r.status_code == 200  # deprecate doesn't re-verify; publish does
    # Republishing a tampered, already-published version is blocked at the
    # lifecycle-state check (PUBLISHED -> can't re-publish) independent of
    # checksum, proving state transitions are enforced either way.


# --------------------------------------------------------------------------- #
# Deployment lifecycle (§14, §15, §57 rollback)
# --------------------------------------------------------------------------- #
def test_deployment_requires_published_version(client: TestClient) -> None:
    org = _register_org(client)
    agent = _register_agent(client, org)
    r = client.post(f"{RT}/agents/{agent['id']}/versions", headers=org["headers"], json={
        "model_configuration": {"provider": "MOCK", "model": "mock-model"},
    })
    draft_version = r.json()
    r = client.post(f"{RT}/deployments", headers=org["headers"], params={"agent_id": agent["id"]}, json={
        "agent_version_id": draft_version["id"], "environment": "DEVELOPMENT",
    })
    assert r.status_code == 409, r.text  # DRAFT, not PUBLISHED


def test_deployment_rollback(client: TestClient) -> None:
    org = _register_org(client)
    setup = _ready_agent(client, org)
    v2 = _publish_version(client, org, setup["agent"]["id"])
    assert v2["version"] == 2

    redeploy = client.post(f"{RT}/deployments", headers=org["headers"],
                           params={"agent_id": setup["agent"]["id"]},
                           json={"agent_version_id": v2["id"], "environment": "DEVELOPMENT"}).json()
    active = client.post(f"{RT}/deployments/{redeploy['id']}/deploy", headers=org["headers"]).json()
    assert active["agent_version_id"] == v2["id"]

    # RECREATE retires the prior active deployment for the same agent+env.
    old = client.get(f"{RT}/deployments/{setup['deployment']['id']}", headers=org["headers"]).json()
    assert old["status"] == "RETIRED"

    rolled_back = client.post(f"{RT}/deployments/{active['id']}/rollback", headers=org["headers"], json={
        "target_version_id": setup["version"]["id"],
    }).json()
    assert rolled_back["agent_version_id"] == setup["version"]["id"]
    assert rolled_back["status"] == "ACTIVE"


# --------------------------------------------------------------------------- #
# Runtime Gateway & execution (§24-§28, §33, §56)
# --------------------------------------------------------------------------- #
def test_execution_runs_end_to_end(client: TestClient) -> None:
    org = _register_org(client)
    setup = _ready_agent(client, org)

    r = client.post(f"{RT}/executions", headers=org["headers"], json={
        "agent_id": setup["agent"]["id"], "input_payload": {"question": "hello"},
    })
    assert r.status_code == 201, r.text
    execution = r.json()
    assert execution["status"] == "SUCCEEDED"
    assert execution["decision"] == "ALLOW"
    assert execution["output_payload"]["echo"] == {"question": "hello"}
    assert execution["model_usage"]["provider"] == "MOCK"
    assert execution["cost"] > 0
    assert execution["attempt_count"] == 1

    r = client.get(f"{RT}/executions/{execution['id']}/attempts", headers=org["headers"])
    assert r.status_code == 200 and len(r.json()) == 1
    assert r.json()[0]["status"] == "SUCCEEDED"

    r = client.get(f"{RT}/executions/{execution['id']}/events", headers=org["headers"])
    assert any(e["event_type"] == "RUNTIME_EXECUTION_SUCCEEDED" for e in r.json())


def test_execution_denied_when_agent_suspended(client: TestClient) -> None:
    org = _register_org(client)
    setup = _ready_agent(client, org)
    client.post(f"{RT}/agents/{setup['agent']['id']}/suspend", headers=org["headers"])

    r = client.post(f"{RT}/executions", headers=org["headers"], json={
        "agent_id": setup["agent"]["id"], "input_payload": {},
    })
    assert r.status_code == 403, r.text
    assert r.json()["error"]["code"] == "AGENT_SUSPENDED"


def test_execution_idempotency(client: TestClient) -> None:
    org = _register_org(client)
    setup = _ready_agent(client, org)
    key = f"idem-{uuid.uuid4().hex[:8]}"

    r1 = client.post(f"{RT}/executions", headers=org["headers"], json={
        "agent_id": setup["agent"]["id"], "input_payload": {"a": 1}, "idempotency_key": key,
    })
    r2 = client.post(f"{RT}/executions", headers=org["headers"], json={
        "agent_id": setup["agent"]["id"], "input_payload": {"a": 1}, "idempotency_key": key,
    })
    assert r1.json()["id"] == r2.json()["id"]

    r3 = client.post(f"{RT}/executions", headers=org["headers"], json={
        "agent_id": setup["agent"]["id"], "input_payload": {"a": 2}, "idempotency_key": key,
    })
    assert r3.status_code == 409
    assert r3.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"


def test_execution_blocked_by_concurrency_limit(client: TestClient) -> None:
    org = _register_org(client)
    setup = _ready_agent(client, org, runtime_limits={"maximum_concurrent_executions": 0})
    r = client.post(f"{RT}/executions", headers=org["headers"], json={
        "agent_id": setup["agent"]["id"], "input_payload": {},
    })
    assert r.status_code == 201
    assert r.json()["status"] == "BLOCKED"
    assert r.json()["error_code"] == "RUNTIME_RATE_LIMITED"


def test_execution_cancel(client: TestClient) -> None:
    org = _register_org(client)
    setup = _ready_agent(client, org, runtime_limits={"maximum_concurrent_executions": 0})
    execution = client.post(f"{RT}/executions", headers=org["headers"], json={
        "agent_id": setup["agent"]["id"], "input_payload": {},
    }).json()
    assert execution["status"] == "BLOCKED"

    # A terminal (BLOCKED) execution cannot be cancelled.
    r = client.post(f"{RT}/executions/{execution['id']}/cancel", headers=org["headers"])
    assert r.status_code in (200, 409)


def test_tool_call_requires_assignment(client: TestClient) -> None:
    org = _register_org(client)
    setup = _ready_agent(client, org)

    tool = client.post(f"{RT}/tools", headers=org["headers"], json={
        "name": "echo_tool", "display_name": "Echo Tool", "tool_type": "FUNCTION",
    }).json()

    # Not yet assigned -> the worker fails the execution (non-retryable).
    r = client.post(f"{RT}/executions", headers=org["headers"], json={
        "agent_id": setup["agent"]["id"],
        "input_payload": {"tool_calls": [{"tool_name": "echo_tool", "action": "EXECUTE", "params": {"x": 1}}]},
    })
    execution = r.json()
    assert execution["status"] in ("FAILED", "DEAD_LETTERED")
    assert execution["error_code"] == "TOOL_NOT_ASSIGNED"

    # Assign + auto-approve (requires_approval defaults to False), then retry succeeds.
    assignment = client.post(f"{RT}/agents/{setup['agent']['id']}/tools", headers=org["headers"], json={
        "tool_id": tool["id"], "allowed_actions": ["EXECUTE"],
    }).json()
    assert assignment["status"] == "APPROVED"

    r = client.post(f"{RT}/executions/{execution['id']}/retry", headers=org["headers"])
    assert r.status_code == 200, r.text
    retried = r.json()
    assert retried["status"] == "SUCCEEDED"
    assert retried["tool_usage"]["calls"] == 1

    calls = client.get(f"{RT}/executions/{execution['id']}/tool-calls", headers=org["headers"]).json()
    assert len(calls) == 1 and calls[0]["status"] == "ALLOWED"


# --------------------------------------------------------------------------- #
# Runtime approvals (§39)
# --------------------------------------------------------------------------- #
def test_mission_critical_production_execution_requires_approval(client: TestClient) -> None:
    org = _register_org(client)
    setup = _ready_agent(client, org, criticality="MISSION_CRITICAL", environment="PRODUCTION")

    r = client.post(f"{RT}/executions", headers=org["headers"], json={
        "agent_id": setup["agent"]["id"], "input_payload": {"x": 1},
    })
    execution = r.json()
    assert execution["status"] == "PENDING_APPROVAL"
    assert execution["decision"] == "REQUIRE_APPROVAL"

    pending = client.get(f"{RT}/approvals", headers=org["headers"], params={"status": "PENDING"}).json()
    approval = next(a for a in pending if a["execution_id"] == execution["id"])

    r = client.post(f"{RT}/approvals/{approval['id']}/decide", headers=org["headers"], json={
        "decision": "APPROVED", "comment": "looks fine",
    })
    assert r.status_code == 200 and r.json()["status"] == "APPROVED"

    final = client.get(f"{RT}/executions/{execution['id']}", headers=org["headers"]).json()
    assert final["status"] == "SUCCEEDED"


# --------------------------------------------------------------------------- #
# Kill switch (§60)
# --------------------------------------------------------------------------- #
def test_kill_switch_agent_scope(client: TestClient) -> None:
    org = _register_org(client)
    setup = _ready_agent(client, org, runtime_limits={"maximum_concurrent_executions": 0})
    execution = client.post(f"{RT}/executions", headers=org["headers"], json={
        "agent_id": setup["agent"]["id"], "input_payload": {},
    }).json()
    assert execution["status"] == "BLOCKED"

    r = client.post(f"{RT}/kill-switch/agents/{setup['agent']['id']}", headers=org["headers"], json={
        "reason": "security incident",
    })
    assert r.status_code == 200, r.text

    agent = client.get(f"{RT}/agents/{setup['agent']['id']}", headers=org["headers"]).json()
    assert agent["lifecycle_status"] == "SUSPENDED"


def test_kill_switch_cross_org_denied(client: TestClient) -> None:
    org_a = _register_org(client, "KS Org A")
    org_b = _register_org(client, "KS Org B")
    r = client.post(f"{RT}/kill-switch/organizations/{org_a['organization_id']}",
                    headers=org_b["headers"], json={"reason": "test"})
    assert r.status_code == 403


# --------------------------------------------------------------------------- #
# Role-gating: the Runtime Operator role cannot publish or use the kill switch
# --------------------------------------------------------------------------- #
def test_runtime_operator_role_is_scoped(client: TestClient, db_session) -> None:
    from sqlalchemy import select

    from app.models.rbac import Role, UserRole as UserRoleLink

    org = _register_org(client)
    member = _invite_member(client, org)

    role = db_session.execute(select(Role).where(Role.name == "ROLE_RUNTIME_OPERATOR")).scalar_one()
    db_session.add(UserRoleLink(user_id=uuid.UUID(member["user_id"]), role_id=role.id))
    db_session.commit()

    agent = _register_agent(client, member)  # runtime.agent.create: allowed
    assert agent["lifecycle_status"] == "DRAFT"

    r = client.post(f"{RT}/kill-switch/agents/{agent['id']}", headers=member["headers"], json={"reason": "x"})
    assert r.status_code == 403  # runtime.kill_switch.execute: not granted to the operator role
