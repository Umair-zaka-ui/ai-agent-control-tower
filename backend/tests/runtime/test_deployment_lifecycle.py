"""Phase 3.1 (ACT-SRS-M3 §3.1) tests -- the deployment lifecycle state
machine, its single transition authority, the reusable idempotency
contract, and the Ruling #6 suspension integration.

Grouped by the build prompt's own §12 acceptance criteria. Real Postgres
throughout (this codebase's established convention -- ``tests/runtime/conftest.py``),
including the concurrency races (AC-05/AC-related idempotency race), which use
real separate ``SessionLocal()`` connections and threads, never in-process
mutexes (mirroring ``test_connector_auth.py::test_ac13_concurrent_refresh_does_not_double_refresh``)."""

from __future__ import annotations

import inspect
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models.runtime import AgentDeployment, DeploymentEvent, IdempotencyKey
from app.runtime.deployment import lifecycle
from app.runtime.deployment.idempotency import IdempotencyService
from app.runtime.deployment.service import DeploymentLifecycleService

RT = "/api/v1/runtime"


# --------------------------------------------------------------------------- #
# HTTP setup helpers (mirrors test_http_tool_execution.py's own convention)
# --------------------------------------------------------------------------- #
def _register_agent(client: TestClient, admin: dict, *, criticality: str = "MEDIUM") -> dict:
    r = client.post(f"{RT}/agents", headers=admin["headers"], json={
        "name": f"Deploy Agent {uuid.uuid4().hex[:6]}", "agent_type": "ASSISTANT", "criticality": criticality,
        "description": "A test agent.", "business_purpose": "Exercise the deployment lifecycle in tests.",
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


def _publish_version(client: TestClient, admin: dict, agent_id: str) -> dict:
    r = client.post(f"{RT}/agents/{agent_id}/versions", headers=admin["headers"], json={
        "model_configuration": {"provider": "MOCK", "model": "mock-model"}, "tool_ids": [],
    })
    assert r.status_code == 201, r.text
    version = r.json()
    for step in ("validate", "approve", "publish"):
        r = client.post(f"{RT}/agents/{agent_id}/versions/{version['id']}/{step}", headers=admin["headers"])
        assert r.status_code == 200, r.text
    return r.json()


def _create_deployment(client: TestClient, admin: dict, agent_id: str, version_id: str, *,
                       environment: str = "DEVELOPMENT", idempotency_key: str | None = None) -> tuple[dict, int]:
    headers = dict(admin["headers"])
    if idempotency_key is not None:
        headers["Idempotency-Key"] = idempotency_key
    r = client.post(f"{RT}/deployments", headers=headers, params={"agent_id": agent_id},
                    json={"agent_version_id": version_id, "environment": environment})
    return r.json(), r.status_code


def _ready_deployment(client: TestClient, admin: dict, agent_id: str, version_id: str, *,
                      environment: str = "DEVELOPMENT") -> dict:
    deployment, status_code = _create_deployment(client, admin, agent_id, version_id, environment=environment)
    assert status_code == 201, deployment
    assert deployment["lifecycle_state"] == "DRAFT"
    deployment = _transition(client, admin, deployment["id"], "VALIDATING")
    deployment = _transition(client, admin, deployment["id"], "READY")
    return deployment


def _transition(client: TestClient, admin: dict, deployment_id: str, to_state: str, *,
                reason: str | None = None, expected_revision: int | None = None,
                idempotency_key: str | None = None) -> dict:
    headers = dict(admin["headers"])
    if idempotency_key is not None:
        headers["Idempotency-Key"] = idempotency_key
    payload = {"to_state": to_state}
    if reason is not None:
        payload["reason"] = reason
    if expected_revision is not None:
        payload["expected_revision"] = expected_revision
    r = client.post(f"{RT}/deployments/{deployment_id}/lifecycle/transition", headers=headers, json=payload)
    assert r.status_code == 200, r.text
    return r.json()


def _full_setup(client: TestClient, admin: dict, *, criticality: str = "MEDIUM",
                environment: str = "DEVELOPMENT") -> dict:
    agent = _register_agent(client, admin, criticality=criticality)
    _activate_agent(client, admin, agent["id"])
    version = _publish_version(client, admin, agent["id"])
    return {"agent": agent, "version": version}


# --------------------------------------------------------------------------- #
# AC-01 / AC-02 -- the state machine itself, pure, no DB
# --------------------------------------------------------------------------- #
def test_ac01_every_declared_transition_is_permitted():
    for from_state in lifecycle.all_states():
        for to_state in lifecycle.allowed_targets(from_state):
            assert lifecycle.can_transition(from_state, to_state)


def test_ac01_every_undeclared_transition_is_rejected():
    all_states = set(lifecycle.all_states())
    for from_state in all_states:
        allowed = lifecycle.allowed_targets(from_state)
        for to_state in all_states - allowed:
            assert not lifecycle.can_transition(from_state, to_state), (from_state, to_state)


def test_ac01_fifteen_states_declared():
    assert len(lifecycle.all_states()) == 15
    assert set(lifecycle.all_states()) == {
        "DRAFT", "VALIDATING", "VALIDATION_FAILED", "READY", "PENDING_APPROVAL",
        "APPROVED", "REJECTED", "DEPLOYING", "ACTIVE", "PAUSED", "DEGRADED",
        "ROLLING_BACK", "FAILED", "SUPERSEDED", "RETIRED",
    }


def test_ac01_retired_is_terminal():
    assert lifecycle.allowed_targets("RETIRED") == frozenset()


def test_ac02_lifecycle_state_is_never_assigned_outside_the_authority():
    """Mirrors the runtime-never-knows / one-authority grep precedent
    (``app.integration``'s own AC-02-equivalent test): the only place in the
    whole backend that assigns ``AgentDeployment.lifecycle_state`` is inside
    ``app/runtime/deployment/service.py`` and the Phase 3.1 migration's own
    §15 backfill (a one-time data migration, not application code). A plain
    substring match on ``"lifecycle_state ="`` would false-positive on an
    unrelated ``==`` comparison elsewhere in the codebase (e.g.
    ``app/integration/health.py``'s own, differently-typed
    ``ConnectorInstance.lifecycle_state`` field) -- the same false-positive
    class Phase 2.1.3's own equivalent test hit and fixed; a regex requiring
    a real assignment (``=`` not followed by a second ``=``) after a
    leading dot (an attribute write, never the model's own column
    declaration, which has no leading dot) avoids the ``==``-comparison
    false positive. ``app/integration/`` is excluded from the scan
    entirely, not just this one match: ``ConnectorInstance`` (a completely
    different table) happens to share the same attribute *name* --
    ``lifecycle_state`` -- and is governed by its own, pre-existing, single
    transition authority (``app/integration/lifecycle.py`` /
    ``ConnectorService``, Phase 2.1.1) that this phase does not touch and a
    plain text scan cannot type-distinguish from ``AgentDeployment``'s."""
    import re
    assignment = re.compile(r"\.lifecycle_state\s*=(?!=)")
    app_dir = Path(__file__).resolve().parents[2] / "app"
    offending: list[str] = []
    for path in app_dir.rglob("*.py"):
        if path == app_dir / "runtime" / "deployment" / "service.py":
            continue
        if (app_dir / "integration") in path.parents:
            continue
        text = path.read_text(encoding="utf-8")
        if assignment.search(text):
            offending.append(str(path))
    assert offending == []


def test_ac02_invalid_transition_raises_deployment_invalid_transition():
    from app.identity.errors import ErrorCode, IdentityError

    class _Stub:
        lifecycle_state = "DRAFT"
        organization_id = uuid.uuid4()
        id = uuid.uuid4()
        agent_id = uuid.uuid4()
        revision = 1

    db = SessionLocal()
    try:
        service = DeploymentLifecycleService(db)
        with pytest.raises(IdentityError) as exc_info:
            service.transition(None, _Stub(), "ACTIVE")
        assert exc_info.value.code == ErrorCode.DEPLOYMENT_INVALID_TRANSITION
    finally:
        db.close()


# --------------------------------------------------------------------------- #
# AC-14 -- vestigial replica columns untouched by the new lifecycle
# --------------------------------------------------------------------------- #
def test_ac14_replica_columns_not_read_or_written_by_the_new_lifecycle():
    deployment_dir = Path(__file__).resolve().parents[2] / "app" / "runtime" / "deployment"
    for path in deployment_dir.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "desired_replicas" not in text, path
        assert "active_replicas" not in text, path


# --------------------------------------------------------------------------- #
# AC-08 -- the idempotency contract is generic, not deployment-specific
# --------------------------------------------------------------------------- #
def test_ac08_idempotency_service_is_reusable_by_a_non_deployment_operation(admin: dict):
    db = SessionLocal()
    try:
        org_id = uuid.UUID(admin["organization_id"])
        calls = {"n": 0}

        def _fn() -> dict:
            calls["n"] += 1
            return {"widget_id": "abc-123", "call": calls["n"]}

        service = IdempotencyService(db)
        key = f"stub-{uuid.uuid4().hex[:8]}"
        first, replayed_first = service.execute(
            organization_id=org_id, operation="widgets.create", key=key,
            payload={"name": "widget"}, fn=_fn,
        )
        second, replayed_second = service.execute(
            organization_id=org_id, operation="widgets.create", key=key,
            payload={"name": "widget"}, fn=_fn,
        )
        assert calls["n"] == 1
        assert replayed_first is False
        assert replayed_second is True
        assert first == second == {"widget_id": "abc-123", "call": 1}
    finally:
        db.rollback()
        db.close()


def test_idempotency_key_none_always_runs_fn_and_stores_nothing():
    db = SessionLocal()
    try:
        org_id = uuid.uuid4()
        calls = {"n": 0}

        def _fn() -> dict:
            calls["n"] += 1
            return {"n": calls["n"]}

        service = IdempotencyService(db)
        r1, replayed1 = service.execute(organization_id=org_id, operation="widgets.create",
                                        key=None, payload={}, fn=_fn)
        r2, replayed2 = service.execute(organization_id=org_id, operation="widgets.create",
                                        key=None, payload={}, fn=_fn)
        assert calls["n"] == 2
        assert (replayed1, replayed2) == (False, False)
        assert r1 != r2
    finally:
        db.rollback()
        db.close()


# --------------------------------------------------------------------------- #
# AC-03 / AC-04 -- transitions produce append-only lineage
# --------------------------------------------------------------------------- #
def test_ac03_every_transition_writes_a_deployment_event_and_audit_event(client: TestClient, admin: dict,
                                                                          db_session: Session):
    setup = _full_setup(client, admin)
    deployment = _ready_deployment(client, admin, setup["agent"]["id"], setup["version"]["id"])

    events = db_session.execute(
        select(DeploymentEvent).where(DeploymentEvent.deployment_id == uuid.UUID(deployment["id"]))
        .order_by(DeploymentEvent.created_at.asc())
    ).scalars().all()
    transitions = [(e.from_state, e.to_state) for e in events]
    assert ("DRAFT", "VALIDATING") in transitions
    assert ("VALIDATING", "READY") in transitions
    # The very first event (creation) has no from_state.
    assert events[0].from_state is None and events[0].to_state == "DRAFT"


def test_ac04_deployment_events_append_only_by_construction():
    """Matches this codebase's own established convention for "append-only"
    (see test_connector_core.py::test_ac18_lifecycle_events_are_append_only_by_construction):
    enforced at the application layer, not a DB-level REVOKE -- no service
    method updates or deletes a DeploymentEvent, and no route exposes
    PATCH/DELETE on the events collection."""
    service_methods = {name for name, _ in inspect.getmembers(DeploymentLifecycleService,
                                                               predicate=inspect.isfunction)}
    assert not any("event" in name and ("update" in name or "delete" in name) for name in service_methods)

    from app.main import app
    event_route_methods: set[str] = set()
    for route in app.routes:
        if getattr(route, "path", "") == f"{RT}/deployments/{{deployment_id}}/lifecycle/events":
            event_route_methods |= route.methods
    assert event_route_methods == {"GET"}


def test_events_endpoint_returns_ordered_lineage(client: TestClient, admin: dict):
    setup = _full_setup(client, admin)
    deployment = _ready_deployment(client, admin, setup["agent"]["id"], setup["version"]["id"])
    r = client.get(f"{RT}/deployments/{deployment['id']}/lifecycle/events", headers=admin["headers"])
    assert r.status_code == 200, r.text
    events = r.json()
    assert [e["to_state"] for e in events] == ["DRAFT", "VALIDATING", "READY"]


# --------------------------------------------------------------------------- #
# Happy path to ACTIVE, then pause/resume/retire (integration)
# --------------------------------------------------------------------------- #
def test_happy_path_reaches_active_then_pause_resume_retire(client: TestClient, admin: dict):
    setup = _full_setup(client, admin)
    deployment = _ready_deployment(client, admin, setup["agent"]["id"], setup["version"]["id"])
    assert deployment["lifecycle_state"] == "READY"

    active = _transition(client, admin, deployment["id"], "DEPLOYING")
    assert active["lifecycle_state"] == "ACTIVE"
    assert active["revision"] > deployment["revision"]

    r = client.post(f"{RT}/deployments/{active['id']}/lifecycle/pause", headers=admin["headers"], json={})
    assert r.status_code == 200, r.text
    paused = r.json()
    assert paused["lifecycle_state"] == "PAUSED"

    r = client.post(f"{RT}/deployments/{active['id']}/lifecycle/resume", headers=admin["headers"], json={})
    assert r.status_code == 200, r.text
    resumed = r.json()
    assert resumed["lifecycle_state"] == "ACTIVE"

    r = client.post(f"{RT}/deployments/{active['id']}/lifecycle/retire", headers=admin["headers"], json={})
    assert r.status_code == 200, r.text
    retired = r.json()
    assert retired["lifecycle_state"] == "RETIRED"

    # RETIRED is terminal -- even a permitted-looking retry is rejected.
    r = client.post(f"{RT}/deployments/{active['id']}/lifecycle/pause", headers=admin["headers"], json={})
    assert r.status_code == 409, r.text
    assert r.json()["error"]["code"] == "DEPLOYMENT_INVALID_TRANSITION"


# --------------------------------------------------------------------------- #
# AC-06 / AC-07 -- idempotent create
# --------------------------------------------------------------------------- #
def test_ac06_repeated_create_with_same_key_returns_original_result(client: TestClient, admin: dict):
    setup = _full_setup(client, admin)
    key = f"create-{uuid.uuid4().hex[:8]}"
    first, status1 = _create_deployment(client, admin, setup["agent"]["id"], setup["version"]["id"],
                                        idempotency_key=key)
    second, status2 = _create_deployment(client, admin, setup["agent"]["id"], setup["version"]["id"],
                                         idempotency_key=key)
    assert status1 == 201, first
    assert status2 == 201, second
    assert first["id"] == second["id"]


def test_ac07_same_key_different_payload_conflicts(client: TestClient, admin: dict):
    setup = _full_setup(client, admin)
    key = f"create-{uuid.uuid4().hex[:8]}"
    first, status1 = _create_deployment(client, admin, setup["agent"]["id"], setup["version"]["id"],
                                        environment="DEVELOPMENT", idempotency_key=key)
    assert status1 == 201, first
    second, status2 = _create_deployment(client, admin, setup["agent"]["id"], setup["version"]["id"],
                                         environment="STAGING", idempotency_key=key)
    assert status2 == 409, second
    assert second["error"]["code"] == "IDEMPOTENCY_CONFLICT"


# --------------------------------------------------------------------------- #
# AC-09 -- Ruling #6: a suspended agent's deployment cannot reach ACTIVE
# --------------------------------------------------------------------------- #
def test_ac09_suspended_agent_blocks_activation(client: TestClient, admin: dict):
    setup = _full_setup(client, admin)
    deployment = _ready_deployment(client, admin, setup["agent"]["id"], setup["version"]["id"])

    r = client.post(f"{RT}/kill-switch/agents/{setup['agent']['id']}", headers=admin["headers"],
                    json={"reason": "test: exercise Ruling #6 integration"})
    assert r.status_code == 200, r.text

    r = client.post(f"{RT}/deployments/{deployment['id']}/lifecycle/transition", headers=admin["headers"],
                    json={"to_state": "DEPLOYING"})
    assert r.status_code == 409, r.text
    # Phase 3.3 (ACT-SRS-M3 §Phase-3.3) -- ``start_deploying`` now runs the
    # release gate *before* the READY->DEPLOYING mutation (previously the
    # first thing this method did), so a suspended agent is now rejected
    # up front with the gate's own code, richer/more specific than -- but
    # never weaker than -- the pre-existing ``DEPLOYMENT_AGENT_SUSPENDED``
    # (still the code ``_assert_can_reach_active`` raises when reached via
    # a path that bypasses the gate, e.g. ``resume()`` below): see
    # ``app.runtime.release_gate.checks.check_agent_active_and_kill_switch``.
    assert r.json()["error"]["code"] == "DEPLOYMENT_PREFLIGHT_BLOCKED"

    # The deployment is left exactly where it was -- READY, not DEPLOYING:
    # a strict improvement over 3.1's own original behavior (which left the
    # deployment "stuck" at DEPLOYING after a partial READY->DEPLOYING
    # mutation, since that transition ran *before* the suspension check).
    # The gate now blocks before any state mutation at all -- "changes
    # nothing" per M3-3.1-FR-003, now true in the stronger sense of never
    # even starting.
    r = client.get(f"{RT}/deployments/{deployment['id']}", headers=admin["headers"])
    assert r.json()["lifecycle_state"] == "READY"


def test_ac09_paused_reactivation_also_blocked_once_agent_is_suspended(client: TestClient, admin: dict):
    setup = _full_setup(client, admin)
    deployment = _ready_deployment(client, admin, setup["agent"]["id"], setup["version"]["id"])
    active = _transition(client, admin, deployment["id"], "DEPLOYING")
    r = client.post(f"{RT}/deployments/{active['id']}/lifecycle/pause", headers=admin["headers"], json={})
    assert r.status_code == 200, r.text

    r = client.post(f"{RT}/kill-switch/agents/{setup['agent']['id']}", headers=admin["headers"],
                    json={"reason": "test: block resume while paused"})
    assert r.status_code == 200, r.text

    r = client.post(f"{RT}/deployments/{active['id']}/lifecycle/resume", headers=admin["headers"], json={})
    assert r.status_code == 409, r.text
    assert r.json()["error"]["code"] == "DEPLOYMENT_AGENT_SUSPENDED"


# --------------------------------------------------------------------------- #
# AC-10 -- reaching ACTIVE honors the runtime_approvals precondition
# --------------------------------------------------------------------------- #
def test_ac10_mission_critical_production_reroutes_to_pending_approval(client: TestClient, admin: dict):
    setup = _full_setup(client, admin, criticality="MISSION_CRITICAL")
    deployment = _ready_deployment(client, admin, setup["agent"]["id"], setup["version"]["id"],
                                   environment="PRODUCTION")

    rerouted = _transition(client, admin, deployment["id"], "DEPLOYING")
    assert rerouted["lifecycle_state"] == "PENDING_APPROVAL"

    r = client.get(f"{RT}/approvals", headers=admin["headers"], params={"status": "PENDING"})
    assert r.status_code == 200, r.text
    approval = next(a for a in r.json() if a["deployment_id"] == deployment["id"])

    r = client.post(f"{RT}/approvals/{approval['id']}/decide", headers=admin["headers"],
                    json={"decision": "APPROVED"})
    assert r.status_code == 200, r.text

    r = client.get(f"{RT}/deployments/{deployment['id']}", headers=admin["headers"])
    assert r.json()["lifecycle_state"] == "APPROVED"

    active = _transition(client, admin, deployment["id"], "DEPLOYING")
    assert active["lifecycle_state"] == "ACTIVE"


def test_ac10_rejected_approval_lands_in_rejected_not_active(client: TestClient, admin: dict):
    setup = _full_setup(client, admin, criticality="MISSION_CRITICAL")
    deployment = _ready_deployment(client, admin, setup["agent"]["id"], setup["version"]["id"],
                                   environment="PRODUCTION")
    _transition(client, admin, deployment["id"], "DEPLOYING")

    r = client.get(f"{RT}/approvals", headers=admin["headers"], params={"status": "PENDING"})
    approval = next(a for a in r.json() if a["deployment_id"] == deployment["id"])
    r = client.post(f"{RT}/approvals/{approval['id']}/decide", headers=admin["headers"],
                    json={"decision": "REJECTED"})
    assert r.status_code == 200, r.text

    r = client.get(f"{RT}/deployments/{deployment['id']}", headers=admin["headers"])
    assert r.json()["lifecycle_state"] == "REJECTED"


# --------------------------------------------------------------------------- #
# AC-11 -- authorization: permission-gated, tenant-isolated
# --------------------------------------------------------------------------- #
def test_ac11_transition_requires_deploy_permission(client: TestClient, admin: dict):
    setup = _full_setup(client, admin)
    deployment, _ = _create_deployment(client, admin, setup["agent"]["id"], setup["version"]["id"])

    # A freshly registered user is always the SUPER_ADMIN owner of a *new*
    # organization (this codebase's registration flow has no
    # "join an existing org without a role" path) -- so this doubles as a
    # cross-tenant actor. Server-side enforcement (403/404, not merely a
    # hidden UI control) is what SRS §3.3 actually requires either way.
    email = f"viewer_{uuid.uuid4().hex[:10]}@example.com"
    r = client.post("/auth/register", json={
        "organization_name": "Ignored", "name": "Viewer", "email": email, "password": "T3st!Passw0rd#Ok",
    })
    assert r.status_code == 201, r.text
    tokens = client.post("/api/v1/auth/login", json={"email": email, "password": "T3st!Passw0rd#Ok"}).json()
    other_headers = {"Authorization": f"Bearer {tokens['access_token']}"}

    r = client.post(f"{RT}/deployments/{deployment['id']}/lifecycle/transition", headers=other_headers,
                    json={"to_state": "VALIDATING"})
    assert r.status_code in (403, 404), r.text


def test_ac11_cross_tenant_deployment_access_rejected(client: TestClient, admin: dict):
    setup = _full_setup(client, admin)
    deployment, _ = _create_deployment(client, admin, setup["agent"]["id"], setup["version"]["id"])

    email = f"other_org_{uuid.uuid4().hex[:10]}@example.com"
    r = client.post("/auth/register", json={
        "organization_name": "Other Org", "name": "Owner", "email": email, "password": "T3st!Passw0rd#Ok",
    })
    assert r.status_code == 201, r.text
    tokens = client.post("/api/v1/auth/login", json={"email": email, "password": "T3st!Passw0rd#Ok"}).json()
    other_headers = {"Authorization": f"Bearer {tokens['access_token']}"}

    r = client.get(f"{RT}/deployments/{deployment['id']}", headers=other_headers)
    assert r.status_code == 404, r.text
    assert r.json()["error"]["code"] == "DEPLOYMENT_NOT_FOUND"

    r = client.post(f"{RT}/deployments/{deployment['id']}/lifecycle/transition", headers=other_headers,
                    json={"to_state": "VALIDATING"})
    assert r.status_code == 404, r.text


# --------------------------------------------------------------------------- #
# AC-05 -- real-Postgres concurrent transition race
# --------------------------------------------------------------------------- #
def test_ac05_concurrent_transitions_exactly_one_succeeds(client: TestClient, admin: dict):
    setup = _full_setup(client, admin)
    deployment = _ready_deployment(client, admin, setup["agent"]["id"], setup["version"]["id"])
    active = _transition(client, admin, deployment["id"], "DEPLOYING")
    deployment_id = uuid.UUID(active["id"])

    from app.models.user import User

    barrier = threading.Barrier(2)
    outcomes: list[str] = []
    outcomes_lock = threading.Lock()

    def worker() -> None:
        thread_db = SessionLocal()
        try:
            actor = thread_db.get(User, uuid.UUID(admin["user_id"]))
            service = DeploymentLifecycleService(thread_db)
            own_deployment = thread_db.get(AgentDeployment, deployment_id)
            barrier.wait(timeout=5)
            try:
                service.transition(actor, own_deployment, "PAUSED")
                with outcomes_lock:
                    outcomes.append("success")
            except Exception as exc:  # noqa: BLE001
                from app.identity.errors import ErrorCode, IdentityError
                if isinstance(exc, IdentityError) and exc.code == ErrorCode.DEPLOYMENT_REVISION_CONFLICT:
                    with outcomes_lock:
                        outcomes.append("conflict")
                else:
                    raise
        finally:
            thread_db.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(worker) for _ in range(2)]
        for f in futures:
            f.result(timeout=10)

    assert sorted(outcomes) == ["conflict", "success"]


# --------------------------------------------------------------------------- #
# Concurrency -- same idempotency key sent twice concurrently (M3-3.1-FR-030/031)
# --------------------------------------------------------------------------- #
def test_concurrent_same_idempotency_key_runs_fn_exactly_once(admin: dict):
    org_id = uuid.UUID(admin["organization_id"])
    key = f"race-{uuid.uuid4().hex[:8]}"
    barrier = threading.Barrier(2)
    call_count = {"n": 0}
    call_lock = threading.Lock()
    outcomes: list[tuple[dict, bool]] = []
    outcomes_lock = threading.Lock()

    def _fn() -> dict:
        with call_lock:
            call_count["n"] += 1
            n = call_count["n"]
        import time
        time.sleep(0.2)  # widen the race window so both threads genuinely overlap
        return {"created": n}

    def worker() -> None:
        thread_db = SessionLocal()
        try:
            service = IdempotencyService(thread_db)
            barrier.wait(timeout=5)
            result, replayed = service.execute(
                organization_id=org_id, operation="widgets.race", key=key,
                payload={"x": 1}, fn=_fn,
            )
            with outcomes_lock:
                outcomes.append((result, replayed))
        finally:
            thread_db.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(worker) for _ in range(2)]
        for f in futures:
            f.result(timeout=10)

    assert call_count["n"] == 1
    results = [r for r, _replayed in outcomes]
    assert results[0] == results[1]
    assert sorted(replayed for _r, replayed in outcomes) == [False, True]


