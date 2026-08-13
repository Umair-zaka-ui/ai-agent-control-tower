"""Phase 3.4 (ACT-SRS-M3 §Phase-3.4) tests -- weighted traffic allocation,
the hot-path version resolver, and ruling #4's execution gate.

Grouped by the build prompt's own §12 acceptance criteria. Real Postgres
throughout (this suite's established convention -- ``tests/runtime/
conftest.py``), including the AC-13 race, which uses real separate
``SessionLocal()`` connections and threads rather than an in-process mutex
(mirroring ``test_deployment_lifecycle.py``'s own precedent).

**On the two deployment machines.** Helpers here deliberately use *both*
activation routes, because the resolver's union-with-veto predicate is only
meaningfully tested if both are represented:

- ``_legacy_deploy`` -> ``POST /deployments/{id}/deploy``, the Milestone 1
  route: leaves ``status=ACTIVE``, ``lifecycle_state=DRAFT``. Every pre-3.4
  execution test in this codebase reaches execution this way, so AC-11's
  "still executable" claim is about exactly these rows.
- ``_lifecycle_deploy`` -> the 3.1 lifecycle route: leaves ``status=CREATED``,
  ``lifecycle_state=ACTIVE``, and (unlike the legacy route's RECREATE, and
  unlike promotion) does not retire or supersede its siblings -- which is
  what lets several versions of one agent serve one environment at once,
  the precondition for weighted allocation.
"""

from __future__ import annotations

import threading
import time
import uuid
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
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
    AgentVersion,
    DeploymentTrafficAllocation,
    DeploymentTrafficWeight,
)
from app.runtime.deployment.resolver import VersionResolver, select_weighted
from app.runtime.deployment.traffic import TrafficAllocationService, is_servable

RT = "/api/v1/runtime"


# --------------------------------------------------------------------------- #
# HTTP setup helpers (this suite's convention: each file defines its own)
# --------------------------------------------------------------------------- #
def _register_agent(client: TestClient, admin: dict, *, criticality: str = "MEDIUM") -> dict:
    # Every field that duplicate detection looks at is made unique per call:
    # two agents in one organization are registered by several tests here,
    # and a near-identical name/description/purpose trips the §duplicate
    # review gate (409) rather than activating.
    nonce = uuid.uuid4().hex[:8]
    r = client.post(f"{RT}/agents", headers=admin["headers"], json={
        "name": f"Traffic Agent {nonce}", "agent_type": "ASSISTANT",
        "criticality": criticality, "description": f"Test agent {nonce}.",
        "business_purpose": f"Exercise traffic allocation {nonce} in tests.",
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
        r = client.post(f"{RT}/agents/{agent_id}/versions/{version['id']}/{step}", headers=admin["headers"])
        assert r.status_code == 200, r.text
    return r.json()


def _create_deployment(client: TestClient, admin: dict, agent_id: str, version_id: str, *,
                      environment: str = "DEVELOPMENT") -> dict:
    r = client.post(f"{RT}/deployments", headers=admin["headers"], params={"agent_id": agent_id},
                    json={"agent_version_id": version_id, "environment": environment})
    assert r.status_code == 201, r.text
    return r.json()


def _lifecycle_deploy(client: TestClient, admin: dict, agent_id: str, version_id: str, *,
                     environment: str = "DEVELOPMENT") -> dict:
    """The 3.1 route: lifecycle_state=ACTIVE, status untouched, siblings
    left alone -- see this module's docstring."""
    deployment = _create_deployment(client, admin, agent_id, version_id, environment=environment)
    for to_state in ("VALIDATING", "READY", "DEPLOYING"):
        r = client.post(f"{RT}/deployments/{deployment['id']}/lifecycle/transition",
                        headers=admin["headers"], json={"to_state": to_state})
        assert r.status_code == 200, r.text
        deployment = r.json()
    assert deployment["lifecycle_state"] == "ACTIVE", deployment
    return deployment


def _legacy_deploy(client: TestClient, admin: dict, agent_id: str, version_id: str, *,
                  environment: str = "DEVELOPMENT") -> dict:
    """The Milestone 1 route: status=ACTIVE, lifecycle_state=DRAFT."""
    deployment = _create_deployment(client, admin, agent_id, version_id, environment=environment)
    r = client.post(f"{RT}/deployments/{deployment['id']}/deploy", headers=admin["headers"])
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "ACTIVE"
    return r.json()


def _environments(client: TestClient, admin: dict) -> dict[str, dict]:
    r = client.get(f"{RT}/environments", headers=admin["headers"])
    assert r.status_code == 200, r.text
    return {e["name"]: e for e in r.json()}


def _setup(client: TestClient, admin: dict) -> dict:
    envs = _environments(client, admin)
    agent = _register_agent(client, admin)
    _activate_agent(client, admin, agent["id"])
    version = _publish_version(client, admin, agent["id"])
    return {"agent": agent, "version": version, "environments": envs}


def _two_serving_versions(client: TestClient, admin: dict) -> dict:
    """One agent, two published versions, both serving DEVELOPMENT
    simultaneously -- the precondition for a weighted split."""
    setup = _setup(client, admin)
    version_a = setup["version"]
    version_b = _publish_version(client, admin, setup["agent"]["id"])
    deployment_a = _lifecycle_deploy(client, admin, setup["agent"]["id"], version_a["id"])
    deployment_b = _lifecycle_deploy(client, admin, setup["agent"]["id"], version_b["id"])
    return {**setup, "version_a": version_a, "version_b": version_b,
            "deployment_a": deployment_a, "deployment_b": deployment_b,
            "environment": setup["environments"]["DEVELOPMENT"]}


def _traffic_url(agent_id: str, environment_id: str, suffix: str = "") -> str:
    return f"{RT}/agents/{agent_id}/environments/{environment_id}/traffic{suffix}"


def _set_traffic(client: TestClient, admin: dict, agent_id: str, environment_id: str,
                weights: list[dict], **kwargs) -> tuple[dict, int]:
    r = client.put(_traffic_url(agent_id, environment_id), headers=admin["headers"],
                   json={"weights": weights, **kwargs})
    return r.json(), r.status_code


def _execute(client: TestClient, admin: dict, agent_id: str, **body) -> tuple[dict, int]:
    r = client.post(f"{RT}/executions", headers=admin["headers"],
                    json={"agent_id": agent_id, "input_payload": {"message": "hi"}, **body})
    return r.json(), r.status_code


def _second_org(client: TestClient) -> dict:
    from tests.runtime.conftest import PASSWORD

    email = f"traffic_other_{uuid.uuid4().hex[:10]}@example.com"
    assert client.post("/auth/register", json={
        "organization_name": "Other Org", "name": "Owner", "email": email, "password": PASSWORD,
    }).status_code == 201
    tokens = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD}).json()
    me = client.get("/api/v1/auth/me",
                    headers={"Authorization": f"Bearer {tokens['access_token']}"}).json()
    return {"headers": {"Authorization": f"Bearer {tokens['access_token']}"},
            "user_id": me["user"]["id"], "organization_id": me["user"]["organization_id"],
            "email": email}


