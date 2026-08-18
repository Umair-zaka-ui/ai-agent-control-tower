"""Phase 3.6 (ACT-SRS-M3 §Phase-3.6) tests -- deployment strategy execution:
the dispatch abstraction, RECREATE, BLUE_GREEN (prepare/switch/preserve/
rollback), and the deliberately-deferred ROLLING seam.

Grouped by the build prompt's own §12 acceptance criteria. Real Postgres
throughout (this suite's convention -- ``tests/runtime/conftest.py``), including
the AC-11 race, which uses a real second connection holding its transaction open
rather than a timing-dependent thread barrier (the same deterministic pattern
Phases 3.4 and 3.5 established).

**Why the setup deploys through the 3.1 lifecycle route.** Two versions of one
agent must be simultaneously servable in one environment for a strategy to have
anything to switch between. The legacy ``POST /deployments/{id}/deploy`` route
implements its own RECREATE by retiring siblings, which would leave nothing to
switch away from; the 3.1 lifecycle route leaves siblings alone. Both are
exercised elsewhere -- see ``test_traffic_resolver_gate.py``'s own note."""

from __future__ import annotations

import inspect
import threading
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy import update as sa_update
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.identity.errors import ErrorCode, IdentityError
from app.models.runtime import AgentDeployment, AgentVersion, DeploymentTrafficAllocation
from app.models.user import User
from app.runtime.deployment import strategies
from app.runtime.deployment.strategies import DeploymentStrategyService
from app.runtime.deployment.traffic import TrafficAllocationService

RT = "/api/v1/runtime"


# --------------------------------------------------------------------------- #
# HTTP setup helpers (this suite's convention: each file defines its own)
# --------------------------------------------------------------------------- #
def _register_agent(client: TestClient, admin: dict) -> dict:
    nonce = uuid.uuid4().hex[:8]
    r = client.post(f"{RT}/agents", headers=admin["headers"], json={
        "name": f"Strategy Agent {nonce}", "agent_type": "ASSISTANT", "criticality": "MEDIUM",
        "description": f"Test agent {nonce}.",
        "business_purpose": f"Exercise deployment strategies {nonce} in tests.",
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
                     strategy: str = "RECREATE", environment: str = "DEVELOPMENT") -> dict:
    r = client.post(f"{RT}/deployments", headers=admin["headers"], params={"agent_id": agent_id},
                    json={"agent_version_id": version_id, "environment": environment,
                          "deployment_strategy": strategy})
    assert r.status_code == 201, r.text
    deployment = r.json()
    assert deployment["deployment_strategy"] == strategy
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


def _setup(client: TestClient, admin: dict, *, candidate_strategy: str) -> dict:
    """One agent; a BLUE version already serving, and a candidate deployed
    alongside it carrying ``candidate_strategy``."""
    envs = _environments(client, admin)
    agent = _register_agent(client, admin)
    _activate_agent(client, admin, agent["id"])
    blue = _publish_version(client, admin, agent["id"])
    green = _publish_version(client, admin, agent["id"])
    blue_deployment = _lifecycle_deploy(client, admin, agent["id"], blue["id"])
    green_deployment = _lifecycle_deploy(client, admin, agent["id"], green["id"],
                                        strategy=candidate_strategy)
    return {"agent": agent, "blue": blue, "green": green,
            "blue_deployment": blue_deployment, "green_deployment": green_deployment,
            "environment": envs["DEVELOPMENT"]}


def _weights(db: Session, setup: dict, admin: dict) -> dict[str, int]:
    db.rollback()
    traffic = TrafficAllocationService(db)
    allocation = traffic.current(uuid.UUID(admin["organization_id"]),
                                uuid.UUID(setup["agent"]["id"]),
                                uuid.UUID(setup["environment"]["id"]))
    if allocation is None:
        return {}
    return {str(w.agent_version_id): w.weight for w in traffic.weights_for(allocation.id)}


def _allocation_count(db: Session, setup: dict) -> int:
    db.rollback()
    return len(db.execute(select(DeploymentTrafficAllocation).where(
        DeploymentTrafficAllocation.agent_id == uuid.UUID(setup["agent"]["id"]))).scalars().all())


def _execute(client: TestClient, admin: dict, deployment_id: str, *,
             headers: dict | None = None):
    return client.post(f"{RT}/deployments/{deployment_id}/strategy/execute",
                       headers=headers or admin["headers"])


def _second_org(client: TestClient) -> dict:
    from tests.runtime.conftest import PASSWORD

    email = f"strategy_other_{uuid.uuid4().hex[:10]}@example.com"
    assert client.post("/auth/register", json={
        "organization_name": "Other Org", "name": "Owner", "email": email, "password": PASSWORD,
    }).status_code == 201
    tokens = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD}).json()
    me = client.get("/api/v1/auth/me",
                    headers={"Authorization": f"Bearer {tokens['access_token']}"}).json()
    return {"headers": {"Authorization": f"Bearer {tokens['access_token']}"},
            "user_id": me["user"]["id"], "organization_id": me["user"]["organization_id"]}


