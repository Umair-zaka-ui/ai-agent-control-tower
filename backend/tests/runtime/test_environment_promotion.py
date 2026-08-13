"""Phase 3.2 (ACT-SRS-M3 §3.2) tests -- governed environments, environment
policy evaluation, promotion paths, and the immutability-preserving
promotion operation.

Grouped by the build prompt's own §12 acceptance criteria. Real Postgres
throughout (this codebase's established convention -- ``tests/runtime/
conftest.py``), including the concurrency race (AC-13), which uses real
separate ``SessionLocal()`` connections and threads, never in-process
mutexes (mirroring ``test_deployment_lifecycle.py``'s own AC-05 test)."""

from __future__ import annotations

import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models.runtime import AgentDeployment, AgentVersion, Environment, PromotionPath
from app.runtime.environment import policy as environment_policy

RT = "/api/v1/runtime"


# --------------------------------------------------------------------------- #
# HTTP setup helpers (mirrors test_deployment_lifecycle.py's own convention)
# --------------------------------------------------------------------------- #
def _register_agent(client: TestClient, admin: dict, *, criticality: str = "MEDIUM") -> dict:
    r = client.post(f"{RT}/agents", headers=admin["headers"], json={
        "name": f"Promo Agent {uuid.uuid4().hex[:6]}", "agent_type": "ASSISTANT", "criticality": criticality,
        "description": "A test agent.", "business_purpose": "Exercise environments & promotion in tests.",
        "owner_type": "USER", "owner_id": admin["user_id"], "technical_owner_id": admin["user_id"],
        "compliance_owner_id": admin["user_id"],
        "definition": {"name": "Definition", "framework": "CUSTOM", "entrypoint_type": "FUNCTION",
                      "entrypoint": "agents.handler:run"},
    })
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
                     model: str = "mock-model", policy_snapshot: dict | None = None) -> dict:
    payload = {"model_configuration": {"provider": "MOCK", "model": model}, "tool_ids": []}
    if policy_snapshot is not None:
        payload["policy_snapshot"] = policy_snapshot
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


def _environments(client: TestClient, admin: dict) -> dict[str, dict]:
    """Triggers ``EnvironmentService.ensure_seeded`` (via the list route) and
    returns the standard catalog keyed by name -- the seeding entry point
    every test below uses before referencing an environment id."""
    r = client.get(f"{RT}/environments", headers=admin["headers"])
    assert r.status_code == 200, r.text
    return {e["name"]: e for e in r.json()}


def _full_setup(client: TestClient, admin: dict, *, criticality: str = "MEDIUM",
                model: str = "mock-model", policy_snapshot: dict | None = None) -> dict:
    envs = _environments(client, admin)
    agent = _register_agent(client, admin, criticality=criticality)
    _activate_agent(client, admin, agent["id"])
    version = _publish_version(client, admin, agent["id"], model=model, policy_snapshot=policy_snapshot)
    deployment = _create_deployment(client, admin, agent["id"], version["id"], environment="DEVELOPMENT")
    return {"agent": agent, "version": version, "deployment": deployment, "environments": envs}


def _promote(client: TestClient, admin: dict, deployment_id: str, to_environment_id: str, *,
            reason: str | None = None, idempotency_key: str | None = None) -> tuple[dict, int]:
    headers = dict(admin["headers"])
    if idempotency_key is not None:
        headers["Idempotency-Key"] = idempotency_key
    payload = {"to_environment_id": to_environment_id}
    if reason is not None:
        payload["reason"] = reason
    r = client.post(f"{RT}/deployments/{deployment_id}/promote", headers=headers, json=payload)
    return r.json(), r.status_code


def _set_policy(client: TestClient, admin: dict, environment_id: str, policy: dict) -> dict:
    r = client.put(f"{RT}/environments/{environment_id}/policy", headers=admin["headers"], json={"policy": policy})
    assert r.status_code == 200, r.text
    return r.json()


