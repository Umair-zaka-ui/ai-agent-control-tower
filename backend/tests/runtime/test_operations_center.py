"""Phase 3.10 (ACT-SRS-M3 §Phase-3.10, §22) backend tests -- the four
read-model endpoints behind the Release Operations Center.

The whole point of this phase is that it adds **no domain logic**, so the
sharpest tests here are the ones that prove absence: that the read-model
module never writes, that these routes cannot change anything, and that
nothing about the deployment engines moved. The rest verify the two
properties a read model can still get wrong -- tenant isolation, and telling
the truth about unsafe state.
"""

from __future__ import annotations

import ast
import uuid
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.agent import Agent
from app.models.runtime import AgentDeployment
from app.runtime import operations as operations_module

RT = "/api/v1/runtime"


# --------------------------------------------------------------------------- #
# Setup helpers (this suite's convention: each file defines its own)
# --------------------------------------------------------------------------- #
def _register_agent(client: TestClient, admin: dict) -> dict:
    nonce = uuid.uuid4().hex[:8]
    r = client.post(f"{RT}/agents", headers=admin["headers"], json={
        "name": f"Ops Agent {nonce}", "agent_type": "ASSISTANT", "criticality": "MEDIUM",
        "description": f"Test agent {nonce}.",
        "business_purpose": f"Exercise the operations center {nonce} in tests.",
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


def _lifecycle_deploy(client: TestClient, admin: dict, agent_id: str, version_id: str) -> dict:
    r = client.post(f"{RT}/deployments", headers=admin["headers"], params={"agent_id": agent_id},
                    json={"agent_version_id": version_id, "environment": "DEVELOPMENT"})
    assert r.status_code == 201, r.text
    deployment = r.json()
    for to_state in ("VALIDATING", "READY", "DEPLOYING"):
        r = client.post(f"{RT}/deployments/{deployment['id']}/lifecycle/transition",
                        headers=admin["headers"], json={"to_state": to_state})
        assert r.status_code == 200, r.text
        deployment = r.json()
    assert deployment["lifecycle_state"] == "ACTIVE", deployment
    return deployment


def _setup(client: TestClient, admin: dict) -> dict:
    # Environments are resolved BEFORE deploying, matching every other
    # Milestone 3 suite. A deployment created before the organization's
    # governed environments exist gets a null ``environment_id`` and is
    # invisible to traffic, rollouts and the environment matrix -- which is
    # what a first draft of this helper discovered the hard way.
    envs = {e["name"]: e for e in client.get(f"{RT}/environments",
                                             headers=admin["headers"]).json()}
    agent = _register_agent(client, admin)
    _activate_agent(client, admin, agent["id"])
    stable = _publish_version(client, admin, agent["id"])
    candidate = _publish_version(client, admin, agent["id"])
    stable_deployment = _lifecycle_deploy(client, admin, agent["id"], stable["id"])
    candidate_deployment = _lifecycle_deploy(client, admin, agent["id"], candidate["id"])
    return {"agent": agent, "stable": stable, "candidate": candidate,
            "stable_deployment": stable_deployment,
            "candidate_deployment": candidate_deployment,
            "environment": envs["DEVELOPMENT"]}


def _second_org(client: TestClient) -> dict:
    from tests.runtime.conftest import PASSWORD

    email = f"ops_other_{uuid.uuid4().hex[:10]}@example.com"
    assert client.post("/auth/register", json={
        "organization_name": "Other Ops Org", "name": "Owner",
        "email": email, "password": PASSWORD,
    }).status_code == 201
    tokens = client.post("/api/v1/auth/login",
                         json={"email": email, "password": PASSWORD}).json()
    return {"headers": {"Authorization": f"Bearer {tokens['access_token']}"}}


def _reviewer(client: TestClient, admin: dict) -> dict:
    from tests.runtime.conftest import PASSWORD

    email = f"ops_viewer_{uuid.uuid4().hex[:10]}@example.com"
    r = client.post("/api/v1/identity/users", headers=admin["headers"], json={
        "email": email, "display_name": "Viewer", "password": PASSWORD, "role": "VIEWER",
        "organization_id": admin["organization_id"],
    })
    assert r.status_code in (200, 201), r.text
    tokens = client.post("/api/v1/auth/login",
                         json={"email": email, "password": PASSWORD}).json()
    return {"headers": {"Authorization": f"Bearer {tokens['access_token']}"}}


def _row_for(body: dict, deployment_id: str) -> dict:
    matches = [r for r in body["deployments"] if r["deployment_id"] == deployment_id]
    assert matches, f"{deployment_id} missing from overview"
    return matches[0]


# --------------------------------------------------------------------------- #
# AC-14 -- the endpoints are read-only, and structurally so
# --------------------------------------------------------------------------- #
def test_ac14_the_read_model_module_never_writes() -> None:
    """Structural, over the AST: the Operations Center adds no domain logic.

    A read model that could write would be a second place deployment state
    changes from -- exactly the thing Phases 3.1-3.9 spent nine sub-phases
    making singular. Checked as *calls*, not as words, because this module's
    docstrings necessarily discuss committing and writing while explaining
    that it does neither."""
    tree = ast.parse(Path(operations_module.__file__).read_text(encoding="utf-8"))
    called = {node.func.attr for node in ast.walk(tree)
              if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)}
    for forbidden in ("add", "add_all", "commit", "delete", "flush", "merge", "execute_many"):
        assert forbidden not in called, f"operations.py calls {forbidden}()"


def test_ac14_the_read_model_imports_no_mutating_service() -> None:
    """It may not even reach the engines that change things -- the UI calls
    those endpoints directly, so a read model holding a reference to one would
    be a bypass waiting to be used."""
    source = Path(operations_module.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            imported.update(alias.name for alias in node.names)
    for forbidden in ("DeploymentLifecycleService", "CanaryRolloutService", "RollbackService",
                      "TrafficAllocationService", "DeploymentStrategyService",
                      "PromotionService", "WorkerFleetService", "SchedulerService",
                      "RollingDeploymentService", "KillSwitchService"):
        assert forbidden not in imported, f"operations.py imports {forbidden}"


def test_ac14_the_operations_routes_are_all_get() -> None:
    from fastapi.routing import APIRoute

    from app.main import app

    routes = [r for r in app.routes
              if isinstance(r, APIRoute) and "/operations/" in r.path]
    assert routes, "the operations read models are not mounted"
    for route in routes:
        assert route.methods - {"HEAD", "OPTIONS"} == {"GET"}, f"{route.path} is not read-only"


def test_ac14_the_endpoints_require_a_view_permission(
    client: TestClient, admin: dict,
) -> None:
    for path in (f"{RT}/operations/overview", f"{RT}/operations/release-history",
                 f"{RT}/rollouts"):
        assert client.get(path).status_code in (401, 403), path


def test_ac11_a_user_without_deployment_view_is_refused(
    client: TestClient, admin: dict,
) -> None:
    """The read models are gated on ``runtime.deployment.view`` -- the same
    permission the deployment list already uses, not a new one.

    A VIEWER does not hold it (``SYSTEM_ROLE_PERMISSIONS``'s read-only set is
    deliberately narrow and does not include the runtime catalog), which makes
    this the honest demonstration that the server, not the UI, is the
    authority: the request is refused server-side whatever the browser
    rendered."""
    _setup(client, admin)
    viewer = _reviewer(client, admin)
    for path in (f"{RT}/operations/overview", f"{RT}/operations/release-history",
                 f"{RT}/rollouts"):
        assert client.get(path, headers=viewer["headers"]).status_code == 403, path


# --------------------------------------------------------------------------- #
# AC-01 -- overview + environment matrix
# --------------------------------------------------------------------------- #
def test_ac01_overview_returns_enriched_rows(
    client: TestClient, admin: dict,
) -> None:
    setup = _setup(client, admin)
    r = client.get(f"{RT}/operations/overview", headers=admin["headers"])
    assert r.status_code == 200, r.text
    body = r.json()

    row = _row_for(body, setup["candidate_deployment"]["id"])
    assert row["agent_name"] == setup["agent"]["name"]
    assert row["environment_name"] == "DEVELOPMENT"
    assert row["version"]["semantic_version"] == setup["candidate"]["semantic_version"]
    assert row["lifecycle_state"] == "ACTIVE"
    assert row["servable"] is True
    assert body["environments"], "the matrix needs its environment axis"
    assert body["summary"]["total"] >= 2


def test_ac01_overview_filters_by_environment(
    client: TestClient, admin: dict,
) -> None:
    setup = _setup(client, admin)
    r = client.get(f"{RT}/operations/overview", headers=admin["headers"],
                   params={"environment_id": setup["environment"]["id"]})
    assert r.status_code == 200, r.text
    rows = r.json()["deployments"]
    assert rows
    assert {row["environment_name"] for row in rows} == {"DEVELOPMENT"}


def test_ac13_overview_never_shows_another_tenants_deployments(
    client: TestClient, admin: dict,
) -> None:
    setup = _setup(client, admin)
    other = _second_org(client)
    body = client.get(f"{RT}/operations/overview", headers=other["headers"]).json()
    ids = {row["deployment_id"] for row in body["deployments"]}
    assert setup["candidate_deployment"]["id"] not in ids
    assert setup["stable_deployment"]["id"] not in ids


# --------------------------------------------------------------------------- #
# AC-02 -- the detail composite, including immutable version identity
# --------------------------------------------------------------------------- #
def test_ac02_detail_carries_the_section_22_field_set(
    client: TestClient, admin: dict,
) -> None:
    setup = _setup(client, admin)
    deployment_id = setup["candidate_deployment"]["id"]
    r = client.get(f"{RT}/operations/deployments/{deployment_id}", headers=admin["headers"])
    assert r.status_code == 200, r.text
    body = r.json()

    for field in ("agent", "version", "environment", "deployment_strategy", "lifecycle_state",
                  "rollout", "allocation", "release_health", "gate", "approvals",
                  "initiated_by", "deployed_at", "duration_seconds", "timeline",
                  "rollback_target", "kill_switch_active", "servable"):
        assert field in body, f"detail is missing §22 field {field}"

    assert body["agent"]["name"] == setup["agent"]["name"]
    assert body["timeline"], "the lifecycle transitions should be reconstructable"
    assert {e["kind"] for e in body["timeline"]} <= {"LIFECYCLE", "ROLLBACK"}


def test_ac02_detail_surfaces_immutable_version_identity(
    client: TestClient, admin: dict,
) -> None:
    """M3-3.10-FR-024 -- an operator must be able to see that what is running
    is the signed, reviewed artifact."""
    setup = _setup(client, admin)
    body = client.get(f"{RT}/operations/deployments/{setup['candidate_deployment']['id']}",
                      headers=admin["headers"]).json()
    version = body["version"]
    assert version["checksum"], "the immutable checksum must be surfaced"
    assert version["checksum_algorithm"]
    assert version["signature_state"] in ("SIGNED", "UNSIGNED")
    # The collapsed state must agree with the raw columns rather than being a
    # separate claim about them.
    signed = version["signature_id"] is not None and version["signed_at"] is not None
    assert version["signature_state"] == ("SIGNED" if signed else "UNSIGNED")


def test_ac13_detail_refuses_another_tenants_deployment(
    client: TestClient, admin: dict,
) -> None:
    setup = _setup(client, admin)
    other = _second_org(client)
    r = client.get(f"{RT}/operations/deployments/{setup['candidate_deployment']['id']}",
                   headers=other["headers"])
    assert r.status_code == 404, r.text
    assert r.json()["error"]["code"] == "DEPLOYMENT_NOT_FOUND"


# --------------------------------------------------------------------------- #
# AC-10 -- truthful state
# --------------------------------------------------------------------------- #
def test_ac10_an_active_kill_switch_is_reported_not_hidden(
    client: TestClient, admin: dict, db_session: Session,
) -> None:
    """§10's absolute rule for this phase: the UI can only show what the read
    model tells it, so a read model that omitted a kill switch would *make*
    the UI present a killed release as deployable."""
    setup = _setup(client, admin)
    assert client.post(f"{RT}/kill-switch/agents/{setup['agent']['id']}",
                       headers=admin["headers"],
                       json={"reason": "Incident."}).status_code == 200

    body = client.get(f"{RT}/operations/overview", headers=admin["headers"]).json()
    row = _row_for(body, setup["candidate_deployment"]["id"])
    assert row["kill_switch_active"] is True
    assert row["agent_lifecycle_status"] == "SUSPENDED"
    assert body["summary"]["kill_switched"] >= 1

    detail = client.get(f"{RT}/operations/deployments/{setup['candidate_deployment']['id']}",
                        headers=admin["headers"]).json()
    assert detail["kill_switch_active"] is True

    db_session.rollback()
    assert db_session.get(Agent, uuid.UUID(setup["agent"]["id"])).lifecycle_status == "SUSPENDED"


def test_ac10_a_block_verdict_is_reported(
    client: TestClient, admin: dict,
) -> None:
    setup = _setup(client, admin)
    # A kill switch produces a BLOCK finding in the release gate (Phase 3.3).
    assert client.post(f"{RT}/kill-switch/agents/{setup['agent']['id']}",
                       headers=admin["headers"],
                       json={"reason": "Incident."}).status_code == 200
    deployment_id = setup["candidate_deployment"]["id"]
    assert client.post(f"{RT}/deployments/{deployment_id}/preflight",
                       headers=admin["headers"]).status_code == 200

    body = client.get(f"{RT}/operations/overview", headers=admin["headers"]).json()
    assert _row_for(body, deployment_id)["gate_verdict"] == "BLOCK"
    assert body["summary"]["blocked"] >= 1

    detail = client.get(f"{RT}/operations/deployments/{deployment_id}",
                        headers=admin["headers"]).json()
    assert detail["gate"]["verdict"] == "BLOCK"
    assert detail["gate"]["findings"], "a BLOCK with no findings is unactionable"


def test_ac10_non_proving_health_is_flagged_as_such(
    client: TestClient, admin: dict,
) -> None:
    """INSUFFICIENT_DATA and UNKNOWN are the absence of evidence, and the read
    model hands that distinction over explicitly rather than leaving a screen
    to infer it from a string."""
    assert "INSUFFICIENT_DATA" in operations_module.NON_PROVING_HEALTH
    assert "UNKNOWN" in operations_module.NON_PROVING_HEALTH
    assert operations_module.OperationsReadModel._health_shape(None) is None

    class _Evaluation:
        health_state = "INSUFFICIENT_DATA"
        sample_count = 0
        metrics: dict = {}
        evaluated_at = None

    shaped = operations_module.OperationsReadModel._health_shape(_Evaluation())
    assert shaped["is_proving"] is False

    class _Healthy(_Evaluation):
        health_state = "HEALTHY"
        sample_count = 50

    assert operations_module.OperationsReadModel._health_shape(_Healthy())["is_proving"] is True


# --------------------------------------------------------------------------- #
# AC-03 -- the rollout list Phase 3.5 never had
# --------------------------------------------------------------------------- #
def test_ac03_rollouts_are_discoverable(
    client: TestClient, admin: dict,
) -> None:
    setup = _setup(client, admin)
    r = client.post(
        f"{RT}/agents/{setup['agent']['id']}/environments/{setup['environment']['id']}/rollouts",
        headers=admin["headers"], json={
            "candidate_version_id": setup["candidate"]["id"],
            "stages": [{"target_weight": 25, "health_requirement": "NONE"},
                       {"target_weight": 100, "health_requirement": "NONE"}],
        })
    assert r.status_code in (200, 201), r.text
    rollout_id = r.json()["id"]

    listed = client.get(f"{RT}/rollouts", headers=admin["headers"])
    assert listed.status_code == 200, listed.text
    rows = {row["id"]: row for row in listed.json()}
    assert rollout_id in rows, "a rollout that exists must be findable"
    row = rows[rollout_id]
    assert row["kind"] == "CANARY"
    assert row["stage_count"] == 2
    assert row["is_live"] is True
    assert row["agent_name"] == setup["agent"]["name"]
    assert row["candidate_version"] == setup["candidate"]["semantic_version"]

    active = client.get(f"{RT}/rollouts", headers=admin["headers"],
                        params={"active_only": True}).json()
    assert rollout_id in {row["id"] for row in active}


def test_ac13_rollouts_are_tenant_scoped(
    client: TestClient, admin: dict,
) -> None:
    setup = _setup(client, admin)
    r = client.post(
        f"{RT}/agents/{setup['agent']['id']}/environments/{setup['environment']['id']}/rollouts",
        headers=admin["headers"], json={
            "candidate_version_id": setup["candidate"]["id"],
            "stages": [{"target_weight": 100, "health_requirement": "NONE"}],
        })
    assert r.status_code in (200, 201), r.text
    rollout_id = r.json()["id"]

    other = _second_org(client)
    rows = client.get(f"{RT}/rollouts", headers=other["headers"]).json()
    assert rollout_id not in {row["id"] for row in rows}


# --------------------------------------------------------------------------- #
# AC-01 -- release history
# --------------------------------------------------------------------------- #
def test_ac01_release_history_reconstructs_the_timeline(
    client: TestClient, admin: dict,
) -> None:
    setup = _setup(client, admin)
    r = client.get(f"{RT}/operations/release-history", headers=admin["headers"])
    assert r.status_code == 200, r.text
    entries = r.json()
    assert entries, "lifecycle transitions should appear in the release history"

    mine = [e for e in entries if e["deployment_id"] == setup["candidate_deployment"]["id"]]
    assert mine, "this deployment's transitions are missing"
    assert {e["kind"] for e in entries} <= {"LIFECYCLE", "ROLLBACK"}
    assert all(e["agent_name"] for e in mine)
    # Newest first.
    stamps = [e["occurred_at"] for e in entries if e["occurred_at"]]
    assert stamps == sorted(stamps, reverse=True)


def test_ac01_release_history_filters_by_agent(
    client: TestClient, admin: dict,
) -> None:
    setup = _setup(client, admin)
    entries = client.get(f"{RT}/operations/release-history", headers=admin["headers"],
                         params={"agent_id": setup["agent"]["id"]}).json()
    assert entries
    assert {e["agent_id"] for e in entries} == {setup["agent"]["id"]}


def test_ac13_release_history_is_tenant_scoped(
    client: TestClient, admin: dict,
) -> None:
    setup = _setup(client, admin)
    other = _second_org(client)
    entries = client.get(f"{RT}/operations/release-history", headers=other["headers"]).json()
    assert setup["candidate_deployment"]["id"] not in {e["deployment_id"] for e in entries}


# --------------------------------------------------------------------------- #
# AC-13 -- no secret reaches the UI
# --------------------------------------------------------------------------- #
def test_ac13_no_secret_material_in_any_operations_payload(
    client: TestClient, admin: dict,
) -> None:
    setup = _setup(client, admin)
    blob = ""
    for path in (f"{RT}/operations/overview", f"{RT}/operations/release-history",
                 f"{RT}/rollouts",
                 f"{RT}/operations/deployments/{setup['candidate_deployment']['id']}"):
        r = client.get(path, headers=admin["headers"])
        assert r.status_code == 200, path
        blob += r.text

    lowered = blob.lower()
    for marker in ("password", "secret", "api_key", "private_key", "access_token",
                   "client_secret"):
        assert marker not in lowered, f"{marker} appears in an operations payload"


# --------------------------------------------------------------------------- #
# AC-15 -- nothing about the engines moved
# --------------------------------------------------------------------------- #
def test_ac15_phase_310_added_no_deployment_logic() -> None:
    """The read-and-trigger principle, asserted against ``main``.

    Every deployment engine must be byte-identical: this phase visualizes and
    triggers, it never reimplements. Unlike Phase 3.7's version of this guard,
    the list is safe against a moving ``main`` -- 3.10 is the last sub-phase of
    the milestone, and an empty diff stays empty after the merge."""
    import subprocess

    repo = Path(__file__).resolve().parents[3]
    protected = [
        "backend/app/runtime/deployment/resolver.py",
        "backend/app/runtime/deployment/traffic.py",
        "backend/app/runtime/deployment/canary.py",
        "backend/app/runtime/deployment/rollout.py",
        "backend/app/runtime/deployment/health.py",
        "backend/app/runtime/deployment/strategies.py",
        "backend/app/runtime/deployment/rollback.py",
        "backend/app/runtime/deployment/rolling.py",
        "backend/app/runtime/deployment/lifecycle.py",
        "backend/app/workers/fleet.py",
        "backend/app/workers/worker.py",
        "backend/app/scheduler/service.py",
    ]
    result = subprocess.run(
        ["git", "diff", "--name-only", "main", "--", *protected],
        cwd=repo, capture_output=True, text=True, check=False)
    assert result.stdout.strip() == "", f"modified: {result.stdout}"


def test_ac15_no_migration_was_added() -> None:
    """This phase reads existing data; a new table would mean it had invented
    domain state."""
    versions = sorted(p.name for p in
                      (Path(__file__).resolve().parents[2] / "migrations" / "versions").glob("*.py"))
    assert versions[-1] == "0044_worker_fleet_rolling.py", versions[-1]


def test_ac16_no_placeholder_markers_in_the_new_code() -> None:
    """Built by concatenation so this list does not match itself."""
    markers = ("TO" + "DO", "FIX" + "ME", "NotImplemented" + "Error",
               "@pytest.mark." + "skip", "@pytest.mark." + "xfail")
    source = Path(operations_module.__file__).read_text(encoding="utf-8")
    for marker in markers:
        assert marker not in source, f"operations.py contains {marker}"


def test_the_overview_does_not_scale_its_query_count_with_row_count(
    client: TestClient, admin: dict, db_session: Session,
) -> None:
    """The reason this endpoint exists at all.

    Rendering the overview client-side would cost roughly five extra requests
    per deployment. This asserts the server side does not have the same shape
    internally -- the query count must be flat, not proportional to rows."""
    from sqlalchemy import event

    from app.core.database import SessionLocal
    from app.models.user import User
    from app.runtime.operations import OperationsReadModel

    _setup(client, admin)
    _setup(client, admin)  # a second agent, four deployments in total

    db = SessionLocal()
    counter = {"n": 0}

    def _count(conn, cursor, statement, parameters, context, executemany):
        counter["n"] += 1

    event.listen(db.bind, "before_cursor_execute", _count)
    try:
        actor = db.get(User, uuid.UUID(admin["user_id"]))
        body = OperationsReadModel(db).overview(actor)
        assert len(body["deployments"]) >= 4
    finally:
        event.remove(db.bind, "before_cursor_execute", _count)
        db.rollback()
        db.close()

    # Seven batch loads plus the actor fetch, with generous headroom -- the
    # property under test is "flat", not an exact number that would break on
    # any future field addition.
    assert counter["n"] <= 15, f"overview issued {counter['n']} queries; it should batch"


def test_the_operations_routes_do_not_collide_with_existing_paths() -> None:
    """``/operations/overview`` sits under a literal segment rather than being
    swallowed by ``/deployments/{deployment_id}``, and ``/rollouts`` does not
    shadow ``/rollouts/{rollout_id}``."""
    from fastapi.routing import APIRoute

    from app.main import app

    paths = [r.path for r in app.routes if isinstance(r, APIRoute)]
    assert paths.count(f"{RT}/rollouts") == 1
    assert f"{RT}/rollouts/{{rollout_id}}" in paths
    assert f"{RT}/operations/overview" in paths
    # The M1 worker endpoints and the 3.9 fleet endpoints both survive.
    assert f"{RT}/workers" in paths
    assert f"{RT}/fleet" in paths


def test_a_retired_deployment_is_reported_as_not_servable(
    client: TestClient, admin: dict, db_session: Session,
) -> None:
    """``servable`` is Phase 3.4's own union-with-veto predicate, reported
    rather than re-derived in the browser -- two implementations of "is this
    actually serving?" would eventually disagree."""
    setup = _setup(client, admin)
    deployment_id = setup["stable_deployment"]["id"]
    r = client.post(f"{RT}/deployments/{deployment_id}/lifecycle/retire",
                    headers=admin["headers"], json={"reason": "Superseded."})
    assert r.status_code == 200, r.text

    body = client.get(f"{RT}/operations/overview", headers=admin["headers"]).json()
    assert _row_for(body, deployment_id)["servable"] is False

    db_session.rollback()
    deployment = db_session.get(AgentDeployment, uuid.UUID(deployment_id))
    assert deployment.lifecycle_state == "RETIRED"