# --------------------------------------------------------------------------- #
# AC-01 -- one abstraction, dispatched on deployment_strategy
# --------------------------------------------------------------------------- #
def test_ac01_every_declared_strategy_has_exactly_one_handler() -> None:
    assert set(strategies._HANDLERS) == set(strategies.STRATEGIES)
    assert isinstance(strategies.handler_for("RECREATE"), strategies.RecreateStrategy)
    assert isinstance(strategies.handler_for("BLUE_GREEN"), strategies.BlueGreenStrategy)
    assert isinstance(strategies.handler_for("ROLLING"), strategies.RollingStrategy)


def test_ac01_the_declared_strategies_match_the_schema_contract() -> None:
    """The abstraction must cover exactly the values the API already accepts,
    so no request body can name a strategy with no handler."""
    from app.runtime.schemas import DeploymentCreate

    pattern = DeploymentCreate.model_fields["deployment_strategy"].metadata[0].pattern
    declared = set(pattern.strip("^$()").split("|"))
    assert declared == set(strategies.STRATEGIES)


def test_ac01_an_unknown_strategy_is_rejected_not_silently_ignored() -> None:
    with pytest.raises(IdentityError) as exc:
        strategies.handler_for("TELEPORT")
    assert exc.value.code == ErrorCode.VALIDATION_ERROR


def test_ac01_dispatch_follows_the_column_not_the_request(
    client: TestClient, admin: dict, db_session: Session,
) -> None:
    """A deployment declared BLUE_GREEN must prepare, not cut over, even though
    the caller sent no strategy at all -- the column is the input."""
    setup = _setup(client, admin, candidate_strategy="BLUE_GREEN")
    r = _execute(client, admin, setup["green_deployment"]["id"])
    assert r.status_code == 200, r.text
    assert r.json()["strategy"] == "BLUE_GREEN"
    assert r.json()["operation"] == "prepare"


# --------------------------------------------------------------------------- #
# AC-02 / AC-03 -- RECREATE
# --------------------------------------------------------------------------- #
def test_ac02_recreate_cuts_over_to_100_percent_and_supersedes_the_previous(
    client: TestClient, admin: dict, db_session: Session,
) -> None:
    setup = _setup(client, admin, candidate_strategy="RECREATE")
    before = _allocation_count(db_session, setup)

    r = _execute(client, admin, setup["green_deployment"]["id"])
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["strategy"] == "RECREATE" and body["operation"] == "cutover"
    assert body["candidate_weight"] == 100 and body["previous_weight"] == 0

    assert _weights(db_session, setup, admin) == {
        setup["green"]["id"]: 100, setup["blue"]["id"]: 0,
    }
    # Went through 3.4's revisioned mechanism, not a direct weight write.
    assert _allocation_count(db_session, setup) == before + 1

    # The previous deployment stops receiving new work: SUPERSEDED is in
    # 3.4's non-serving set, so the resolver will not route to it at all.
    db_session.rollback()
    previous = db_session.get(AgentDeployment, uuid.UUID(setup["blue_deployment"]["id"]))
    assert previous.lifecycle_state == "SUPERSEDED"
    assert previous.superseded_by_deployment_id == uuid.UUID(setup["green_deployment"]["id"])


def test_ac02_recreate_is_atomic_at_the_allocation_level(
    client: TestClient, admin: dict, db_session: Session,
) -> None:
    """FR-012 -- there is no committed allocation in which neither version
    serves or both serve fully. Asserted over *every* revision this agent has
    ever had, not just the final one."""
    setup = _setup(client, admin, candidate_strategy="RECREATE")
    _execute(client, admin, setup["green_deployment"]["id"])

    db_session.rollback()
    traffic = TrafficAllocationService(db_session)
    allocations = db_session.execute(select(DeploymentTrafficAllocation).where(
        DeploymentTrafficAllocation.agent_id == uuid.UUID(setup["agent"]["id"]))).scalars().all()
    assert allocations
    for allocation in allocations:
        weights = traffic.weights_for(allocation.id)
        assert sum(w.weight for w in weights) == 100
        assert sum(1 for w in weights if w.weight == 100) <= 1


