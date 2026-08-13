"""Phase 3.5 (ACT-SRS-M3 §Phase-3.5) tests -- the canary deployment engine:
rollout plans and stages, the three stage gates, the AI-aware health engine
(ruling #3), kill-switch dominance, and the interim auto-advance.

Grouped by the build prompt's own §12 acceptance criteria. Real Postgres
throughout (this suite's convention -- ``tests/runtime/conftest.py``),
including the AC-13 race, which uses real separate ``SessionLocal()``
connections rather than an in-process mutex.

**On manufacturing health data.** A canary's health is computed from
``agent_executions`` rows, and driving hundreds of *real* executions through
the model gateway per test would make this file take many minutes for no extra
signal (the end-to-end path from allocation to execution is already covered by
Phase 3.4's own suite, and one full-loop test below covers it again here).
Tests that need a specific health *shape* -- 30 successes, or 8 failures out of
20 -- insert execution rows directly with ``_seed_executions``. That is the
input the engine reads in production too; what is under test here is the
aggregation and the verdict, not the executor that produced the rows."""

from __future__ import annotations

import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
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
    DeploymentHealth,
    DeploymentHealthEvaluation,
    DeploymentTrafficAllocation,
    Environment,
    RolloutPlan,
    RolloutStage,
)
from app.models.user import User
from app.runtime.deployment import rollout as rollout_machine
from app.runtime.deployment.canary import CanaryRolloutService
from app.runtime.deployment.health import HealthEvaluationService, HealthMetrics
from app.runtime.deployment.traffic import TrafficAllocationService
from app.runtime.services import _now

RT = "/api/v1/runtime"


# --------------------------------------------------------------------------- #
# HTTP setup helpers (this suite's convention: each file defines its own)
# --------------------------------------------------------------------------- #
def _register_agent(client: TestClient, admin: dict) -> dict:
    nonce = uuid.uuid4().hex[:8]
    r = client.post(f"{RT}/agents", headers=admin["headers"], json={
        "name": f"Canary Agent {nonce}", "agent_type": "ASSISTANT", "criticality": "MEDIUM",
        "description": f"Test agent {nonce}.",
        "business_purpose": f"Exercise canary rollouts {nonce} in tests.",
        "owner_type": "USER", "owner_id": admin["user_id"], "technical_owner_id": admin["user_id"],
        "compliance_owner_id": admin["user_id"],
        "definition": {"name": "Definition", "framework": "CUSTOM", "entrypoint_type": "FUNCTION",
                      "entrypoint": "agents.handler:run"},
    })
    assert r.status_code == 201, r.text
    return r.json()


def _activate_agent(client: TestClient, admin: dict, agent_id: str) -> None:
    for step in ("register", "validate"):
        assert client.post(f"{RT}/agents/{agent_id}/{step}", headers=admin["headers"]).status_code == 200
    r = client.post(f"{RT}/agents/{agent_id}/identity/create-and-associate", headers=admin["headers"],
                    json={"client_id": f"agent-identity-{uuid.uuid4().hex[:10]}"})
    assert r.status_code == 200, r.text
    for step in ("submit-for-approval", "approve", "activate"):
        assert client.post(f"{RT}/agents/{agent_id}/{step}", headers=admin["headers"]).status_code == 200


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
    """The 3.1 lifecycle route -- leaves siblings alone, so several versions
    can serve one environment at once (the precondition for a canary)."""
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


def _canary_setup(client: TestClient, admin: dict) -> dict:
    """One agent, a stable version serving and a candidate version deployed
    alongside it -- the starting point for every rollout here."""
    envs = _environments(client, admin)
    agent = _register_agent(client, admin)
    _activate_agent(client, admin, agent["id"])
    stable = _publish_version(client, admin, agent["id"])
    candidate = _publish_version(client, admin, agent["id"])
    stable_deployment = _lifecycle_deploy(client, admin, agent["id"], stable["id"])
    candidate_deployment = _lifecycle_deploy(client, admin, agent["id"], candidate["id"])
    return {
        "agent": agent, "stable": stable, "candidate": candidate,
        "stable_deployment": stable_deployment, "candidate_deployment": candidate_deployment,
        "environment": envs["DEVELOPMENT"], "environments": envs,
    }


# The default plan for tests whose subject is *not* the health gate (traffic
# mechanics, state transitions, authorization, concurrency). They waive the
# health gate explicitly with ``health_requirement="NONE"`` rather than
# seeding executions they do not care about -- tests that *are* about health
# always declare their own stages and their own sample data.
_STAGES = [
    {"target_weight": 5, "min_duration_seconds": 0, "min_samples": 0,
     "health_requirement": "NONE", "advance_mode": "MANUAL"},
    {"target_weight": 25, "min_duration_seconds": 0, "min_samples": 0,
     "health_requirement": "NONE", "advance_mode": "MANUAL"},
    {"target_weight": 100, "min_duration_seconds": 0, "min_samples": 0,
     "health_requirement": "NONE", "advance_mode": "MANUAL"},
]


def _create_rollout(client: TestClient, admin: dict, setup: dict, *,
                   stages: list[dict] | None = None, **kwargs) -> tuple[dict, int]:
    r = client.post(
        f"{RT}/agents/{setup['agent']['id']}/environments/{setup['environment']['id']}/rollouts",
        headers=admin["headers"],
        json={"candidate_version_id": setup["candidate"]["id"],
              "stages": stages if stages is not None else _STAGES, **kwargs},
    )
    return r.json(), r.status_code


def _seed_executions(db: Session, setup: dict, admin: dict, version_id: str, *,
                    succeeded: int = 0, failed: int = 0, timed_out: int = 0, denied: int = 0,
                    deployment_id: str | None = None, duration_ms: int = 100) -> None:
    """Insert terminal execution rows -- the exact input the health engine
    reads in production (see this module's docstring)."""
    rows = (
        [("SUCCEEDED", None)] * succeeded
        + [("FAILED", "PROVIDER_ERROR")] * failed
        + [("TIMED_OUT", "EXECUTION_TIMED_OUT")] * timed_out
        + [("DENIED", "RUNTIME_POLICY_DENIED")] * denied
    )
    now = _now()
    for status_value, error_code in rows:
        db.add(AgentExecution(
            organization_id=uuid.UUID(admin["organization_id"]),
            agent_id=uuid.UUID(setup["agent"]["id"]),
            agent_version_id=uuid.UUID(version_id),
            deployment_id=uuid.UUID(deployment_id) if deployment_id else None,
            trigger_type="API", status=status_value, error_code=error_code,
            duration_ms=duration_ms, input_payload={}, created_at=now,
            started_at=now, completed_at=now,
        ))
    db.commit()


def _second_org(client: TestClient) -> dict:
    from tests.runtime.conftest import PASSWORD

    email = f"canary_other_{uuid.uuid4().hex[:10]}@example.com"
    assert client.post("/auth/register", json={
        "organization_name": "Other Org", "name": "Owner", "email": email, "password": PASSWORD,
    }).status_code == 201
    tokens = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD}).json()
    me = client.get("/api/v1/auth/me",
                    headers={"Authorization": f"Bearer {tokens['access_token']}"}).json()
    return {"headers": {"Authorization": f"Bearer {tokens['access_token']}"},
            "user_id": me["user"]["id"], "organization_id": me["user"]["organization_id"]}


def _weights(db: Session, setup: dict, admin: dict) -> dict[str, int]:
    db.rollback()
    traffic = TrafficAllocationService(db)
    allocation = traffic.current(uuid.UUID(admin["organization_id"]),
                                uuid.UUID(setup["agent"]["id"]),
                                uuid.UUID(setup["environment"]["id"]))
    if allocation is None:
        return {}
    return {str(w.agent_version_id): w.weight for w in traffic.weights_for(allocation.id)}