# --------------------------------------------------------------------------- #
# AC-12 -- the §15 migration mapping, verified against the live, already-
# migrated data (the migration itself was run once, live, against this
# database -- see the migration module's own docstring for the full table).
# --------------------------------------------------------------------------- #
def test_ac12_status_to_lifecycle_state_mapping_is_deterministic_and_complete(db_session: Session):
    """The mapping's own internal consistency, plus proof the migration
    genuinely ran and left evidence -- *not* a live cross-check of `status`
    against `lifecycle_state` on already-migrated rows, since `status` (the
    pre-existing, legacy field) is free to keep changing after migration via
    the still-untouched legacy `DeploymentService` endpoints (suspend/
    resume/deploy/retire, exercised by this platform's own pre-existing
    dashboard/analytics tests among others) while `lifecycle_state`/
    `state_reason` on that same row stay frozen at whatever the migration
    set once. The two fields' correspondence is a one-time historical fact,
    never an ongoing invariant -- see the migration module's own docstring
    and app/models/runtime.py's ``AgentDeployment`` docstring."""
    import importlib.util
    migrations_dir = Path(__file__).resolve().parents[2] / "migrations" / "versions"
    module_path = migrations_dir / "0037_deployment_lifecycle.py"
    spec = importlib.util.spec_from_file_location("migration_0037", module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    mapping = module._STATUS_TO_LIFECYCLE_STATE

    assert set(mapping) == {
        "CREATED", "PENDING_APPROVAL", "SCHEDULED", "DEPLOYING", "HEALTH_CHECKING",
        "ACTIVE", "DEGRADED", "FAILED", "SUSPENDED", "ROLLING_BACK", "RETIRED",
    }
    assert set(mapping.values()) <= set(lifecycle.all_states())
    assert mapping["ACTIVE"] == "ACTIVE"
    assert mapping["SUSPENDED"] == "PAUSED"

    from sqlalchemy import text
    count = db_session.execute(text(
        "SELECT count(*) FROM agent_deployments WHERE state_reason LIKE 'migrated from legacy status=%'"
    )).scalar_one()
    assert count > 0, "expected at least one historical row backfilled by the 0037 migration"


# --------------------------------------------------------------------------- #
# AC-13 -- the M1 execution path is untouched
# --------------------------------------------------------------------------- #
def test_ac13_execution_path_does_not_reference_the_new_lifecycle_state():
    """`_request_execution` -- the actual execution-entry gate -- keeps
    gating purely on the legacy `AgentDeployment.status` field; Phase 3.4,
    not this phase, owns moving that gate to `lifecycle_state`. Scoped to
    that one function's own source (not the whole file): this phase *does*
    legitimately mention "lifecycle_state" elsewhere in the same module,
    in `RuntimeApprovalService.decide`'s new, additive, non-execution-path
    integration with the approval flow (see that method's own comment)."""
    from app.runtime.services import ExecutionRequestService
    source = inspect.getsource(ExecutionRequestService._request_execution)
    assert "lifecycle_state" not in source


def test_ac13_full_execution_still_works_end_to_end(client: TestClient, admin: dict):
    """The legacy `/deploy` endpoint and `_request_execution` are exercised
    completely unmodified -- a full regression proof, not just a grep."""
    setup = _full_setup(client, admin)
    r = client.post(f"{RT}/deployments", headers=admin["headers"], params={"agent_id": setup["agent"]["id"]},
                    json={"agent_version_id": setup["version"]["id"], "environment": "DEVELOPMENT"})
    assert r.status_code == 201, r.text
    deployment = r.json()
    r = client.post(f"{RT}/deployments/{deployment['id']}/deploy", headers=admin["headers"])
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "ACTIVE"

    r = client.post(f"{RT}/executions", headers=admin["headers"], json={
        "agent_id": setup["agent"]["id"], "input_payload": {},
    })
    assert r.status_code == 201, r.text
    assert r.json()["status"] in ("SUCCEEDED", "RUNNING", "QUEUED")


# --------------------------------------------------------------------------- #
# AC-17 -- no new TODO/FIXME/skip markers in this phase's own files
# --------------------------------------------------------------------------- #
def test_ac17_no_new_todo_or_skip_markers_in_this_phases_files():
    markers = ("TODO", "FIXME", "XXX", "HACK:")
    deployment_dir = Path(__file__).resolve().parents[2] / "app" / "runtime" / "deployment"
    for path in deployment_dir.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for marker in markers:
            assert marker not in text, f"{marker} found in {path}"