# --------------------------------------------------------------------------- #
# AC-01 -- weights total exactly 100
# --------------------------------------------------------------------------- #
def test_ac01_weights_must_total_exactly_100(client: TestClient, admin: dict) -> None:
    setup = _two_serving_versions(client, admin)
    agent_id, env_id = setup["agent"]["id"], setup["environment"]["id"]

    for weights in (
        [{"agent_version_id": setup["version_a"]["id"], "weight": 90},
         {"agent_version_id": setup["version_b"]["id"], "weight": 5}],       # 95
        [{"agent_version_id": setup["version_a"]["id"], "weight": 90},
         {"agent_version_id": setup["version_b"]["id"], "weight": 20}],      # 110
        [{"agent_version_id": setup["version_a"]["id"], "weight": 0},
         {"agent_version_id": setup["version_b"]["id"], "weight": 0}],       # 0
    ):
        body, code = _set_traffic(client, admin, agent_id, env_id, weights)
        assert code == 422, body
        assert body["error"]["code"] == "TRAFFIC_WEIGHTS_INVALID", body

    body, code = _set_traffic(client, admin, agent_id, env_id, [
        {"agent_version_id": setup["version_a"]["id"], "weight": 90},
        {"agent_version_id": setup["version_b"]["id"], "weight": 10},
    ])
    assert code == 200, body
    assert sum(w["weight"] for w in body["weights"]) == 100


def test_ac01_a_version_may_not_appear_twice(client: TestClient, admin: dict) -> None:
    setup = _two_serving_versions(client, admin)
    body, code = _set_traffic(client, admin, setup["agent"]["id"], setup["environment"]["id"], [
        {"agent_version_id": setup["version_a"]["id"], "weight": 50},
        {"agent_version_id": setup["version_a"]["id"], "weight": 50},
    ])
    assert code == 422, body
    assert body["error"]["code"] == "TRAFFIC_WEIGHTS_INVALID"


# --------------------------------------------------------------------------- #
# AC-02 -- only eligible versions may receive weight
# --------------------------------------------------------------------------- #
def test_ac02_unpublished_version_is_not_eligible(client: TestClient, admin: dict) -> None:
    setup = _two_serving_versions(client, admin)
    r = client.post(f"{RT}/agents/{setup['agent']['id']}/versions", headers=admin["headers"],
                    json={"model_configuration": {"provider": "MOCK", "model": "mock-model"}})
    draft = r.json()

    body, code = _set_traffic(client, admin, setup["agent"]["id"], setup["environment"]["id"], [
        {"agent_version_id": setup["version_a"]["id"], "weight": 50},
        {"agent_version_id": draft["id"], "weight": 50},
    ])
    assert code == 422, body
    assert body["error"]["code"] == "VERSION_NOT_ELIGIBLE", body


def test_ac02_version_without_an_active_deployment_is_not_eligible(
    client: TestClient, admin: dict,
) -> None:
    """Published and signed, but never deployed into this environment -- the
    "backed by an active deployment" half of eligibility."""
    setup = _two_serving_versions(client, admin)
    undeployed = _publish_version(client, admin, setup["agent"]["id"])

    body, code = _set_traffic(client, admin, setup["agent"]["id"], setup["environment"]["id"], [
        {"agent_version_id": setup["version_a"]["id"], "weight": 50},
        {"agent_version_id": undeployed["id"], "weight": 50},
    ])
    assert code == 422, body
    assert body["error"]["code"] == "VERSION_NOT_ELIGIBLE", body


def test_ac02_another_agents_version_is_not_eligible(client: TestClient, admin: dict) -> None:
    setup = _two_serving_versions(client, admin)
    other = _setup(client, admin)

    body, code = _set_traffic(client, admin, setup["agent"]["id"], setup["environment"]["id"], [
        {"agent_version_id": setup["version_a"]["id"], "weight": 50},
        {"agent_version_id": other["version"]["id"], "weight": 50},
    ])
    assert code == 422, body
    assert body["error"]["code"] == "VERSION_NOT_ELIGIBLE", body


# --------------------------------------------------------------------------- #
# AC-03 -- atomic updates; a partial/invalid state is never observable
# --------------------------------------------------------------------------- #
def test_ac03_a_rejected_update_leaves_the_previous_allocation_intact(
    client: TestClient, admin: dict, db_session: Session,
) -> None:
    setup = _two_serving_versions(client, admin)
    agent_id, env_id = setup["agent"]["id"], setup["environment"]["id"]
    good, code = _set_traffic(client, admin, agent_id, env_id, [
        {"agent_version_id": setup["version_a"]["id"], "weight": 70},
        {"agent_version_id": setup["version_b"]["id"], "weight": 30},
    ])
    assert code == 200, good

    # An invalid follow-up: correct sum, but one ineligible version. It must
    # not partially apply -- neither the eligible entry nor a new revision.
    undeployed = _publish_version(client, admin, agent_id)
    body, code = _set_traffic(client, admin, agent_id, env_id, [
        {"agent_version_id": setup["version_a"]["id"], "weight": 40},
        {"agent_version_id": undeployed["id"], "weight": 60},
    ])
    assert code == 422, body

    current, code = client.get(_traffic_url(agent_id, env_id), headers=admin["headers"]).json(), 200
    assert current["revision"] == good["revision"]
    assert {w["agent_version_id"]: w["weight"] for w in current["weights"]} == {
        setup["version_a"]["id"]: 70, setup["version_b"]["id"]: 30,
    }
    # And nothing half-written landed in the table.
    rows = db_session.execute(select(DeploymentTrafficAllocation).where(
        DeploymentTrafficAllocation.agent_id == uuid.UUID(agent_id))).scalars().all()
    assert len(rows) == 1


def test_ac03_every_stored_current_allocation_sums_to_100(
    client: TestClient, admin: dict, db_session: Session,
) -> None:
    """The invariant stated as a property over whatever is in the database,
    not just over the row this test wrote."""
    setup = _two_serving_versions(client, admin)
    for split in ((90, 10), (50, 50), (1, 99)):
        _, code = _set_traffic(client, admin, setup["agent"]["id"], setup["environment"]["id"], [
            {"agent_version_id": setup["version_a"]["id"], "weight": split[0]},
            {"agent_version_id": setup["version_b"]["id"], "weight": split[1]},
        ])
        assert code == 200

    db_session.rollback()
    for allocation in db_session.execute(select(DeploymentTrafficAllocation).where(
            DeploymentTrafficAllocation.is_current.is_(True))).scalars():
        total = sum(w.weight for w in db_session.execute(
            select(DeploymentTrafficWeight).where(
                DeploymentTrafficWeight.allocation_id == allocation.id)).scalars())
        assert total == 100, f"allocation {allocation.id} sums to {total}"