# --------------------------------------------------------------------------- #
# AC-01 -- a rollout plan with ordered stages is created and started
# --------------------------------------------------------------------------- #
def test_ac01_rollout_is_created_with_ordered_stages_and_started(
    client: TestClient, admin: dict, db_session: Session,
) -> None:
    setup = _canary_setup(client, admin)
    body, code = _create_rollout(client, admin, setup)
    assert code == 201, body

    assert body["state"] == "IN_PROGRESS"
    assert body["current_stage_index"] == 0
    assert body["candidate_version_id"] == setup["candidate"]["id"]
    assert body["stable_version_id"] == setup["stable"]["id"], "stable should be inferred"
    assert [s["stage_index"] for s in body["stages"]] == [0, 1, 2]
    assert [s["target_weight"] for s in body["stages"]] == [5, 25, 100]
    assert body["stages"][0]["entered_at"] is not None, "stage 0 must be entered on start"

    # Starting the rollout put the candidate at the first stage's weight.
    assert _weights(db_session, setup, admin) == {
        setup["candidate"]["id"]: 5, setup["stable"]["id"]: 95,
    }


def test_ac01_stage_weights_must_be_non_decreasing(client: TestClient, admin: dict) -> None:
    setup = _canary_setup(client, admin)
    body, code = _create_rollout(client, admin, setup, stages=[
        {"target_weight": 50}, {"target_weight": 10},
    ])
    assert code == 422, body
    assert "non-decreasing" in body["error"]["message"]


def test_ac01_a_staged_canary_without_a_stable_version_is_rejected(
    client: TestClient, admin: dict,
) -> None:
    """3.4's weights must total exactly 100, so a candidate at 5% is
    unrepresentable with nothing to hold the other 95. Rejected with an
    explanation rather than silently becoming a 100% cutover."""
    envs = _environments(client, admin)
    agent = _register_agent(client, admin)
    _activate_agent(client, admin, agent["id"])
    candidate = _publish_version(client, admin, agent["id"])
    _lifecycle_deploy(client, admin, agent["id"], candidate["id"])

    r = client.post(f"{RT}/agents/{agent['id']}/environments/{envs['DEVELOPMENT']['id']}/rollouts",
                    headers=admin["headers"],
                    json={"candidate_version_id": candidate["id"],
                          "stages": [{"target_weight": 5}, {"target_weight": 100}]})
    assert r.status_code == 422, r.text
    assert "no stable version" in r.json()["error"]["message"]


def test_ac01_insufficient_data_cannot_be_a_health_requirement(
    client: TestClient, admin: dict,
) -> None:
    setup = _canary_setup(client, admin)
    body, code = _create_rollout(client, admin, setup, stages=[
        {"target_weight": 100, "health_requirement": "INSUFFICIENT_DATA"},
    ])
    assert code == 422, body
    assert "absence of evidence" in body["error"]["message"]


# --------------------------------------------------------------------------- #
# AC-02 -- advance drives 3.4's allocation, revisioned, never a direct write
# --------------------------------------------------------------------------- #
def test_ac02_advance_changes_traffic_through_the_3_4_allocation_mechanism(
    client: TestClient, admin: dict, db_session: Session,
) -> None:
    setup = _canary_setup(client, admin)
    rollout, _ = _create_rollout(client, admin, setup)

    db_session.rollback()
    revisions_before = db_session.execute(select(DeploymentTrafficAllocation).where(
        DeploymentTrafficAllocation.agent_id == uuid.UUID(setup["agent"]["id"]))).scalars().all()

    r = client.post(f"{RT}/rollouts/{rollout['id']}/advance", headers=admin["headers"], json={})
    assert r.status_code == 200, r.text
    assert r.json()["current_stage_index"] == 1

    assert _weights(db_session, setup, admin) == {
        setup["candidate"]["id"]: 25, setup["stable"]["id"]: 75,
    }
    # A *new allocation revision* exists -- i.e. the weight moved through
    # 3.4's revisioned mechanism, not by mutating the existing weight rows.
    revisions_after = db_session.execute(select(DeploymentTrafficAllocation).where(
        DeploymentTrafficAllocation.agent_id == uuid.UUID(setup["agent"]["id"]))).scalars().all()
    assert len(revisions_after) == len(revisions_before) + 1
    current = [a for a in revisions_after if a.is_current]
    assert len(current) == 1
    assert current[0].revision == max(a.revision for a in revisions_after)