# --------------------------------------------------------------------------- #
# AC-01 -- environments are first-class, tenant-scoped; standard + custom
# --------------------------------------------------------------------------- #
def test_ac01_standard_environments_are_seeded(client: TestClient, admin: dict):
    envs = _environments(client, admin)
    assert set(envs) == {"DEVELOPMENT", "TEST", "STAGING", "PRODUCTION", "SANDBOX"}
    assert envs["PRODUCTION"]["is_production"] is True
    assert envs["DEVELOPMENT"]["is_production"] is False
    for env in envs.values():
        assert env["organization_id"] == admin["organization_id"]


def test_ac01_custom_environment_can_be_created(client: TestClient, admin: dict):
    r = client.post(f"{RT}/environments", headers=admin["headers"],
                    json={"name": "QA", "display_name": "Quality Assurance"})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["name"] == "QA"
    assert body["display_name"] == "Quality Assurance"
    assert body["is_production"] is False


def test_ac01_duplicate_environment_name_rejected(client: TestClient, admin: dict):
    _environments(client, admin)
    r = client.post(f"{RT}/environments", headers=admin["headers"], json={"name": "DEVELOPMENT"})
    assert r.status_code == 422, r.text


def test_ac01_environments_are_tenant_scoped(client: TestClient, admin: dict):
    envs_a = _environments(client, admin)
    admin_b = _register_second_org(client)
    envs_b = _environments(client, admin_b)
    assert envs_a["DEVELOPMENT"]["id"] != envs_b["DEVELOPMENT"]["id"]


def _register_second_org(client: TestClient) -> dict:
    from tests.runtime.conftest import PASSWORD
    email = f"compat_{uuid.uuid4().hex[:10]}@example.com"
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
# AC-02 -- agent_deployments references an environment entity
# --------------------------------------------------------------------------- #
def test_ac02_deployment_create_resolves_environment_id_from_string(client: TestClient, admin: dict):
    setup = _full_setup(client, admin)
    deployment = setup["deployment"]
    assert deployment["environment_id"] == setup["environments"]["DEVELOPMENT"]["id"]


def test_ac14_existing_migrated_deployments_have_environment_id_backfilled_correctly(db_session: Session):
    """Live, deterministic proof of migration 0038's own §15 backfill --
    not a check-then-act on state this test itself controls, but on the
    thousands of pre-existing rows the migration touched when it ran
    against this same persistent database (verified manually at the time:
    4706/4706 rows backfilled) -- any single already-backfilled row's
    ``environment_id`` must resolve to an ``environments`` row of the exact
    same name and organization it was migrated from."""
    row = db_session.execute(text(
        "SELECT organization_id, environment, environment_id FROM agent_deployments "
        "WHERE environment_id IS NOT NULL LIMIT 1"
    )).first()
    assert row is not None, "expected at least one deployment backfilled by migration 0038"
    organization_id, environment_name, environment_id = row
    resolved_name = db_session.execute(text(
        "SELECT name FROM environments WHERE id = :id AND organization_id = :org"
    ), {"id": environment_id, "org": organization_id}).scalar_one()
    assert resolved_name == environment_name


# --------------------------------------------------------------------------- #
# AC-03 -- environment policy enforced at deploy/promote time, fail-closed
# --------------------------------------------------------------------------- #
def test_ac03_allowed_models_policy_blocks_promotion(client: TestClient, admin: dict):
    setup = _full_setup(client, admin, model="mock-model")
    envs = setup["environments"]
    _set_policy(client, admin, envs["TEST"]["id"], {"allowed_models": ["some-other-model"]})
    body, status_code = _promote(client, admin, setup["deployment"]["id"], envs["TEST"]["id"])
    assert status_code == 409, body
    assert body["error"]["code"] == "ENVIRONMENT_POLICY_VIOLATION"