# --------------------------------------------------------------------------- #
# AC-04 --每 change creates a new revision with auditable from/to lineage
# --------------------------------------------------------------------------- #
def test_ac04_each_change_creates_a_new_revision_with_lineage(
    client: TestClient, admin: dict, db_session: Session,
) -> None:
    setup = _two_serving_versions(client, admin)
    agent_id, env_id = setup["agent"]["id"], setup["environment"]["id"]

    first, _ = _set_traffic(client, admin, agent_id, env_id, [
        {"agent_version_id": setup["version_a"]["id"], "weight": 100},
        {"agent_version_id": setup["version_b"]["id"], "weight": 0},
    ], reason="initial")
    second, _ = _set_traffic(client, admin, agent_id, env_id, [
        {"agent_version_id": setup["version_a"]["id"], "weight": 90},
        {"agent_version_id": setup["version_b"]["id"], "weight": 10},
    ], reason="start the canary")
    assert first["revision"] == 1 and second["revision"] == 2
    assert second["is_current"] is True
    assert second["created_by"] == admin["user_id"]
    assert second["reason"] == "start the canary"

    history = client.get(_traffic_url(agent_id, env_id, "/history"), headers=admin["headers"]).json()
    assert [h["revision"] for h in history] == [2, 1]
    assert [h["is_current"] for h in history] == [True, False]

    # The audit event carries the from/to weights, so "who changed the split
    # to what" is answerable without diffing revisions by hand.
    from app.models.runtime import RuntimeEvent

    db_session.rollback()
    event = db_session.execute(
        select(RuntimeEvent)
        .where(RuntimeEvent.event_type == "DEPLOYMENT_TRAFFIC_CHANGED",
               RuntimeEvent.agent_id == uuid.UUID(agent_id))
        .order_by(RuntimeEvent.created_at.desc())
    ).scalars().first()
    assert event is not None
    assert event.payload["revision"] == 2
    assert event.payload["from"] == {setup["version_a"]["id"]: 100, setup["version_b"]["id"]: 0}
    assert event.payload["to"] == {setup["version_a"]["id"]: 90, setup["version_b"]["id"]: 10}


# --------------------------------------------------------------------------- #
# AC-05 -- routing respects the weights
# --------------------------------------------------------------------------- #
def test_ac05_distribution_approximates_the_configured_weights(
    client: TestClient, admin: dict, db_session: Session,
) -> None:
    setup = _two_serving_versions(client, admin)
    _set_traffic(client, admin, setup["agent"]["id"], setup["environment"]["id"], [
        {"agent_version_id": setup["version_a"]["id"], "weight": 90},
        {"agent_version_id": setup["version_b"]["id"], "weight": 10},
    ])

    # Exercised through the resolver directly rather than 2000 full HTTP
    # executions: this asserts the *routing* distribution, and a full
    # execution per sample would make the test minutes long for no extra
    # signal (the end-to-end path is covered by AC-09/AC-11's own tests).
    db_session.rollback()
    agent = db_session.get(Agent, uuid.UUID(setup["agent"]["id"]))
    resolver = VersionResolver(db_session)
    counts = Counter(str(resolver.resolve(agent).version.id) for _ in range(2000))

    share_a = counts[setup["version_a"]["id"]] / 2000
    assert 0.85 <= share_a <= 0.95, counts
    assert counts[setup["version_b"]["id"]] > 0, counts


def test_ac05_a_100_percent_allocation_never_routes_elsewhere(
    client: TestClient, admin: dict, db_session: Session,
) -> None:
    setup = _two_serving_versions(client, admin)
    _set_traffic(client, admin, setup["agent"]["id"], setup["environment"]["id"], [
        {"agent_version_id": setup["version_a"]["id"], "weight": 100},
        {"agent_version_id": setup["version_b"]["id"], "weight": 0},
    ])
    db_session.rollback()
    agent = db_session.get(Agent, uuid.UUID(setup["agent"]["id"]))
    resolver = VersionResolver(db_session)
    resolved = {str(resolver.resolve(agent).version.id) for _ in range(200)}
    assert resolved == {setup["version_a"]["id"]}


def test_ac05_select_weighted_is_proportional_as_a_unit() -> None:
    class _Entry:
        def __init__(self, version_id: uuid.UUID, weight: int) -> None:
            self.agent_version_id, self.weight = version_id, weight

    a, b = uuid.UUID(int=1), uuid.UUID(int=2)
    entries = [_Entry(a, 25), _Entry(b, 75)]
    counts = Counter(select_weighted(entries, None).agent_version_id for _ in range(4000))
    assert 0.20 <= counts[a] / 4000 <= 0.30, counts


# --------------------------------------------------------------------------- #
# AC-06 -- deterministic / sticky routing on a stable key
# --------------------------------------------------------------------------- #
def test_ac06_the_same_routing_key_always_resolves_the_same_version(
    client: TestClient, admin: dict, db_session: Session,
) -> None:
    setup = _two_serving_versions(client, admin)
    _set_traffic(client, admin, setup["agent"]["id"], setup["environment"]["id"], [
        {"agent_version_id": setup["version_a"]["id"], "weight": 50},
        {"agent_version_id": setup["version_b"]["id"], "weight": 50},
    ])
    db_session.rollback()
    agent = db_session.get(Agent, uuid.UUID(setup["agent"]["id"]))
    resolver = VersionResolver(db_session)

    for key in ("user-42", "session-abcdef", "tenant-9", "correlation-xyz"):
        resolved = {str(resolver.resolve(agent, routing_key=key).version.id) for _ in range(50)}
        assert len(resolved) == 1, f"key {key} was not sticky: {resolved}"

    # Different keys must not all collapse onto one version, or "sticky"
    # would be indistinguishable from "always picks the same version".
    spread = {str(resolver.resolve(agent, routing_key=f"user-{i}").version.id) for i in range(60)}
    assert len(spread) == 2, spread


def test_ac06_sticky_routing_end_to_end_over_http(client: TestClient, admin: dict) -> None:
    setup = _two_serving_versions(client, admin)
    _set_traffic(client, admin, setup["agent"]["id"], setup["environment"]["id"], [
        {"agent_version_id": setup["version_a"]["id"], "weight": 50},
        {"agent_version_id": setup["version_b"]["id"], "weight": 50},
    ])
    versions = set()
    for _ in range(8):
        body, code = _execute(client, admin, setup["agent"]["id"], routing_key="session-stable-1")
        assert code == 201, body
        versions.add(body["agent_version_id"])
    assert len(versions) == 1, versions


def test_ac06_correlation_id_is_used_as_the_sticky_key_when_no_routing_key_given(
    client: TestClient, admin: dict,
) -> None:
    setup = _two_serving_versions(client, admin)
    _set_traffic(client, admin, setup["agent"]["id"], setup["environment"]["id"], [
        {"agent_version_id": setup["version_a"]["id"], "weight": 50},
        {"agent_version_id": setup["version_b"]["id"], "weight": 50},
    ])
    versions = set()
    for _ in range(8):
        body, code = _execute(client, admin, setup["agent"]["id"], correlation_id="conv-7")
        assert code == 201, body
        versions.add(body["agent_version_id"])
    assert len(versions) == 1, versions