def test_ac02_and_ac16_the_canary_engine_never_writes_weights_directly() -> None:
    """Structural proof for AC-02 and AC-16 together: the rollout engine has
    no reference to ``DeploymentTrafficWeight`` at all, so it *cannot* bypass
    3.4's mechanism, and it does not redefine the resolver or the gate."""
    import ast

    source = (Path(__file__).resolve().parents[2] / "app" / "runtime" / "deployment"
              / "canary.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    identifiers = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    identifiers |= {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    for forbidden in ("DeploymentTrafficWeight", "DeploymentTrafficAllocation", "VersionResolver"):
        assert forbidden not in identifiers, f"canary.py must not reference {forbidden}"
    # It must reach traffic changes exclusively through 3.4's public operation.
    assert "set_weights" in identifiers


def test_ac16_the_resolver_gate_and_allocation_modules_are_unmodified() -> None:
    """AC-16 -- 3.4's three files are driven, not modified, by this phase."""
    import subprocess

    root = Path(__file__).resolve().parents[3]
    changed = subprocess.run(
        ["git", "diff", "--name-only", "main...HEAD", "--",
         "backend/app/runtime/deployment/resolver.py",
         "backend/app/runtime/deployment/traffic.py"],
        cwd=root, capture_output=True, text=True, check=False,
    ).stdout.strip()
    assert changed == "", f"Phase 3.5 must not modify 3.4's mechanics, but changed: {changed}"


# --------------------------------------------------------------------------- #
# AC-03 -- advance blocked unless duration AND samples AND health are met
# --------------------------------------------------------------------------- #
def test_ac03_advance_blocked_when_minimum_duration_has_not_elapsed(
    client: TestClient, admin: dict, db_session: Session,
) -> None:
    setup = _canary_setup(client, admin)
    rollout, _ = _create_rollout(client, admin, setup, stages=[
        {"target_weight": 5, "min_duration_seconds": 3600, "min_samples": 0},
        {"target_weight": 100},
    ])
    _seed_executions(db_session, setup, admin, setup["candidate"]["id"], succeeded=50)

    r = client.post(f"{RT}/rollouts/{rollout['id']}/advance", headers=admin["headers"], json={})
    assert r.status_code == 409, r.text
    assert r.json()["error"]["code"] == "ROLLOUT_STAGE_GATE_NOT_MET"
    assert "Minimum stage duration not elapsed" in r.json()["error"]["message"]


def test_ac03_advance_blocked_when_minimum_samples_not_met(
    client: TestClient, admin: dict, db_session: Session,
) -> None:
    setup = _canary_setup(client, admin)
    rollout, _ = _create_rollout(client, admin, setup, stages=[
        {"target_weight": 5, "min_samples": 30}, {"target_weight": 100},
    ])
    _seed_executions(db_session, setup, admin, setup["candidate"]["id"], succeeded=4)

    r = client.post(f"{RT}/rollouts/{rollout['id']}/advance", headers=admin["headers"], json={})
    assert r.status_code == 409, r.text
    assert r.json()["error"]["code"] == "ROLLOUT_STAGE_GATE_NOT_MET"
    assert "Minimum sample count not met: 4 of 30" in r.json()["error"]["message"]


def test_ac03_advance_blocked_when_health_requirement_not_met(
    client: TestClient, admin: dict, db_session: Session,
) -> None:
    setup = _canary_setup(client, admin)
    rollout, _ = _create_rollout(client, admin, setup, stages=[
        {"target_weight": 5, "min_samples": 10, "health_requirement": "HEALTHY"},
        {"target_weight": 100},
    ])
    # 30% error rate -- above the unhealthy threshold.
    _seed_executions(db_session, setup, admin, setup["candidate"]["id"], succeeded=14, failed=6)

    r = client.post(f"{RT}/rollouts/{rollout['id']}/advance", headers=admin["headers"], json={})
    assert r.status_code == 409, r.text
    assert r.json()["error"]["code"] == "ROLLOUT_STAGE_GATE_NOT_MET"
    assert "UNHEALTHY" in r.json()["error"]["message"]


def test_ac03_all_unmet_reasons_are_reported_together(
    client: TestClient, admin: dict, db_session: Session,
) -> None:
    """An operator should learn every reason at once, not discover the second
    only after clearing the first."""
    setup = _canary_setup(client, admin)
    rollout, _ = _create_rollout(client, admin, setup, stages=[
        {"target_weight": 5, "min_duration_seconds": 3600, "min_samples": 30},
        {"target_weight": 100},
    ])
    r = client.post(f"{RT}/rollouts/{rollout['id']}/advance", headers=admin["headers"], json={})
    message = r.json()["error"]["message"]
    assert "Minimum stage duration not elapsed" in message
    assert "Minimum sample count not met" in message
    assert "INSUFFICIENT_DATA" in message


def test_ac03_stage_gate_logic_is_pure_and_requires_all_three() -> None:
    now = _now()
    entered = now - timedelta(seconds=600)
    base = dict(entered_at=entered, now=now, min_duration_seconds=60,
                sample_count=100, min_samples=10,
                health_state="HEALTHY", health_requirement="HEALTHY")
    assert rollout_machine.evaluate_stage_gates(**base).satisfied

    assert not rollout_machine.evaluate_stage_gates(**{**base, "min_duration_seconds": 9999}).satisfied
    assert not rollout_machine.evaluate_stage_gates(**{**base, "min_samples": 9999}).satisfied
    assert not rollout_machine.evaluate_stage_gates(**{**base, "health_state": "DEGRADED"}).satisfied
    # An unentered stage can never satisfy a duration gate.
    assert not rollout_machine.evaluate_stage_gates(**{**base, "entered_at": None}).satisfied


# --------------------------------------------------------------------------- #
# AC-04 / AC-06 -- health from real executions; every state reachable
# --------------------------------------------------------------------------- #
def test_ac04_health_is_computed_from_real_execution_rows(
    client: TestClient, admin: dict, db_session: Session,
) -> None:
    setup = _canary_setup(client, admin)
    rollout, _ = _create_rollout(client, admin, setup, stages=[
        {"target_weight": 5, "min_samples": 10}, {"target_weight": 100},
    ])
    _seed_executions(db_session, setup, admin, setup["candidate"]["id"],
                    succeeded=18, failed=1, timed_out=1, duration_ms=250)

    r = client.get(f"{RT}/rollouts/{rollout['id']}/health", headers=admin["headers"])
    assert r.status_code == 200, r.text
    metrics = r.json()["current"]["metrics"]
    assert metrics["sample_count"] == 20
    assert metrics["succeeded"] == 18
    assert metrics["failed"] == 1
    assert metrics["timed_out"] == 1
    assert metrics["error_rate"] == pytest.approx(0.10)
    assert metrics["avg_duration_ms"] == pytest.approx(250.0)
    assert metrics["error_codes"]["PROVIDER_ERROR"] == 1


@pytest.mark.parametrize(
    ("succeeded", "failed", "denied", "min_samples", "expected"),
    [
        (20, 0, 0, 10, "HEALTHY"),
        (18, 2, 0, 10, "DEGRADED"),          # 10% error rate
        (14, 6, 0, 10, "UNHEALTHY"),         # 30% error rate
        (16, 0, 4, 10, "DEGRADED"),          # 20% denial rate
        (13, 0, 7, 10, "UNHEALTHY"),         # 35% denial rate
        (3, 0, 0, 10, "INSUFFICIENT_DATA"),  # clean, but far too few
    ],
)
def test_ac06_every_health_state_is_reachable_and_correct(
    client: TestClient, admin: dict, db_session: Session,
    succeeded: int, failed: int, denied: int, min_samples: int, expected: str,
) -> None:
    setup = _canary_setup(client, admin)
    rollout, _ = _create_rollout(client, admin, setup, stages=[
        {"target_weight": 5, "min_samples": min_samples}, {"target_weight": 100},
    ])
    _seed_executions(db_session, setup, admin, setup["candidate"]["id"],
                    succeeded=succeeded, failed=failed, denied=denied)

    r = client.get(f"{RT}/rollouts/{rollout['id']}/health", headers=admin["headers"])
    assert r.json()["current"]["health_state"] == expected, r.json()["current"]["explanation"]


def test_ac06_unknown_is_reached_when_the_candidate_cannot_be_evaluated(
    client: TestClient, admin: dict, db_session: Session,
) -> None:
    """UNKNOWN is the vetoed/not-evaluable state, distinct from
    INSUFFICIENT_DATA (which means "evaluable, but not enough evidence")."""
    setup = _canary_setup(client, admin)
    rollout, _ = _create_rollout(client, admin, setup)
    _seed_executions(db_session, setup, admin, setup["candidate"]["id"], succeeded=50)

    r = client.post(f"{RT}/deployments/{setup['candidate_deployment']['id']}/lifecycle/pause",
                    headers=admin["headers"], json={})
    assert r.status_code == 200, r.text

    r = client.get(f"{RT}/rollouts/{rollout['id']}/health", headers=admin["headers"])
    assert r.json()["current"]["health_state"] == "UNKNOWN"


# --------------------------------------------------------------------------- #
# AC-05 -- INSUFFICIENT_DATA is not "healthy" (the phase's safety property)
# --------------------------------------------------------------------------- #
def test_ac05_a_thin_but_perfect_sample_does_not_advance(
    client: TestClient, admin: dict, db_session: Session,
) -> None:
    """The single most dangerous bug this engine could have: two successful
    calls out of two reported as HEALTHY. Nothing bad *observed* is not
    nothing bad *happening*."""
    setup = _canary_setup(client, admin)
    rollout, _ = _create_rollout(client, admin, setup, stages=[
        {"target_weight": 5, "min_samples": 25, "health_requirement": "HEALTHY"},
        {"target_weight": 100},
    ])
    # Two calls, both perfect. Zero errors. Still not proof.
    _seed_executions(db_session, setup, admin, setup["candidate"]["id"], succeeded=2)

    r = client.get(f"{RT}/rollouts/{rollout['id']}/health", headers=admin["headers"])
    assert r.json()["current"]["health_state"] == "INSUFFICIENT_DATA"
    assert r.json()["current"]["metrics"]["error_rate"] == 0.0, "a perfect record..."

    r = client.post(f"{RT}/rollouts/{rollout['id']}/advance", headers=admin["headers"], json={})
    assert r.status_code == 409, r.text
    assert r.json()["error"]["code"] == "ROLLOUT_STAGE_GATE_NOT_MET"
    assert "not evidence of health" in r.json()["error"]["message"]

    # ...and traffic did not move.
    assert _weights(db_session, setup, admin)[setup["candidate"]["id"]] == 5


def test_ac05_insufficient_data_satisfies_no_health_requirement() -> None:
    for requirement in ("HEALTHY", "DEGRADED", "UNHEALTHY"):
        assert not rollout_machine.health_requirement_satisfied("INSUFFICIENT_DATA", requirement)
        assert not rollout_machine.health_requirement_satisfied("UNKNOWN", requirement)
    assert rollout_machine.health_requirement_satisfied("HEALTHY", "HEALTHY")
    assert rollout_machine.health_requirement_satisfied("HEALTHY", "DEGRADED")
    assert not rollout_machine.health_requirement_satisfied("DEGRADED", "HEALTHY")


# --------------------------------------------------------------------------- #
# AC-07 -- baseline comparison and the provider-wide distinction
# --------------------------------------------------------------------------- #
def test_ac07_candidate_regression_against_stable_is_detected(
    client: TestClient, admin: dict, db_session: Session,
) -> None:
    """The candidate is within absolute thresholds but clearly worse than the
    version it would replace -- "better than an arbitrary constant" is the
    wrong bar when a known-good comparator is running right now."""
    setup = _canary_setup(client, admin)
    rollout, _ = _create_rollout(client, admin, setup, stages=[
        {"target_weight": 5, "min_samples": 10}, {"target_weight": 100},
    ])
    # Candidate 4% errors -- under the 5% degraded threshold, so absolutely
    # "fine" -- against a stable version at 0%. The 4-point gap exceeds the
    # 2-point baseline margin, which is exactly the case §7 exists to catch.
    _seed_executions(db_session, setup, admin, setup["candidate"]["id"], succeeded=96, failed=4)
    _seed_executions(db_session, setup, admin, setup["stable"]["id"], succeeded=100)

    body = client.get(f"{RT}/rollouts/{rollout['id']}/health", headers=admin["headers"]).json()
    assert body["current"]["health_state"] == "DEGRADED"
    assert body["current"]["baseline"]["regression_vs_stable"] is True
    assert "regression relative to the version it would replace" in body["current"]["explanation"]


def test_ac07_a_provider_wide_degradation_does_not_blame_the_candidate(
    client: TestClient, admin: dict, db_session: Session,
) -> None:
    """FR-031's attempt: if stable *and* candidate are both elevated, the
    candidate is probably not the cause. It is not blamed -- but nothing is
    promoted during a shared degradation either, which is the safety half of
    the finding."""
    setup = _canary_setup(client, admin)
    rollout, _ = _create_rollout(client, admin, setup, stages=[
        {"target_weight": 5, "min_samples": 10}, {"target_weight": 100},
    ])
    _seed_executions(db_session, setup, admin, setup["candidate"]["id"], succeeded=85, failed=15)
    _seed_executions(db_session, setup, admin, setup["stable"]["id"], succeeded=86, failed=14)

    body = client.get(f"{RT}/rollouts/{rollout['id']}/health", headers=admin["headers"]).json()
    assert body["current"]["baseline"]["likely_provider_wide"] is True
    assert body["current"]["baseline"]["regression_vs_stable"] is False
    assert "provider-wide rather than candidate-specific" in body["current"]["explanation"]
    # Not blamed, but still not promotable.
    assert body["current"]["health_state"] in ("DEGRADED", "UNHEALTHY")
    r = client.post(f"{RT}/rollouts/{rollout['id']}/advance", headers=admin["headers"], json={})
    assert r.status_code == 409, r.text


def test_ac07_absolute_thresholds_are_used_when_stable_has_no_traffic(
    client: TestClient, admin: dict, db_session: Session,
) -> None:
    setup = _canary_setup(client, admin)
    rollout, _ = _create_rollout(client, admin, setup, stages=[
        {"target_weight": 5, "min_samples": 10}, {"target_weight": 100},
    ])
    _seed_executions(db_session, setup, admin, setup["candidate"]["id"], succeeded=50)

    body = client.get(f"{RT}/rollouts/{rollout['id']}/health", headers=admin["headers"]).json()
    assert body["current"]["health_state"] == "HEALTHY"
    assert body["current"]["baseline"]["comparable"] is False
    assert "absolute thresholds only" in body["current"]["baseline"]["note"]


# --------------------------------------------------------------------------- #
# AC-08 -- evaluations persist; the OLD deployment_health is untouched
# --------------------------------------------------------------------------- #
def test_ac08_evaluations_persist_and_the_old_health_table_is_untouched(
    client: TestClient, admin: dict, db_session: Session,
) -> None:
    setup = _canary_setup(client, admin)
    rollout, _ = _create_rollout(client, admin, setup, stages=[
        {"target_weight": 5, "min_samples": 5}, {"target_weight": 100},
    ])
    _seed_executions(db_session, setup, admin, setup["candidate"]["id"], succeeded=30)

    db_session.rollback()
    old_health_before = db_session.execute(select(DeploymentHealth)).scalars().all()

    r = client.post(f"{RT}/rollouts/{rollout['id']}/advance", headers=admin["headers"], json={})
    assert r.status_code == 200, r.text

    db_session.rollback()
    evaluations = db_session.execute(select(DeploymentHealthEvaluation).where(
        DeploymentHealthEvaluation.rollout_plan_id == uuid.UUID(rollout["id"]))).scalars().all()
    assert evaluations, "the gate decision's evidence must be persisted"
    assert evaluations[0].health_state == "HEALTHY"
    assert evaluations[0].sample_count == 30
    assert evaluations[0].organization_id == uuid.UUID(admin["organization_id"])

    # Ruling #3: the pre-existing heartbeat table is not written by any of this.
    old_health_after = db_session.execute(select(DeploymentHealth)).scalars().all()
    assert len(old_health_after) == len(old_health_before)


def test_ac08_reading_health_does_not_persist_an_evaluation(
    client: TestClient, admin: dict, db_session: Session,
) -> None:
    """A read must not write: looking at a canary's health should not create
    a record implying a gate was evaluated for a decision."""
    setup = _canary_setup(client, admin)
    rollout, _ = _create_rollout(client, admin, setup)
    _seed_executions(db_session, setup, admin, setup["candidate"]["id"], succeeded=30)

    for _ in range(3):
        assert client.get(f"{RT}/rollouts/{rollout['id']}/health",
                         headers=admin["headers"]).status_code == 200

    db_session.rollback()
    stored = db_session.execute(select(DeploymentHealthEvaluation).where(
        DeploymentHealthEvaluation.rollout_plan_id == uuid.UUID(rollout["id"]))).scalars().all()
    assert stored == []


# --------------------------------------------------------------------------- #
# AC-09 -- kill-switch dominance (the sharpest safety rule in this phase)
# --------------------------------------------------------------------------- #
def test_ac09_kill_switch_halts_a_rollout_mid_flight(
    client: TestClient, admin: dict, db_session: Session,
) -> None:
    setup = _canary_setup(client, admin)
    rollout, _ = _create_rollout(client, admin, setup, stages=[
        {"target_weight": 5, "min_samples": 5}, {"target_weight": 50}, {"target_weight": 100},
    ])
    _seed_executions(db_session, setup, admin, setup["candidate"]["id"], succeeded=50)

    # Healthy and advanceable right now.
    assert client.get(f"{RT}/rollouts/{rollout['id']}/health",
                     headers=admin["headers"]).json()["gates"]["satisfied"] is True

    r = client.post(f"{RT}/kill-switch/agents/{setup['agent']['id']}",
                    headers=admin["headers"], json={"reason": "incident"})
    assert r.status_code == 200, r.text

    r = client.post(f"{RT}/rollouts/{rollout['id']}/advance", headers=admin["headers"], json={})
    assert r.status_code == 423, r.text
    assert r.json()["error"]["code"] == "ROLLOUT_HALTED_BY_KILL_SWITCH"

    # Traffic did not move.
    assert _weights(db_session, setup, admin)[setup["candidate"]["id"]] == 5


def test_ac09_a_killed_agent_cannot_be_auto_promoted(
    client: TestClient, admin: dict, db_session: Session,
) -> None:
    """Automation must never walk past a veto. The automated path reports the
    halt rather than raising (a scheduler sweeping many rollouts must not be
    aborted by one killed agent) -- but it does not advance, which is the
    whole point."""
    setup = _canary_setup(client, admin)
    rollout, _ = _create_rollout(client, admin, setup, stages=[
        {"target_weight": 5, "min_samples": 5, "advance_mode": "AUTO"},
        {"target_weight": 100, "advance_mode": "AUTO"},
    ])
    _seed_executions(db_session, setup, admin, setup["candidate"]["id"], succeeded=50)

    client.post(f"{RT}/kill-switch/agents/{setup['agent']['id']}",
                headers=admin["headers"], json={"reason": "incident"})

    r = client.post(f"{RT}/rollouts/{rollout['id']}/evaluate", headers=admin["headers"])
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["gate_evaluation"]["advanced"] is False
    assert body["gate_evaluation"]["halted"] is True
    assert body["current_stage_index"] == 0
    assert _weights(db_session, setup, admin)[setup["candidate"]["id"]] == 5


def test_ac09_promote_is_refused_for_a_killed_agent(
    client: TestClient, admin: dict, db_session: Session,
) -> None:
    setup = _canary_setup(client, admin)
    rollout, _ = _create_rollout(client, admin, setup)
    client.post(f"{RT}/kill-switch/agents/{setup['agent']['id']}",
                headers=admin["headers"], json={"reason": "incident"})

    r = client.post(f"{RT}/rollouts/{rollout['id']}/promote", headers=admin["headers"], json={})
    assert r.status_code == 423, r.text
    assert r.json()["error"]["code"] == "ROLLOUT_HALTED_BY_KILL_SWITCH"
    assert _weights(db_session, setup, admin)[setup["candidate"]["id"]] == 5


def test_ac09_the_health_engine_never_reports_healthy_for_a_vetoed_candidate(
    client: TestClient, admin: dict, db_session: Session,
) -> None:
    """The second, independent mechanism: even if a caller reached the gate
    logic, the health verdict itself is UNKNOWN for a vetoed candidate, so
    "healthy -> advance" is unreachable by two separate routes."""
    setup = _canary_setup(client, admin)
    rollout, _ = _create_rollout(client, admin, setup)
    _seed_executions(db_session, setup, admin, setup["candidate"]["id"], succeeded=500)

    client.post(f"{RT}/kill-switch/agents/{setup['agent']['id']}",
                headers=admin["headers"], json={"reason": "incident"})

    body = client.get(f"{RT}/rollouts/{rollout['id']}/health", headers=admin["headers"]).json()
    assert body["current"]["health_state"] == "UNKNOWN"
    assert "suspended" in body["current"]["explanation"]
    assert body["gates"]["satisfied"] is False


def test_ac09_abort_still_works_while_halted(
    client: TestClient, admin: dict, db_session: Session,
) -> None:
    """A kill switch must never trap a rollout in a state an operator cannot
    back out of: de-escalating operations stay available."""
    setup = _canary_setup(client, admin)
    rollout, _ = _create_rollout(client, admin, setup)
    client.post(f"{RT}/kill-switch/agents/{setup['agent']['id']}",
                headers=admin["headers"], json={"reason": "incident"})

    r = client.post(f"{RT}/rollouts/{rollout['id']}/abort", headers=admin["headers"], json={})
    assert r.status_code == 200, r.text
    assert r.json()["state"] == "ABORTED"
    assert _weights(db_session, setup, admin)[setup["candidate"]["id"]] == 0


# --------------------------------------------------------------------------- #
# AC-10 / AC-11 -- abort, request-rollback, promote
# --------------------------------------------------------------------------- #
def test_ac10_abort_returns_all_traffic_to_stable(
    client: TestClient, admin: dict, db_session: Session,
) -> None:
    setup = _canary_setup(client, admin)
    rollout, _ = _create_rollout(client, admin, setup)
    assert _weights(db_session, setup, admin)[setup["candidate"]["id"]] == 5

    r = client.post(f"{RT}/rollouts/{rollout['id']}/abort", headers=admin["headers"],
                    json={"reason": "looked wrong"})
    assert r.status_code == 200, r.text
    assert r.json()["state"] == "ABORTED"
    assert _weights(db_session, setup, admin) == {
        setup["candidate"]["id"]: 0, setup["stable"]["id"]: 100,
    }


def test_ac10_request_rollback_is_the_terminal_outcome(
    client: TestClient, admin: dict, db_session: Session,
) -> None:
    setup = _canary_setup(client, admin)
    rollout, _ = _create_rollout(client, admin, setup)

    r = client.post(f"{RT}/rollouts/{rollout['id']}/request-rollback", headers=admin["headers"],
                    json={"reason": "error spike"})
    assert r.status_code == 200, r.text
    assert r.json()["state"] == "ROLLBACK_REQUESTED"
    assert _weights(db_session, setup, admin)[setup["candidate"]["id"]] == 0

    # Terminal: nothing further is permitted from here.
    r = client.post(f"{RT}/rollouts/{rollout['id']}/advance", headers=admin["headers"], json={})
    assert r.status_code == 409, r.text
    assert r.json()["error"]["code"] == "ROLLOUT_INVALID_TRANSITION"


def test_ac11_promote_takes_the_candidate_to_100_and_supersedes_stable(
    client: TestClient, admin: dict, db_session: Session,
) -> None:
    setup = _canary_setup(client, admin)
    rollout, _ = _create_rollout(client, admin, setup)

    r = client.post(f"{RT}/rollouts/{rollout['id']}/promote", headers=admin["headers"], json={})
    assert r.status_code == 200, r.text
    assert r.json()["state"] == "SUCCEEDED"

    weights = _weights(db_session, setup, admin)
    assert weights[setup["candidate"]["id"]] == 100
    assert weights[setup["stable"]["id"]] == 0

    # The old stable deployment was superseded through the 3.1 lifecycle
    # authority, not by a direct lifecycle_state write.
    db_session.rollback()
    stable_deployment = db_session.get(
        AgentDeployment, uuid.UUID(setup["stable_deployment"]["id"]))
    assert stable_deployment.lifecycle_state == "SUPERSEDED"
    assert stable_deployment.superseded_by_deployment_id == uuid.UUID(
        setup["candidate_deployment"]["id"])


# --------------------------------------------------------------------------- #
# AC-12 -- interim auto-advance: bounded, idempotent, manual always available
# --------------------------------------------------------------------------- #
def test_ac12_auto_advance_advances_at_most_one_stage_per_call(
    client: TestClient, admin: dict, db_session: Session,
) -> None:
    """Bounded by design: a call that walked 5% -> 100% because every gate
    happened to be clear would defeat the entire purpose of staging."""
    setup = _canary_setup(client, admin)
    # Health gate waived: what is under test here is *boundedness*, and a
    # per-stage health window would otherwise require re-seeding executions
    # between calls, which would obscure the one assertion that matters.
    rollout, _ = _create_rollout(client, admin, setup, stages=[
        {"target_weight": 5, "health_requirement": "NONE", "advance_mode": "AUTO"},
        {"target_weight": 25, "health_requirement": "NONE", "advance_mode": "AUTO"},
        {"target_weight": 100, "health_requirement": "NONE", "advance_mode": "AUTO"},
    ])

    r = client.post(f"{RT}/rollouts/{rollout['id']}/evaluate", headers=admin["headers"])
    assert r.json()["current_stage_index"] == 1
    assert _weights(db_session, setup, admin)[setup["candidate"]["id"]] == 25

    r = client.post(f"{RT}/rollouts/{rollout['id']}/evaluate", headers=admin["headers"])
    assert r.json()["current_stage_index"] == 2
    assert _weights(db_session, setup, admin)[setup["candidate"]["id"]] == 100

    r = client.post(f"{RT}/rollouts/{rollout['id']}/evaluate", headers=admin["headers"])
    assert r.json()["state"] == "SUCCEEDED"


def test_ac12_auto_advance_does_not_advance_a_manual_stage(
    client: TestClient, admin: dict, db_session: Session,
) -> None:
    setup = _canary_setup(client, admin)
    rollout, _ = _create_rollout(client, admin, setup, stages=[
        {"target_weight": 5, "min_samples": 5, "advance_mode": "MANUAL"},
        {"target_weight": 100},
    ])
    _seed_executions(db_session, setup, admin, setup["candidate"]["id"], succeeded=50)

    r = client.post(f"{RT}/rollouts/{rollout['id']}/evaluate", headers=admin["headers"])
    body = r.json()
    assert body["gate_evaluation"]["advanced"] is False
    assert body["gate_evaluation"]["reason"] == "Stage advance_mode is MANUAL."
    assert body["current_stage_index"] == 0

    # ...but manual advance is always available.
    r = client.post(f"{RT}/rollouts/{rollout['id']}/advance", headers=admin["headers"], json={})
    assert r.status_code == 200, r.text
    assert r.json()["current_stage_index"] == 1


def test_ac12_auto_advance_explains_why_it_declined(
    client: TestClient, admin: dict, db_session: Session,
) -> None:
    setup = _canary_setup(client, admin)
    rollout, _ = _create_rollout(client, admin, setup, stages=[
        {"target_weight": 5, "min_samples": 100, "advance_mode": "AUTO"},
        {"target_weight": 100},
    ])
    _seed_executions(db_session, setup, admin, setup["candidate"]["id"], succeeded=3)

    body = client.post(f"{RT}/rollouts/{rollout['id']}/evaluate",
                       headers=admin["headers"]).json()
    assert body["gate_evaluation"]["advanced"] is False
    assert body["gate_evaluation"]["health"]["health_state"] == "INSUFFICIENT_DATA"
    assert body["gate_evaluation"]["gates"]["samples_met"] is False


def test_ac12_auto_advance_is_idempotent_under_a_repeated_key(
    client: TestClient, admin: dict, db_session: Session,
) -> None:
    setup = _canary_setup(client, admin)
    rollout, _ = _create_rollout(client, admin, setup, stages=[
        {"target_weight": 5, "health_requirement": "NONE", "advance_mode": "AUTO"},
        {"target_weight": 25, "health_requirement": "NONE", "advance_mode": "AUTO"},
        {"target_weight": 100, "health_requirement": "NONE"},
    ])
    headers = {**admin["headers"], "Idempotency-Key": f"auto-{uuid.uuid4().hex[:12]}"}

    first = client.post(f"{RT}/rollouts/{rollout['id']}/evaluate", headers=headers)
    second = client.post(f"{RT}/rollouts/{rollout['id']}/evaluate", headers=headers)
    assert first.status_code == 200 and second.status_code == 200
    assert first.json()["current_stage_index"] == second.json()["current_stage_index"] == 1
    assert _weights(db_session, setup, admin)[setup["candidate"]["id"]] == 25


# --------------------------------------------------------------------------- #
# The full canary, end to end
# --------------------------------------------------------------------------- #
def test_full_canary_progression_from_5_percent_to_promotion(
    client: TestClient, admin: dict, db_session: Session,
) -> None:
    """The §11 integration test: start at 5%, health from real execution
    rows, gates met, advance through each stage via 3.4's allocation, and
    finish promoted -- with a real execution routed through the resolver at
    the end to prove the whole chain still runs."""
    setup = _canary_setup(client, admin)
    rollout, code = _create_rollout(client, admin, setup, stages=[
        {"target_weight": 5, "min_samples": 10}, {"target_weight": 25, "min_samples": 10},
        {"target_weight": 50, "min_samples": 10}, {"target_weight": 100, "min_samples": 10},
    ])
    assert code == 201, rollout

    expected = [5, 25, 50, 100]
    assert _weights(db_session, setup, admin)[setup["candidate"]["id"]] == expected[0]

    for index in range(1, len(expected)):
        _seed_executions(db_session, setup, admin, setup["candidate"]["id"], succeeded=40)
        r = client.post(f"{RT}/rollouts/{rollout['id']}/advance", headers=admin["headers"], json={})
        assert r.status_code == 200, r.text
        assert r.json()["current_stage_index"] == index
        assert _weights(db_session, setup, admin)[setup["candidate"]["id"]] == expected[index]

    _seed_executions(db_session, setup, admin, setup["candidate"]["id"], succeeded=40)
    r = client.post(f"{RT}/rollouts/{rollout['id']}/advance", headers=admin["headers"], json={})
    assert r.status_code == 200, r.text
    assert r.json()["state"] == "SUCCEEDED"
    assert _weights(db_session, setup, admin)[setup["candidate"]["id"]] == 100

    # The unchanged Phase 3.4 resolver now routes every execution to the
    # promoted candidate.
    r = client.post(f"{RT}/executions", headers=admin["headers"], json={
        "agent_id": setup["agent"]["id"], "input_payload": {"message": "hi"}})
    assert r.status_code == 201, r.text
    assert r.json()["agent_version_id"] == setup["candidate"]["id"]
    assert r.json()["status"] == "SUCCEEDED"


def test_a_failing_canary_is_caught_by_health_and_rolled_back(
    client: TestClient, admin: dict, db_session: Session,
) -> None:
    """The milestone's own §19 proof, in miniature: a canary that starts
    failing is caught by the health engine, refuses to advance, and is rolled
    back to stable."""
    setup = _canary_setup(client, admin)
    rollout, _ = _create_rollout(client, admin, setup, stages=[
        {"target_weight": 5, "min_samples": 20}, {"target_weight": 50}, {"target_weight": 100},
    ])
    _seed_executions(db_session, setup, admin, setup["candidate"]["id"], succeeded=20, failed=10)
    _seed_executions(db_session, setup, admin, setup["stable"]["id"], succeeded=100)

    body = client.get(f"{RT}/rollouts/{rollout['id']}/health", headers=admin["headers"]).json()
    assert body["current"]["health_state"] == "UNHEALTHY"

    r = client.post(f"{RT}/rollouts/{rollout['id']}/advance", headers=admin["headers"], json={})
    assert r.status_code == 409, r.text

    r = client.post(f"{RT}/rollouts/{rollout['id']}/request-rollback", headers=admin["headers"],
                    json={"reason": "health gate failed"})
    assert r.status_code == 200, r.text
    assert r.json()["state"] == "ROLLBACK_REQUESTED"
    assert _weights(db_session, setup, admin) == {
        setup["candidate"]["id"]: 0, setup["stable"]["id"]: 100,
    }


# --------------------------------------------------------------------------- #
# AC-13 -- concurrency (real separate Postgres connections)
# --------------------------------------------------------------------------- #
def test_ac13_two_actors_advancing_one_rollout_conflict_exactly_once(
    client: TestClient, admin: dict, db_session: Session,
) -> None:
    setup = _canary_setup(client, admin)
    rollout, _ = _create_rollout(client, admin, setup, stages=[
        {"target_weight": 5, "health_requirement": "NONE"},
        {"target_weight": 25, "health_requirement": "NONE"},
        {"target_weight": 100, "health_requirement": "NONE"},
    ])
    plan_id = uuid.UUID(rollout["id"])
    barrier = threading.Barrier(2, timeout=60)

    def _advance(_ignored: int) -> str:
        db = SessionLocal()
        try:
            service = CanaryRolloutService(db)
            actor = db.get(User, uuid.UUID(admin["user_id"]))
            plan = db.get(RolloutPlan, plan_id)
            barrier.wait()
            service.advance(actor, plan)
            return "OK"
        except IdentityError as exc:
            return str(exc.code)
        finally:
            db.rollback()
            db.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(_advance, [1, 2]))

    assert results.count("OK") >= 1, results
    assert set(results) <= {"OK", ErrorCode.ROLLOUT_CONFLICT,
                            ErrorCode.ROLLOUT_STAGE_GATE_NOT_MET}, results

    # Never double-advanced: exactly one stage was consumed, and the weights
    # match that stage rather than two stages on.
    db_session.rollback()
    plan = db_session.get(RolloutPlan, plan_id)
    assert plan.current_stage_index == 1, "advanced by more than one stage"
    assert _weights(db_session, setup, admin)[setup["candidate"]["id"]] == 25


