"""Phase 3.3 (ACT-SRS-M3 §Phase-3.3) tests -- the deployment preflight /
release gate engine: ``ReleaseGateService``, its aggregated checks, the
freshness rule, and its wiring into the 3.1 deployment lifecycle.

Grouped by the build prompt's own §12 acceptance criteria. Real Postgres
throughout (this codebase's established convention -- ``tests/runtime/
conftest.py``), mirroring ``test_environment_promotion.py``'s and
``test_deployment_lifecycle.py``'s own setup-helper conventions (each test
file in this suite defines its own local helpers rather than importing
across files)."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.identity.models.agent_identity import AgentIdentity
from app.models.runtime import AgentVersion, DeploymentHealth, DeploymentPreflightResult, Tool
from app.runtime.release_gate import checks

RT = "/api/v1/runtime"


# --------------------------------------------------------------------------- #
# HTTP setup helpers
# --------------------------------------------------------------------------- #
def _register_agent(client: TestClient, admin: dict, *, criticality: str = "MEDIUM") -> dict:
    payload = {
        "name": f"Gate Agent {uuid.uuid4().hex[:6]}", "agent_type": "ASSISTANT", "criticality": criticality,
        "description": "A test agent.", "business_purpose": "Exercise the release gate in tests.",
        "owner_type": "USER", "owner_id": admin["user_id"], "technical_owner_id": admin["user_id"],
        "compliance_owner_id": admin["user_id"],
        "definition": {"name": "Definition", "framework": "CUSTOM", "entrypoint_type": "FUNCTION",
                      "entrypoint": "agents.handler:run"},
    }
    r = client.post(f"{RT}/agents", headers=admin["headers"], json=payload)
    assert r.status_code == 201, r.text
    return r.json()


def _activate_agent(client: TestClient, admin: dict, agent_id: str) -> None:
    for step in ("register", "validate"):
        r = client.post(f"{RT}/agents/{agent_id}/{step}", headers=admin["headers"])
        assert r.status_code == 200, r.text
    r = client.post(f"{RT}/agents/{agent_id}/identity/create-and-associate", headers=admin["headers"], json={
        "client_id": f"agent-identity-{uuid.uuid4().hex[:10]}",
    })
    assert r.status_code == 200, r.text
    for step in ("submit-for-approval", "approve", "activate"):
        r = client.post(f"{RT}/agents/{agent_id}/{step}", headers=admin["headers"])
        assert r.status_code == 200, r.text


def _publish_version(client: TestClient, admin: dict, agent_id: str, *,
                     provider: str = "MOCK", model: str = "mock-model",
                     tool_ids: list[str] | None = None) -> dict:
    payload = {"model_configuration": {"provider": provider, "model": model}, "tool_ids": tool_ids or []}
    r = client.post(f"{RT}/agents/{agent_id}/versions", headers=admin["headers"], json=payload)
    assert r.status_code == 201, r.text
    version = r.json()
    for step in ("validate", "approve", "publish"):
        r = client.post(f"{RT}/agents/{agent_id}/versions/{version['id']}/{step}", headers=admin["headers"])
        assert r.status_code == 200, r.text
    return r.json()


def _create_deployment(client: TestClient, admin: dict, agent_id: str, version_id: str, *,
                       environment: str = "DEVELOPMENT") -> dict:
    r = client.post(f"{RT}/deployments", headers=admin["headers"], params={"agent_id": agent_id},
                    json={"agent_version_id": version_id, "environment": environment})
    assert r.status_code == 201, r.text
    return r.json()


def _ready_deployment(client: TestClient, admin: dict, agent_id: str, version_id: str, *,
                      environment: str = "DEVELOPMENT") -> dict:
    deployment = _create_deployment(client, admin, agent_id, version_id, environment=environment)
    deployment = _transition(client, admin, deployment["id"], "VALIDATING")
    deployment = _transition(client, admin, deployment["id"], "READY")
    return deployment


def _transition(client: TestClient, admin: dict, deployment_id: str, to_state: str) -> dict:
    r = client.post(f"{RT}/deployments/{deployment_id}/lifecycle/transition", headers=admin["headers"],
                    json={"to_state": to_state})
    assert r.status_code == 200, r.text
    return r.json()


def _environments(client: TestClient, admin: dict) -> dict[str, dict]:
    r = client.get(f"{RT}/environments", headers=admin["headers"])
    assert r.status_code == 200, r.text
    return {e["name"]: e for e in r.json()}


def _full_setup(client: TestClient, admin: dict, *, criticality: str = "MEDIUM",
                provider: str = "MOCK", model: str = "mock-model", tool_ids: list[str] | None = None) -> dict:
    _environments(client, admin)
    agent = _register_agent(client, admin, criticality=criticality)
    _activate_agent(client, admin, agent["id"])
    version = _publish_version(client, admin, agent["id"], provider=provider, model=model, tool_ids=tool_ids)
    return {"agent": agent, "version": version}


def _create_tool(client: TestClient, admin: dict, *, data_classification: str = "INTERNAL") -> dict:
    r = client.post(f"{RT}/tools", headers=admin["headers"], json={
        "name": f"tool_{uuid.uuid4().hex[:8]}", "display_name": "Test Tool", "tool_type": "FUNCTION",
        "data_classification": data_classification,
    })
    assert r.status_code == 201, r.text
    return r.json()


def _preflight(client: TestClient, admin: dict, deployment_id: str) -> tuple[dict, int]:
    r = client.post(f"{RT}/deployments/{deployment_id}/preflight", headers=admin["headers"])
    return r.json(), r.status_code


def _register_second_org(client: TestClient) -> dict:
    from tests.runtime.conftest import PASSWORD
    email = f"gate_{uuid.uuid4().hex[:10]}@example.com"
    reg = client.post("/auth/register", json={
        "organization_name": "Second Org", "name": "Owner", "email": email, "password": PASSWORD,
    })
    assert reg.status_code == 201, reg.text
    tokens = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD}).json()
    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {tokens['access_token']}"}).json()
    return {
        "headers": {"Authorization": f"Bearer {tokens['access_token']}"},
        "user_id": me["user"]["id"], "organization_id": me["user"]["organization_id"], "email": email,
    }


# --------------------------------------------------------------------------- #
# AC-01 / AC-02 -- one verdict, structured findings
# --------------------------------------------------------------------------- #
def test_ac01_evaluate_returns_verdict_and_findings(client: TestClient, admin: dict):
    setup = _full_setup(client, admin)
    deployment = _ready_deployment(client, admin, setup["agent"]["id"], setup["version"]["id"])
    body, status_code = _preflight(client, admin, deployment["id"])
    assert status_code == 200, body
    assert body["verdict"] in ("PASS", "WARNING", "BLOCK")
    assert isinstance(body["findings"], list)
    assert body["deployment_id"] == deployment["id"]
    assert body["evaluated_at"] is not None


def test_ac02_finding_fields_are_all_present(client: TestClient, admin: dict):
    # No stored credential for MOCK -> PREFLIGHT_PROVIDER_CREDENTIALS_UNAVAILABLE (WARNING).
    setup = _full_setup(client, admin)
    deployment = _ready_deployment(client, admin, setup["agent"]["id"], setup["version"]["id"])
    body, status_code = _preflight(client, admin, deployment["id"])
    assert status_code == 200, body
    assert body["findings"], "expected at least one finding (no provider credential configured)"
    for finding in body["findings"]:
        for field in ("code", "severity", "source", "explanation", "remediation"):
            assert finding[field], f"finding missing/empty '{field}': {finding}"
        assert finding["severity"] in ("WARNING", "BLOCK")


# --------------------------------------------------------------------------- #
# AC-03 -- BLOCK dominates WARNING dominates PASS (pure, no DB)
# --------------------------------------------------------------------------- #
def test_ac03_block_dominates_warning_dominates_pass():
    def f(severity: str) -> checks.Finding:
        return checks.Finding(code="X", severity=severity, source="s", explanation="e", remediation="r")

    assert checks.verdict_for([]) == "PASS"
    assert checks.verdict_for([f("WARNING")]) == "WARNING"
    assert checks.verdict_for([f("WARNING"), f("BLOCK")]) == "BLOCK"
    assert checks.verdict_for([f("BLOCK"), f("WARNING"), f("BLOCK")]) == "BLOCK"


# --------------------------------------------------------------------------- #
# AC-04 -- a BLOCK prevents deployment via the 3.1 lifecycle authority
# --------------------------------------------------------------------------- #
def test_ac04_block_prevents_deployment_from_reaching_deploying(client: TestClient, admin: dict):
    setup = _full_setup(client, admin)
    deployment = _ready_deployment(client, admin, setup["agent"]["id"], setup["version"]["id"])

    # Deprecate the version out from under the (already-created) deployment --
    # PREFLIGHT_VERSION_NOT_PUBLISHED should now BLOCK the transition.
    r = client.post(f"{RT}/agents/{setup['agent']['id']}/versions/{setup['version']['id']}/deprecate",
                    headers=admin["headers"])
    assert r.status_code == 200, r.text

    r = client.post(f"{RT}/deployments/{deployment['id']}/lifecycle/transition", headers=admin["headers"],
                    json={"to_state": "DEPLOYING"})
    assert r.status_code == 409, r.text
    assert r.json()["error"]["code"] == "DEPLOYMENT_PREFLIGHT_BLOCKED"

    # Fails closed *before* mutating anything -- still READY, not DEPLOYING.
    r = client.get(f"{RT}/deployments/{deployment['id']}", headers=admin["headers"])
    assert r.json()["lifecycle_state"] == "READY"

    # And the block is persisted for diagnosis.
    latest = client.get(f"{RT}/deployments/{deployment['id']}/preflight", headers=admin["headers"]).json()
    assert latest["verdict"] == "BLOCK"
    assert any(f["code"] == "PREFLIGHT_VERSION_NOT_PUBLISHED" for f in latest["findings"])


# --------------------------------------------------------------------------- #
# AC-05 / AC-11 -- every check calls an existing capability (verified by
# call, not copy) -- spot-checked for the environment-policy and approval
# checks, the two most structurally analogous to the build prompt's own
# "connector health" example.
# --------------------------------------------------------------------------- #
def test_ac05_environment_policy_check_calls_the_real_policy_module(client: TestClient, admin: dict,
                                                                     monkeypatch: pytest.MonkeyPatch):
    calls = []
    original = checks.environment_policy.evaluate

    def spy(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(checks.environment_policy, "evaluate", spy)

    setup = _full_setup(client, admin)
    deployment = _ready_deployment(client, admin, setup["agent"]["id"], setup["version"]["id"])
    _preflight(client, admin, deployment["id"])
    assert calls, "check_environment_policy did not call app.runtime.environment.policy.evaluate"


def test_ac05_approval_check_reuses_lifecycle_services_own_private_methods(client: TestClient, admin: dict,
                                                                           monkeypatch: pytest.MonkeyPatch):
    from app.runtime.deployment.service import DeploymentLifecycleService

    calls = []
    original = DeploymentLifecycleService._requires_deployment_approval

    def spy(self, *args, **kwargs):
        calls.append(1)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(DeploymentLifecycleService, "_requires_deployment_approval", spy)

    setup = _full_setup(client, admin)
    deployment = _ready_deployment(client, admin, setup["agent"]["id"], setup["version"]["id"])
    _preflight(client, admin, deployment["id"])
    assert calls, "check_approvals did not call DeploymentLifecycleService._requires_deployment_approval"


# --------------------------------------------------------------------------- #
# AC-06 -- an unevaluable check produces PREFLIGHT_CHECK_UNAVAILABLE, fails
# closed (never silence)
# --------------------------------------------------------------------------- #
def test_ac06_unevaluable_check_fails_closed(client: TestClient, admin: dict, db_session: Session,
                                             monkeypatch: pytest.MonkeyPatch):
    setup = _full_setup(client, admin)
    deployment_row = _ready_deployment(client, admin, setup["agent"]["id"], setup["version"]["id"])

    def _boom(ctx):
        raise RuntimeError("simulated check failure")

    monkeypatch.setattr(checks, "_CHECKS", (_boom,))

    from app.models.agent import Agent
    from app.models.runtime import AgentDeployment

    deployment = db_session.get(AgentDeployment, uuid.UUID(deployment_row["id"]))
    agent = db_session.get(Agent, deployment.agent_id)
    version = db_session.get(AgentVersion, deployment.agent_version_id)
    ctx = checks.GateContext(db=db_session, agent=agent, version=version, deployment=deployment)

    findings = checks.run_checks(ctx)
    assert len(findings) == 1
    assert findings[0].code == "PREFLIGHT_CHECK_UNAVAILABLE"
    assert findings[0].severity == "BLOCK"
    assert checks.verdict_for(findings) == "BLOCK"


# --------------------------------------------------------------------------- #
# AC-07 / AC-08 -- kill switch: absolute BLOCK, re-checked at transition
# --------------------------------------------------------------------------- #
def test_ac07_active_kill_switch_is_always_a_block(client: TestClient, admin: dict):
    setup = _full_setup(client, admin)
    deployment = _ready_deployment(client, admin, setup["agent"]["id"], setup["version"]["id"])

    # Force a severity override for the kill-switch code -- must be ignored.
    envs = _environments(client, admin)
    client.put(f"{RT}/environments/{envs['DEVELOPMENT']['id']}/policy", headers=admin["headers"],
              json={"policy": {"preflight_severity_overrides": {"PREFLIGHT_KILL_SWITCH_ACTIVE": "WARNING"}}})

    r = client.post(f"{RT}/kill-switch/agents/{setup['agent']['id']}", headers=admin["headers"],
                    json={"reason": "test: AC-07"})
    assert r.status_code == 200, r.text

    body, status_code = _preflight(client, admin, deployment["id"])
    assert status_code == 200, body
    assert body["verdict"] == "BLOCK"
    finding = next(f for f in body["findings"] if f["code"] == "PREFLIGHT_KILL_SWITCH_ACTIVE")
    assert finding["severity"] == "BLOCK"  # override ignored -- AC-07 is absolute


def test_ac08_kill_switch_re_checked_at_transition_not_trusted_from_prior_pass(client: TestClient, admin: dict):
    setup = _full_setup(client, admin)
    client.put(f"{RT}/providers/MOCK/credentials", headers=admin["headers"], json={"secret": "sk-test"})
    deployment = _ready_deployment(client, admin, setup["agent"]["id"], setup["version"]["id"])

    # A PASS while the agent is healthy.
    body, status_code = _preflight(client, admin, deployment["id"])
    assert status_code == 200, body
    assert body["verdict"] == "PASS", body

    # Kill the agent *after* that PASS.
    r = client.post(f"{RT}/kill-switch/agents/{setup['agent']['id']}", headers=admin["headers"],
                    json={"reason": "test: AC-08"})
    assert r.status_code == 200, r.text

    # The deploy attempt re-evaluates fresh -- the prior PASS is not trusted.
    r = client.post(f"{RT}/deployments/{deployment['id']}/lifecycle/transition", headers=admin["headers"],
                    json={"to_state": "DEPLOYING"})
    assert r.status_code == 409, r.text
    assert r.json()["error"]["code"] == "DEPLOYMENT_PREFLIGHT_BLOCKED"


# --------------------------------------------------------------------------- #
# AC-09 / AC-10 -- the freshness rule
# --------------------------------------------------------------------------- #
def test_ac09_pure_freshness_states():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert checks.evaluate_freshness(None, 900, now=now) == "MISSING"
    assert checks.evaluate_freshness(now - timedelta(seconds=100), 900, now=now) == "FRESH"
    assert checks.evaluate_freshness(now - timedelta(seconds=1000), 900, now=now) == "STALE"


def test_ac09_stale_health_signal_does_not_pass(client: TestClient, admin: dict, db_session: Session):
    setup = _full_setup(client, admin)
    deployment = _ready_deployment(client, admin, setup["agent"]["id"], setup["version"]["id"])

    r = client.post(f"{RT}/deployments/{deployment['id']}/heartbeat", headers=admin["headers"],
                    json={"worker_id": "w1", "status": "HEALTHY"})
    assert r.status_code == 200, r.text

    # Push the just-recorded heartbeat into the past, beyond the platform
    # default freshness bound (900s).
    row = db_session.execute(
        select(DeploymentHealth).where(DeploymentHealth.deployment_id == uuid.UUID(deployment["id"]))
    ).scalar_one()
    row.checked_at = datetime.now(timezone.utc) - timedelta(seconds=2000)
    db_session.commit()

    body, status_code = _preflight(client, admin, deployment["id"])
    assert status_code == 200, body
    finding = next(f for f in body["findings"] if f["code"] == "PREFLIGHT_HEALTH_SIGNAL_STALE")
    assert finding["severity"] == "WARNING"  # default severity, not silently PASS
    assert body["verdict"] != "PASS"


def test_ac10_freshness_bound_is_configurable_per_environment(client: TestClient, admin: dict, db_session: Session):
    setup = _full_setup(client, admin)
    deployment = _ready_deployment(client, admin, setup["agent"]["id"], setup["version"]["id"])
    envs = _environments(client, admin)

    r = client.post(f"{RT}/deployments/{deployment['id']}/heartbeat", headers=admin["headers"],
                    json={"worker_id": "w1", "status": "HEALTHY"})
    assert r.status_code == 200, r.text
    row = db_session.execute(
        select(DeploymentHealth).where(DeploymentHealth.deployment_id == uuid.UUID(deployment["id"]))
    ).scalar_one()
    row.checked_at = datetime.now(timezone.utc) - timedelta(seconds=120)
    db_session.commit()

    # A 60s bound makes a 120s-old signal stale...
    client.put(f"{RT}/environments/{envs['DEVELOPMENT']['id']}/policy", headers=admin["headers"],
              json={"policy": {"preflight_freshness_bound_seconds": 60}})
    body, _ = _preflight(client, admin, deployment["id"])
    assert any(f["code"] == "PREFLIGHT_HEALTH_SIGNAL_STALE" for f in body["findings"])

    # ...while a 600s bound makes the same signal fresh.
    client.put(f"{RT}/environments/{envs['DEVELOPMENT']['id']}/policy", headers=admin["headers"],
              json={"policy": {"preflight_freshness_bound_seconds": 600}})
    body, _ = _preflight(client, admin, deployment["id"])
    assert not any(f["code"] == "PREFLIGHT_HEALTH_SIGNAL_STALE" for f in body["findings"])


def test_ac09_fresh_but_unhealthy_signal_blocks(client: TestClient, admin: dict):
    setup = _full_setup(client, admin)
    deployment = _ready_deployment(client, admin, setup["agent"]["id"], setup["version"]["id"])
    r = client.post(f"{RT}/deployments/{deployment['id']}/heartbeat", headers=admin["headers"],
                    json={"worker_id": "w1", "status": "UNHEALTHY"})
    assert r.status_code == 200, r.text

    body, status_code = _preflight(client, admin, deployment["id"])
    assert status_code == 200, body
    assert body["verdict"] == "BLOCK"
    assert any(f["code"] == "PREFLIGHT_HEALTH_SIGNAL_UNHEALTHY" and f["severity"] == "BLOCK"
              for f in body["findings"])


# --------------------------------------------------------------------------- #
# AC-12 -- persisted results retrievable (latest + history)
# --------------------------------------------------------------------------- #
def test_ac12_results_persisted_latest_and_history(client: TestClient, admin: dict):
    setup = _full_setup(client, admin)
    deployment = _ready_deployment(client, admin, setup["agent"]["id"], setup["version"]["id"])

    _preflight(client, admin, deployment["id"])
    _preflight(client, admin, deployment["id"])
    third, _ = _preflight(client, admin, deployment["id"])

    latest = client.get(f"{RT}/deployments/{deployment['id']}/preflight", headers=admin["headers"]).json()
    assert latest["id"] == third["id"]

    history = client.get(f"{RT}/deployments/{deployment['id']}/preflight/history",
                         headers=admin["headers"]).json()
    assert len(history) >= 3
    assert history[0]["id"] == third["id"]  # most recent first


def test_ac12_no_result_yet_returns_null(client: TestClient, admin: dict):
    setup = _full_setup(client, admin)
    deployment = _ready_deployment(client, admin, setup["agent"]["id"], setup["version"]["id"])
    r = client.get(f"{RT}/deployments/{deployment['id']}/preflight", headers=admin["headers"])
    assert r.status_code == 200
    assert r.json() is None


# --------------------------------------------------------------------------- #
# AC-13 -- authorization: permission enforcement + cross-tenant rejection
# --------------------------------------------------------------------------- #
def test_ac13_preflight_endpoints_require_authentication(client: TestClient):
    fake_id = str(uuid.uuid4())
    assert client.get(f"{RT}/deployments/{fake_id}/preflight").status_code in (401, 403)
    assert client.post(f"{RT}/deployments/{fake_id}/preflight").status_code in (401, 403)
    assert client.get(f"{RT}/deployments/{fake_id}/preflight/history").status_code in (401, 403)


def test_ac13_cross_tenant_preflight_access_rejected(client: TestClient, admin: dict):
    setup = _full_setup(client, admin)
    deployment = _ready_deployment(client, admin, setup["agent"]["id"], setup["version"]["id"])
    other = _register_second_org(client)

    r = client.get(f"{RT}/deployments/{deployment['id']}/preflight", headers=other["headers"])
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "DEPLOYMENT_NOT_FOUND"

    r = client.post(f"{RT}/deployments/{deployment['id']}/preflight", headers=other["headers"])
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "DEPLOYMENT_NOT_FOUND"


# --------------------------------------------------------------------------- #
# Individual check -> finding-code mapping (build prompt §11's "each
# individual failure -> the right BLOCK finding")
# --------------------------------------------------------------------------- #
def test_checksum_tamper_blocks(client: TestClient, admin: dict, db_session: Session):
    setup = _full_setup(client, admin)
    deployment = _ready_deployment(client, admin, setup["agent"]["id"], setup["version"]["id"])

    version = db_session.get(AgentVersion, uuid.UUID(setup["version"]["id"]))
    version.checksum = "sha256:0000000000000000000000000000000000000000000000000000000000000000000"
    db_session.commit()

    body, _ = _preflight(client, admin, deployment["id"])
    assert body["verdict"] == "BLOCK"
    assert any(f["code"] == "PREFLIGHT_CHECKSUM_INVALID" for f in body["findings"])


def test_invalid_machine_identity_blocks(client: TestClient, admin: dict, db_session: Session):
    setup = _full_setup(client, admin)
    deployment = _ready_deployment(client, admin, setup["agent"]["id"], setup["version"]["id"])

    identity = db_session.execute(
        select(AgentIdentity).where(AgentIdentity.agent_id == uuid.UUID(setup["agent"]["id"]))
    ).scalar_one()
    identity.status = "REVOKED"
    db_session.commit()

    body, _ = _preflight(client, admin, deployment["id"])
    assert body["verdict"] == "BLOCK"
    assert any(f["code"] == "PREFLIGHT_IDENTITY_INVALID" for f in body["findings"])


def test_disabled_bound_tool_blocks(client: TestClient, admin: dict, db_session: Session):
    tool = _create_tool(client, admin)
    setup = _full_setup(client, admin, tool_ids=[tool["id"]])
    deployment = _ready_deployment(client, admin, setup["agent"]["id"], setup["version"]["id"])

    row = db_session.get(Tool, uuid.UUID(tool["id"]))
    row.enabled = False
    db_session.commit()

    body, _ = _preflight(client, admin, deployment["id"])
    assert body["verdict"] == "BLOCK"
    assert any(f["code"] == "PREFLIGHT_TOOLS_INVALID" for f in body["findings"])


def test_unregistered_provider_blocks(client: TestClient, admin: dict):
    setup = _full_setup(client, admin, provider="NONEXISTENT_PROVIDER")
    deployment = _ready_deployment(client, admin, setup["agent"]["id"], setup["version"]["id"])
    body, _ = _preflight(client, admin, deployment["id"])
    assert body["verdict"] == "BLOCK"
    assert any(f["code"] == "PREFLIGHT_PROVIDER_UNAVAILABLE" for f in body["findings"])


def test_missing_owner_warns_not_blocks(client: TestClient, admin: dict, db_session: Session):
    # Registration itself requires an owner (AGENT_DEFINITION_REQUIRED) --
    # ``owner_id`` can only go missing later (e.g. an ownership change), so
    # this exercises that defensive path directly.
    from app.models.agent import Agent

    setup = _full_setup(client, admin)
    agent_row = db_session.get(Agent, uuid.UUID(setup["agent"]["id"]))
    agent_row.owner_id = None
    db_session.commit()

    deployment = _ready_deployment(client, admin, setup["agent"]["id"], setup["version"]["id"])
    body, _ = _preflight(client, admin, deployment["id"])
    finding = next((f for f in body["findings"] if f["code"] == "PREFLIGHT_OWNER_MISSING"), None)
    assert finding is not None
    assert finding["severity"] == "WARNING"


def test_environment_policy_violation_reused_as_a_gate_finding(client: TestClient, admin: dict):
    """AC-11 -- the same ``ENVIRONMENT_POLICY_VIOLATION`` code 3.2's own
    narrow choke point raises, now also surfaced as a gate finding."""
    envs = _environments(client, admin)
    client.put(f"{RT}/environments/{envs['DEVELOPMENT']['id']}/policy", headers=admin["headers"],
              json={"policy": {"allowed_models": ["some-other-model"]}})
    setup = _full_setup(client, admin, model="mock-model")
    deployment = _ready_deployment(client, admin, setup["agent"]["id"], setup["version"]["id"])
    body, _ = _preflight(client, admin, deployment["id"])
    assert body["verdict"] == "BLOCK"
    assert any(f["code"] == "ENVIRONMENT_POLICY_VIOLATION" for f in body["findings"])


def test_pending_approval_warns_not_blocks(client: TestClient, admin: dict):
    setup = _full_setup(client, admin, criticality="MISSION_CRITICAL")
    deployment = _ready_deployment(client, admin, setup["agent"]["id"], setup["version"]["id"],
                                   environment="PRODUCTION")
    body, _ = _preflight(client, admin, deployment["id"])
    finding = next((f for f in body["findings"] if f["code"] == "PREFLIGHT_APPROVAL_PENDING"), None)
    assert finding is not None
    assert finding["severity"] == "WARNING"

    # And the reroute-to-PENDING_APPROVAL path is completely undisturbed by
    # the gate call inside start_deploying (a WARNING never raises).
    r = client.post(f"{RT}/deployments/{deployment['id']}/lifecycle/transition", headers=admin["headers"],
                    json={"to_state": "DEPLOYING"})
    assert r.status_code == 200, r.text
    assert r.json()["lifecycle_state"] == "PENDING_APPROVAL"


# --------------------------------------------------------------------------- #
# Full happy path -> PASS (§11's integration scenario, MOCK credential
# stored so PREFLIGHT_PROVIDER_CREDENTIALS_UNAVAILABLE doesn't leave a
# lingering WARNING)
# --------------------------------------------------------------------------- #
def test_happy_path_yields_pass(client: TestClient, admin: dict):
    client.put(f"{RT}/providers/MOCK/credentials", headers=admin["headers"], json={"secret": "sk-test"})
    setup = _full_setup(client, admin)
    deployment = _ready_deployment(client, admin, setup["agent"]["id"], setup["version"]["id"])
    body, status_code = _preflight(client, admin, deployment["id"])
    assert status_code == 200, body
    assert body["verdict"] == "PASS", body["findings"]
    assert body["findings"] == []


# --------------------------------------------------------------------------- #
# AC-17 -- no TODO/FIXME/NotImplementedError/skip/xfail in the new code
# --------------------------------------------------------------------------- #
def test_ac17_no_todo_markers_in_release_gate_module():
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[2] / "app" / "runtime" / "release_gate"
    forbidden = ("TODO", "FIXME", "NotImplementedError", "pytest.mark.skip", "pytest.mark.xfail")
    offenders = [
        str(path) for path in root.rglob("*.py")
        if any(term in path.read_text(encoding="utf-8") for term in forbidden)
    ]
    assert offenders == []


# --------------------------------------------------------------------------- #
# Regression: M1 execution path and vocabulary boundary untouched
# --------------------------------------------------------------------------- #
def test_release_gate_module_never_references_forbidden_integration_vocabulary():
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[2] / "app" / "runtime"
    forbidden = ("connector", "connectorhealthcheck", "connectorregistry", "auth_scheme", "oauthtoken",
                "authscheme")
    offenders = [
        str(path) for path in root.rglob("*.py")
        if any(term in path.read_text(encoding="utf-8").lower() for term in forbidden)
    ]
    assert offenders == []