# --------------------------------------------------------------------------- #
# AC-07 -- the resolver does NOT bypass authorization (the sharpest line)
# --------------------------------------------------------------------------- #
def test_ac07_unauthorized_execution_is_rejected_on_the_resolver_path(
    client: TestClient, admin: dict,
) -> None:
    """An actor without ``runtime.execution.create`` must be rejected exactly
    as before 3.4 -- on an agent whose traffic *is* resolved through an
    allocation, so the rejection is happening on the new path, not on a
    lucky pre-resolver short-circuit."""
    from tests.runtime.conftest import PASSWORD

    setup = _two_serving_versions(client, admin)
    _set_traffic(client, admin, setup["agent"]["id"], setup["environment"]["id"], [
        {"agent_version_id": setup["version_a"]["id"], "weight": 90},
        {"agent_version_id": setup["version_b"]["id"], "weight": 10},
    ])

    # A VIEWER in the same organization: same tenant, same agent, same
    # allocation -- only the permission differs.
    email = f"viewer_{uuid.uuid4().hex[:10]}@example.com"
    r = client.post("/api/v1/identity/users", headers=admin["headers"], json={
        "email": email, "display_name": "Viewer", "password": PASSWORD, "role": "VIEWER",
        "organization_id": admin["organization_id"],
    })
    assert r.status_code in (200, 201), r.text
    tokens = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD}).json()
    viewer_headers = {"Authorization": f"Bearer {tokens['access_token']}"}

    r = client.post(f"{RT}/executions", headers=viewer_headers, json={
        "agent_id": setup["agent"]["id"], "input_payload": {"message": "hi"},
    })
    assert r.status_code == 403, r.text

    # The same actor, same request, *is* allowed for the admin -- so the
    # rejection above is the permission check, not a broken setup.
    body, code = _execute(client, admin, setup["agent"]["id"])
    assert code == 201, body