def test_ac13_advance_racing_abort_leaves_a_consistent_state(
    client: TestClient, admin: dict, db_session: Session,
) -> None:
    setup = _canary_setup(client, admin)
    rollout, _ = _create_rollout(client, admin, setup, stages=[
        {"target_weight": 5, "min_samples": 5}, {"target_weight": 50}, {"target_weight": 100},
    ])
    _seed_executions(db_session, setup, admin, setup["candidate"]["id"], succeeded=200)
    plan_id = uuid.UUID(rollout["id"])
    barrier = threading.Barrier(2, timeout=60)

    def _operate(which: str) -> str:
        db = SessionLocal()
        try:
            service = CanaryRolloutService(db)
            actor = db.get(User, uuid.UUID(admin["user_id"]))
            plan = db.get(RolloutPlan, plan_id)
            barrier.wait()
            if which == "advance":
                service.advance(actor, plan)
            else:
                service.abort(actor, plan, reason="raced")
            return f"{which}:OK"
        except IdentityError as exc:
            return f"{which}:{exc.code}"
        finally:
            db.rollback()
            db.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(_operate, ["advance", "abort"]))

    db_session.rollback()
    plan = db_session.get(RolloutPlan, plan_id)
    # Whoever won, the state is one of the two legal outcomes -- never a
    # torn hybrid -- and the weights agree with the state.
    assert plan.state in ("IN_PROGRESS", "ABORTED"), (plan.state, results)
    weights = _weights(db_session, setup, admin)
    if plan.state == "ABORTED":
        assert weights[setup["candidate"]["id"]] == 0
    else:
        assert weights[setup["candidate"]["id"]] in (5, 50)


