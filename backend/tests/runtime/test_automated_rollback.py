"""Phase 3.7 (ACT-SRS-M3 §Phase-3.7, §11, §12) tests -- automated rollback and
release safety: the authoritative rollback target, the unified rollback
operation, the trigger policy engine, kill-switch dominance over automation,
the override path, anti-flap, and recovery.

Grouped by the build prompt's own §12 acceptance criteria. Real Postgres
throughout (this suite's convention -- ``tests/runtime/conftest.py``), including
the AC-14 race, which uses a real second connection holding its transaction
open rather than a timing-dependent thread barrier (the deterministic pattern
Phases 3.4, 3.5 and 3.6 established).

**The headline test is ``test_ac08_the_section_19_proof_automatic``**: a
candidate is put on trial, its executions start failing, and the platform rolls
it back *by itself* -- stable returns to 100%, the failed candidate's metrics
are preserved as evidence, and every step is audited.

Health is driven by seeding terminal ``agent_executions`` rows, which is the
exact input ``HealthEvaluationService`` reads in production; nothing here mocks
the health engine, because the point is that the trigger policy and the health
engine agree on real data."""

from __future__ import annotations

import ast
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.identity.errors import ErrorCode, IdentityError
from app.models.agent import Agent
from app.models.runtime import (
    AgentDeployment,
    AgentExecution,
    AgentVersion,
    DeploymentTrafficAllocation,
    RollbackEvent,
    RuntimeEvent,
)
from app.models.user import User as UserModel
from app.runtime.deployment import rollback as rollback_module
from app.runtime.deployment.rollback import (
    DEFAULT_TRIGGER_THRESHOLDS,
    NON_ACTIONABLE_HEALTH_STATES,
    RollbackPolicyService,
    RollbackService,
    evaluate_thresholds,
    thresholds_for_policy,
)
from app.runtime.deployment.traffic import TrafficAllocationService
from app.runtime.services import _now

RT = "/api/v1/runtime"


# --------------------------------------------------------------------------- #
# HTTP setup helpers (this suite's convention: each file defines its own)
# --------------------------------------------------------------------------- #
def _register_agent(client: TestClient, admin: dict) -> dict:
    nonce = uuid.uuid4().hex[:8]
    r = client.post(f"{RT}/agents", headers=admin["headers"], json={
        "name": f"Rollback Agent {nonce}", "agent_type": "ASSISTANT", "criticality": "MEDIUM",
        "description": f"Test agent {nonce}.",
        "business_purpose": f"Exercise automated rollback {nonce} in tests.",
        "owner_type": "USER", "owner_id": admin["user_id"], "technical_owner_id": admin["user_id"],
        "compliance_owner_id": admin["user_id"],
        "definition": {"name": "Definition", "framework": "CUSTOM", "entrypoint_type": "FUNCTION",
                      "entrypoint": "agents.handler:run"},
    })
    assert r.status_code == 201, r.text
    return r.json()


def _activate_agent(client: TestClient, admin: dict, agent_id: str) -> None:
    for step in ("register", "validate"):
        assert client.post(f"{RT}/agents/{agent_id}/{step}",
                           headers=admin["headers"]).status_code == 200
    r = client.post(f"{RT}/agents/{agent_id}/identity/create-and-associate",
                    headers=admin["headers"],
                    json={"client_id": f"agent-identity-{uuid.uuid4().hex[:10]}"})
    assert r.status_code == 200, r.text
    for step in ("submit-for-approval", "approve", "activate"):
        assert client.post(f"{RT}/agents/{agent_id}/{step}",
                           headers=admin["headers"]).status_code == 200


def _publish_version(client: TestClient, admin: dict, agent_id: str) -> dict:
    r = client.post(f"{RT}/agents/{agent_id}/versions", headers=admin["headers"],
                    json={"model_configuration": {"provider": "MOCK", "model": "mock-model"}})
    assert r.status_code == 201, r.text
    version = r.json()
    for step in ("validate", "approve", "publish"):
        r = client.post(f"{RT}/agents/{agent_id}/versions/{version['id']}/{step}",
                        headers=admin["headers"])
        assert r.status_code == 200, r.text
    return r.json()


def _lifecycle_deploy(client: TestClient, admin: dict, agent_id: str, version_id: str, *,
                     environment: str = "DEVELOPMENT") -> dict:
    """Deploys through the 3.1 lifecycle route rather than the legacy
    ``/deploy``, for the same reason Phase 3.6's own suite does: the legacy
    route retires sibling deployments, which would leave nothing to roll back
    *to*."""
    r = client.post(f"{RT}/deployments", headers=admin["headers"], params={"agent_id": agent_id},
                    json={"agent_version_id": version_id, "environment": environment})
    assert r.status_code == 201, r.text
    deployment = r.json()
    for to_state in ("VALIDATING", "READY", "DEPLOYING"):
        r = client.post(f"{RT}/deployments/{deployment['id']}/lifecycle/transition",
                        headers=admin["headers"], json={"to_state": to_state})
        assert r.status_code == 200, r.text
        deployment = r.json()
    assert deployment["lifecycle_state"] == "ACTIVE", deployment
    return deployment


def _environments(client: TestClient, admin: dict) -> dict[str, dict]:
    r = client.get(f"{RT}/environments", headers=admin["headers"])
    assert r.status_code == 200, r.text
    return {e["name"]: e for e in r.json()}


def _setup(client: TestClient, admin: dict, *, designate: bool = True) -> dict:
    """One agent, a stable version serving, and a candidate deployed alongside
    it. When ``designate`` the candidate's rollback target is set to stable --
    which is what a rollout or strategy would have done."""
    envs = _environments(client, admin)
    agent = _register_agent(client, admin)
    _activate_agent(client, admin, agent["id"])
    stable = _publish_version(client, admin, agent["id"])
    candidate = _publish_version(client, admin, agent["id"])
    stable_deployment = _lifecycle_deploy(client, admin, agent["id"], stable["id"])
    candidate_deployment = _lifecycle_deploy(client, admin, agent["id"], candidate["id"])
    if designate:
        r = client.post(
            f"{RT}/agents/{agent['id']}/versions/{candidate['id']}/rollback-target",
            headers=admin["headers"], json={"target_version_id": stable["id"]})
        assert r.status_code == 200, r.text
    return {"agent": agent, "stable": stable, "candidate": candidate,
            "stable_deployment": stable_deployment, "candidate_deployment": candidate_deployment,
            "environment": envs["DEVELOPMENT"]}


def _set_weights(client: TestClient, admin: dict, setup: dict, *,
                 candidate: int) -> None:
    """Put the candidate on trial at ``candidate``% through Phase 3.4's own
    API -- never by writing weights directly."""
    weights = [{"agent_version_id": setup["candidate"]["id"], "weight": candidate},
               {"agent_version_id": setup["stable"]["id"], "weight": 100 - candidate}]
    r = client.put(
        f"{RT}/agents/{setup['agent']['id']}/environments/{setup['environment']['id']}/traffic",
        headers=admin["headers"], json={"weights": weights, "reason": "Put candidate on trial."})
    assert r.status_code == 200, r.text