def test_ac07_the_resolver_module_never_imports_the_authorization_gateway() -> None:
    """Structural proof of non-bypass: the resolver cannot authorize *or*
    dispatch, because it has no reference to the gateway, the policy engine
    or the worker. It selects a version and returns a plain value; the
    pre-existing ``authorize(deployment)`` call in
    ``ExecutionRequestService._request_execution`` still does the deciding."""
    import ast

    source = (Path(__file__).resolve().parents[2] / "app" / "runtime" / "deployment"
              / "resolver.py").read_text(encoding="utf-8")
    tree = ast.parse(source)

    # Checked against the parsed AST, not raw text: the module's docstring
    # discusses the gateway at length (explaining precisely why it must not
    # touch it), and a substring scan would flag that prose. Only real
    # imports and real identifiers count.
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
        elif isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
    assert not [m for m in imported if "authorization" in m or "policy" in m], imported

    identifiers = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    identifiers |= {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    for forbidden in ("AuthorizationGateway", "RuntimePolicyService", "ExecutionWorkerService",
                     "authorize", "authorize_agent", "ToolLoopOrchestrator"):
        assert forbidden not in identifiers, f"resolver.py must not reference {forbidden}"


def test_ac07_authorization_still_runs_after_the_resolver_in_the_execution_path() -> None:
    """The ordering the non-bypass argument depends on: the resolver call
    site sits *before* the ``authorize(...)`` call, and that call still
    exists. A refactor that removed or reordered it would fail here."""
    import inspect

    from app.runtime.services import ExecutionRequestService

    source = inspect.getsource(ExecutionRequestService._request_execution)
    resolver_at = source.index("VersionResolver(self.db).resolve(")
    authorize_at = source.index("decision = authorize(deployment)")
    assert resolver_at < authorize_at
    assert "if not decision.allowed:" in source


# --------------------------------------------------------------------------- #
# AC-08 -- an immutable version is selected, never mutated
# --------------------------------------------------------------------------- #
def test_ac08_resolution_never_mutates_the_selected_version(
    client: TestClient, admin: dict, db_session: Session,
) -> None:
    setup = _two_serving_versions(client, admin)
    _set_traffic(client, admin, setup["agent"]["id"], setup["environment"]["id"], [
        {"agent_version_id": setup["version_a"]["id"], "weight": 50},
        {"agent_version_id": setup["version_b"]["id"], "weight": 50},
    ])
    db_session.rollback()
    before = {
        str(v.id): (v.checksum, v.status, v.signature_id, v.version)
        for v in db_session.execute(select(AgentVersion).where(
            AgentVersion.agent_id == uuid.UUID(setup["agent"]["id"]))).scalars()
    }

    agent = db_session.get(Agent, uuid.UUID(setup["agent"]["id"]))
    resolver = VersionResolver(db_session)
    for _ in range(50):
        resolver.resolve(agent, routing_key=uuid.uuid4().hex)
    db_session.rollback()

    after = {
        str(v.id): (v.checksum, v.status, v.signature_id, v.version)
        for v in db_session.execute(select(AgentVersion).where(
            AgentVersion.agent_id == uuid.UUID(setup["agent"]["id"]))).scalars()
    }
    assert before == after


# --------------------------------------------------------------------------- #
# AC-09 -- ruling #4: no active deployment => fail closed
# --------------------------------------------------------------------------- #
def test_ac09_execution_with_no_deployment_at_all_is_rejected(
    client: TestClient, admin: dict,
) -> None:
    setup = _setup(client, admin)  # published, never deployed
    body, code = _execute(client, admin, setup["agent"]["id"])
    assert code == 404, body
    assert body["error"]["code"] == "DEPLOYMENT_NOT_FOUND", body


def test_ac09_no_servable_version_in_the_allocation_fails_closed(
    client: TestClient, admin: dict, db_session: Session,
) -> None:
    """The genuinely new fail-closed mode, and the reason it needs its own
    error code: a servable deployment still exists (so this is *not* the
    pre-existing "no active deployment" case), an allocation exists, but
    nothing the allocation actually weights can serve. The execution must be
    rejected -- never silently rerouted to the servable deployment's own
    version, which the operator's weights deliberately gave 0%.

    Set up as 0/100 with the 100% side then paused: deployment A stays
    servable and is the deployment the pre-3.4 rule would have picked, so a
    regression that fell back to it would show up here as a 201."""
    setup = _two_serving_versions(client, admin)
    _set_traffic(client, admin, setup["agent"]["id"], setup["environment"]["id"], [
        {"agent_version_id": setup["version_a"]["id"], "weight": 0},
        {"agent_version_id": setup["version_b"]["id"], "weight": 100},
    ])
    # 3.1 lifecycle pause writes only lifecycle_state -- the veto half of
    # the predicate.
    r = client.post(f"{RT}/deployments/{setup['deployment_b']['id']}/lifecycle/pause",
                    headers=admin["headers"], json={})
    assert r.status_code == 200, r.text

    # Deployment A is still servable; only its *weight* is zero.
    from app.models.runtime import AgentDeployment as _D

    db_session.rollback()
    assert is_servable(db_session.get(_D, uuid.UUID(setup["deployment_a"]["id"])))

    body, code = _execute(client, admin, setup["agent"]["id"])
    assert code == 409, body
    assert body["error"]["code"] == "NO_ACTIVE_DEPLOYMENT", body


def test_ac09_the_fail_closed_rejection_is_audited(
    client: TestClient, admin: dict, db_session: Session,
) -> None:
    from app.models.runtime import RuntimeEvent

    setup = _setup(client, admin)
    _execute(client, admin, setup["agent"]["id"])

    db_session.rollback()
    event = db_session.execute(
        select(RuntimeEvent).where(
            RuntimeEvent.event_type == "RUNTIME_EXECUTION_NO_ACTIVE_DEPLOYMENT",
            RuntimeEvent.agent_id == uuid.UUID(setup["agent"]["id"]))
    ).scalars().first()
    assert event is not None
    assert event.severity == "WARNING"
    assert event.payload["code"] == "DEPLOYMENT_NOT_FOUND"


# --------------------------------------------------------------------------- #
# AC-10 -- paused / killed / superseded are non-serving
# --------------------------------------------------------------------------- #
def test_ac10_a_paused_deployment_does_not_serve(client: TestClient, admin: dict) -> None:
    setup = _setup(client, admin)
    deployment = _lifecycle_deploy(client, admin, setup["agent"]["id"], setup["version"]["id"])
    body, code = _execute(client, admin, setup["agent"]["id"])
    assert code == 201, body

    r = client.post(f"{RT}/deployments/{deployment['id']}/lifecycle/pause",
                    headers=admin["headers"], json={})
    assert r.status_code == 200, r.text

    body, code = _execute(client, admin, setup["agent"]["id"])
    assert code == 404, body
    assert body["error"]["code"] == "DEPLOYMENT_NOT_FOUND", body


def test_ac10_a_killed_agent_serves_nothing(client: TestClient, admin: dict) -> None:
    """Kill-switch dominance. ORGANIZATION scope writes only the legacy
    ``status`` column, so this is exactly the case a lifecycle-only gate
    would have silently kept serving."""
    setup = _setup(client, admin)
    _legacy_deploy(client, admin, setup["agent"]["id"], setup["version"]["id"])
    body, code = _execute(client, admin, setup["agent"]["id"])
    assert code == 201, body

    r = client.post(f"{RT}/kill-switch/organizations/{admin['organization_id']}",
                    headers=admin["headers"], json={"reason": "test"})
    assert r.status_code == 200, r.text

    body, code = _execute(client, admin, setup["agent"]["id"])
    assert code in (404, 409, 423), body
    assert body["error"]["code"] in ("DEPLOYMENT_NOT_FOUND", "NO_ACTIVE_DEPLOYMENT",
                                   "AGENT_SUSPENDED", "KILL_SWITCH_ACTIVE"), body


def test_ac10_a_superseded_deployment_is_not_routed_to(
    client: TestClient, admin: dict, db_session: Session,
) -> None:
    setup = _two_serving_versions(client, admin)
    _set_traffic(client, admin, setup["agent"]["id"], setup["environment"]["id"], [
        {"agent_version_id": setup["version_a"]["id"], "weight": 50},
        {"agent_version_id": setup["version_b"]["id"], "weight": 50},
    ])
    r = client.post(f"{RT}/deployments/{setup['deployment_b']['id']}/lifecycle/transition",
                    headers=admin["headers"], json={"to_state": "SUPERSEDED"})
    assert r.status_code == 200, r.text

    db_session.rollback()
    agent = db_session.get(Agent, uuid.UUID(setup["agent"]["id"]))
    resolver = VersionResolver(db_session)
    resolved = {str(resolver.resolve(agent).version.id) for _ in range(120)}
    assert resolved == {setup["version_a"]["id"]}, resolved


def test_ac10_a_revoked_version_is_not_routed_to(
    client: TestClient, admin: dict, db_session: Session,
) -> None:
    setup = _two_serving_versions(client, admin)
    _set_traffic(client, admin, setup["agent"]["id"], setup["environment"]["id"], [
        {"agent_version_id": setup["version_a"]["id"], "weight": 50},
        {"agent_version_id": setup["version_b"]["id"], "weight": 50},
    ])
    r = client.post(
        f"{RT}/agents/{setup['agent']['id']}/versions/{setup['version_b']['id']}/revoke",
        headers=admin["headers"], json={"reason": "compromised"})
    assert r.status_code == 200, r.text

    db_session.rollback()
    agent = db_session.get(Agent, uuid.UUID(setup["agent"]["id"]))
    resolver = VersionResolver(db_session)
    resolved = {str(resolver.resolve(agent).version.id) for _ in range(120)}
    assert resolved == {setup["version_a"]["id"]}, resolved


def test_ac10_servability_predicate_truth_table() -> None:
    """The union-with-veto rule as a table, so a future change to either
    machine's state names fails here loudly rather than silently opening or
    closing the gate. See docs/deployment/traffic-and-resolution.md."""
    class _D:
        def __init__(self, status: str, lifecycle_state: str) -> None:
            self.status, self.lifecycle_state = status, lifecycle_state

    # (status, lifecycle_state, expected servable)
    table = [
        ("ACTIVE", "DRAFT", True),        # legacy deploy -- every M1 test
        ("CREATED", "ACTIVE", True),      # 3.1/3.2 lifecycle deploy, promotion
        ("ACTIVE", "ACTIVE", True),       # both machines agree
        ("ACTIVE", "PAUSED", False),      # 3.1 pause vetoes
        ("ACTIVE", "SUPERSEDED", False),  # 3.2 supersede vetoes
        ("SUSPENDED", "ACTIVE", False),   # kill switch vetoes
        ("SUSPENDED", "DRAFT", False),
        ("RETIRED", "ACTIVE", False),
        ("CREATED", "DRAFT", False),      # never deployed by either machine
        ("CREATED", "READY", False),
        ("FAILED", "ACTIVE", False),
    ]
    for status, lifecycle_state, expected in table:
        assert is_servable(_D(status, lifecycle_state)) is expected, (status, lifecycle_state)


# --------------------------------------------------------------------------- #
# AC-11 -- the §15 backfill preserves every previously-executable agent
# --------------------------------------------------------------------------- #
def test_ac11_a_legacy_deployed_agent_still_executes(client: TestClient, admin: dict) -> None:
    """The AC-11 claim in the shape it actually matters: an agent deployed
    the Milestone 1 way (status=ACTIVE, lifecycle_state=DRAFT, no allocation
    row) executes unchanged after 3.4, through the implicit 100% rule."""
    setup = _setup(client, admin)
    deployment = _legacy_deploy(client, admin, setup["agent"]["id"], setup["version"]["id"])

    body, code = _execute(client, admin, setup["agent"]["id"])
    assert code == 201, body
    assert body["agent_version_id"] == setup["version"]["id"]
    assert body["deployment_id"] == deployment["id"]
    assert body["status"] == "SUCCEEDED", body


def test_ac11_backfill_sql_targets_exactly_the_servable_deployments(
    client: TestClient, admin: dict, db_session: Session,
) -> None:
    """Runs migration 0040's own backfill predicate against live data and
    checks it selects the deployments the resolver considers servable --
    proving the migration and the runtime agree on "active", which is what
    "no previously-executable agent breaks" rests on."""
    from sqlalchemy import text

    from migrations.versions import __name__ as _  # noqa: F401  (package import guard)

    setup = _two_serving_versions(client, admin)
    paused = _lifecycle_deploy(client, admin, setup["agent"]["id"],
                              _publish_version(client, admin, setup["agent"]["id"])["id"])
    r = client.post(f"{RT}/deployments/{paused['id']}/lifecycle/pause",
                    headers=admin["headers"], json={})
    assert r.status_code == 200

    db_session.rollback()
    servable_ids = {row[0] for row in db_session.execute(text("""
        SELECT d.id FROM agent_deployments d
        WHERE d.agent_id = :agent_id
          AND (d.status = 'ACTIVE' OR d.lifecycle_state = 'ACTIVE')
          AND d.status NOT IN ('SUSPENDED', 'RETIRED', 'FAILED', 'ROLLING_BACK')
          AND d.lifecycle_state NOT IN ('PAUSED', 'SUPERSEDED', 'RETIRED', 'FAILED',
                                        'ROLLING_BACK', 'REJECTED', 'VALIDATION_FAILED')
    """), {"agent_id": uuid.UUID(setup["agent"]["id"])})}

    all_deployments = db_session.execute(select(AgentDeployment).where(
        AgentDeployment.agent_id == uuid.UUID(setup["agent"]["id"]))).scalars().all()
    assert servable_ids == {d.id for d in all_deployments if is_servable(d)}
    assert uuid.UUID(paused["id"]) not in servable_ids


def test_ac11_backfilled_rows_exist_and_are_well_formed(db_session: Session) -> None:
    """Whatever migration 0040 backfilled into this test database must obey
    the same invariants the API enforces: exactly one current allocation per
    (agent, environment), each summing to 100."""
    db_session.rollback()
    current = db_session.execute(select(DeploymentTrafficAllocation).where(
        DeploymentTrafficAllocation.is_current.is_(True))).scalars().all()
    seen: set[tuple[uuid.UUID, uuid.UUID]] = set()
    for allocation in current:
        key = (allocation.agent_id, allocation.environment_id)
        assert key not in seen, f"two current allocations for {key}"
        seen.add(key)
        weights = db_session.execute(select(DeploymentTrafficWeight).where(
            DeploymentTrafficWeight.allocation_id == allocation.id)).scalars().all()
        assert weights, f"allocation {allocation.id} has no weights"
        assert sum(w.weight for w in weights) == 100


# --------------------------------------------------------------------------- #
# AC-12 -- the deliberate M1 test migration is real and documented
# --------------------------------------------------------------------------- #
def test_ac12_the_migrated_promotion_gate_test_asserts_the_new_behaviour() -> None:
    """Ruling #4's behaviour change is explicit, not hidden by a weakened
    assertion. The one migrated test is
    ``test_environment_promotion.py::test_ac15_promoting_to_lifecycle_active_
    now_serves_execution``: it previously asserted a promoted deployment
    could NOT execute; it now asserts it CAN, still pinning
    ``status != 'ACTIVE'`` so the admission can only have come from
    ``lifecycle_state``. This test fails if that migration is ever reverted
    or softened into accepting either outcome."""
    source = (Path(__file__).resolve().parent / "test_environment_promotion.py").read_text(
        encoding="utf-8")
    assert "test_ac15_promoting_to_lifecycle_active_now_serves_execution" in source
    assert "MIGRATED IN PHASE 3.4" in source
    assert "has_no_effect_on_the_legacy_execution_gate" not in source
    # It must still assert a definite outcome, not tolerate both.
    assert "assert r.status_code == 201, r.text" in source
    assert "assert row.status != \"ACTIVE\"" in source


# --------------------------------------------------------------------------- #
# AC-13 -- concurrent allocation updates (real separate Postgres connections)
# --------------------------------------------------------------------------- #
def test_ac13_concurrent_allocation_updates_conflict_exactly_once(
    client: TestClient, admin: dict, db_session: Session,
) -> None:
    setup = _two_serving_versions(client, admin)
    _set_traffic(client, admin, setup["agent"]["id"], setup["environment"]["id"], [
        {"agent_version_id": setup["version_a"]["id"], "weight": 100},
        {"agent_version_id": setup["version_b"]["id"], "weight": 0},
    ])
    agent_uuid = uuid.UUID(setup["agent"]["id"])
    env_uuid = uuid.UUID(setup["environment"]["id"])

    # Deterministic, not timing-dependent. Two *unsynchronised* threads
    # racing this would usually just serialize -- the second reads the
    # first's committed revision and legitimately succeeds, which is correct
    # but is not the conflict AC-13 is about, and makes the test flaky.
    #
    # Instead a real second connection opens a transaction, inserts its own
    # current allocation, and *holds the transaction open*. The writer under
    # test then reads the still-committed revision 1, computes revision 2,
    # and blocks inside Postgres on the partial unique index until the other
    # transaction resolves -- exactly what two admins hitting PUT at the same
    # moment produces. When the competitor commits, the writer's insert must
    # fail and surface as TRAFFIC_ALLOCATION_CONFLICT, never a raw 500.
    competitor_ready = threading.Event()
    may_commit = threading.Event()
    competitor_result: list[str] = []

    def _competing_admin() -> None:
        db = SessionLocal()
        try:
            # Same ordering the service uses: clear the previous current row
            # first, then insert this transaction's own.
            previous = db.execute(select(DeploymentTrafficAllocation).where(
                DeploymentTrafficAllocation.agent_id == agent_uuid,
                DeploymentTrafficAllocation.revision == 1)).scalars().one()
            previous.is_current = False
            db.flush()
            allocation = DeploymentTrafficAllocation(
                organization_id=uuid.UUID(admin["organization_id"]), agent_id=agent_uuid,
                environment_id=env_uuid, revision=2, is_current=True,
                reason="the other admin", created_by=uuid.UUID(admin["user_id"]),
            )
            db.add(allocation)
            db.flush()
            db.add(DeploymentTrafficWeight(
                allocation_id=allocation.id,
                agent_version_id=uuid.UUID(setup["version_a"]["id"]),
                deployment_id=uuid.UUID(setup["deployment_a"]["id"]), weight=100,
            ))
            db.flush()
            competitor_ready.set()
            may_commit.wait(timeout=30)
            db.commit()
            competitor_result.append("OK")
        finally:
            db.close()

    competitor = threading.Thread(target=_competing_admin)
    competitor.start()
    assert competitor_ready.wait(timeout=30), "competing transaction never opened"

    # Release the competitor shortly after the writer below starts blocking.
    threading.Timer(0.75, may_commit.set).start()

    db = SessionLocal()
    try:
        from app.models.runtime import Environment
        from app.models.user import User

        service = TrafficAllocationService(db)
        with pytest.raises(IdentityError) as exc_info:
            service.set_weights(
                db.get(User, uuid.UUID(admin["user_id"])),
                db.get(Agent, agent_uuid),
                db.get(Environment, env_uuid),
                [{"agent_version_id": uuid.UUID(setup["version_a"]["id"]), "weight": 30},
                 {"agent_version_id": uuid.UUID(setup["version_b"]["id"]), "weight": 70}],
            )
        assert exc_info.value.code == ErrorCode.TRAFFIC_ALLOCATION_CONFLICT
    finally:
        db.rollback()
        db.close()

    competitor.join(timeout=30)
    assert competitor_result == ["OK"], "the winning writer did not commit"

    # One winner, one current allocation, still summing to 100 -- the weights
    # were never transiently invalid, and the loser left nothing behind.
    db_session.rollback()
    current = db_session.execute(select(DeploymentTrafficAllocation).where(
        DeploymentTrafficAllocation.agent_id == agent_uuid,
        DeploymentTrafficAllocation.is_current.is_(True))).scalars().all()
    assert len(current) == 1
    assert current[0].reason == "the other admin"
    weights = db_session.execute(select(DeploymentTrafficWeight).where(
        DeploymentTrafficWeight.allocation_id == current[0].id)).scalars().all()
    assert sum(w.weight for w in weights) == 100


def test_ac13_many_concurrent_writers_never_break_the_invariant(
    client: TestClient, admin: dict, db_session: Session,
) -> None:
    """The safety property, under a genuinely unsynchronised race on real
    separate connections: whoever wins, the end state is always exactly one
    current allocation summing to 100, and every writer either succeeded or
    was told it conflicted -- never a raw error, never a torn allocation."""
    setup = _two_serving_versions(client, admin)
    agent_uuid = uuid.UUID(setup["agent"]["id"])
    env_uuid = uuid.UUID(setup["environment"]["id"])
    barrier = threading.Barrier(6, timeout=60)

    def _writer(split: int) -> str:
        db = SessionLocal()
        try:
            from app.models.runtime import Environment
            from app.models.user import User

            service = TrafficAllocationService(db)
            actor = db.get(User, uuid.UUID(admin["user_id"]))
            agent = db.get(Agent, agent_uuid)
            environment = db.get(Environment, env_uuid)
            barrier.wait()
            service.set_weights(actor, agent, environment, [
                {"agent_version_id": uuid.UUID(setup["version_a"]["id"]), "weight": split},
                {"agent_version_id": uuid.UUID(setup["version_b"]["id"]), "weight": 100 - split},
            ])
            return "OK"
        except IdentityError as exc:
            return str(exc.code)
        finally:
            db.rollback()
            db.close()

    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(_writer, [10, 20, 30, 40, 50, 60]))

    assert results.count("OK") >= 1, results
    assert set(results) <= {"OK", ErrorCode.TRAFFIC_ALLOCATION_CONFLICT}, results

    db_session.rollback()
    current = db_session.execute(select(DeploymentTrafficAllocation).where(
        DeploymentTrafficAllocation.agent_id == agent_uuid,
        DeploymentTrafficAllocation.is_current.is_(True))).scalars().all()
    assert len(current) == 1, current
    weights = db_session.execute(select(DeploymentTrafficWeight).where(
        DeploymentTrafficWeight.allocation_id == current[0].id)).scalars().all()
    assert sum(w.weight for w in weights) == 100