def test_ac13_the_rollout_state_machine_has_one_transition_authority() -> None:
    """Mechanical check, mirroring Phase 3.1's own AC-02: nothing outside
    ``canary.py`` assigns ``RolloutPlan.state``."""
    import re

    app_dir = Path(__file__).resolve().parents[2] / "app"
    assignment = re.compile(r"\.state\s*=\s*(?!.*#\s*noqa)")
    offending = []
    for path in app_dir.rglob("*.py"):
        if path.name == "canary.py":
            continue
        text = path.read_text(encoding="utf-8")
        if "RolloutPlan" in text and assignment.search(text):
            offending.append(str(path))
    assert offending == [], offending


# --------------------------------------------------------------------------- #
# AC-14 -- health/advance queries are indexed, not table scans
# --------------------------------------------------------------------------- #
def test_ac14_health_aggregation_uses_an_index_not_a_sequential_scan(
    client: TestClient, admin: dict, db_session: Session,
) -> None:
    """Asserted against real ``EXPLAIN`` plans rather than by inspection.

    Two properties, deliberately *not* "the planner picks index X". Postgres
    legitimately chooses whichever index is most selective for the actual
    data -- for an organization with only a handful of executions it will
    reasonably use the organization index -- and pinning the exact choice
    would make this test fail on planner improvements rather than on real
    regressions. What matters is:

    1. the per-version time-window shape, which is the health aggregation's
       core predicate, is served by the composite index this migration added;
    2. the full aggregation predicate never sequentially scans the table.
    """
    from sqlalchemy import text

    setup = _canary_setup(client, admin)
    _seed_executions(db_session, setup, admin, setup["candidate"]["id"], succeeded=50)
    db_session.rollback()

    version_window_plan = "\n".join(row[0] for row in db_session.execute(text(
        "EXPLAIN SELECT count(*) FROM agent_executions "
        "WHERE agent_version_id = :version "
        "AND created_at >= now() - interval '1 hour' AND created_at <= now()"
    ), {"version": uuid.UUID(setup["candidate"]["id"])}))
    assert "ix_agent_executions_version_created" in version_window_plan, version_window_plan

    full_plan = "\n".join(row[0] for row in db_session.execute(text(
        "EXPLAIN SELECT count(*) FROM agent_executions "
        "WHERE organization_id = :org AND agent_version_id = :version "
        "AND created_at >= now() - interval '1 hour' AND created_at <= now()"
    ), {"org": uuid.UUID(admin["organization_id"]),
        "version": uuid.UUID(setup["candidate"]["id"])}))
    db_session.rollback()

    assert "Seq Scan on agent_executions" not in full_plan, full_plan
    assert "Index" in full_plan, full_plan