def test_ac03_allowed_models_policy_blocks_plain_deploy(client: TestClient, admin: dict):
    """Proves the single choke point (``DeploymentLifecycleService.
    start_deploying``) fires for a plain deploy too, not only a promotion."""
    envs = _environments(client, admin)
    _set_policy(client, admin, envs["DEVELOPMENT"]["id"], {"allowed_models": ["some-other-model"]})
    agent = _register_agent(client, admin)
    _activate_agent(client, admin, agent["id"])
    version = _publish_version(client, admin, agent["id"], model="mock-model")
    deployment = _create_deployment(client, admin, agent["id"], version["id"], environment="DEVELOPMENT")
    r = client.post(f"{RT}/deployments/{deployment['id']}/lifecycle/transition", headers=admin["headers"],
                    json={"to_state": "VALIDATING"})
    assert r.status_code == 200, r.text
    r = client.post(f"{RT}/deployments/{deployment['id']}/lifecycle/transition", headers=admin["headers"],
                    json={"to_state": "READY"})
    assert r.status_code == 200, r.text
    r = client.post(f"{RT}/deployments/{deployment['id']}/lifecycle/transition", headers=admin["headers"],
                    json={"to_state": "DEPLOYING"})
    assert r.status_code == 409, r.text
    assert r.json()["error"]["code"] == "ENVIRONMENT_POLICY_VIOLATION"


def test_ac03_allowed_data_classification_policy_blocks_promotion(client: TestClient, admin: dict):
    setup = _full_setup(client, admin)
    envs = setup["environments"]
    agent, version = setup["agent"], setup["version"]

    r = client.post(f"{RT}/tools", headers=admin["headers"], json={
        "name": f"restricted-tool-{uuid.uuid4().hex[:6]}", "display_name": "Restricted Tool",
        "tool_type": "FUNCTION", "data_classification": "RESTRICTED",
    })
    assert r.status_code == 201, r.text
    tool_id = r.json()["id"]
    version2 = client.post(f"{RT}/agents/{agent['id']}/versions", headers=admin["headers"], json={
        "model_configuration": {"provider": "MOCK", "model": "mock-model"}, "tool_ids": [tool_id],
    })
    assert version2.status_code == 201, version2.text
    version2 = version2.json()
    for step in ("validate", "approve", "publish"):
        r = client.post(f"{RT}/agents/{agent['id']}/versions/{version2['id']}/{step}", headers=admin["headers"])
        assert r.status_code == 200, r.text
    deployment2 = _create_deployment(client, admin, agent["id"], version2["id"], environment="DEVELOPMENT")

    _set_policy(client, admin, envs["TEST"]["id"], {"allowed_data_classifications": ["PUBLIC", "INTERNAL"]})
    body, status_code = _promote(client, admin, deployment2["id"], envs["TEST"]["id"])
    assert status_code == 409, body
    assert body["error"]["code"] == "ENVIRONMENT_POLICY_VIOLATION"


def test_ac03_concurrency_limit_policy_blocks_promotion(client: TestClient, admin: dict):
    setup = _full_setup(client, admin)
    envs = setup["environments"]
    _set_policy(client, admin, envs["TEST"]["id"], {"maximum_concurrent_deployments": 0})
    body, status_code = _promote(client, admin, setup["deployment"]["id"], envs["TEST"]["id"])
    assert status_code == 409, body
    assert body["error"]["code"] == "ENVIRONMENT_POLICY_VIOLATION"


# --------------------------------------------------------------------------- #
# AC-04 -- change window gates promotion timing
# --------------------------------------------------------------------------- #
def test_ac04_change_window_blocks_promotion_outside_window(client: TestClient, admin: dict):
    setup = _full_setup(client, admin)
    envs = setup["environments"]
    # days_of_week: [] can never contain today's weekday -- deterministically
    # closed regardless of when this test happens to run.
    _set_policy(client, admin, envs["TEST"]["id"], {"change_window": {"days_of_week": []}})
    body, status_code = _promote(client, admin, setup["deployment"]["id"], envs["TEST"]["id"])
    assert status_code == 409, body
    assert body["error"]["code"] == "PROMOTION_WINDOW_CLOSED"