def test_ac13_expected_revision_rejects_a_stale_writer(client: TestClient, admin: dict) -> None:
    setup = _two_serving_versions(client, admin)
    agent_id, env_id = setup["agent"]["id"], setup["environment"]["id"]
    first, _ = _set_traffic(client, admin, agent_id, env_id, [
        {"agent_version_id": setup["version_a"]["id"], "weight": 100},
        {"agent_version_id": setup["version_b"]["id"], "weight": 0},
    ])
    _set_traffic(client, admin, agent_id, env_id, [
        {"agent_version_id": setup["version_a"]["id"], "weight": 60},
        {"agent_version_id": setup["version_b"]["id"], "weight": 40},
    ])
    body, code = _set_traffic(client, admin, agent_id, env_id, [
        {"agent_version_id": setup["version_a"]["id"], "weight": 10},
        {"agent_version_id": setup["version_b"]["id"], "weight": 90},
    ], expected_revision=first["revision"])
    assert code == 409, body
    assert body["error"]["code"] == "TRAFFIC_ALLOCATION_CONFLICT", body


def test_ac13_an_allocation_racing_a_pause_never_routes_to_the_paused_version(
    client: TestClient, admin: dict, db_session: Session,
) -> None:
    setup = _two_serving_versions(client, admin)
    _set_traffic(client, admin, setup["agent"]["id"], setup["environment"]["id"], [
        {"agent_version_id": setup["version_a"]["id"], "weight": 50},
        {"agent_version_id": setup["version_b"]["id"], "weight": 50},
    ])
    # Pause B *after* the weights were set: the allocation still names it,
    # but the resolver re-checks servability at resolution time (FR-022), so
    # no allocation rewrite is needed for traffic to stop.
    r = client.post(f"{RT}/deployments/{setup['deployment_b']['id']}/lifecycle/pause",
                    headers=admin["headers"], json={})
    assert r.status_code == 200, r.text

    db_session.rollback()
    agent = db_session.get(Agent, uuid.UUID(setup["agent"]["id"]))
    resolver = VersionResolver(db_session)
    resolved = {str(resolver.resolve(agent).version.id) for _ in range(120)}
    assert resolved == {setup["version_a"]["id"]}, resolved