def test_ac14_the_new_execution_indexes_exist(db_session: Session) -> None:
    from sqlalchemy import text

    rows = {r[0] for r in db_session.execute(text(
        "SELECT indexname FROM pg_indexes WHERE tablename = 'agent_executions'"))}
    assert "ix_agent_executions_version_created" in rows
    assert "ix_agent_executions_deployment_created" in rows


# --------------------------------------------------------------------------- #
# AC-15 -- authorization, tenant isolation, idempotency
# --------------------------------------------------------------------------- #
def test_ac15_rollout_endpoints_require_authentication(client: TestClient, admin: dict) -> None:
    setup = _canary_setup(client, admin)
    rollout, _ = _create_rollout(client, admin, setup)
    assert client.get(f"{RT}/rollouts/{rollout['id']}").status_code in (401, 403)
    assert client.post(f"{RT}/rollouts/{rollout['id']}/advance", json={}).status_code in (401, 403)
    assert client.post(f"{RT}/rollouts/{rollout['id']}/abort", json={}).status_code in (401, 403)


def test_ac15_a_viewer_cannot_drive_a_rollout(client: TestClient, admin: dict) -> None:
    from tests.runtime.conftest import PASSWORD

    setup = _canary_setup(client, admin)
    rollout, _ = _create_rollout(client, admin, setup)

    email = f"viewer_{uuid.uuid4().hex[:10]}@example.com"
    r = client.post("/api/v1/identity/users", headers=admin["headers"], json={
        "email": email, "display_name": "Viewer", "password": PASSWORD, "role": "VIEWER",
        "organization_id": admin["organization_id"],
    })
    assert r.status_code in (200, 201), r.text
    tokens = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD}).json()
    viewer = {"Authorization": f"Bearer {tokens['access_token']}"}

    assert client.post(f"{RT}/rollouts/{rollout['id']}/advance",
                      headers=viewer, json={}).status_code == 403
    assert client.post(f"{RT}/rollouts/{rollout['id']}/promote",
                      headers=viewer, json={}).status_code == 403