def test_ac03_a_release_gate_block_stops_the_recreate_cutover(
    client: TestClient, admin: dict, db_session: Session,
) -> None:
    setup = _setup(client, admin, candidate_strategy="RECREATE")
    before = _weights(db_session, setup, admin)

    # Revoking the candidate version makes the release gate BLOCK on
    # PREFLIGHT_VERSION_NOT_PUBLISHED, without touching the agent or the
    # deployment (so this tests the gate, not the kill-switch veto).
    r = client.post(f"{RT}/agents/{setup['agent']['id']}/versions/{setup['green']['id']}/revoke",
                    headers=admin["headers"], json={"reason": "compromised"})
    assert r.status_code == 200, r.text

    r = _execute(client, admin, setup["green_deployment"]["id"])
    assert r.status_code == 409, r.text
    assert r.json()["error"]["code"] == "STRATEGY_GATE_BLOCKED"
    assert "PREFLIGHT_VERSION_NOT_PUBLISHED" in r.json()["error"]["message"]

    # Fail closed: traffic did not move.
    assert _weights(db_session, setup, admin) == before


# --------------------------------------------------------------------------- #
# AC-04..AC-07 -- BLUE_GREEN
# --------------------------------------------------------------------------- #
def test_ac04_prepare_warms_green_at_zero_while_blue_serves_everything(
    client: TestClient, admin: dict, db_session: Session,
) -> None:
    setup = _setup(client, admin, candidate_strategy="BLUE_GREEN")
    r = _execute(client, admin, setup["green_deployment"]["id"])
    assert r.status_code == 200, r.text
    assert r.json()["operation"] == "prepare"

    assert _weights(db_session, setup, admin) == {
        setup["green"]["id"]: 0, setup["blue"]["id"]: 100,
    }
    # GREEN is warm: deployed and servable, just not routed to.
    db_session.rollback()
    green_deployment = db_session.get(AgentDeployment,
                                     uuid.UUID(setup["green_deployment"]["id"]))
    assert green_deployment.lifecycle_state == "ACTIVE"


def test_ac04_a_real_execution_still_reaches_blue_while_green_is_warm(
    client: TestClient, admin: dict,
) -> None:
    """The warm state is not just a row: 3.4's unchanged resolver must still
    route every request to BLUE, because GREEN's weight is zero."""
    setup = _setup(client, admin, candidate_strategy="BLUE_GREEN")
    _execute(client, admin, setup["green_deployment"]["id"])

    for _ in range(6):
        r = client.post(f"{RT}/executions", headers=admin["headers"], json={
            "agent_id": setup["agent"]["id"], "input_payload": {"message": "hi"}})
        assert r.status_code == 201, r.text
        assert r.json()["agent_version_id"] == setup["blue"]["id"]


def test_ac05_the_switch_is_one_atomic_allocation_transition(
    client: TestClient, admin: dict, db_session: Session,
) -> None:
    setup = _setup(client, admin, candidate_strategy="BLUE_GREEN")
    _execute(client, admin, setup["green_deployment"]["id"])
    before = _allocation_count(db_session, setup)

    r = client.post(f"{RT}/deployments/{setup['green_deployment']['id']}/strategy/blue-green/switch",
                    headers=admin["headers"])
    assert r.status_code == 200, r.text
    assert r.json()["operation"] == "switch"

    assert _weights(db_session, setup, admin) == {
        setup["green"]["id"]: 100, setup["blue"]["id"]: 0,
    }
    # Exactly one new revision -- both weights moved together, so no committed
    # state exists in which BLUE and GREEN were both serving.
    assert _allocation_count(db_session, setup) == before + 1


def test_ac05_a_switch_before_prepare_is_refused(
    client: TestClient, admin: dict, db_session: Session,
) -> None:
    setup = _setup(client, admin, candidate_strategy="BLUE_GREEN")
    before = _weights(db_session, setup, admin)

    r = client.post(f"{RT}/deployments/{setup['green_deployment']['id']}/strategy/blue-green/switch",
                    headers=admin["headers"])
    assert r.status_code == 409, r.text
    assert r.json()["error"]["code"] == "BLUE_GREEN_NOT_PREPARED"
    assert _weights(db_session, setup, admin) == before