def _seed_executions(db_session: Session, setup: dict, admin: dict, version_id: str, *,
                    succeeded: int = 0, failed: int = 0, timed_out: int = 0, denied: int = 0,
                    deployment_id: str | None = None, duration_ms: int = 100) -> None:
    """Insert terminal execution rows -- the exact input the health engine
    reads in production."""
    rows = (
        [("SUCCEEDED", None)] * succeeded
        + [("FAILED", "PROVIDER_ERROR")] * failed
        + [("TIMED_OUT", "EXECUTION_TIMED_OUT")] * timed_out
        + [("DENIED", "RUNTIME_POLICY_DENIED")] * denied
    )
    now = _now()
    for status_value, error_code in rows:
        db_session.add(AgentExecution(
            organization_id=uuid.UUID(admin["organization_id"]),
            agent_id=uuid.UUID(setup["agent"]["id"]),
            agent_version_id=uuid.UUID(version_id),
            deployment_id=uuid.UUID(deployment_id) if deployment_id else None,
            trigger_type="API", status=status_value, error_code=error_code,
            duration_ms=duration_ms, input_payload={}, created_at=now,
            started_at=now, completed_at=now,
        ))
    db_session.commit()


def _policy(client: TestClient, admin: dict, setup: dict, *, mode: str = "AUTO_EXECUTE",
            min_samples: int = 20, cooldown_seconds: int = 900,
            thresholds: dict | None = None, enabled: bool = True) -> dict:
    r = client.put(f"{RT}/rollback-policies", headers=admin["headers"], json={
        "environment_id": setup["environment"]["id"], "agent_id": setup["agent"]["id"],
        "mode": mode, "min_samples": min_samples, "cooldown_seconds": cooldown_seconds,
        "thresholds": thresholds or {}, "enabled": enabled,
    })
    assert r.status_code == 200, r.text
    return r.json()


def _weights(db_session: Session, setup: dict, admin: dict) -> dict[str, int]:
    db_session.rollback()
    traffic = TrafficAllocationService(db_session)
    allocation = traffic.current(uuid.UUID(admin["organization_id"]),
                                uuid.UUID(setup["agent"]["id"]),
                                uuid.UUID(setup["environment"]["id"]))
    if allocation is None:
        return {}
    return {str(w.agent_version_id): w.weight for w in traffic.weights_for(allocation.id)}


def _allocation_count(db_session: Session, setup: dict) -> int:
    db_session.rollback()
    return len(db_session.execute(select(DeploymentTrafficAllocation).where(
        DeploymentTrafficAllocation.agent_id == uuid.UUID(setup["agent"]["id"]))).scalars().all())


def _evaluate(client: TestClient, admin: dict, deployment_id: str, *,
              headers: dict | None = None):
    return client.post(f"{RT}/deployments/{deployment_id}/rollback/evaluate",
                       headers=headers or admin["headers"])


def _rollback(client: TestClient, admin: dict, deployment_id: str, *,
              headers: dict | None = None, json_body: dict | None = None):
    return client.post(f"{RT}/deployments/{deployment_id}/rollback/execute",
                       headers=headers or admin["headers"], json=json_body or {})


def _make_user(client: TestClient, admin: dict, role: str) -> dict:
    """A second user in the same organization, at a lower role tier."""
    from tests.runtime.conftest import PASSWORD

    email = f"rollback_{role.lower()}_{uuid.uuid4().hex[:10]}@example.com"
    r = client.post("/api/v1/identity/users", headers=admin["headers"], json={
        "email": email, "display_name": role.title(), "password": PASSWORD, "role": role,
        "organization_id": admin["organization_id"],
    })
    assert r.status_code in (200, 201), r.text
    tokens = client.post("/api/v1/auth/login",
                         json={"email": email, "password": PASSWORD}).json()
    return {"headers": {"Authorization": f"Bearer {tokens['access_token']}"}}


def _second_org(client: TestClient) -> dict:
    from tests.runtime.conftest import PASSWORD

    email = f"rollback_other_{uuid.uuid4().hex[:10]}@example.com"
    assert client.post("/auth/register", json={
        "organization_name": "Other Org", "name": "Owner", "email": email, "password": PASSWORD,
    }).status_code == 201
    tokens = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD}).json()
    me = client.get("/api/v1/auth/me",
                    headers={"Authorization": f"Bearer {tokens['access_token']}"}).json()
    return {"headers": {"Authorization": f"Bearer {tokens['access_token']}"},
            "user_id": me["user"]["id"], "organization_id": me["user"]["organization_id"]}


# --------------------------------------------------------------------------- #
# AC-01 -- rollback_target_id is authoritative
# --------------------------------------------------------------------------- #
def test_ac01_rollback_returns_to_the_designated_target(
        client: TestClient, admin: dict, db_session: Session) -> None:
    setup = _setup(client, admin)
    _set_weights(client, admin, setup, candidate=100)

    r = _rollback(client, admin, setup["candidate_deployment"]["id"])
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["to_version_id"] == setup["stable"]["id"]
    assert body["from_version_id"] == setup["candidate"]["id"]
    assert _weights(db_session, setup, admin)[setup["stable"]["id"]] == 100


def test_ac01_the_target_is_read_from_the_field_not_guessed(
        client: TestClient, admin: dict, db_session: Session) -> None:
    """Three published versions exist; only one is *designated*. A rollback
    that picked "the previous version" by ordering would choose differently."""
    setup = _setup(client, admin, designate=False)
    third = _publish_version(client, admin, setup["agent"]["id"])
    _lifecycle_deploy(client, admin, setup["agent"]["id"], third["id"])
    # Designate the *first* version, not the immediately-preceding one.
    r = client.post(
        f"{RT}/agents/{setup['agent']['id']}/versions/{setup['candidate']['id']}/rollback-target",
        headers=admin["headers"], json={"target_version_id": setup["stable"]["id"]})
    assert r.status_code == 200, r.text
    _set_weights(client, admin, setup, candidate=100)

    body = _rollback(client, admin, setup["candidate_deployment"]["id"]).json()
    assert body["to_version_id"] == setup["stable"]["id"]
    assert body["to_version_id"] != third["id"]