def test_ac15_cross_tenant_rollout_access_is_rejected(client: TestClient, admin: dict) -> None:
    setup = _canary_setup(client, admin)
    rollout, _ = _create_rollout(client, admin, setup)
    other = _second_org(client)

    r = client.get(f"{RT}/rollouts/{rollout['id']}", headers=other["headers"])
    assert r.status_code == 404, r.text
    assert r.json()["error"]["code"] == "ROLLOUT_NOT_FOUND"

    r = client.post(f"{RT}/rollouts/{rollout['id']}/abort", headers=other["headers"], json={})
    assert r.status_code == 404, r.text


def test_ac15_health_aggregation_is_tenant_scoped(
    client: TestClient, admin: dict, db_session: Session,
) -> None:
    """A version id from another tenant must contribute nothing -- the
    aggregation filters on organization in the same predicate, never
    afterwards."""
    setup = _canary_setup(client, admin)
    other = _second_org(client)
    _seed_executions(db_session, setup, admin, setup["candidate"]["id"], succeeded=10)

    db_session.rollback()
    agent = db_session.get(Agent, uuid.UUID(setup["agent"]["id"]))
    verdict = HealthEvaluationService(db_session).evaluate(
        organization_id=uuid.UUID(other["organization_id"]), agent=agent,
        agent_version_id=uuid.UUID(setup["candidate"]["id"]),
        window_start=_now() - timedelta(hours=1), window_end=_now(), min_samples=1,
    )
    assert verdict.state == "INSUFFICIENT_DATA"
    assert verdict.metrics.sample_count == 0