# --------------------------------------------------------------------------- #
# AC-14 -- the resolver hot path is indexed and bounded
# --------------------------------------------------------------------------- #
def test_ac14_resolver_hot_path_is_bounded_in_queries_and_time(
    client: TestClient, admin: dict, db_session: Session,
) -> None:
    """Two properties, because either alone can hide a regression: a bounded
    *query count* (no per-execution join explosion) and a bounded wall
    time."""
    from sqlalchemy import event

    setup = _two_serving_versions(client, admin)
    _set_traffic(client, admin, setup["agent"]["id"], setup["environment"]["id"], [
        {"agent_version_id": setup["version_a"]["id"], "weight": 90},
        {"agent_version_id": setup["version_b"]["id"], "weight": 10},
    ])
    db_session.rollback()
    agent = db_session.get(Agent, uuid.UUID(setup["agent"]["id"]))
    resolver = VersionResolver(db_session)

    statements: list[str] = []

    def _before_cursor(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(db_session.get_bind(), "before_cursor_execute", _before_cursor)
    try:
        resolver.resolve(agent)  # warm
        statements.clear()
        resolver.resolve(agent)
        per_resolution = len(statements)

        start = time.perf_counter()
        for _ in range(200):
            resolver.resolve(agent)
        elapsed_ms = (time.perf_counter() - start) * 1000 / 200
    finally:
        event.remove(db_session.get_bind(), "before_cursor_execute", _before_cursor)

    assert per_resolution <= 3, f"{per_resolution} queries per resolution:\n" + "\n".join(statements)
    assert elapsed_ms < 25, f"{elapsed_ms:.2f} ms per resolution"


def test_ac14_the_hot_path_lookup_index_exists(db_session: Session) -> None:
    from sqlalchemy import text

    rows = {row[0] for row in db_session.execute(text(
        "SELECT indexname FROM pg_indexes WHERE tablename = 'deployment_traffic_allocations'"))}
    assert "ix_traffic_allocations_agent_environment_current" in rows
    assert "uq_traffic_allocations_current" in rows


# --------------------------------------------------------------------------- #
# AC-15 -- no cache is used, so no stale window exists
# --------------------------------------------------------------------------- #
def test_ac15_no_cache_is_used_and_changes_take_effect_immediately(
    client: TestClient, admin: dict, db_session: Session,
) -> None:
    """This phase deliberately ships no resolution cache (see
    ``resolver.py``'s docstring), so FR-030's invalidation requirement is met
    by construction. Asserted two ways: a weight change is visible to the
    very next resolution, and the resolver module holds no module-level
    mutable cache to go stale."""
    import app.runtime.deployment.resolver as resolver_module

    setup = _two_serving_versions(client, admin)
    agent_id, env_id = setup["agent"]["id"], setup["environment"]["id"]
    _set_traffic(client, admin, agent_id, env_id, [
        {"agent_version_id": setup["version_a"]["id"], "weight": 100},
        {"agent_version_id": setup["version_b"]["id"], "weight": 0},
    ])
    db_session.rollback()
    agent = db_session.get(Agent, uuid.UUID(setup["agent"]["id"]))
    resolver = VersionResolver(db_session)
    assert {str(resolver.resolve(agent).version.id) for _ in range(40)} == {setup["version_a"]["id"]}

    _set_traffic(client, admin, agent_id, env_id, [
        {"agent_version_id": setup["version_a"]["id"], "weight": 0},
        {"agent_version_id": setup["version_b"]["id"], "weight": 100},
    ])
    db_session.rollback()
    assert {str(resolver.resolve(agent).version.id) for _ in range(40)} == {setup["version_b"]["id"]}

    caches = [name for name, value in vars(resolver_module).items()
              if isinstance(value, (dict, list, set)) and not name.startswith("__")]
    assert caches == [], f"resolver module holds mutable module-level state: {caches}"


# --------------------------------------------------------------------------- #
# AC-16 -- authz, tenant isolation, idempotency on the allocation endpoints
# --------------------------------------------------------------------------- #
def test_ac16_traffic_endpoints_require_authentication(client: TestClient, admin: dict) -> None:
    setup = _two_serving_versions(client, admin)
    url = _traffic_url(setup["agent"]["id"], setup["environment"]["id"])
    assert client.get(url).status_code in (401, 403)
    assert client.put(url, json={"weights": []}).status_code in (401, 403)
    assert client.get(url + "/history").status_code in (401, 403)


def test_ac16_cross_tenant_allocation_access_is_rejected(client: TestClient, admin: dict) -> None:
    setup = _two_serving_versions(client, admin)
    other = _second_org(client)
    url = _traffic_url(setup["agent"]["id"], setup["environment"]["id"])

    r = client.get(url, headers=other["headers"])
    assert r.status_code == 404, r.text
    assert r.json()["error"]["code"] == "AGENT_NOT_FOUND"

    r = client.put(url, headers=other["headers"], json={"weights": [
        {"agent_version_id": setup["version_a"]["id"], "weight": 100},
    ]})
    assert r.status_code == 404, r.text
    assert r.json()["error"]["code"] == "AGENT_NOT_FOUND"


def test_ac16_environment_from_another_tenant_is_rejected(client: TestClient, admin: dict) -> None:
    setup = _two_serving_versions(client, admin)
    other = _second_org(client)
    other_envs = _environments(client, other)

    r = client.get(_traffic_url(setup["agent"]["id"], other_envs["DEVELOPMENT"]["id"]),
                   headers=admin["headers"])
    assert r.status_code == 404, r.text
    assert r.json()["error"]["code"] == "ENVIRONMENT_NOT_FOUND"


def test_ac16_idempotency_key_is_honoured_on_the_weight_setting_put(
    client: TestClient, admin: dict, db_session: Session,
) -> None:
    setup = _two_serving_versions(client, admin)
    url = _traffic_url(setup["agent"]["id"], setup["environment"]["id"])
    payload = {"weights": [
        {"agent_version_id": setup["version_a"]["id"], "weight": 70},
        {"agent_version_id": setup["version_b"]["id"], "weight": 30},
    ]}
    headers = {**admin["headers"], "Idempotency-Key": f"traffic-{uuid.uuid4().hex[:12]}"}

    first = client.put(url, headers=headers, json=payload)
    second = client.put(url, headers=headers, json=payload)
    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    # Replayed, not re-applied: the same revision comes back, and no second
    # revision was created.
    assert second.json()["id"] == first.json()["id"]
    assert second.json()["revision"] == first.json()["revision"]

    db_session.rollback()
    revisions = db_session.execute(select(DeploymentTrafficAllocation).where(
        DeploymentTrafficAllocation.agent_id == uuid.UUID(setup["agent"]["id"]))).scalars().all()
    assert len(revisions) == 1


# --------------------------------------------------------------------------- #
# End-to-end: agent -> env -> deployment -> allocation -> version -> execution
# --------------------------------------------------------------------------- #
def test_full_path_resolves_through_allocation_into_the_existing_execution_path(
    client: TestClient, admin: dict,
) -> None:
    setup = _two_serving_versions(client, admin)
    _set_traffic(client, admin, setup["agent"]["id"], setup["environment"]["id"], [
        {"agent_version_id": setup["version_a"]["id"], "weight": 0},
        {"agent_version_id": setup["version_b"]["id"], "weight": 100},
    ])
    body, code = _execute(client, admin, setup["agent"]["id"])
    assert code == 201, body
    # Routed by the allocation to B -- not to A, which is what the
    # pre-3.4 "newest active deployment" rule would have chosen.
    assert body["agent_version_id"] == setup["version_b"]["id"], body
    assert body["deployment_id"] == setup["deployment_b"]["id"], body
    # ...and then ran through the unchanged M1 execution path.
    assert body["status"] == "SUCCEEDED", body
    assert body["decision"] == "ALLOW"
    assert body["output_payload"] is not None


# --------------------------------------------------------------------------- #
# AC-19 -- no new TODO/FIXME/NotImplementedError/skip/xfail
# --------------------------------------------------------------------------- #
def test_ac19_no_todo_fixme_or_skipped_tests_in_this_phases_files() -> None:
    root = Path(__file__).resolve().parents[2]
    targets = [
        root / "app" / "runtime" / "deployment" / "traffic.py",
        root / "app" / "runtime" / "deployment" / "resolver.py",
        root / "migrations" / "versions" / "0040_traffic_allocation.py",
    ]
    for path in targets:
        text = path.read_text(encoding="utf-8")
        for banned in ("TODO", "FIXME", "NotImplementedError", "xfail"):
            assert banned not in text, f"{path.name} contains {banned}"