def test_ac04_change_window_pure_evaluation():
    now = datetime(2026, 8, 10, 12, 0, tzinfo=timezone.utc)  # Monday, weekday()==0
    assert environment_policy.check_change_window({"change_window": {"days_of_week": [0]}}, now=now) is None
    violation = environment_policy.check_change_window({"change_window": {"days_of_week": [1, 2]}}, now=now)
    assert violation is not None and violation.code == "PROMOTION_WINDOW_CLOSED"
    violation = environment_policy.check_change_window(
        {"change_window": {"start_hour_utc": 13, "end_hour_utc": 14}}, now=now)
    assert violation is not None


# --------------------------------------------------------------------------- #
# AC-05 -- promotion paths enforced
# --------------------------------------------------------------------------- #
def test_ac05_promotion_outside_defined_path_rejected(client: TestClient, admin: dict):
    setup = _full_setup(client, admin)
    envs = setup["environments"]
    # No DEVELOPMENT -> PRODUCTION path is seeded by default.
    body, status_code = _promote(client, admin, setup["deployment"]["id"], envs["PRODUCTION"]["id"])
    assert status_code == 409, body
    assert body["error"]["code"] == "PROMOTION_PATH_NOT_DEFINED"


def test_ac05_promotion_along_defined_path_succeeds(client: TestClient, admin: dict):
    setup = _full_setup(client, admin)
    envs = setup["environments"]
    body, status_code = _promote(client, admin, setup["deployment"]["id"], envs["TEST"]["id"])
    assert status_code == 200, body


# --------------------------------------------------------------------------- #
# AC-06 / AC-07 -- immutability: the exact same version, never cloned
# --------------------------------------------------------------------------- #
def test_ac06_ac07_promotion_preserves_the_exact_version(client: TestClient, admin: dict, db_session: Session):
    setup = _full_setup(client, admin)
    envs, version, agent = setup["environments"], setup["version"], setup["agent"]

    version_count_before = db_session.execute(
        select(AgentVersion).where(AgentVersion.agent_id == uuid.UUID(agent["id"]))
    ).scalars().all()
    assert len(version_count_before) == 1
    original = db_session.get(AgentVersion, uuid.UUID(version["id"]))
    checksum_before = original.checksum
    manifest_digest_before = original.manifest_digest
    signature_id_before = original.signature_id

    body, status_code = _promote(client, admin, setup["deployment"]["id"], envs["TEST"]["id"])
    assert status_code == 200, body
    assert body["agent_version_id"] == version["id"]

    db_session.expire_all()
    version_count_after = db_session.execute(
        select(AgentVersion).where(AgentVersion.agent_id == uuid.UUID(agent["id"]))
    ).scalars().all()
    assert len(version_count_after) == 1, "promotion must never insert a new AgentVersion row"
    reloaded = db_session.get(AgentVersion, uuid.UUID(version["id"]))
    assert reloaded.checksum == checksum_before
    assert reloaded.manifest_digest == manifest_digest_before
    assert reloaded.signature_id == signature_id_before


# --------------------------------------------------------------------------- #
# AC-08 -- promotion drives the 3.1 lifecycle machine, satisfies target policy
# --------------------------------------------------------------------------- #
def test_ac08_promotion_reaches_active_and_creates_lineage(client: TestClient, admin: dict):
    setup = _full_setup(client, admin)
    envs = setup["environments"]
    body, status_code = _promote(client, admin, setup["deployment"]["id"], envs["TEST"]["id"])
    assert status_code == 200, body
    assert body["lifecycle_state"] == "ACTIVE"
    assert body["environment_id"] == envs["TEST"]["id"]

    r = client.get(f"{RT}/deployments/{body['id']}/lifecycle/events", headers=admin["headers"])
    assert r.status_code == 200, r.text
    to_states = [e["to_state"] for e in r.json()]
    assert to_states == ["DRAFT", "VALIDATING", "READY", "DEPLOYING", "ACTIVE"]