def test_ac06_blue_is_preserved_as_a_designated_rollback_target(
    client: TestClient, admin: dict, db_session: Session,
) -> None:
    """The defining difference from RECREATE: after a switch BLUE is still
    deployed and instantly returnable, not superseded."""
    setup = _setup(client, admin, candidate_strategy="BLUE_GREEN")
    _execute(client, admin, setup["green_deployment"]["id"])
    r = client.post(f"{RT}/deployments/{setup['green_deployment']['id']}/strategy/blue-green/switch",
                    headers=admin["headers"])
    assert r.status_code == 200, r.text

    db_session.rollback()
    # 1. Lineage recorded on the existing rollback_target_id field.
    green_version = db_session.get(AgentVersion, uuid.UUID(setup["green"]["id"]))
    assert green_version.rollback_target_id == uuid.UUID(setup["blue"]["id"])

    # 2. BLUE's deployment is still ACTIVE -- preserved, not superseded.
    blue_deployment = db_session.get(AgentDeployment,
                                    uuid.UUID(setup["blue_deployment"]["id"]))
    assert blue_deployment.lifecycle_state == "ACTIVE"
    assert blue_deployment.superseded_by_deployment_id is None

    # 3. But it serves nothing -- preserved is not split-serving.
    assert _weights(db_session, setup, admin)[setup["blue"]["id"]] == 0


def test_ac06_no_accidental_split_serving_after_a_switch(
    client: TestClient, admin: dict,
) -> None:
    """§10 -- BLUE being preserved must not mean BLUE still gets traffic."""
    setup = _setup(client, admin, candidate_strategy="BLUE_GREEN")
    _execute(client, admin, setup["green_deployment"]["id"])
    client.post(f"{RT}/deployments/{setup['green_deployment']['id']}/strategy/blue-green/switch",
                headers=admin["headers"])

    for _ in range(8):
        r = client.post(f"{RT}/executions", headers=admin["headers"], json={
            "agent_id": setup["agent"]["id"], "input_payload": {"message": "hi"}})
        assert r.status_code == 201, r.text
        assert r.json()["agent_version_id"] == setup["green"]["id"]


def test_ac07_rollback_returns_traffic_to_blue_atomically(
    client: TestClient, admin: dict, db_session: Session,
) -> None:
    setup = _setup(client, admin, candidate_strategy="BLUE_GREEN")
    _execute(client, admin, setup["green_deployment"]["id"])
    client.post(f"{RT}/deployments/{setup['green_deployment']['id']}/strategy/blue-green/switch",
                headers=admin["headers"])
    before = _allocation_count(db_session, setup)

    r = client.post(
        f"{RT}/deployments/{setup['green_deployment']['id']}/strategy/blue-green/rollback",
        headers=admin["headers"])
    assert r.status_code == 200, r.text
    assert r.json()["operation"] == "rollback"

    assert _weights(db_session, setup, admin) == {
        setup["blue"]["id"]: 100, setup["green"]["id"]: 0,
    }
    assert _allocation_count(db_session, setup) == before + 1

    # And execution follows immediately.
    r = client.post(f"{RT}/executions", headers=admin["headers"], json={
        "agent_id": setup["agent"]["id"], "input_payload": {"message": "hi"}})
    assert r.json()["agent_version_id"] == setup["blue"]["id"]


def test_ac07_rollback_without_a_preserved_blue_is_refused(
    client: TestClient, admin: dict,
) -> None:
    setup = _setup(client, admin, candidate_strategy="BLUE_GREEN")
    _execute(client, admin, setup["green_deployment"]["id"])  # prepared, never switched

    r = client.post(
        f"{RT}/deployments/{setup['green_deployment']['id']}/strategy/blue-green/rollback",
        headers=admin["headers"])
    assert r.status_code == 409, r.text
    assert r.json()["error"]["code"] == "BLUE_GREEN_NOT_PREPARED"


def test_full_blue_green_lifecycle_warm_switch_preserve_rollback(
    client: TestClient, admin: dict, db_session: Session,
) -> None:
    """The §11 end-to-end integration test, in one narrative."""
    setup = _setup(client, admin, candidate_strategy="BLUE_GREEN")
    blue, green = setup["blue"]["id"], setup["green"]["id"]
    deployment_id = setup["green_deployment"]["id"]

    _execute(client, admin, deployment_id)
    assert _weights(db_session, setup, admin) == {blue: 100, green: 0}

    client.post(f"{RT}/deployments/{deployment_id}/strategy/blue-green/switch",
                headers=admin["headers"])
    assert _weights(db_session, setup, admin) == {blue: 0, green: 100}

    client.post(f"{RT}/deployments/{deployment_id}/strategy/blue-green/rollback",
                headers=admin["headers"])
    assert _weights(db_session, setup, admin) == {blue: 100, green: 0}

    # Every transition was its own audited allocation revision -- 3 changes.
    db_session.rollback()
    revisions = sorted(a.revision for a in db_session.execute(
        select(DeploymentTrafficAllocation).where(
            DeploymentTrafficAllocation.agent_id == uuid.UUID(setup["agent"]["id"]))).scalars())
    assert revisions == list(range(1, len(revisions) + 1)), revisions
    assert len(revisions) >= 3