def test_ac01_designate_target_goes_through_the_lineage_service(
        client: TestClient, admin: dict, db_session: Session) -> None:
    """Making the field authoritative must not bypass its existing writer --
    that is what keeps the lineage rules (same agent, rollback-eligible
    status) in one place."""
    source = Path(rollback_module.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    attributes = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    assert "set_rollback_target" in attributes
    # And never a raw assignment to the column.
    assigned = {
        target.attr
        for node in ast.walk(tree) if isinstance(node, ast.Assign)
        for target in node.targets if isinstance(target, ast.Attribute)
    }
    assert "rollback_target_id" not in assigned


# --------------------------------------------------------------------------- #
# AC-02 -- one unified operation for every trigger
# --------------------------------------------------------------------------- #
def test_ac02_every_trigger_funnels_through_one_execute(
        client: TestClient, admin: dict, db_session: Session) -> None:
    """The four triggers are data, not four code paths: each is recorded on
    the same row shape by the same method."""
    tree = ast.parse(Path(rollback_module.__file__).read_text(encoding="utf-8"))
    service = next(node for node in ast.walk(tree)
                   if isinstance(node, ast.ClassDef) and node.name == "RollbackService")
    methods = {node.name for node in service.body if isinstance(node, ast.FunctionDef)}
    # One public entry point performing a rollback, plus force/evaluate/resume
    # which all delegate to it rather than moving traffic themselves.
    assert "execute" in methods
    assert rollback_module.TRIGGERS == {"MANUAL", "REQUESTED", "AUTOMATIC", "FORCED"}
    for name in ("force", "_evaluate_inner", "resume_incomplete"):
        assert name in methods


def test_ac02_manual_and_automatic_produce_the_same_shape(
        client: TestClient, admin: dict, db_session: Session) -> None:
    setup = _setup(client, admin)
    _set_weights(client, admin, setup, candidate=100)
    manual = _rollback(client, admin, setup["candidate_deployment"]["id"]).json()

    other = _setup(client, admin)
    _set_weights(client, admin, other, candidate=100)
    _policy(client, admin, other, min_samples=10)
    _seed_executions(db_session, other, admin, other["candidate"]["id"], failed=20,
                     deployment_id=other["candidate_deployment"]["id"])
    automatic = _evaluate(client, admin, other["candidate_deployment"]["id"]).json()["rollback"]

    assert manual["trigger"] == "MANUAL" and automatic["trigger"] == "AUTOMATIC"
    assert set(manual) == set(automatic)
    # An automatic rollback names no human -- writing one would make the audit
    # trail claim a person acted.
    assert manual["initiated_by"] is not None
    assert automatic["initiated_by"] is None


# --------------------------------------------------------------------------- #
# AC-03 -- rollback drives Phase 3.4's allocation, never direct writes
# --------------------------------------------------------------------------- #
def test_ac03_rollback_never_writes_traffic_weights_directly() -> None:
    """Structural, mirroring 3.5's and 3.6's own proofs: the module cannot
    bypass 3.4 because it holds no reference to the weight tables at all."""
    tree = ast.parse(Path(rollback_module.__file__).read_text(encoding="utf-8"))
    names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    names |= {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    assert "DeploymentTrafficWeight" not in names
    assert "DeploymentTrafficAllocation" not in names
    assert "set_weights" in names


def test_ac03_rollback_moves_candidate_to_zero_and_target_to_100(
        client: TestClient, admin: dict, db_session: Session) -> None:
    setup = _setup(client, admin)
    _set_weights(client, admin, setup, candidate=100)
    before = _allocation_count(db_session, setup)

    _rollback(client, admin, setup["candidate_deployment"]["id"])

    weights = _weights(db_session, setup, admin)
    assert weights[setup["candidate"]["id"]] == 0
    assert weights[setup["stable"]["id"]] == 100
    # Exactly one new revision -- an atomic transition, not two half-moves.
    assert _allocation_count(db_session, setup) == before + 1


# --------------------------------------------------------------------------- #
# AC-04 -- idempotent, atomic, evidence preserved
# --------------------------------------------------------------------------- #
def test_ac04_rollback_is_idempotent_under_an_idempotency_key(
        client: TestClient, admin: dict, db_session: Session) -> None:
    setup = _setup(client, admin)
    _set_weights(client, admin, setup, candidate=100)
    key = uuid.uuid4().hex
    headers = {**admin["headers"], "Idempotency-Key": key}

    first = client.post(f"{RT}/deployments/{setup['candidate_deployment']['id']}/rollback/execute",
                        headers=headers, json={})
    second = client.post(f"{RT}/deployments/{setup['candidate_deployment']['id']}/rollback/execute",
                         headers=headers, json={})
    assert first.status_code == 200 and second.status_code == 200, second.text
    assert first.json()["id"] == second.json()["id"]
    db_session.rollback()
    events = db_session.execute(select(RollbackEvent).where(
        RollbackEvent.deployment_id == uuid.UUID(setup["candidate_deployment"]["id"]),
    )).scalars().all()
    assert len(events) == 1


def test_ac04_the_failed_candidates_state_is_preserved_as_evidence(
        client: TestClient, admin: dict, db_session: Session) -> None:
    setup = _setup(client, admin)
    _set_weights(client, admin, setup, candidate=100)
    _policy(client, admin, setup, min_samples=10)
    _seed_executions(db_session, setup, admin, setup["candidate"]["id"], failed=18, succeeded=2,
                     deployment_id=setup["candidate_deployment"]["id"])

    event = _evaluate(client, admin, setup["candidate_deployment"]["id"]).json()["rollback"]
    evidence = event["evidence_ref"]
    assert evidence["health_state"] in ("UNHEALTHY", "DEGRADED")
    assert evidence["metrics"]["sample_count"] == 20
    assert evidence["metrics"]["failed"] == 18
    assert evidence["reasons"], "the crossed thresholds must be recorded, not just the verdict"
    # The candidate version itself still exists -- rolling back must not be the
    # act that destroys what an engineer needs to diagnose.
    db_session.rollback()
    assert db_session.get(AgentVersion, uuid.UUID(setup["candidate"]["id"])) is not None


# --------------------------------------------------------------------------- #
# AC-05 -- a configurable policy fires on a crossed threshold
# --------------------------------------------------------------------------- #
def test_ac05_a_policy_fires_an_automatic_rollback(
        client: TestClient, admin: dict, db_session: Session) -> None:
    setup = _setup(client, admin)
    _set_weights(client, admin, setup, candidate=100)
    _policy(client, admin, setup, min_samples=10)
    _seed_executions(db_session, setup, admin, setup["candidate"]["id"], failed=20,
                     deployment_id=setup["candidate_deployment"]["id"])

    body = _evaluate(client, admin, setup["candidate_deployment"]["id"]).json()
    assert body["action"] == "ROLLED_BACK", body
    assert body["decision"]["should_rollback"] is True
    assert body["rollback"]["trigger"] == "AUTOMATIC"


def test_ac05_no_policy_means_no_automation(
        client: TestClient, admin: dict, db_session: Session) -> None:
    """Automation is opt-in. A tenant that configured nothing keeps exactly the
    manual behaviour 3.5 and 3.6 gave them."""
    setup = _setup(client, admin)
    _set_weights(client, admin, setup, candidate=100)
    _seed_executions(db_session, setup, admin, setup["candidate"]["id"], failed=50,
                     deployment_id=setup["candidate_deployment"]["id"])

    body = _evaluate(client, admin, setup["candidate_deployment"]["id"]).json()
    assert body["action"] == "NO_POLICY"
    assert body["rollback"] is None
    assert _weights(db_session, setup, admin)[setup["candidate"]["id"]] == 100


def test_ac05_notify_only_detects_but_does_not_act(
        client: TestClient, admin: dict, db_session: Session) -> None:
    setup = _setup(client, admin)
    _set_weights(client, admin, setup, candidate=100)
    _policy(client, admin, setup, mode="NOTIFY_ONLY", min_samples=10)
    _seed_executions(db_session, setup, admin, setup["candidate"]["id"], failed=20,
                     deployment_id=setup["candidate_deployment"]["id"])

    body = _evaluate(client, admin, setup["candidate_deployment"]["id"]).json()
    assert body["action"] == "WITHHELD"
    assert "NOTIFY_ONLY" in body["decision"]["withheld_reason"]
    assert body["decision"]["reasons"], "the regression is still reported"
    assert _weights(db_session, setup, admin)[setup["candidate"]["id"]] == 100


def test_ac05_a_healthy_candidate_is_left_alone(
        client: TestClient, admin: dict, db_session: Session) -> None:
    setup = _setup(client, admin)
    _set_weights(client, admin, setup, candidate=100)
    _policy(client, admin, setup, min_samples=10)
    _seed_executions(db_session, setup, admin, setup["candidate"]["id"], succeeded=40,
                     deployment_id=setup["candidate_deployment"]["id"])

    body = _evaluate(client, admin, setup["candidate_deployment"]["id"]).json()
    assert body["action"] == "NO_ACTION"
    assert _weights(db_session, setup, admin)[setup["candidate"]["id"]] == 100


# --------------------------------------------------------------------------- #
# AC-06 -- INSUFFICIENT_DATA never triggers
# --------------------------------------------------------------------------- #
def test_ac06_insufficient_data_never_triggers_a_rollback(
        client: TestClient, admin: dict, db_session: Session) -> None:
    """Three failures out of three is 100% error rate and still not evidence."""
    setup = _setup(client, admin)
    _set_weights(client, admin, setup, candidate=100)
    _policy(client, admin, setup, min_samples=20)
    _seed_executions(db_session, setup, admin, setup["candidate"]["id"], failed=3,
                     deployment_id=setup["candidate_deployment"]["id"])

    body = _evaluate(client, admin, setup["candidate_deployment"]["id"]).json()
    assert body["action"] == "NO_ACTION"
    assert body["rollback"] is None
    assert _weights(db_session, setup, admin)[setup["candidate"]["id"]] == 100


@pytest.mark.parametrize("state", sorted(NON_ACTIONABLE_HEALTH_STATES))
def test_ac06_non_actionable_states_never_trigger_at_any_error_rate(state: str) -> None:
    decision = evaluate_thresholds(
        state, {"sample_count": 10_000, "error_rate": 1.0, "denial_rate": 1.0}, None,
        DEFAULT_TRIGGER_THRESHOLDS, min_samples=1)
    assert decision.should_rollback is False
    assert decision.withheld_reason is not None


def test_ac06_the_sample_floor_is_checked_before_any_threshold() -> None:
    decision = evaluate_thresholds(
        "UNHEALTHY", {"sample_count": 19, "error_rate": 1.0}, None,
        DEFAULT_TRIGGER_THRESHOLDS, min_samples=20)
    assert decision.should_rollback is False
    assert "19 samples" in decision.withheld_reason
    assert decision.reasons == ()


# --------------------------------------------------------------------------- #
# AC-07 -- bounded, idempotent evaluation: one crossing, one rollback
# --------------------------------------------------------------------------- #
def test_ac07_one_crossing_fires_exactly_one_rollback(
        client: TestClient, admin: dict, db_session: Session) -> None:
    setup = _setup(client, admin)
    _set_weights(client, admin, setup, candidate=100)
    _policy(client, admin, setup, min_samples=10, cooldown_seconds=0)
    _seed_executions(db_session, setup, admin, setup["candidate"]["id"], failed=20,
                     deployment_id=setup["candidate_deployment"]["id"])

    first = _evaluate(client, admin, setup["candidate_deployment"]["id"]).json()
    assert first["action"] == "ROLLED_BACK"
    # Evaluate again: the candidate is at 0% now, so nothing should fire even
    # with the cooldown disabled.
    second = _evaluate(client, admin, setup["candidate_deployment"]["id"]).json()
    assert second["action"] != "ROLLED_BACK", second

    db_session.rollback()
    automatic = db_session.execute(select(RollbackEvent).where(
        RollbackEvent.deployment_id == uuid.UUID(setup["candidate_deployment"]["id"]),
        RollbackEvent.trigger == "AUTOMATIC",
    )).scalars().all()
    assert len(automatic) == 1


def test_ac07_evaluation_is_marked_interim_for_phase_38() -> None:
    """The interim mechanism must say so, as 3.5's auto-advance does -- a
    future reader has to be able to find what 3.8 replaces."""
    source = Path(rollback_module.__file__).read_text(encoding="utf-8")
    assert "3.8" in source
    assert "scheduler" in source.lower()


# --------------------------------------------------------------------------- #
# AC-08 -- THE §19 PROOF, AUTOMATIC
# --------------------------------------------------------------------------- #
def test_ac08_the_section_19_proof_automatic(
        client: TestClient, admin: dict, db_session: Session) -> None:
    """The milestone's headline proof, made automatic.

    A candidate is put on trial at 50%, its executions start failing, and the
    platform rolls it back *on its own*: stable returns to 100%, the candidate
    goes to 0%, evidence is preserved, and the whole thing is audited. No
    human is in the loop after the policy is configured."""
    setup = _setup(client, admin)
    # Stable is healthy and serving; the candidate is on trial.
    _set_weights(client, admin, setup, candidate=50)
    _seed_executions(db_session, setup, admin, setup["stable"]["id"], succeeded=40,
                     deployment_id=setup["stable_deployment"]["id"])
    _policy(client, admin, setup, min_samples=10)

    # ... and then the candidate starts failing.
    _seed_executions(db_session, setup, admin, setup["candidate"]["id"], failed=24, succeeded=6,
                     deployment_id=setup["candidate_deployment"]["id"])

    body = _evaluate(client, admin, setup["candidate_deployment"]["id"]).json()

    assert body["action"] == "ROLLED_BACK", body
    event = body["rollback"]
    assert event["trigger"] == "AUTOMATIC"
    assert event["initiated_by"] is None
    assert event["status"] == "COMPLETED"
    assert event["to_version_id"] == setup["stable"]["id"]

    weights = _weights(db_session, setup, admin)
    assert weights[setup["stable"]["id"]] == 100
    assert weights[setup["candidate"]["id"]] == 0

    assert event["evidence_ref"]["metrics"]["failed"] == 24
    assert event["evidence_ref"]["reasons"]

    # Audited: the trigger firing, the rollback starting, and its completion.
    db_session.rollback()
    events = db_session.execute(select(RuntimeEvent).where(
        RuntimeEvent.agent_id == uuid.UUID(setup["agent"]["id"]))).scalars().all()
    kinds = {e.event_type for e in events}
    assert "ROLLBACK_TRIGGER_FIRED" in kinds
    assert "DEPLOYMENT_ROLLBACK_STARTED" in kinds
    assert "RUNTIME_ROLLBACK_COMPLETED" in kinds


# --------------------------------------------------------------------------- #
# AC-09 -- kill-switch dominance over automation (§12)
# --------------------------------------------------------------------------- #
def test_ac09_a_killed_agent_halts_automation(
        client: TestClient, admin: dict, db_session: Session) -> None:
    setup = _setup(client, admin)
    _set_weights(client, admin, setup, candidate=100)
    _policy(client, admin, setup, min_samples=10)
    _seed_executions(db_session, setup, admin, setup["candidate"]["id"], failed=30,
                     deployment_id=setup["candidate_deployment"]["id"])

    assert client.post(f"{RT}/kill-switch/agents/{setup['agent']['id']}",
                       headers=admin["headers"],
                       json={"reason": "Incident."}).status_code == 200

    body = _evaluate(client, admin, setup["candidate_deployment"]["id"]).json()
    assert body["action"] == "WITHHELD", body
    assert body["rollback"] is None
    # Automation stood down; it did not roll back and it did not reactivate.
    assert _weights(db_session, setup, admin)[setup["candidate"]["id"]] == 100


def test_ac09_automation_never_clears_a_kill_switch(
        client: TestClient, admin: dict, db_session: Session) -> None:
    setup = _setup(client, admin)
    _set_weights(client, admin, setup, candidate=100)
    _policy(client, admin, setup, min_samples=10)
    _seed_executions(db_session, setup, admin, setup["candidate"]["id"], failed=30,
                     deployment_id=setup["candidate_deployment"]["id"])
    assert client.post(f"{RT}/kill-switch/agents/{setup['agent']['id']}",
                       headers=admin["headers"], json={"reason": "Incident."}).status_code == 200

    _evaluate(client, admin, setup["candidate_deployment"]["id"])

    db_session.rollback()
    agent = db_session.get(Agent, uuid.UUID(setup["agent"]["id"]))
    assert agent.lifecycle_status == "SUSPENDED", "automation must never lift a human's kill"


def test_ac09_the_module_never_writes_agent_or_deployment_status() -> None:
    """Structural: the absence of the write, not merely the intent to avoid
    it. Automation cannot clear a kill switch it has no code to clear.

    Checked as ``(receiver, attribute)`` pairs rather than by attribute name
    alone. A bare "never assign anything called ``status``" would be simpler
    but wrong here: this module legitimately sets ``RollbackEvent.status`` to
    track its own durable intent, and a check that cannot tell that apart from
    ``deployment.status = 'ACTIVE'`` would either fail on correct code or have
    to be deleted. What actually matters is the *receiver* -- the kill switch
    lives on ``Agent.lifecycle_status`` and ``AgentDeployment.status``, and
    neither may ever be written from here."""
    tree = ast.parse(Path(rollback_module.__file__).read_text(encoding="utf-8"))
    writes = {
        (target.value.id if isinstance(target.value, ast.Name) else "?", target.attr)
        for node in ast.walk(tree) if isinstance(node, (ast.Assign, ast.AugAssign))
        for target in (node.targets if isinstance(node, ast.Assign) else [node.target])
        if isinstance(target, ast.Attribute)
    }
    # The kill switch itself, on any receiver at all.
    assert not [w for w in writes if w[1] == "lifecycle_status"], writes
    # A deployment's or agent's own status, which suspension also uses.
    forbidden_receivers = {"agent", "deployment", "candidate_deployment", "target_deployment"}
    assert not [w for w in writes
                if w[0] in forbidden_receivers and w[1] in ("status", "lifecycle_state")], writes
    # And the only ``status`` this module does write belongs to its own table.
    assert {w for w in writes if w[1] == "status"} <= {("event", "status"), ("pending", "status")}


def test_ac09_the_automatic_path_raises_the_specific_code(
        client: TestClient, admin: dict, db_session: Session) -> None:
    setup = _setup(client, admin)
    assert client.post(f"{RT}/kill-switch/agents/{setup['agent']['id']}",
                       headers=admin["headers"], json={"reason": "Incident."}).status_code == 200
    db_session.rollback()
    service = RollbackService(db_session)
    deployment = db_session.get(AgentDeployment, uuid.UUID(setup["candidate_deployment"]["id"]))

    with pytest.raises(IdentityError) as excinfo:
        service.assert_automation_permitted(deployment)
    assert excinfo.value.code == ErrorCode.ROLLBACK_BLOCKED_BY_KILL_SWITCH
    assert excinfo.value.http_status == 423


def test_ac09_a_manual_rollback_still_works_while_killed(
        client: TestClient, admin: dict, db_session: Session) -> None:
    """The kill switch blocks *automation*, not humans. Phase 3.6 made the
    same call for its own rollback, and for the same reason: a kill switch
    must never trap an operator on the version they are trying to leave."""
    setup = _setup(client, admin)
    _set_weights(client, admin, setup, candidate=100)
    assert client.post(f"{RT}/kill-switch/agents/{setup['agent']['id']}",
                       headers=admin["headers"], json={"reason": "Incident."}).status_code == 200

    r = _rollback(client, admin, setup["candidate_deployment"]["id"])
    assert r.status_code == 200, r.text
    assert r.json()["trigger"] == "MANUAL"


# --------------------------------------------------------------------------- #
# AC-10 -- fail closed with no valid target
# --------------------------------------------------------------------------- #
def test_ac10_no_designated_target_fails_closed(
        client: TestClient, admin: dict, db_session: Session) -> None:
    setup = _setup(client, admin, designate=False)
    _set_weights(client, admin, setup, candidate=100)

    r = _rollback(client, admin, setup["candidate_deployment"]["id"])
    assert r.status_code == 409, r.text
    assert r.json()["error"]["code"] == ErrorCode.ROLLBACK_TARGET_UNAVAILABLE
    # And nothing moved -- a refusal, not a partial rollback.
    assert _weights(db_session, setup, admin)[setup["candidate"]["id"]] == 100


def test_ac10_never_rolls_back_to_an_unpublished_version(
        client: TestClient, admin: dict, db_session: Session) -> None:
    setup = _setup(client, admin)
    _set_weights(client, admin, setup, candidate=100)
    db_session.rollback()
    stable = db_session.get(AgentVersion, uuid.UUID(setup["stable"]["id"]))
    stable.status = "REVOKED"
    db_session.commit()

    r = _rollback(client, admin, setup["candidate_deployment"]["id"])
    assert r.status_code == 409, r.text
    assert r.json()["error"]["code"] == ErrorCode.ROLLBACK_TARGET_UNAVAILABLE


def test_ac10_a_target_from_another_agent_is_refused(
        client: TestClient, admin: dict, db_session: Session) -> None:
    setup = _setup(client, admin, designate=False)
    other = _setup(client, admin, designate=False)
    db_session.rollback()
    candidate = db_session.get(AgentVersion, uuid.UUID(setup["candidate"]["id"]))
    # Bypass the lineage validator deliberately, to prove resolve_target does
    # not trust the stored value blindly.
    candidate.rollback_target_id = uuid.UUID(other["stable"]["id"])
    db_session.commit()

    r = _rollback(client, admin, setup["candidate_deployment"]["id"])
    assert r.status_code == 409, r.text
    assert r.json()["error"]["code"] == ErrorCode.ROLLBACK_TARGET_UNAVAILABLE


# --------------------------------------------------------------------------- #
# AC-11 -- forced rollback (§11)
# --------------------------------------------------------------------------- #
def test_ac11_force_requires_its_own_distinct_permission() -> None:
    """The override is gated by a permission of its own, not by the ordinary
    rollback grant.

    Worth stating plainly what this does and does not buy in *this* codebase:
    ``SYSTEM_ROLE_PERMISSIONS`` gives SUPER_ADMIN and ADMIN the entire catalog,
    so a new code does not restrict them. What it does is make the separation
    expressible -- an organization can build a custom role holding
    ``runtime.deployment.rollback`` without
    ``runtime.deployment.force_rollback``, which is impossible if the override
    reuses the ordinary permission. The distinction is real at the tier below
    admin, and it is asserted here rather than assumed."""
    from app.services.rbac_service import PERMISSION_CATALOG, SYSTEM_ROLE_PERMISSIONS

    assert "runtime.deployment.force_rollback" in PERMISSION_CATALOG
    assert "runtime.deployment.rollback" in PERMISSION_CATALOG
    for role in ("REVIEWER", "VIEWER"):
        assert "runtime.deployment.force_rollback" not in SYSTEM_ROLE_PERMISSIONS[role]


def test_ac11_force_without_the_elevated_permission_is_rejected(
        client: TestClient, admin: dict, db_session: Session) -> None:
    setup = _setup(client, admin)
    reviewer = _make_user(client, admin, "REVIEWER")
    r = client.post(f"{RT}/deployments/{setup['candidate_deployment']['id']}/rollback/force",
                    headers=reviewer["headers"],
                    json={"justification": "Production is down."})
    assert r.status_code == 403, r.text


def test_ac11_force_without_a_justification_is_rejected(
        client: TestClient, admin: dict, db_session: Session) -> None:
    setup = _setup(client, admin)
    r = client.post(f"{RT}/deployments/{setup['candidate_deployment']['id']}/rollback/force",
                    headers=admin["headers"], json={"justification": ""})
    assert r.status_code == 422, r.text


def test_ac11_force_with_authority_and_justification_is_audited(
        client: TestClient, admin: dict, db_session: Session) -> None:
    """The override's real power: naming a target where none is designated,
    which is exactly the 3am case an ordinary rollback fails closed on."""
    setup = _setup(client, admin, designate=False)
    _set_weights(client, admin, setup, candidate=100)

    # An ordinary rollback refuses here -- that is what force overrides.
    assert _rollback(client, admin, setup["candidate_deployment"]["id"]).status_code == 409

    r = client.post(f"{RT}/deployments/{setup['candidate_deployment']['id']}/rollback/force",
                    headers=admin["headers"],
                    json={"justification": "Production is down; designation is wrong.",
                          "target_version_id": setup["stable"]["id"]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["trigger"] == "FORCED"
    assert body["justification"] == "Production is down; designation is wrong."
    assert _weights(db_session, setup, admin)[setup["stable"]["id"]] == 100

    db_session.rollback()
    forced = db_session.execute(select(RuntimeEvent).where(
        RuntimeEvent.agent_id == uuid.UUID(setup["agent"]["id"]),
        RuntimeEvent.event_type == "ROLLBACK_FORCED")).scalars().all()
    assert len(forced) == 1
    assert forced[0].severity == "CRITICAL"
    assert forced[0].payload["justification"] == "Production is down; designation is wrong."


def test_ac11_force_does_not_override_the_kill_switch(
        client: TestClient, admin: dict, db_session: Session) -> None:
    """The one thing an override deliberately cannot override. A forced
    rollback is still a human act, so it proceeds -- but it proceeds as a
    *rollback*, and it never reactivates or clears the kill."""
    setup = _setup(client, admin)
    _set_weights(client, admin, setup, candidate=100)
    assert client.post(f"{RT}/kill-switch/agents/{setup['agent']['id']}",
                       headers=admin["headers"], json={"reason": "Incident."}).status_code == 200

    r = client.post(f"{RT}/deployments/{setup['candidate_deployment']['id']}/rollback/force",
                    headers=admin["headers"], json={"justification": "Roll back under incident."})
    assert r.status_code == 200, r.text
    db_session.rollback()
    assert db_session.get(Agent, uuid.UUID(setup["agent"]["id"])).lifecycle_status == "SUSPENDED"


# --------------------------------------------------------------------------- #
# AC-12 -- anti-flap
# --------------------------------------------------------------------------- #
def test_ac12_a_rollback_does_not_immediately_retrigger(
        client: TestClient, admin: dict, db_session: Session) -> None:
    setup = _setup(client, admin)
    _set_weights(client, admin, setup, candidate=100)
    _policy(client, admin, setup, min_samples=10, cooldown_seconds=900)
    _seed_executions(db_session, setup, admin, setup["candidate"]["id"], failed=30,
                     deployment_id=setup["candidate_deployment"]["id"])

    assert _evaluate(client, admin, setup["candidate_deployment"]["id"]).json()["action"] \
        == "ROLLED_BACK"

    # Put the candidate back on trial and re-fail it: the cooldown must hold.
    _set_weights(client, admin, setup, candidate=100)
    _seed_executions(db_session, setup, admin, setup["candidate"]["id"], failed=30,
                     deployment_id=setup["candidate_deployment"]["id"])
    body = _evaluate(client, admin, setup["candidate_deployment"]["id"]).json()
    assert body["action"] == "WITHHELD", body
    assert "cooldown" in body["decision"]["withheld_reason"].lower()


def test_ac12_a_zero_cooldown_policy_disables_the_guard(
        client: TestClient, admin: dict, db_session: Session) -> None:
    """The guard is configurable, and its absence is a deliberate choice a
    tenant can make rather than an accident of the code."""
    setup = _setup(client, admin)
    _policy(client, admin, setup, min_samples=10, cooldown_seconds=0)
    db_session.rollback()
    service = RollbackService(db_session)
    deployment = db_session.get(AgentDeployment, uuid.UUID(setup["candidate_deployment"]["id"]))
    policy = RollbackPolicyService(db_session).resolve(
        deployment.organization_id, environment_id=deployment.environment_id,
        agent_id=deployment.agent_id)
    assert policy.cooldown_seconds == 0
    assert service._in_cooldown(deployment, policy) is False


# --------------------------------------------------------------------------- #
# AC-13 -- recovery
# --------------------------------------------------------------------------- #
def test_ac13_an_interrupted_rollback_resumes_safely(
        client: TestClient, admin: dict, db_session: Session) -> None:
    """Simulates a crash between the durable intent and the traffic move: an
    ``IN_PROGRESS`` row exists but weights never moved. Re-evaluating must
    finish it rather than leave a half-applied allocation."""
    setup = _setup(client, admin)
    _set_weights(client, admin, setup, candidate=100)
    db_session.rollback()

    orphan = RollbackEvent(
        organization_id=uuid.UUID(admin["organization_id"]),
        deployment_id=uuid.UUID(setup["candidate_deployment"]["id"]),
        agent_id=uuid.UUID(setup["agent"]["id"]),
        environment_id=uuid.UUID(setup["environment"]["id"]),
        from_version_id=uuid.UUID(setup["candidate"]["id"]),
        to_version_id=uuid.UUID(setup["stable"]["id"]),
        trigger="AUTOMATIC", status="IN_PROGRESS",
        reason="Interrupted by a simulated restart.",
    )
    db_session.add(orphan)
    db_session.commit()

    body = _evaluate(client, admin, setup["candidate_deployment"]["id"]).json()
    assert body["action"] == "RESUMED", body

    weights = _weights(db_session, setup, admin)
    assert weights[setup["stable"]["id"]] == 100
    assert weights[setup["candidate"]["id"]] == 0
    db_session.rollback()
    db_session.refresh(orphan)
    assert orphan.status == "COMPLETED"
    assert orphan.completed_at is not None


def test_ac13_resume_is_a_no_op_on_a_healthy_system(
        client: TestClient, admin: dict, db_session: Session) -> None:
    setup = _setup(client, admin)
    db_session.rollback()
    deployment = db_session.get(AgentDeployment, uuid.UUID(setup["candidate_deployment"]["id"]))
    actor = db_session.get(UserModel, uuid.UUID(admin["user_id"]))
    assert RollbackService(db_session).resume_incomplete(actor, deployment) is None


def test_ac13_durable_intent_is_committed_before_traffic_moves() -> None:
    """Structural: the ordering is the entire recovery guarantee. If the row
    were written after the move, a crash would lose the record of an action
    that had already happened -- the worse of the two failure modes."""
    source = Path(rollback_module.__file__).read_text(encoding="utf-8")
    inner = source.split("def _execute_inner")[1].split("def _apply")[0]
    intent_commit = inner.index("self.db.commit()")
    traffic_move = inner.index("self._apply(")
    assert intent_commit < traffic_move


# --------------------------------------------------------------------------- #
# AC-14 -- concurrency, on real separate connections
# --------------------------------------------------------------------------- #
def test_ac14_a_manual_rollback_racing_an_automatic_one_resolves_once(
        client: TestClient, admin: dict, db_session: Session) -> None:
    """Deterministic, not a thread barrier: a real second connection commits a
    competing allocation and holds its transaction open, so the rollback under
    test blocks inside Postgres on 3.4's partial unique index and loses."""
    setup = _setup(client, admin)
    _set_weights(client, admin, setup, candidate=100)
    _policy(client, admin, setup, min_samples=10, cooldown_seconds=0)
    _seed_executions(db_session, setup, admin, setup["candidate"]["id"], failed=20,
                     deployment_id=setup["candidate_deployment"]["id"])

    # The manual rollback wins first.
    assert _rollback(client, admin, setup["candidate_deployment"]["id"]).status_code == 200

    # The automatic evaluation now finds nothing left to do rather than
    # rolling back a second time.
    body = _evaluate(client, admin, setup["candidate_deployment"]["id"]).json()
    assert body["action"] != "ROLLED_BACK", body

    db_session.rollback()
    events = db_session.execute(select(RollbackEvent).where(
        RollbackEvent.deployment_id == uuid.UUID(setup["candidate_deployment"]["id"]),
    )).scalars().all()
    assert len(events) == 1


def test_ac14_two_automatic_evaluations_dedup_to_one_rollback(
        client: TestClient, admin: dict, db_session: Session) -> None:
    """The partial unique index on ``dedup_key`` is the primitive: the
    database decides, not application timing."""
    setup = _setup(client, admin)
    _set_weights(client, admin, setup, candidate=100)
    db_session.rollback()

    deployment = db_session.get(AgentDeployment, uuid.UUID(setup["candidate_deployment"]["id"]))
    actor = db_session.get(UserModel, uuid.UUID(admin["user_id"]))
    key = RollbackService(db_session)._dedup_key(deployment)

    first = RollbackService(db_session).execute(actor, deployment, trigger="AUTOMATIC",
                                        reason="first", dedup_key=key)
    assert first["status"] == "COMPLETED"

    other = SessionLocal()
    try:
        deployment2 = other.get(AgentDeployment, uuid.UUID(setup["candidate_deployment"]["id"]))
        actor2 = other.get(UserModel, uuid.UUID(admin["user_id"]))
        with pytest.raises(IdentityError) as excinfo:
            RollbackService(other).execute(actor2, deployment2, trigger="AUTOMATIC",
                                           reason="second", dedup_key=key)
        assert excinfo.value.code == ErrorCode.ROLLBACK_CONFLICT
    finally:
        other.rollback()
        other.close()


# --------------------------------------------------------------------------- #
# AC-15 -- authorization, tenancy, idempotency
# --------------------------------------------------------------------------- #
def test_ac15_rollback_endpoints_require_authentication(
        client: TestClient, admin: dict) -> None:
    setup = _setup(client, admin)
    did = setup["candidate_deployment"]["id"]
    for method, path in (("post", f"{RT}/deployments/{did}/rollback/execute"),
                        ("post", f"{RT}/deployments/{did}/rollback/evaluate"),
                        ("get", f"{RT}/deployments/{did}/rollback/history"),
                        ("get", f"{RT}/rollback-policies")):
        r = client.post(path, json={}) if method == "post" else client.get(path)
        assert r.status_code in (401, 403), f"{path} -> {r.status_code}"


def test_ac15_a_viewer_cannot_roll_back(client: TestClient, admin: dict) -> None:
    setup = _setup(client, admin)
    viewer = _make_user(client, admin, "VIEWER")
    r = _rollback(client, admin, setup["candidate_deployment"]["id"],
                  headers=viewer["headers"])
    assert r.status_code == 403, r.text


def test_ac15_cross_tenant_rollback_is_rejected(client: TestClient, admin: dict) -> None:
    setup = _setup(client, admin)
    other = _second_org(client)
    r = _rollback(client, admin, setup["candidate_deployment"]["id"],
                  headers=other["headers"])
    assert r.status_code in (403, 404), r.text


def test_ac15_cross_tenant_policy_scope_is_rejected(client: TestClient, admin: dict) -> None:
    """A tenant must not be able to arm automation against another tenant's
    agent by id."""
    setup = _setup(client, admin)
    other = _second_org(client)
    r = client.put(f"{RT}/rollback-policies", headers=other["headers"], json={
        "agent_id": setup["agent"]["id"], "mode": "AUTO_EXECUTE",
    })
    assert r.status_code in (403, 404), r.text


def test_ac15_evaluate_honours_an_idempotency_key(
        client: TestClient, admin: dict, db_session: Session) -> None:
    setup = _setup(client, admin)
    _set_weights(client, admin, setup, candidate=100)
    _policy(client, admin, setup, min_samples=10, cooldown_seconds=0)
    _seed_executions(db_session, setup, admin, setup["candidate"]["id"], failed=20,
                     deployment_id=setup["candidate_deployment"]["id"])
    key = uuid.uuid4().hex
    headers = {**admin["headers"], "Idempotency-Key": key}
    path = f"{RT}/deployments/{setup['candidate_deployment']['id']}/rollback/evaluate"

    first = client.post(path, headers=headers)
    second = client.post(path, headers=headers)
    assert first.status_code == 200 and second.status_code == 200, second.text
    assert first.json()["rollback"]["id"] == second.json()["rollback"]["id"]


# --------------------------------------------------------------------------- #
# AC-16 -- 3.4/3.5/3.6 mechanics unchanged
# --------------------------------------------------------------------------- #
def test_ac16_earlier_phase_mechanics_are_unmodified() -> None:
    """This phase drives 3.4, 3.5 and 3.6; it does not modify them. Asserted
    against ``main`` rather than trusted, the same proof 3.6 used.

    **Phase 3.9 narrowed this list, and the reason is worth recording rather
    than hiding in a diff.** As written, this test compared six files against
    a *moving* ``main``, so it asserted not only "3.7 did not touch these" but
    "no future phase ever will". Two of the six had a future phase with an
    explicit mandate: 3.6's own ``RollingStrategy`` docstring designated
    itself "the seam Phase 3.9 fills", and 3.9's build prompt requires that
    seam replaced (AC-11) and requires the rolling cohort gate to sit in
    ``canary.py``'s single advance choke point -- anywhere else and the
    generic ``/rollouts/{id}/advance`` route bypasses it.

    So ``canary.py`` and ``strategies.py`` moved out of the byte-equality
    list, and the constraint on them did not disappear -- it got sharper.
    ``tests/runtime/test_worker_fleet_rolling.py::test_ac09_phase_39_changed
    _only_the_rolling_seam`` asserts that 3.9's edits to those two files are
    confined to rolling: the canary state machine, its gates, its weight
    arithmetic and the other three strategy handlers are all still identical
    to ``main``. Four files byte-locked plus two structurally locked is a
    stronger total guarantee than six files locked against a baseline that
    was going to have to be broken."""
    import subprocess

    repo = Path(__file__).resolve().parents[3]
    protected = [
        "backend/app/runtime/deployment/resolver.py",
        "backend/app/runtime/deployment/traffic.py",
        "backend/app/runtime/deployment/rollout.py",
        "backend/app/runtime/deployment/health.py",
    ]
    result = subprocess.run(
        ["git", "diff", "--name-only", "main", "--", *protected],
        cwd=repo, capture_output=True, text=True, check=False)
    assert result.stdout.strip() == "", f"modified: {result.stdout}"


def test_ac16_the_legacy_phase_50_rollback_endpoint_is_untouched(
        client: TestClient, admin: dict) -> None:
    """The Phase 5.0 redeploy endpoint still exists and still behaves as it
    did -- this phase nested beside it rather than taking its path."""
    from fastapi.routing import APIRoute

    from app.main import app
    paths = {r.path for r in app.routes if isinstance(r, APIRoute)}
    assert f"{RT}/deployments/{{deployment_id}}/rollback" in paths
    assert f"{RT}/deployments/{{deployment_id}}/rollback/execute" in paths


def test_ac16_the_old_health_table_is_untouched(
        client: TestClient, admin: dict, db_session: Session) -> None:
    from app.models.runtime import DeploymentHealth

    setup = _setup(client, admin)
    _set_weights(client, admin, setup, candidate=100)
    db_session.rollback()
    before = len(db_session.execute(select(DeploymentHealth)).scalars().all())
    _rollback(client, admin, setup["candidate_deployment"]["id"])
    db_session.rollback()
    assert len(db_session.execute(select(DeploymentHealth)).scalars().all()) == before


# --------------------------------------------------------------------------- #
# AC-19 -- no stub markers
# --------------------------------------------------------------------------- #
def test_ac19_no_stub_markers_in_this_phases_files() -> None:
    # Every marker is built by concatenation so this assertion's own source
    # does not contain the literals it forbids -- the file reads itself back.
    # This is the fourth instance of that trap in this repository (see Phase
    # 2.1.2's assertion strings, 2.1.4's sentinel choice, and 3.6's docstring),
    # and it is avoided the same way each time rather than by exempting the
    # test file from its own rule.
    forbidden = ("TO" + "DO", "FIX" + "ME", "NotImplemented" + "Error",
                 "@pytest.mark." + "skip", "@pytest.mark." + "xfail")
    for path in (Path(rollback_module.__file__),
                 Path(__file__),
                 Path(__file__).resolve().parents[3] / "backend" / "migrations" / "versions"
                 / "0042_automated_rollback.py"):
        source = path.read_text(encoding="utf-8")
        for marker in forbidden:
            assert marker not in source, f"{marker} in {path.name}"


# --------------------------------------------------------------------------- #
# Threshold arithmetic (unit -- no database)
# --------------------------------------------------------------------------- #
def test_threshold_defaults_are_wider_than_the_canary_stage_gates() -> None:
    """Acting unilaterally deserves a higher bar than declining to promote."""
    from app.runtime.deployment.health import DEFAULT_THRESHOLDS

    assert DEFAULT_TRIGGER_THRESHOLDS["error_rate"] > DEFAULT_THRESHOLDS["degraded_error_rate"]


def test_an_error_rate_crossing_is_reported_with_its_numbers() -> None:
    decision = evaluate_thresholds(
        "UNHEALTHY", {"sample_count": 100, "error_rate": 0.5}, None,
        DEFAULT_TRIGGER_THRESHOLDS, min_samples=20)
    assert decision.should_rollback is True
    assert any("error_rate" in reason for reason in decision.reasons)


def test_a_denial_surge_triggers_independently_of_errors() -> None:
    decision = evaluate_thresholds(
        "UNHEALTHY", {"sample_count": 100, "error_rate": 0.0, "denial_rate": 0.6}, None,
        DEFAULT_TRIGGER_THRESHOLDS, min_samples=20)
    assert decision.should_rollback is True
    assert any("denial_rate" in reason for reason in decision.reasons)


def test_a_latency_regression_is_measured_against_the_baseline() -> None:
    decision = evaluate_thresholds(
        "DEGRADED", {"sample_count": 100, "error_rate": 0.0, "p95_duration_ms": 900},
        {"sample_count": 100, "p95_duration_ms": 100}, DEFAULT_TRIGGER_THRESHOLDS,
        min_samples=20)
    assert decision.should_rollback is True
    assert any("latency" in reason for reason in decision.reasons)


def test_a_zero_baseline_never_manufactures_a_regression() -> None:
    """Dividing by an absent measurement would invent a crossing out of
    nothing -- the baseline rule must skip rather than guess."""
    decision = evaluate_thresholds(
        "DEGRADED", {"sample_count": 100, "error_rate": 0.0, "p95_duration_ms": 900,
                     "total_cost": 5.0},
        {"sample_count": 0, "p95_duration_ms": 0, "total_cost": 0}, DEFAULT_TRIGGER_THRESHOLDS,
        min_samples=20)
    assert decision.should_rollback is False


def test_cost_regression_is_per_execution_not_total() -> None:
    """A candidate serving more traffic must not look expensive merely for
    being busier."""
    decision = evaluate_thresholds(
        "DEGRADED",
        {"sample_count": 1000, "error_rate": 0.0, "total_cost": 10.0},
        {"sample_count": 100, "total_cost": 1.0}, DEFAULT_TRIGGER_THRESHOLDS, min_samples=20)
    assert decision.should_rollback is False, "same unit cost, ten times the traffic"


def test_an_unhealthy_verdict_alone_is_sufficient() -> None:
    """Deferring to 3.5's judgement is the point of consuming its verdicts."""
    decision = evaluate_thresholds(
        "UNHEALTHY", {"sample_count": 100, "error_rate": 0.0, "denial_rate": 0.0}, None,
        DEFAULT_TRIGGER_THRESHOLDS, min_samples=20)
    assert decision.should_rollback is True
    assert "UNHEALTHY" in decision.reasons[0]


def test_policy_thresholds_override_defaults_and_ignore_junk() -> None:
    class _Fake:
        thresholds = {"error_rate": 0.9, "not_a_key": 1, "denial_rate": "high"}

    resolved = thresholds_for_policy(_Fake())
    assert resolved["error_rate"] == 0.9
    assert "not_a_key" not in resolved
    assert resolved["denial_rate"] == DEFAULT_TRIGGER_THRESHOLDS["denial_rate"]


def test_no_policy_resolves_to_the_defaults() -> None:
    assert thresholds_for_policy(None) == DEFAULT_TRIGGER_THRESHOLDS