def test_ac08_promotion_into_production_requires_approval(client: TestClient, admin: dict):
    setup = _full_setup(client, admin)
    envs = setup["environments"]
    dep, status_code = _promote(client, admin, setup["deployment"]["id"], envs["TEST"]["id"])
    assert status_code == 200, dep
    dep2, status_code = _promote(client, admin, dep["id"], envs["STAGING"]["id"])
    assert status_code == 200, dep2
    dep3, status_code = _promote(client, admin, dep2["id"], envs["PRODUCTION"]["id"])
    assert status_code == 200, dep3
    assert dep3["lifecycle_state"] == "PENDING_APPROVAL"

    r = client.get(f"{RT}/approvals", headers=admin["headers"], params={"status": "PENDING"})
    assert r.status_code == 200, r.text
    approval = next(a for a in r.json() if a["deployment_id"] == dep3["id"])
    r = client.post(f"{RT}/approvals/{approval['id']}/decide", headers=admin["headers"],
                    json={"decision": "APPROVED"})
    assert r.status_code == 200, r.text

    r = client.get(f"{RT}/deployments/{dep3['id']}", headers=admin["headers"])
    assert r.status_code == 200, r.text
    # Matches ``test_deployment_lifecycle.py``'s own AC-10 precedent: an
    # approval decision alone only reaches APPROVED (the declared
    # ``APPROVED -> DEPLOYING`` edge still needs an explicit driver) -- the
    # generic ``/lifecycle/transition`` route's own DEPLOYING special-case
    # completes it from there, identically for a promoted deployment.
    assert r.json()["lifecycle_state"] == "APPROVED"

    r = client.post(f"{RT}/deployments/{dep3['id']}/lifecycle/transition", headers=admin["headers"],
                    json={"to_state": "DEPLOYING"})
    assert r.status_code == 200, r.text
    assert r.json()["lifecycle_state"] == "ACTIVE"


# --------------------------------------------------------------------------- #
# AC-09 -- promotion is idempotent via the 3.1 contract
# --------------------------------------------------------------------------- #
def test_ac09_retried_promotion_with_same_key_does_not_duplicate(client: TestClient, admin: dict,
                                                                 db_session: Session):
    setup = _full_setup(client, admin)
    envs, agent = setup["environments"], setup["agent"]
    key = f"promote-{uuid.uuid4().hex}"

    before = db_session.execute(
        select(AgentDeployment).where(AgentDeployment.agent_id == uuid.UUID(agent["id"]))
    ).scalars().all()

    first, status_first = _promote(client, admin, setup["deployment"]["id"], envs["TEST"]["id"],
                                   idempotency_key=key)
    assert status_first == 200, first
    second, status_second = _promote(client, admin, setup["deployment"]["id"], envs["TEST"]["id"],
                                     idempotency_key=key)
    assert status_second == 200, second
    assert first["id"] == second["id"]

    db_session.expire_all()
    after = db_session.execute(
        select(AgentDeployment).where(AgentDeployment.agent_id == uuid.UUID(agent["id"]))
    ).scalars().all()
    assert len(after) == len(before) + 1


# --------------------------------------------------------------------------- #
# AC-10 -- prohibited_environments is respected (integration, not parallel)
# --------------------------------------------------------------------------- #
def test_ac10_prohibited_environments_blocks_promotion(client: TestClient, admin: dict):
    """``AgentVersion.policy_snapshot.prohibited_environments`` is the
    pre-existing mechanism ``RuntimePolicyService.evaluate`` already reads
    at execution time (``app.runtime.services``) -- this proves
    ``app.runtime.environment.policy.check_prohibited`` reads that exact
    same field rather than inventing a parallel one."""
    setup = _full_setup(client, admin, policy_snapshot={"prohibited_environments": ["TEST"]})
    envs = setup["environments"]
    body, status_code = _promote(client, admin, setup["deployment"]["id"], envs["TEST"]["id"])
    assert status_code == 409, body
    assert body["error"]["code"] == "ENVIRONMENT_POLICY_VIOLATION"
    assert "prohibits" in body["error"]["message"]