def test_ac03_the_gate_is_re_evaluated_at_the_switch_not_only_at_prepare(
    client: TestClient, admin: dict, db_session: Session,
) -> None:
    """A deployment can pass validation and then be compromised before anyone
    presses the button. Re-checking at the switch is the value of a gate."""
    setup = _setup(client, admin, candidate_strategy="BLUE_GREEN")
    _execute(client, admin, setup["green_deployment"]["id"])
    prepared = _weights(db_session, setup, admin)

    r = client.post(f"{RT}/agents/{setup['agent']['id']}/versions/{setup['green']['id']}/revoke",
                    headers=admin["headers"], json={"reason": "found a problem"})
    assert r.status_code == 200, r.text

    r = client.post(f"{RT}/deployments/{setup['green_deployment']['id']}/strategy/blue-green/switch",
                    headers=admin["headers"])
    assert r.status_code == 409, r.text
    assert r.json()["error"]["code"] == "STRATEGY_GATE_BLOCKED"
    assert _weights(db_session, setup, admin) == prepared


# --------------------------------------------------------------------------- #
# AC-08 / AC-13 -- structural: drives 3.4, changes nothing it does not own
# --------------------------------------------------------------------------- #
def test_ac08_strategies_never_write_traffic_weights_directly() -> None:
    """Structural proof, mirroring 3.5's own: the module cannot bypass 3.4's
    atomic mechanism because it holds no reference to the weight tables."""
    import ast

    source = (Path(__file__).resolve().parents[2] / "app" / "runtime" / "deployment"
              / "strategies.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    identifiers = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    identifiers |= {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}

    for forbidden in ("DeploymentTrafficWeight", "DeploymentTrafficAllocation"):
        assert forbidden not in identifiers, f"strategies.py must not reference {forbidden}"
    assert "set_weights" in identifiers, "traffic must move through 3.4's set_weights"


def test_ac13_phase_3_4_and_3_5_mechanics_are_unmodified() -> None:
    """AC-13 -- the resolver, the allocation service and the canary engine are
    driven by this phase, not modified by it."""
    import subprocess

    root = Path(__file__).resolve().parents[3]
    changed = subprocess.run(
        ["git", "diff", "--name-only", "main...HEAD", "--",
         "backend/app/runtime/deployment/resolver.py",
         "backend/app/runtime/deployment/traffic.py",
         "backend/app/runtime/deployment/canary.py",
         "backend/app/runtime/deployment/rollout.py",
         "backend/app/runtime/deployment/health.py"],
        cwd=root, capture_output=True, text=True, check=False,
    ).stdout.strip()
    assert changed == "", f"Phase 3.6 must not modify 3.4/3.5 mechanics, but changed: {changed}"


# --------------------------------------------------------------------------- #
# AC-09 -- ROLLING: deferred in 3.6, implemented in 3.9, honest in both
# --------------------------------------------------------------------------- #
def test_ac09_rolling_without_a_fleet_still_does_nothing_at_all(
    client: TestClient, admin: dict, db_session: Session,
) -> None:
    """Phase 3.9 replaced the deferral with a real handler, so this test's
    subject changed -- but the property it was really guarding did not, and
    it is asserted here more strongly than before.

    3.6's version proved ROLLING never half-executes over a substrate it does
    not have. 3.9 gave it a substrate, and the same rule now applies to the
    substrate being *absent or empty*: with no live workers, rolling fails
    closed and moves no traffic. The error is specific
    (``ROLLING_COHORT_INVALID``) rather than the old ``STRATEGY_ROLLING_
    DEFERRED``, and the outcome is identical -- nothing happened.

    The fleet is explicitly emptied first. ``capacity_by_cohort`` counts any
    worker that heartbeated recently, and this suite shares a database with
    Phase 3.9's, which registers real ones; without this the test would pass
    or fail depending on which file ran first."""
    from app.models.worker import WorkerRegistration
    from app.runtime.services import _now

    db_session.execute(sa_update(WorkerRegistration)
                       .where(WorkerRegistration.status != "STOPPED")
                       .values(status="STOPPED", active_count=0, stopped_at=_now()))
    db_session.commit()

    setup = _setup(client, admin, candidate_strategy="ROLLING")
    before = _weights(db_session, setup, admin)

    r = _execute(client, admin, setup["green_deployment"]["id"])
    assert r.status_code == 422, r.text
    assert r.json()["error"]["code"] == "ROLLING_COHORT_INVALID"
    # It did nothing at all -- not a partial execution.
    assert _weights(db_session, setup, admin) == before


def test_ac09_no_replica_columns_anywhere_in_the_deployment_package() -> None:
    """The vestigial columns are never read or written by strategy logic --
    which is what makes deferring ROLLING honest rather than lazy.

    Asserts the *bare name*, not just an attribute access, matching Phase 3.1's
    own AC-14 test rather than relaxing it. That is the stricter rule and the
    right one: a module that cannot even name these columns cannot quietly grow
    a rolling handler around them. (3.1's test already covers the whole package;
    this one exists because AC-09 asks this phase to prove it for its own file,
    and because a future reader of *this* suite should see the constraint.)"""
    strategies_source = (Path(__file__).resolve().parents[2] / "app" / "runtime"
                        / "deployment" / "strategies.py").read_text(encoding="utf-8")
    for column in ("desired_replicas", "active_replicas"):
        assert column not in strategies_source, f"strategies.py names {column}"


def test_ac09_the_rolling_handler_is_real_not_a_stub() -> None:
    """AC-16's sharper half, updated by Phase 3.9 to the stricter claim.

    3.6 asserted the deferral was a raised, typed error rather than a
    ``NotImplementedError`` placeholder. 3.9 asserts something harder to
    satisfy: the handler is now a real dispatch into a real service, it is
    registered under its own name, and the placeholder never appeared."""
    source = (Path(__file__).resolve().parents[2] / "app" / "runtime" / "deployment"
              / "strategies.py").read_text(encoding="utf-8")
    assert "NotImplementedError" not in source

    handler = strategies.RollingStrategy()
    assert handler.name == "ROLLING"
    assert strategies.handler_for("ROLLING") is not None
    body = inspect.getsource(handler.execute)
    assert "RollingDeploymentService" in body
    assert "STRATEGY_ROLLING_DEFERRED" not in body


def test_canary_dispatch_points_at_the_rollout_engine(
    client: TestClient, admin: dict,
) -> None:
    setup = _setup(client, admin, candidate_strategy="CANARY")
    r = _execute(client, admin, setup["green_deployment"]["id"])
    assert r.status_code == 422, r.text
    assert "rollouts" in r.json()["error"]["message"]


# --------------------------------------------------------------------------- #
# AC-10 -- kill-switch dominance
# --------------------------------------------------------------------------- #
def test_ac10_kill_switch_halts_a_blue_green_prepare(
    client: TestClient, admin: dict, db_session: Session,
) -> None:
    setup = _setup(client, admin, candidate_strategy="BLUE_GREEN")
    before = _weights(db_session, setup, admin)
    client.post(f"{RT}/kill-switch/agents/{setup['agent']['id']}",
                headers=admin["headers"], json={"reason": "incident"})

    r = _execute(client, admin, setup["green_deployment"]["id"])
    assert r.status_code == 423, r.text
    assert r.json()["error"]["code"] == "KILL_SWITCH_ACTIVE"
    assert _weights(db_session, setup, admin) == before


def test_ac10_kill_switch_halts_the_switch_so_green_is_never_activated(
    client: TestClient, admin: dict, db_session: Session,
) -> None:
    """The sharpest case: GREEN is prepared and ready, then the agent is
    killed. The switch must not activate it."""
    setup = _setup(client, admin, candidate_strategy="BLUE_GREEN")
    _execute(client, admin, setup["green_deployment"]["id"])
    prepared = _weights(db_session, setup, admin)

    client.post(f"{RT}/kill-switch/agents/{setup['agent']['id']}",
                headers=admin["headers"], json={"reason": "incident"})

    r = client.post(f"{RT}/deployments/{setup['green_deployment']['id']}/strategy/blue-green/switch",
                    headers=admin["headers"])
    assert r.status_code == 423, r.text
    assert r.json()["error"]["code"] == "KILL_SWITCH_ACTIVE"
    assert _weights(db_session, setup, admin) == prepared
    assert _weights(db_session, setup, admin)[setup["green"]["id"]] == 0


def test_ac10_recreate_is_halted_by_a_kill_switch(
    client: TestClient, admin: dict, db_session: Session,
) -> None:
    setup = _setup(client, admin, candidate_strategy="RECREATE")
    before = _weights(db_session, setup, admin)
    client.post(f"{RT}/kill-switch/agents/{setup['agent']['id']}",
                headers=admin["headers"], json={"reason": "incident"})

    r = _execute(client, admin, setup["green_deployment"]["id"])
    assert r.status_code == 423, r.text
    assert _weights(db_session, setup, admin) == before


def test_ac10_rollback_still_works_while_killed(
    client: TestClient, admin: dict, db_session: Session,
) -> None:
    """De-escalation must stay reachable: a kill switch must never trap an
    operator on the version they are trying to leave."""
    setup = _setup(client, admin, candidate_strategy="BLUE_GREEN")
    _execute(client, admin, setup["green_deployment"]["id"])
    client.post(f"{RT}/deployments/{setup['green_deployment']['id']}/strategy/blue-green/switch",
                headers=admin["headers"])
    client.post(f"{RT}/kill-switch/agents/{setup['agent']['id']}",
                headers=admin["headers"], json={"reason": "incident"})

    r = client.post(
        f"{RT}/deployments/{setup['green_deployment']['id']}/strategy/blue-green/rollback",
        headers=admin["headers"])
    assert r.status_code == 200, r.text
    assert _weights(db_session, setup, admin)[setup["blue"]["id"]] == 100


# --------------------------------------------------------------------------- #
# AC-11 -- concurrency (real separate Postgres connections)
# --------------------------------------------------------------------------- #
def test_ac11_two_actors_executing_a_strategy_conflict_exactly_once(
    client: TestClient, admin: dict, db_session: Session,
) -> None:
    """Deterministic, not timing-dependent: a real second connection opens a
    transaction, commits a competing allocation, and holds it open, so the
    strategy under test blocks inside Postgres on 3.4's partial unique index
    and loses -- the same pattern Phases 3.4 and 3.5 use."""
    from app.models.runtime import DeploymentTrafficWeight

    setup = _setup(client, admin, candidate_strategy="RECREATE")
    agent_uuid = uuid.UUID(setup["agent"]["id"])
    env_uuid = uuid.UUID(setup["environment"]["id"])

    competitor_ready = threading.Event()
    may_commit = threading.Event()
    competitor_done: list[str] = []

    def _competing_admin() -> None:
        db = SessionLocal()
        try:
            # A freshly-deployed agent has *no* allocation row yet -- 3.4's
            # implicit-100% rule means one is only created when someone first
            # sets weights, which in this setup nobody has. So the competitor
            # may legitimately be creating revision 1.
            traffic = TrafficAllocationService(db)
            current = traffic.current(uuid.UUID(admin["organization_id"]), agent_uuid, env_uuid)
            next_revision = 1
            if current is not None:
                current.is_current = False
                db.flush()
                next_revision = current.revision + 1
            allocation = DeploymentTrafficAllocation(
                organization_id=uuid.UUID(admin["organization_id"]), agent_id=agent_uuid,
                environment_id=env_uuid, revision=next_revision, is_current=True,
                reason="the other operator", created_by=uuid.UUID(admin["user_id"]),
            )
            db.add(allocation)
            db.flush()
            db.add(DeploymentTrafficWeight(
                allocation_id=allocation.id,
                agent_version_id=uuid.UUID(setup["blue"]["id"]),
                deployment_id=uuid.UUID(setup["blue_deployment"]["id"]), weight=100))
            db.flush()
            competitor_ready.set()
            may_commit.wait(timeout=30)
            db.commit()
            competitor_done.append("OK")
        finally:
            db.close()

    competitor = threading.Thread(target=_competing_admin)
    competitor.start()
    assert competitor_ready.wait(timeout=30), "competing transaction never opened"
    threading.Timer(0.75, may_commit.set).start()

    db = SessionLocal()
    try:
        service = DeploymentStrategyService(db)
        actor = db.get(User, uuid.UUID(admin["user_id"]))
        with pytest.raises(IdentityError) as exc:
            service.execute(actor, uuid.UUID(setup["green_deployment"]["id"]))
        assert exc.value.code == ErrorCode.STRATEGY_CONFLICT
    finally:
        db.rollback()
        db.close()

    competitor.join(timeout=30)
    assert competitor_done == ["OK"]

    # The loser left nothing behind: one current allocation, still summing 100.
    db_session.rollback()
    current = db_session.execute(select(DeploymentTrafficAllocation).where(
        DeploymentTrafficAllocation.agent_id == agent_uuid,
        DeploymentTrafficAllocation.is_current.is_(True))).scalars().all()
    assert len(current) == 1
    assert sum(_weights(db_session, setup, admin).values()) == 100


# --------------------------------------------------------------------------- #
# AC-12 -- authorization, tenant isolation, idempotency
# --------------------------------------------------------------------------- #
def test_ac12_strategy_endpoints_require_authentication(
    client: TestClient, admin: dict,
) -> None:
    setup = _setup(client, admin, candidate_strategy="BLUE_GREEN")
    did = setup["green_deployment"]["id"]
    assert client.post(f"{RT}/deployments/{did}/strategy/execute").status_code in (401, 403)
    assert client.post(
        f"{RT}/deployments/{did}/strategy/blue-green/switch").status_code in (401, 403)
    assert client.post(
        f"{RT}/deployments/{did}/strategy/blue-green/rollback").status_code in (401, 403)


def test_ac12_a_viewer_cannot_execute_a_strategy(client: TestClient, admin: dict) -> None:
    from tests.runtime.conftest import PASSWORD

    setup = _setup(client, admin, candidate_strategy="RECREATE")
    email = f"viewer_{uuid.uuid4().hex[:10]}@example.com"
    r = client.post("/api/v1/identity/users", headers=admin["headers"], json={
        "email": email, "display_name": "Viewer", "password": PASSWORD, "role": "VIEWER",
        "organization_id": admin["organization_id"],
    })
    assert r.status_code in (200, 201), r.text
    tokens = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD}).json()
    viewer = {"Authorization": f"Bearer {tokens['access_token']}"}

    r = client.post(f"{RT}/deployments/{setup['green_deployment']['id']}/strategy/execute",
                    headers=viewer)
    assert r.status_code == 403, r.text