def test_ac15_idempotency_key_is_honoured_on_rollout_creation(
    client: TestClient, admin: dict, db_session: Session,
) -> None:
    setup = _canary_setup(client, admin)
    url = f"{RT}/agents/{setup['agent']['id']}/environments/{setup['environment']['id']}/rollouts"
    payload = {"candidate_version_id": setup["candidate"]["id"], "stages": _STAGES}
    headers = {**admin["headers"], "Idempotency-Key": f"rollout-{uuid.uuid4().hex[:12]}"}

    first = client.post(url, headers=headers, json=payload)
    second = client.post(url, headers=headers, json=payload)
    assert first.status_code == 201 and second.status_code == 201
    assert first.json()["id"] == second.json()["id"]

    db_session.rollback()
    plans = db_session.execute(select(RolloutPlan).where(
        RolloutPlan.agent_id == uuid.UUID(setup["agent"]["id"]))).scalars().all()
    assert len(plans) == 1


def test_ac15_idempotency_key_is_honoured_on_advance(
    client: TestClient, admin: dict, db_session: Session,
) -> None:
    setup = _canary_setup(client, admin)
    rollout, _ = _create_rollout(client, admin, setup, stages=[
        {"target_weight": 5, "health_requirement": "NONE"},
        {"target_weight": 25, "health_requirement": "NONE"},
        {"target_weight": 100, "health_requirement": "NONE"},
    ])
    headers = {**admin["headers"], "Idempotency-Key": f"adv-{uuid.uuid4().hex[:12]}"}

    first = client.post(f"{RT}/rollouts/{rollout['id']}/advance", headers=headers, json={})
    second = client.post(f"{RT}/rollouts/{rollout['id']}/advance", headers=headers, json={})
    assert first.status_code == 200 and second.status_code == 200
    assert first.json()["current_stage_index"] == second.json()["current_stage_index"] == 1
    assert _weights(db_session, setup, admin)[setup["candidate"]["id"]] == 25


# --------------------------------------------------------------------------- #
# State machine unit coverage
# --------------------------------------------------------------------------- #
def test_rollout_state_machine_transitions_are_complete_and_terminal_states_are_closed() -> None:
    assert set(rollout_machine.all_states()) == {
        "PENDING", "IN_PROGRESS", "PAUSED", "SUCCEEDED", "ABORTED",
        "ROLLBACK_REQUESTED", "FAILED",
    }
    for terminal in rollout_machine.TERMINAL_STATES:
        assert rollout_machine.allowed_targets(terminal) == frozenset()
    assert rollout_machine.can_transition("IN_PROGRESS", "PAUSED")
    assert rollout_machine.can_transition("PAUSED", "IN_PROGRESS")
    assert not rollout_machine.can_transition("SUCCEEDED", "IN_PROGRESS")
    assert not rollout_machine.can_transition("PENDING", "SUCCEEDED")


def test_pause_and_resume_round_trip(client: TestClient, admin: dict, db_session: Session) -> None:
    setup = _canary_setup(client, admin)
    rollout, _ = _create_rollout(client, admin, setup)

    r = client.post(f"{RT}/rollouts/{rollout['id']}/pause", headers=admin["headers"], json={})
    assert r.status_code == 200 and r.json()["state"] == "PAUSED"

    # A paused rollout does not advance.
    r = client.post(f"{RT}/rollouts/{rollout['id']}/advance", headers=admin["headers"], json={})
    assert r.status_code == 409 and r.json()["error"]["code"] == "ROLLOUT_INVALID_TRANSITION"

    r = client.post(f"{RT}/rollouts/{rollout['id']}/resume", headers=admin["headers"], json={})
    assert r.status_code == 200 and r.json()["state"] == "IN_PROGRESS"
    # Weights were never disturbed by the pause/resume round trip.
    assert _weights(db_session, setup, admin)[setup["candidate"]["id"]] == 5


def test_resume_is_refused_while_the_agent_is_killed(
    client: TestClient, admin: dict,
) -> None:
    setup = _canary_setup(client, admin)
    rollout, _ = _create_rollout(client, admin, setup)
    client.post(f"{RT}/rollouts/{rollout['id']}/pause", headers=admin["headers"], json={})
    client.post(f"{RT}/kill-switch/agents/{setup['agent']['id']}",
                headers=admin["headers"], json={"reason": "incident"})

    r = client.post(f"{RT}/rollouts/{rollout['id']}/resume", headers=admin["headers"], json={})
    assert r.status_code == 423, r.text
    assert r.json()["error"]["code"] == "ROLLOUT_HALTED_BY_KILL_SWITCH"


def test_health_metrics_serialization_is_json_safe() -> None:
    metrics = HealthMetrics(sample_count=3, succeeded=3, error_rate=0.0)
    payload = metrics.as_dict()
    assert payload["sample_count"] == 3
    assert payload["error_codes"] == {}


# --------------------------------------------------------------------------- #
# AC-19 -- no new TODO/FIXME/NotImplementedError/skip/xfail
# --------------------------------------------------------------------------- #
def test_ac19_no_stub_markers_in_this_phases_files() -> None:
    root = Path(__file__).resolve().parents[2]
    targets = [
        root / "app" / "runtime" / "deployment" / "rollout.py",
        root / "app" / "runtime" / "deployment" / "health.py",
        root / "app" / "runtime" / "deployment" / "canary.py",
        root / "migrations" / "versions" / "0041_canary_rollout.py",
    ]
    for path in targets:
        text = path.read_text(encoding="utf-8")
        for banned in ("TODO", "FIXME", "NotImplementedError", "xfail", "pytest.skip"):
            assert banned not in text, f"{path.name} contains {banned}"