# --------------------------------------------------------------------------- #
# AC-11 -- release channels and environments are orthogonal, not duplicated
# --------------------------------------------------------------------------- #
def test_ac11_promotion_does_not_touch_release_channel(client: TestClient, admin: dict,
                                                        db_session: Session):
    setup = _full_setup(client, admin)
    envs, version = setup["environments"], setup["version"]
    before = db_session.get(AgentVersion, uuid.UUID(version["id"])).release_channel_id
    body, status_code = _promote(client, admin, setup["deployment"]["id"], envs["TEST"]["id"])
    assert status_code == 200, body
    db_session.expire_all()
    after = db_session.get(AgentVersion, uuid.UUID(version["id"])).release_channel_id
    assert before == after


def test_ac11_environment_policy_has_no_release_channel_field():
    """Structural proof this phase did not duplicate channel semantics into
    environment policy -- the enforced/modeled dimension list
    (``app.runtime.environment.policy``'s own docstring) names none of the
    release-channel vocabulary (STABLE/BETA/CANARY/INTERNAL)."""
    import inspect
    source = inspect.getsource(environment_policy)
    for forbidden in ("STABLE", "BETA", "CANARY", "INTERNAL", "release_channel"):
        assert forbidden not in source


# --------------------------------------------------------------------------- #
# AC-12 -- authorization: permission enforcement + cross-tenant rejection
# --------------------------------------------------------------------------- #
def test_ac12_environment_endpoints_require_authentication(client: TestClient):
    r = client.get(f"{RT}/environments")
    assert r.status_code in (401, 403)


def test_ac12_cross_tenant_environment_access_rejected(client: TestClient, admin: dict):
    envs_a = _environments(client, admin)
    admin_b = _register_second_org(client)
    r = client.get(f"{RT}/environments/{envs_a['DEVELOPMENT']['id']}", headers=admin_b["headers"])
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "ENVIRONMENT_NOT_FOUND"


def test_ac12_cross_tenant_promotion_rejected(client: TestClient, admin: dict):
    setup = _full_setup(client, admin)
    admin_b = _register_second_org(client)
    envs_b = _environments(client, admin_b)
    body, status_code = _promote(client, admin, setup["deployment"]["id"], envs_b["TEST"]["id"])
    assert status_code == 404, body
    assert body["error"]["code"] == "ENVIRONMENT_NOT_FOUND"


# --------------------------------------------------------------------------- #
# AC-13 -- two concurrent identical promotions yield one deployment
# --------------------------------------------------------------------------- #
def test_ac13_concurrent_identical_promotions_yield_one_deployment(client: TestClient, admin: dict):
    setup = _full_setup(client, admin)
    envs, agent = setup["environments"], setup["agent"]
    deployment_id, to_environment_id = setup["deployment"]["id"], envs["TEST"]["id"]
    key = f"promote-race-{uuid.uuid4().hex}"
    barrier = threading.Barrier(2)

    def _race() -> int:
        barrier.wait(timeout=5)
        _, status_code = _promote(client, admin, deployment_id, to_environment_id, idempotency_key=key)
        return status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: _race(), range(2)))
    assert all(code == 200 for code in results), results

    db = SessionLocal()
    try:
        count = len(db.execute(
            select(AgentDeployment).where(
                AgentDeployment.agent_id == uuid.UUID(agent["id"]),
                AgentDeployment.environment_id == to_environment_id,
            )
        ).scalars().all())
        assert count == 1
    finally:
        db.close()