def test_ac12_cross_tenant_strategy_execution_is_rejected(
    client: TestClient, admin: dict,
) -> None:
    setup = _setup(client, admin, candidate_strategy="RECREATE")
    other = _second_org(client)

    r = client.post(f"{RT}/deployments/{setup['green_deployment']['id']}/strategy/execute",
                    headers=other["headers"])
    assert r.status_code == 404, r.text
    assert r.json()["error"]["code"] == "DEPLOYMENT_NOT_FOUND"


def test_ac12_idempotency_key_is_honoured_on_strategy_execute(
    client: TestClient, admin: dict, db_session: Session,
) -> None:
    setup = _setup(client, admin, candidate_strategy="RECREATE")
    headers = {**admin["headers"], "Idempotency-Key": f"strategy-{uuid.uuid4().hex[:12]}"}
    before = _allocation_count(db_session, setup)

    first = _execute(client, admin, setup["green_deployment"]["id"], headers=headers)
    second = _execute(client, admin, setup["green_deployment"]["id"], headers=headers)
    assert first.status_code == 200 and second.status_code == 200, second.text
    assert first.json() == second.json()
    # Replayed, not re-applied: only one new allocation revision.
    assert _allocation_count(db_session, setup) == before + 1


def test_ac12_idempotency_key_is_honoured_on_the_blue_green_switch(
    client: TestClient, admin: dict, db_session: Session,
) -> None:
    setup = _setup(client, admin, candidate_strategy="BLUE_GREEN")
    _execute(client, admin, setup["green_deployment"]["id"])
    before = _allocation_count(db_session, setup)
    url = f"{RT}/deployments/{setup['green_deployment']['id']}/strategy/blue-green/switch"
    headers = {**admin["headers"], "Idempotency-Key": f"switch-{uuid.uuid4().hex[:12]}"}

    first = client.post(url, headers=headers)
    second = client.post(url, headers=headers)
    assert first.status_code == 200 and second.status_code == 200, second.text
    assert first.json() == second.json()
    assert _allocation_count(db_session, setup) == before + 1


# --------------------------------------------------------------------------- #
# AC-16 -- no stub markers
# --------------------------------------------------------------------------- #
def test_ac16_no_stub_markers_in_this_phases_files() -> None:
    source = (Path(__file__).resolve().parents[2] / "app" / "runtime" / "deployment"
              / "strategies.py").read_text(encoding="utf-8")
    for banned in ("TODO", "FIXME", "NotImplementedError", "xfail", "pytest.skip"):
        assert banned not in source, f"strategies.py contains {banned}"