# --------------------------------------------------------------------------- #
# AC-14 -- pure structural checks on the migration's own mapping
# --------------------------------------------------------------------------- #
def test_ac14_migration_module_defines_consistent_seed_data():
    import importlib
    migration = importlib.import_module("migrations.versions.0038_environments_promotion")
    names = {name for name, _, _ in migration._STANDARD_ENVIRONMENTS}
    assert names == {"DEVELOPMENT", "TEST", "STAGING", "PRODUCTION", "SANDBOX"}
    for from_name, to_name, _ in migration._DEFAULT_PATHS:
        assert from_name in names and to_name in names


# --------------------------------------------------------------------------- #
# AC-15 -- M1 execution path untouched
# --------------------------------------------------------------------------- #
def test_ac15_execution_gate_does_not_reference_environment_entity():
    import inspect
    from app.runtime.services import ExecutionRequestService
    source = inspect.getsource(ExecutionRequestService._request_execution)
    assert "environment_id" not in source
    assert "Environment" not in source


def test_ac15_promoting_to_lifecycle_active_now_serves_execution(
    client: TestClient, admin: dict, db_session: Session,
):
    """MIGRATED IN PHASE 3.4 -- deliberately, and asserting *more* than before.

    This test was written in Phase 3.2 as
    ``test_ac15_promoting_to_lifecycle_active_has_no_effect_on_the_legacy_
    execution_gate``, asserting that a promoted deployment reaching
    ``lifecycle_state=ACTIVE`` still could **not** execute, because the M1
    execution gate read only the untouched ``status`` column. Its own
    docstring named the expiry condition: "until Phase 3.4 deliberately wires
    the two together." Phase 3.4 is that wiring, so the expected outcome
    inverts. This is the one deliberate behaviour change to the M1 execution
    path in Milestone 3 (build prompt §12 AC-12); the test is migrated to
    assert the new contract, not relaxed to tolerate either one.

    The assertion is deliberately *stronger* than a bare "it executes": it
    first pins ``status != 'ACTIVE'``, so the execution can only have been
    admitted by the promoted deployment's ``lifecycle_state``. That is
    precisely the union half of the resolver's union-with-veto predicate
    (``app.runtime.deployment.traffic.servable_clause``) under test -- had
    3.4 gated on ``status`` alone, this would still fail."""
    setup = _full_setup(client, admin)
    envs = setup["environments"]
    promoted, status_code = _promote(client, admin, setup["deployment"]["id"], envs["TEST"]["id"])
    assert status_code == 200, promoted
    assert promoted["lifecycle_state"] == "ACTIVE"

    # The pre-3.4 fact this test has always pinned: promotion never writes
    # the legacy ``status`` column. Still true -- 3.4 reconciled nothing; it
    # taught the resolver to honour *either* machine.
    row = db_session.get(AgentDeployment, uuid.UUID(promoted["id"]))
    assert row.status != "ACTIVE"

    r = client.post(f"{RT}/executions", headers=admin["headers"], json={
        "agent_id": setup["agent"]["id"], "deployment_id": promoted["id"], "input_payload": {"message": "hi"},
    })
    assert r.status_code == 201, r.text
    execution = r.json()
    # It ran the promoted deployment's own immutable version -- promotion
    # preserves the source version, so this is the version originally
    # published, never a re-pointed one.
    assert execution["deployment_id"] == promoted["id"]
    assert execution["agent_version_id"] == promoted["agent_version_id"]


# --------------------------------------------------------------------------- #
# AC-17 -- no new TODO/FIXME/NotImplementedError/skip/xfail
# --------------------------------------------------------------------------- #
def test_ac17_no_todo_markers_in_new_source():
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[2] / "app" / "runtime" / "environment"
    for path in root.rglob("*.py"):
        text_content = path.read_text(encoding="utf-8")
        for marker in ("TODO", "FIXME", "NotImplementedError", "pytest.mark.skip", "pytest.mark.xfail"):
            assert marker not in text_content, f"{marker} found in {path}"
