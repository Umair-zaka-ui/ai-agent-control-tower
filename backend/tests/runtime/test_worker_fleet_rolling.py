"""Phase 3.9 (ACT-SRS-M3 §Phase-3.9, §16, §21) tests -- the distributed
execution worker fleet and ROLLING deployment over real worker cohorts.

Grouped by the build prompt's own §12 acceptance criteria.

**The two gates are ``test_ac03_*`` and ``test_ac05_*``.** Both use *real
separate database connections* (a second ``SessionLocal``), never an
in-process mutex or a thread barrier, because the properties under test are
about operating-system processes coordinating solely through Postgres. A test
that shared a session would prove nothing about either.

``test_ac03_*`` is the one that matters most in the milestone: it proves the
claim transaction commits *before* the execution runs, so a worker holds no
database lock across model or tool network I/O. That is the M1 deadlock,
which this phase reproduces at fleet scale if it gets the boundary wrong, and
it is checked three ways -- behaviourally, from inside a running execution,
and structurally.

**Shared-database hygiene.** ``claim_next`` deliberately claims *any* queued
execution, globally and across tenants -- that is what a shared worker pool
is. This suite runs against the same persistent local database as every other
test, so ``_quiesce`` parks leftover work before each test that asserts "my
execution ran". Without it, a test would intermittently claim an older row
from an unrelated suite and assert against the wrong execution. The same
hygiene Phase 3.8 needed for job definitions, for the same reason.
"""

from __future__ import annotations

import ast
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select, text, update
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.identity.errors import ErrorCode, IdentityError
from app.models.agent import Agent
from app.models.runtime import (
    AgentExecution,
    ExecutionLock,
    RolloutPlan,
    RuntimeEvent,
)
from app.models.user import User as UserModel
from app.models.worker import WorkerRegistration
from app.runtime.deployment import rolling as rolling_module
from app.runtime.deployment import strategies as strategies_module
from app.runtime.deployment.rolling import RollingDeploymentService, derive_cohort_steps
from app.runtime.deployment.traffic import TrafficAllocationService
from app.runtime.services import ExecutionWorkerService, _now
from app.workers import fleet as fleet_module
from app.workers import runner as runner_module
from app.workers.fleet import WorkerFleetService
from app.workers.worker import ExecutionWorker

RT = "/api/v1/runtime"


# --------------------------------------------------------------------------- #
# Shared-database hygiene
# --------------------------------------------------------------------------- #
def _quiesce(db: Session) -> None:
    """Remove other suites' leftovers from the shared queue and fleet.

    Terminalizes stray non-terminal executions, drops their locks, and stops
    every registered worker. Changes nothing about what this phase's code
    does with real work -- it only guarantees that "the queue" and "the fleet"
    mean *this test's* queue and fleet."""
    db.rollback()
    db.execute(delete(ExecutionLock))
    db.execute(update(AgentExecution)
               .where(AgentExecution.status.in_(("QUEUED", "RUNNING")))
               .values(status="CANCELLED", completed_at=_now()))
    db.execute(update(WorkerRegistration)
               .where(WorkerRegistration.status != "STOPPED")
               .values(status="STOPPED", active_count=0, stopped_at=_now()))
    db.commit()


# --------------------------------------------------------------------------- #
# HTTP setup helpers (this suite's convention: each file defines its own)
# --------------------------------------------------------------------------- #
def _register_agent(client: TestClient, admin: dict) -> dict:
    nonce = uuid.uuid4().hex[:8]
    r = client.post(f"{RT}/agents", headers=admin["headers"], json={
        "name": f"Fleet Agent {nonce}", "agent_type": "ASSISTANT", "criticality": "MEDIUM",
        "description": f"Test agent {nonce}.",
        "business_purpose": f"Exercise the worker fleet {nonce} in tests.",
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
                     strategy: str = "RECREATE", environment: str = "DEVELOPMENT") -> dict:
    """Deploys through the 3.1 lifecycle route rather than the legacy
    ``/deploy``, for the reason Phases 3.6 and 3.7 both documented: the legacy
    route retires sibling deployments, leaving nothing to roll between."""
    r = client.post(f"{RT}/deployments", headers=admin["headers"], params={"agent_id": agent_id},
                    json={"agent_version_id": version_id, "environment": environment,
                          "deployment_strategy": strategy})
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


def _setup(client: TestClient, admin: dict, *, candidate_strategy: str = "ROLLING") -> dict:
    envs = _environments(client, admin)
    agent = _register_agent(client, admin)
    _activate_agent(client, admin, agent["id"])
    stable = _publish_version(client, admin, agent["id"])
    candidate = _publish_version(client, admin, agent["id"])
    stable_deployment = _lifecycle_deploy(client, admin, agent["id"], stable["id"])
    candidate_deployment = _lifecycle_deploy(client, admin, agent["id"], candidate["id"],
                                             strategy=candidate_strategy)
    return {"agent": agent, "stable": stable, "candidate": candidate,
            "stable_deployment": stable_deployment,
            "candidate_deployment": candidate_deployment,
            "environment": envs["DEVELOPMENT"]}


def _enqueue(db: Session, setup: dict, admin: dict, *, count: int = 1) -> list[uuid.UUID]:
    """Put real, claimable work on the queue.

    Inserted directly rather than through ``POST /executions``, because that
    endpoint runs a worker *inline* and would complete the execution before
    any fleet worker could see it. The row is identical to the one the API
    produces -- this only skips the eager execution, not the enqueue."""
    ids = []
    for _ in range(count):
        execution = AgentExecution(
            organization_id=uuid.UUID(admin["organization_id"]),
            agent_id=uuid.UUID(setup["agent"]["id"]),
            agent_version_id=uuid.UUID(setup["candidate"]["id"]),
            deployment_id=uuid.UUID(setup["candidate_deployment"]["id"]),
            trigger_type="API", status="QUEUED", priority="NORMAL",
            input_payload={}, queued_at=_now(),
        )
        db.add(execution)
        db.flush()
        ids.append(execution.id)
    db.commit()
    return ids


def _register_workers(db: Session, cohorts: dict[str, int]) -> list[WorkerRegistration]:
    """Register one worker per cohort with the given declared concurrency."""
    fleet = WorkerFleetService(db)
    return [fleet.register(f"w-{cohort}-{uuid.uuid4().hex[:6]}",
                           cohort=cohort, concurrency=concurrency)
            for cohort, concurrency in cohorts.items()]


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
# AC-01 -- worker identity, registration, heartbeat, lifecycle
# --------------------------------------------------------------------------- #
def test_ac01_a_worker_registers_heartbeats_and_is_observable(
    client: TestClient, admin: dict, db_session: Session,
) -> None:
    _quiesce(db_session)
    worker = ExecutionWorker(worker_id=f"w-{uuid.uuid4().hex[:8]}", cohort="alpha", concurrency=3)
    row = worker.start()
    assert row.status == "RUNNING"
    assert row.cohort == "alpha"
    assert row.concurrency == 3

    first_beat = row.heartbeat_at
    worker.heartbeat()

    r = client.get(f"{RT}/fleet", headers=admin["headers"])
    assert r.status_code == 200, r.text
    body = r.json()
    listed = {w["worker_id"]: w for w in body["workers"]}
    assert worker.worker_id in listed
    assert listed[worker.worker_id]["concurrency"] == 3
    assert body["capacity_by_cohort"]["alpha"] == 3

    db_session.rollback()
    refreshed = WorkerFleetService(db_session).get_or_404(worker.worker_id)
    assert refreshed.heartbeat_at >= first_beat


def test_ac01_worker_lifecycle_running_draining_stopped(db_session: Session) -> None:
    _quiesce(db_session)
    worker = ExecutionWorker(worker_id=f"w-{uuid.uuid4().hex[:8]}", concurrency=1)
    worker.start()
    fleet = WorkerFleetService(db_session)

    worker.drain()
    db_session.rollback()
    assert fleet.get_or_404(worker.worker_id).status == "DRAINING"

    worker.stop()
    db_session.rollback()
    stopped = fleet.get_or_404(worker.worker_id)
    assert stopped.status == "STOPPED"
    assert stopped.stopped_at is not None


def test_ac01_re_registration_updates_rather_than_duplicates(db_session: Session) -> None:
    """A restarted process is the same worker returning, not a new one. A row
    per launch would make the fleet a history of boots and would make capacity
    arithmetic count dead processes."""
    _quiesce(db_session)
    worker_id = f"w-{uuid.uuid4().hex[:8]}"
    fleet = WorkerFleetService(db_session)
    fleet.register(worker_id, cohort="a", concurrency=2)
    fleet.drain(worker_id)
    fleet.register(worker_id, cohort="a", concurrency=5)

    db_session.rollback()
    rows = db_session.execute(select(WorkerRegistration).where(
        WorkerRegistration.worker_id == worker_id)).scalars().all()
    assert len(rows) == 1
    # A process that has just started is by definition not draining.
    assert rows[0].status == "RUNNING"
    assert rows[0].concurrency == 5


def test_ac01_a_stopped_worker_cannot_heartbeat_back_into_the_fleet(
    db_session: Session,
) -> None:
    """Letting a heartbeat quietly undo a stop would make drain-then-stop
    racy: the stopping worker's last in-flight beat could resurrect it."""
    _quiesce(db_session)
    fleet = WorkerFleetService(db_session)
    worker_id = f"w-{uuid.uuid4().hex[:8]}"
    fleet.register(worker_id)
    fleet.stop(worker_id)

    with pytest.raises(IdentityError) as exc:
        fleet.heartbeat(worker_id)
    assert exc.value.code == ErrorCode.WORKER_INVALID_STATE


def test_ac01_an_unknown_worker_is_a_404(db_session: Session) -> None:
    with pytest.raises(IdentityError) as exc:
        WorkerFleetService(db_session).get_or_404("no-such-worker")
    assert exc.value.code == ErrorCode.WORKER_NOT_FOUND


# --------------------------------------------------------------------------- #
# AC-02 -- the claim, preserving M1's FOR UPDATE SKIP LOCKED
# --------------------------------------------------------------------------- #
def test_ac02_the_claim_still_uses_for_update_skip_locked() -> None:
    """Structural: M1's claim primitive is preserved, not replaced.

    Asserted on the call rather than on the words, because this method's own
    docstring discusses ``SKIP LOCKED`` at length -- a source grep for the
    phrase would match the explanation and pass even if the query lost it."""
    import inspect

    source = inspect.getsource(ExecutionWorkerService.claim_next)
    body = source.split('"""')[-1]
    assert "with_for_update(skip_locked=True)" in body


def test_ac02_one_execution_is_claimed_by_exactly_one_worker(
    client: TestClient, admin: dict, db_session: Session,
) -> None:
    """Two real connections, one queued execution."""
    _quiesce(db_session)
    setup = _setup(client, admin)
    (execution_id,) = _enqueue(db_session, setup, admin)

    def _claim(worker_id: str) -> str | None:
        db = SessionLocal()
        try:
            claimed = ExecutionWorkerService(db).claim_next(worker_id)
            return str(claimed.id) if claimed is not None else None
        finally:
            db.rollback()
            db.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(_claim, ["worker-a", "worker-b"]))

    assert results.count(str(execution_id)) == 1, results
    assert results.count(None) == 1, results

    db_session.rollback()
    locks = db_session.execute(select(ExecutionLock).where(
        ExecutionLock.execution_id == execution_id)).scalars().all()
    assert len(locks) == 1, "execution_locks.execution_id is UNIQUE -- one owner or none"


def test_ac02_a_drained_worker_claims_nothing(
    client: TestClient, admin: dict, db_session: Session,
) -> None:
    _quiesce(db_session)
    setup = _setup(client, admin)
    _enqueue(db_session, setup, admin)

    worker = ExecutionWorker(worker_id=f"w-{uuid.uuid4().hex[:8]}", concurrency=2)
    worker.start()
    worker.drain()

    assert worker.available_slots == 0
    assert worker.tick() == 0
    assert worker.claim_and_run() is None


# --------------------------------------------------------------------------- #
# AC-03 -- THE GATE: the claim commits before the execution runs
# --------------------------------------------------------------------------- #
def test_ac03_the_claim_commits_before_the_execution_runs(
    client: TestClient, admin: dict, db_session: Session,
) -> None:
    """The proof, on real separate connections.

    After ``claim_next`` returns, a *different* connection must be able to
    take ``FOR UPDATE NOWAIT`` on the very row that was just claimed. Before
    Phase 3.9 this blocked, because the claim held its lock for the whole
    attempt; ``NOWAIT`` turns that block into an immediate error, so this
    test fails loudly rather than hanging if the boundary ever moves back."""
    _quiesce(db_session)
    setup = _setup(client, admin)
    (execution_id,) = _enqueue(db_session, setup, admin)

    claimer = SessionLocal()
    other = SessionLocal()
    try:
        claimed = ExecutionWorkerService(claimer).claim_next("boundary-worker")
        assert claimed is not None and claimed.id == execution_id

        # No lock is held across what would be the model/tool I/O.
        row = other.execute(
            text("SELECT status FROM agent_executions WHERE id = :i FOR UPDATE NOWAIT"),
            {"i": str(execution_id)},
        ).first()
        assert row is not None
        # And the claim is durably visible to that other connection -- which
        # is what stops a peer re-claiming it.
        assert row[0] == "RUNNING"
        other.rollback()
    finally:
        claimer.rollback()
        claimer.close()
        other.rollback()
        other.close()


def test_ac03_no_lock_is_held_across_model_io(
    client: TestClient, admin: dict, db_session: Session, monkeypatch,
) -> None:
    """The same property, observed from *inside* the model call.

    The model invocation is the network I/O window -- the long, slow,
    third-party-dependent part of an attempt, and precisely where the M1
    deadlock lived: ``_execute_parallel`` spawns tool threads around here, and
    each needs ``FOR KEY SHARE`` on this execution's row to insert a
    ``tool_calls`` child. If the worker still held its claim lock at this
    moment, those threads would block while the main thread waited on
    ``future.result()`` -- an application-level join waiting on a
    database-level lock wait, which Postgres's deadlock detector cannot see.

    **The lock mode is the point, and it took a failing test to get right.**
    The probe asks for ``FOR KEY SHARE NOWAIT`` -- *exactly* the lock a tool
    thread's ``INSERT INTO tool_calls`` needs on its parent row, and exactly
    the one the old claim-held ``FOR UPDATE`` blocked. Two ``FOR KEY SHARE``
    holders coexist happily, which is why the tool threads never fought each
    other; the deadlock was always the exclusive claim lock standing in their
    way.

    A first draft of this test probed with ``FOR UPDATE NOWAIT`` and failed
    against correct code, because by mid-attempt the worker legitimately holds
    a shared lock on its own row (it has inserted children of it) and an
    exclusive request conflicts with that. Asserting the strongest lock
    available would have been asserting something the design never promised.

    ``NOWAIT`` so a regression fails loudly instead of hanging."""
    _quiesce(db_session)
    setup = _setup(client, admin)
    (execution_id,) = _enqueue(db_session, setup, admin)
    observed: dict = {}

    from app.runtime.providers.mock import MockProvider

    original = MockProvider.complete

    def _probe(self, request):
        probe = SessionLocal()
        try:
            probe.execute(
                text("SELECT id FROM agent_executions WHERE id = :i FOR KEY SHARE NOWAIT"),
                {"i": str(execution_id)},
            ).first()
            observed["lock_free"] = True
        except Exception as exc:  # noqa: BLE001 -- recorded as data, then asserted
            observed["lock_free"] = False
            observed["error"] = str(exc)
        finally:
            probe.rollback()
            probe.close()
        return original(self, request)

    monkeypatch.setattr(MockProvider, "complete", _probe)

    db = SessionLocal()
    try:
        executed = ExecutionWorkerService(db).run_once("probe-worker")
    finally:
        db.rollback()
        db.close()

    assert executed is not None and executed.id == execution_id
    assert observed.get("lock_free") is True, observed


def test_ac03_the_commit_boundary_is_structural_not_incidental() -> None:
    """AST, not text: ``claim_next`` must end with a commit, and the commit
    must be on the claim path rather than only in some later ``finally``.

    Checked structurally because this method's docstring necessarily explains
    the words "commit" and "flush" at length -- a source grep would match the
    prose and prove nothing about the code."""
    import inspect
    import textwrap

    tree = ast.parse(textwrap.dedent(inspect.getsource(ExecutionWorkerService.claim_next)))
    func = tree.body[0]
    calls = [node for node in ast.walk(func)
             if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)]
    committed = [c for c in calls if c.func.attr == "commit"]
    flushed = [c for c in calls if c.func.attr == "flush"]
    assert committed, "claim_next must commit the claim before returning"
    assert not flushed, "a flush here would hold the claim lock across the execution"


# --------------------------------------------------------------------------- #
# AC-04 -- execution behaviour is identical to M1
# --------------------------------------------------------------------------- #
def test_ac04_a_worker_runs_a_real_execution_end_to_end(
    client: TestClient, admin: dict, db_session: Session,
) -> None:
    """The whole M1 pipeline, driven by a fleet worker instead of inline:
    provider call, token accounting, cost, terminal status and audit."""
    _quiesce(db_session)
    setup = _setup(client, admin)
    (execution_id,) = _enqueue(db_session, setup, admin)

    worker = ExecutionWorker(worker_id=f"w-{uuid.uuid4().hex[:8]}", concurrency=1)
    worker.start()
    assert worker.claim_and_run() == execution_id

    db_session.rollback()
    execution = db_session.get(AgentExecution, execution_id)
    assert execution.status == "SUCCEEDED", execution.error_message
    assert execution.output_payload is not None
    assert execution.model_usage["provider"] == "MOCK"
    assert execution.total_tokens is not None and execution.total_tokens > 0
    assert execution.cost_amount is not None
    assert execution.completed_at is not None
    assert execution.duration_ms is not None

    events = db_session.execute(select(RuntimeEvent).where(
        RuntimeEvent.execution_id == execution_id)).scalars().all()
    assert any(e.event_type == "RUNTIME_EXECUTION_SUCCEEDED" for e in events)


def test_ac04_the_worker_module_contains_no_execution_logic() -> None:
    """Structural preservation: distributing execution must not *reimplement*
    it. If the fleet held any of the model/tool/retry/cost logic, "the M1
    suite still passes" would be a much weaker claim than it is.

    Checked over the AST's *names in use*, not over the source text. The
    module docstring necessarily names the very machinery it delegates to
    while explaining that it delegates -- a text grep would match the
    explanation and fail on correct code, which is the self-match trap this
    repository keeps rediscovering."""
    import inspect

    from app.workers import worker as worker_module

    tree = ast.parse(inspect.getsource(worker_module))
    used = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    used |= {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    for forbidden in ("ModelGatewayService", "ToolGatewayService", "ToolLoopOrchestrator",
                      "PricingService", "_fail_or_retry", "calculate_cost", "_execute"):
        assert forbidden not in used, f"worker.py implements {forbidden}"
    # The one execution entry point it is allowed to call.
    assert "run_once" in used


def test_ac04_the_lock_is_released_after_the_attempt(
    client: TestClient, admin: dict, db_session: Session,
) -> None:
    _quiesce(db_session)
    setup = _setup(client, admin)
    (execution_id,) = _enqueue(db_session, setup, admin)

    db = SessionLocal()
    try:
        ExecutionWorkerService(db).run_once("cleanup-worker")
    finally:
        db.rollback()
        db.close()

    db_session.rollback()
    assert db_session.execute(select(ExecutionLock).where(
        ExecutionLock.execution_id == execution_id)).scalars().first() is None


# --------------------------------------------------------------------------- #
# AC-05 -- THE §21 PROOF: two workers, real separate connections
# --------------------------------------------------------------------------- #
def test_ac05_the_section_21_proof_two_workers_contend(
    client: TestClient, admin: dict, db_session: Session,
) -> None:
    """All four parts of §21, on real separate connections.

    (a) one execution is claimed exactly once;
    (b) different executions progress concurrently across workers;
    (c) a crashed worker's expired lease is recovered;
    (d) recovery causes no duplicate successful execution."""
    _quiesce(db_session)
    setup = _setup(client, admin)
    execution_ids = _enqueue(db_session, setup, admin, count=4)

    # (a) + (b) -- two workers, four executions, own connections throughout.
    def _drain_queue(worker_id: str) -> list[str]:
        worker = ExecutionWorker(worker_id=worker_id, concurrency=1)
        worker.start()
        ran = []
        while True:
            got = worker.claim_and_run()
            if got is None:
                break
            ran.append(str(got))
        return ran

    with ThreadPoolExecutor(max_workers=2) as pool:
        runs = list(pool.map(_drain_queue, [f"w1-{uuid.uuid4().hex[:6]}",
                                            f"w2-{uuid.uuid4().hex[:6]}"]))

    all_run = runs[0] + runs[1]
    # (a) no execution ran on both workers, and none ran twice anywhere.
    assert len(all_run) == len(set(all_run)), f"an execution ran twice: {all_run}"
    assert set(all_run) == {str(i) for i in execution_ids}
    # (b) both workers actually did work -- otherwise this proves nothing
    # about concurrency, only about a queue draining.
    assert runs[0] and runs[1], f"one worker did everything: {runs}"

    db_session.rollback()
    for execution_id in execution_ids:
        assert db_session.get(AgentExecution, execution_id).status == "SUCCEEDED"


def test_ac05_a_crashed_workers_lease_is_recovered_without_duplicate_success(
    client: TestClient, admin: dict, db_session: Session,
) -> None:
    """(c) + (d). The crash is simulated the only honest way: claim on one
    connection, then abandon it without finishing, and expire the lease."""
    _quiesce(db_session)
    setup = _setup(client, admin)
    (execution_id,) = _enqueue(db_session, setup, admin)

    crashed = SessionLocal()
    try:
        claimed = ExecutionWorkerService(crashed).claim_next("doomed-worker")
        assert claimed is not None
    finally:
        # The process dies here: no _execute, no cleanup, no commit of a
        # terminal state. The claim is already committed, which is exactly
        # what makes the orphan visible instead of invisible.
        crashed.close()

    db_session.rollback()
    assert db_session.get(AgentExecution, execution_id).status == "RUNNING"

    # Expire the lease, as wall-clock time would.
    db_session.execute(update(ExecutionLock)
                       .where(ExecutionLock.execution_id == execution_id)
                       .values(expires_at=_now() - timedelta(minutes=10)))
    db_session.commit()

    survivor = SessionLocal()
    try:
        reaped = ExecutionWorkerService(survivor).reap_expired_locks()
        assert reaped == 1
    finally:
        survivor.rollback()
        survivor.close()

    db_session.rollback()
    execution = db_session.get(AgentExecution, execution_id)
    assert execution.status == "QUEUED", "a recovered execution must be re-claimable"
    assert db_session.execute(select(ExecutionLock).where(
        ExecutionLock.execution_id == execution_id)).scalars().first() is None

    # (d) it now runs exactly once, to exactly one success.
    worker = ExecutionWorker(worker_id=f"w-{uuid.uuid4().hex[:8]}", concurrency=1)
    worker.start()
    assert worker.claim_and_run() == execution_id
    assert worker.claim_and_run() is None

    db_session.rollback()
    execution = db_session.get(AgentExecution, execution_id)
    assert execution.status == "SUCCEEDED"
    succeeded = db_session.execute(select(AgentExecution).where(
        AgentExecution.id == execution_id,
        AgentExecution.status == "SUCCEEDED")).scalars().all()
    assert len(succeeded) == 1


# --------------------------------------------------------------------------- #
# AC-06 -- drain & graceful shutdown
# --------------------------------------------------------------------------- #
def test_ac06_graceful_shutdown_drains_then_stops(db_session: Session) -> None:
    _quiesce(db_session)
    worker = ExecutionWorker(worker_id=f"w-{uuid.uuid4().hex[:8]}", concurrency=2)
    worker.start()
    worker.shutdown()

    db_session.rollback()
    row = WorkerFleetService(db_session).get_or_404(worker.worker_id)
    assert row.status == "STOPPED"
    assert row.active_count == 0


def test_ac06_an_api_drain_reaches_the_running_process(
    client: TestClient, admin: dict, db_session: Session,
) -> None:
    """The drain endpoint writes a request; ``refresh`` is what turns it into
    behaviour. Without this reconciliation the endpoint would only decorate a
    database row while the process kept claiming."""
    _quiesce(db_session)
    worker = ExecutionWorker(worker_id=f"w-{uuid.uuid4().hex[:8]}", concurrency=2)
    worker.start()
    assert worker.status == "RUNNING"

    r = client.post(f"{RT}/fleet/workers/{worker.worker_id}/drain", headers=admin["headers"])
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "DRAINING"

    assert worker.refresh() == "DRAINING"
    assert worker.available_slots == 0


def test_ac06_refresh_never_promotes_a_drained_worker_back(db_session: Session) -> None:
    """Undoing an operator's drain from inside the process being drained is
    never the right resolution of that disagreement."""
    _quiesce(db_session)
    worker = ExecutionWorker(worker_id=f"w-{uuid.uuid4().hex[:8]}")
    worker.start()
    WorkerFleetService(db_session).drain(worker.worker_id)
    assert worker.refresh() == "DRAINING"

    # Someone re-registers the row as RUNNING; the process still refuses to
    # promote itself out of draining on a refresh.
    WorkerFleetService(db_session).register(worker.worker_id)
    assert worker.refresh() == "DRAINING"


def test_ac06_draining_a_stopped_worker_is_refused(db_session: Session) -> None:
    _quiesce(db_session)
    fleet = WorkerFleetService(db_session)
    worker_id = f"w-{uuid.uuid4().hex[:8]}"
    fleet.register(worker_id)
    fleet.stop(worker_id)
    with pytest.raises(IdentityError) as exc:
        fleet.drain(worker_id)
    assert exc.value.code == ErrorCode.WORKER_INVALID_STATE


def test_ac06_draining_twice_is_idempotent(db_session: Session) -> None:
    """An operator retrying a drain during an incident should not be punished
    for it."""
    _quiesce(db_session)
    fleet = WorkerFleetService(db_session)
    worker_id = f"w-{uuid.uuid4().hex[:8]}"
    fleet.register(worker_id)
    assert fleet.drain(worker_id).status == "DRAINING"
    assert fleet.drain(worker_id).status == "DRAINING"


# --------------------------------------------------------------------------- #
# AC-07 -- backpressure & queue depth
# --------------------------------------------------------------------------- #
def test_ac07_a_worker_at_capacity_does_not_over_claim(db_session: Session) -> None:
    _quiesce(db_session)
    worker = ExecutionWorker(worker_id=f"w-{uuid.uuid4().hex[:8]}", concurrency=2)
    worker.start()
    assert worker.available_slots == 2
    assert worker._acquire_slot() is True
    assert worker._acquire_slot() is True
    assert worker.available_slots == 0
    # The third request is refused by the worker itself, before any query.
    assert worker._acquire_slot() is False
    worker._release_slot()
    assert worker.available_slots == 1


def test_ac07_queue_depth_is_reportable(
    client: TestClient, admin: dict, db_session: Session,
) -> None:
    _quiesce(db_session)
    setup = _setup(client, admin)
    _enqueue(db_session, setup, admin, count=3)
    _register_workers(db_session, {"alpha": 2, "beta": 1})

    r = client.get(f"{RT}/fleet/queue-depth", headers=admin["headers"])
    assert r.status_code == 200, r.text
    depth = r.json()
    assert depth["queued"] == 3
    assert depth["capacity"] == 3
    assert depth["workers_accepting_work"] == 2
    assert depth["available_slots"] == 3


def test_ac07_queue_depth_counts_unclaimed_work_not_work_in_progress(
    client: TestClient, admin: dict, db_session: Session,
) -> None:
    _quiesce(db_session)
    setup = _setup(client, admin)
    _enqueue(db_session, setup, admin, count=2)

    db = SessionLocal()
    try:
        ExecutionWorkerService(db).claim_next("depth-worker")
    finally:
        db.rollback()
        db.close()

    db_session.rollback()
    depth = WorkerFleetService(db_session).queue_depth()
    assert depth["queued"] == 1
    assert depth["running"] == 1


# --------------------------------------------------------------------------- #
# AC-08 -- registrations and leases are ephemeral
# --------------------------------------------------------------------------- #
def test_ac08_a_stale_worker_is_not_treated_as_live(db_session: Session) -> None:
    _quiesce(db_session)
    fleet = WorkerFleetService(db_session)
    worker_id = f"w-{uuid.uuid4().hex[:8]}"
    fleet.register(worker_id, cohort="ghost", concurrency=4)

    # Its capacity counts while it is alive...
    assert fleet.capacity_by_cohort().get("ghost") == 4

    # ...and stops counting the moment it goes quiet, before anything has
    # even swept it. Staleness is a property of the data, not of the sweep.
    db_session.execute(update(WorkerRegistration)
                       .where(WorkerRegistration.worker_id == worker_id)
                       .values(heartbeat_at=_now() - timedelta(hours=1)))
    db_session.commit()
    assert "ghost" not in fleet.capacity_by_cohort()

    assert fleet.reap_stale_workers() >= 1
    db_session.rollback()
    assert fleet.get_or_404(worker_id).status == "STOPPED"


def test_ac08_stale_worker_recovery_is_audited_to_the_execution_tenant(
    client: TestClient, admin: dict, db_session: Session,
) -> None:
    """A worker belongs to no organization, but the executions it stranded
    belong to real ones -- which is the only honest attribution available."""
    _quiesce(db_session)
    setup = _setup(client, admin)
    (execution_id,) = _enqueue(db_session, setup, admin)

    worker_id = f"w-{uuid.uuid4().hex[:8]}"
    WorkerFleetService(db_session).register(worker_id)
    dying = SessionLocal()
    try:
        ExecutionWorkerService(dying).claim_next(worker_id)
    finally:
        dying.close()

    db_session.execute(update(WorkerRegistration)
                       .where(WorkerRegistration.worker_id == worker_id)
                       .values(heartbeat_at=_now() - timedelta(hours=1)))
    db_session.commit()
    assert WorkerFleetService(db_session).reap_stale_workers() >= 1

    db_session.rollback()
    events = db_session.execute(select(RuntimeEvent).where(
        RuntimeEvent.organization_id == uuid.UUID(admin["organization_id"]),
        RuntimeEvent.event_type == "WORKER_STALE_RECOVERED")).scalars().all()
    assert any(e.payload and e.payload.get("execution_id") == str(execution_id)
               for e in events), "the stranded execution's tenant was not told"


def test_ac08_reaping_a_worker_does_not_itself_release_the_execution() -> None:
    """Structural: worker recovery and execution recovery are deliberately
    separate, so two components can never disagree about whether an execution
    had attempts left. ``reap_stale_workers`` must not contain a second copy
    of the retry policy."""
    source = Path(fleet_module.__file__).read_text(encoding="utf-8")
    body = source.split('"""', 2)[-1]
    for forbidden in ("_fail_or_retry", "DEAD_LETTERED", "attempt_count"):
        assert forbidden not in body, f"fleet.py reimplements execution recovery ({forbidden})"


def test_ac08_the_api_can_force_a_sweep_when_the_fleet_is_down(
    client: TestClient, admin: dict, db_session: Session,
) -> None:
    _quiesce(db_session)
    r = client.post(f"{RT}/fleet/reap", headers=admin["headers"])
    assert r.status_code == 200, r.text
    assert "queued" in r.json()


# --------------------------------------------------------------------------- #
# AC-09 -- ROLLING over real worker cohorts
# --------------------------------------------------------------------------- #
def test_ac09_steps_are_derived_from_real_capacity_not_an_invented_ladder() -> None:
    """The arithmetic that decides how much production traffic moves, tested
    without a fleet because it is pure.

    A fleet of 8 and 2 slots gives 80/100 -- *not* 25/50/75/100. That is the
    whole difference between rolling and a canary, and the reason 3.6 could
    not write this."""
    steps = derive_cohort_steps({"big": 8, "small": 2})
    assert [s.target_weight for s in steps] == [80, 100]
    assert [s.cohort for s in steps] == ["big", "small"]

    even = derive_cohort_steps({"c1": 1, "c2": 1, "c3": 1, "c4": 1})
    assert [s.target_weight for s in even] == [25, 50, 75, 100]

    # An undivided fleet rolls in one step -- the honest description of
    # converting something with no partitions.
    assert [s.target_weight for s in derive_cohort_steps({"default": 3})] == [100]


def test_ac09_the_final_step_is_always_exactly_100() -> None:
    """Without the pin, a rollout could finish at 99% and leave the old
    version quietly serving one request in a hundred forever."""
    for capacities in ({"a": 1, "b": 1, "c": 1}, {"a": 7, "b": 3, "c": 3},
                       {"a": 1, "b": 1, "c": 1, "d": 1, "e": 1, "f": 1, "g": 1}):
        steps = derive_cohort_steps(capacities)
        assert steps[-1].target_weight == 100, capacities
        weights = [s.target_weight for s in steps]
        assert weights == sorted(weights), weights
        assert len(set(weights)) == len(weights), f"a step that moves nothing: {weights}"


def test_ac09_rolling_with_no_fleet_fails_closed(
    client: TestClient, admin: dict, db_session: Session,
) -> None:
    """The gate that makes the fleet load-bearing. With no workers, rolling
    refuses -- it does not roll over an imaginary fleet."""
    _quiesce(db_session)
    setup = _setup(client, admin)

    r = client.post(f"{RT}/deployments/{setup['candidate_deployment']['id']}/strategy/rolling",
                    headers=admin["headers"])
    assert r.status_code == 422, r.text
    assert r.json()["error"]["code"] == "ROLLING_COHORT_INVALID"
    # Nothing moved.
    assert _weights(db_session, setup, admin) == {}


def test_ac09_rolling_shifts_traffic_across_real_cohorts(
    client: TestClient, admin: dict, db_session: Session,
) -> None:
    """The positive path: a real fleet produces real, fleet-shaped steps and
    the first cohort's conversion moves real traffic through 3.4."""
    _quiesce(db_session)
    setup = _setup(client, admin)
    _register_workers(db_session, {"01-first": 8, "02-second": 2})

    r = client.post(f"{RT}/deployments/{setup['candidate_deployment']['id']}/strategy/rolling",
                    headers=admin["headers"], json={"health_requirement": "NONE"})
    assert r.status_code == 200, r.text
    plan = r.json()
    assert plan["kind"] == "ROLLING"
    assert plan["state"] == "IN_PROGRESS"
    assert [s["target_weight"] for s in plan["stages"]] == [80, 100]
    assert [s["cohort"] for s in plan["cohort_plan"]["steps"]] == ["01-first", "02-second"]
    assert plan["cohort_plan"]["total_capacity"] == 10

    weights = _weights(db_session, setup, admin)
    assert weights[setup["candidate"]["id"]] == 80
    assert weights[setup["stable"]["id"]] == 20


def test_ac09_rolling_drives_34_and_writes_no_weights_of_its_own() -> None:
    """Structural, matching 3.5's and 3.6's own guard: there is no
    ``DeploymentTrafficWeight`` import in the rolling module, so bypassing
    3.4 is impossible rather than merely discouraged."""
    source = Path(rolling_module.__file__).read_text(encoding="utf-8")
    assert "DeploymentTrafficWeight" not in source


def test_ac09_phase_39_changed_only_the_rolling_seam() -> None:
    """The replacement for the two files Phase 3.7's AC-16 guard released.

    3.9 is mandated to edit ``strategies.py`` (AC-11) and ``canary.py`` (the
    cohort gate must sit in the one advance choke point, or the generic
    rollout route bypasses it). This asserts those edits are *confined to
    rolling*.

    Compared as the modules' declared surface rather than as a text diff:
    every class and function that existed on ``main`` must still exist, and
    any addition must be one of the two named rolling helpers. A text diff
    would flag comment and docstring edits, which prove nothing; this catches
    what would actually matter -- 3.9 quietly removing or renaming a piece of
    the canary engine or one of the other strategy handlers.

    **Additions are asserted as a subset, not an equality, and that is not a
    hedge.** ``main`` moves: once this branch merges, ``git show main:...``
    returns the 3.9 files themselves and the addition set becomes empty.
    Equality would make this test pass on the branch and fail forever after --
    exactly the trap Phase 3.7's own byte-identity guard fell into by
    comparing against a moving baseline, which is why this test exists at all.
    The durable half of the assertion is the one above it: nothing may ever
    disappear from either module's surface."""
    import subprocess

    repo = Path(__file__).resolve().parents[3]

    def _surface(blob: str) -> set[str]:
        tree = ast.parse(blob)
        return {f"{node.__class__.__name__}:{node.name}" for node in ast.walk(tree)
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))}

    expected_additions = {
        "backend/app/runtime/deployment/canary.py": {
            "FunctionDef:_assert_kind_preconditions", "FunctionDef:_label"},
        "backend/app/runtime/deployment/strategies.py": set(),
    }
    for path, allowed in expected_additions.items():
        before = subprocess.run(["git", "show", "main:" + path], cwd=repo,
                                capture_output=True, text=True, check=True).stdout
        now = (repo / path).read_text(encoding="utf-8")
        old_surface, new_surface = _surface(before), _surface(now)
        assert not (old_surface - new_surface), path + " lost " + str(old_surface - new_surface)
        unexpected = (new_surface - old_surface) - allowed
        assert not unexpected, path + " added unexpected surface " + str(unexpected)


# --------------------------------------------------------------------------- #
# AC-10 -- progressive, pausable, abortable, rollback-integrated
# --------------------------------------------------------------------------- #
def _start_rolling(client: TestClient, admin: dict, setup: dict, **options) -> dict:
    body = {"health_requirement": "NONE"}
    body.update(options)
    r = client.post(f"{RT}/deployments/{setup['candidate_deployment']['id']}/strategy/rolling",
                    headers=admin["headers"], json=body)
    assert r.status_code == 200, r.text
    return r.json()


def test_ac10_rolling_advances_cohort_by_cohort_to_completion(
    client: TestClient, admin: dict, db_session: Session,
) -> None:
    _quiesce(db_session)
    setup = _setup(client, admin)
    _register_workers(db_session, {"01-a": 1, "02-b": 1, "03-c": 1, "04-d": 1})
    plan = _start_rolling(client, admin, setup)
    assert [s["target_weight"] for s in plan["stages"]] == [25, 50, 75, 100]
    assert _weights(db_session, setup, admin)[setup["candidate"]["id"]] == 25

    for expected in (50, 75, 100):
        r = client.post(f"{RT}/rollouts/{plan['id']}/advance", headers=admin["headers"])
        assert r.status_code == 200, r.text
        assert _weights(db_session, setup, admin)[setup["candidate"]["id"]] == expected

    # The final cohort is converted at 100%, but the plan is not finished
    # until one more advance clears it -- 3.5's engine completes on the
    # advance *past* the last stage, not on entering it. Rolling inherits
    # that deliberately: reaching full traffic and declaring the rollout over
    # are two decisions, and an operator may want to sit at 100% first.
    db_session.rollback()
    assert db_session.get(RolloutPlan, uuid.UUID(plan["id"])).state == "IN_PROGRESS"

    r = client.post(f"{RT}/rollouts/{plan['id']}/advance", headers=admin["headers"])
    assert r.status_code == 200, r.text
    db_session.rollback()
    assert db_session.get(RolloutPlan, uuid.UUID(plan["id"])).state == "SUCCEEDED"
    assert _weights(db_session, setup, admin)[setup["candidate"]["id"]] == 100


def test_ac10_rolling_is_pausable_and_abortable(
    client: TestClient, admin: dict, db_session: Session,
) -> None:
    """Inherited wholesale from Phase 3.5's engine -- which is the point of
    reusing it rather than writing a second state machine."""
    _quiesce(db_session)
    setup = _setup(client, admin)
    _register_workers(db_session, {"01-a": 1, "02-b": 1})
    plan = _start_rolling(client, admin, setup)

    r = client.post(f"{RT}/rollouts/{plan['id']}/pause", headers=admin["headers"],
                    json={"reason": "Investigating latency."})
    assert r.status_code == 200, r.text
    assert r.json()["state"] == "PAUSED"

    r = client.post(f"{RT}/rollouts/{plan['id']}/resume", headers=admin["headers"], json={})
    assert r.status_code == 200, r.text
    assert r.json()["state"] == "IN_PROGRESS"

    r = client.post(f"{RT}/rollouts/{plan['id']}/abort", headers=admin["headers"],
                    json={"reason": "Called off."})
    assert r.status_code == 200, r.text
    assert r.json()["state"] == "ABORTED"


def test_ac10_a_failing_rolling_deployment_can_request_rollback(
    client: TestClient, admin: dict, db_session: Session,
) -> None:
    """M3-3.9-FR-033 -- rollback integration is inherited, not rebuilt: a
    rolling plan reaches the same ROLLBACK_REQUESTED state 3.7 understands."""
    _quiesce(db_session)
    setup = _setup(client, admin)
    _register_workers(db_session, {"01-a": 1, "02-b": 1})
    plan = _start_rolling(client, admin, setup)

    r = client.post(f"{RT}/rollouts/{plan['id']}/request-rollback", headers=admin["headers"],
                    json={"reason": "Error rate spiked."})
    assert r.status_code == 200, r.text
    assert r.json()["state"] == "ROLLBACK_REQUESTED"
    # Traffic returned to the stable version.
    assert _weights(db_session, setup, admin)[setup["stable"]["id"]] == 100


def test_ac10_a_dead_cohort_stops_the_next_step(
    client: TestClient, admin: dict, db_session: Session,
) -> None:
    """The gate that cannot be bypassed: it lives inside the advance itself,
    so the generic rollout route hits it too."""
    _quiesce(db_session)
    setup = _setup(client, admin)
    workers = _register_workers(db_session, {"01-a": 1, "02-b": 1})
    plan = _start_rolling(client, admin, setup)

    # The second cohort's machine dies.
    second = [w for w in workers if w.cohort == "02-b"][0]
    db_session.execute(update(WorkerRegistration)
                       .where(WorkerRegistration.worker_id == second.worker_id)
                       .values(heartbeat_at=_now() - timedelta(hours=1)))
    db_session.commit()

    r = client.post(f"{RT}/rollouts/{plan['id']}/advance", headers=admin["headers"])
    assert r.status_code == 422, r.text
    assert r.json()["error"]["code"] == "ROLLING_COHORT_INVALID"
    # Fails closed: traffic stayed where it was.
    assert _weights(db_session, setup, admin)[setup["candidate"]["id"]] == 50


def test_ac10_rolling_refuses_to_run_beside_another_plan(
    client: TestClient, admin: dict, db_session: Session,
) -> None:
    """Two plans moving one allocation would each keep setting weights the
    other did not expect."""
    _quiesce(db_session)
    setup = _setup(client, admin)
    _register_workers(db_session, {"01-a": 1, "02-b": 1})
    _start_rolling(client, admin, setup)

    r = client.post(f"{RT}/deployments/{setup['candidate_deployment']['id']}/strategy/rolling",
                    headers=admin["headers"], json={"health_requirement": "NONE"})
    assert r.status_code == 409, r.text
    assert r.json()["error"]["code"] == "ROLLOUT_CONFLICT"


# --------------------------------------------------------------------------- #
# AC-11 -- the 3.6 deferred seam is gone
# --------------------------------------------------------------------------- #
def test_ac11_invoking_rolling_executes_rather_than_defers(
    client: TestClient, admin: dict, db_session: Session,
) -> None:
    _quiesce(db_session)
    setup = _setup(client, admin, candidate_strategy="ROLLING")
    _register_workers(db_session, {"default": 4})

    r = client.post(f"{RT}/deployments/{setup['candidate_deployment']['id']}/strategy/execute",
                    headers=admin["headers"])
    assert r.status_code == 200, r.text
    outcome = r.json()
    assert outcome["strategy"] == "ROLLING"
    assert outcome["operation"] == "start"
    assert outcome["candidate_weight"] == 100  # one cohort = one step
    assert "worker cohort" in outcome["detail"]


def test_ac11_nothing_raises_the_deferred_error_any_more() -> None:
    """The transition, asserted mechanically. The ``ErrorCode`` member is
    deliberately *kept* -- it was returned to real API consumers with a
    documented meaning -- but nothing constructs it."""
    app_dir = Path(__file__).resolve().parents[2] / "app"
    raisers = []
    for path in app_dir.rglob("*.py"):
        if path.name == "errors.py":
            continue  # the member's own definition and its status mapping
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr == "STRATEGY_ROLLING_DEFERRED":
                raisers.append(str(path))
    assert raisers == [], raisers


def test_ac11_the_rolling_handler_is_real_not_a_stub() -> None:
    source = Path(strategies_module.__file__).read_text(encoding="utf-8")
    assert "NotImplementedError" not in source
    handler = strategies_module.RollingStrategy()
    assert handler.name == "ROLLING"
    # It dispatches into the real service rather than raising.
    import inspect
    body = inspect.getsource(handler.execute)
    assert "RollingDeploymentService" in body


# --------------------------------------------------------------------------- #
# AC-12 -- the PG16/17 recovery mismatch is resolved
# --------------------------------------------------------------------------- #
def test_ac12_compose_declares_the_postgres_version_the_project_runs() -> None:
    """A §26 production-readiness gate, carried here from Phase 3.8.

    Compose previously declared PostgreSQL 16 with a different database name
    than the one this project is developed, backed up and restored against.
    That is not cosmetic: a logical dump from 17 will not restore into 16, and
    a 16 data directory cannot be read by 17 -- so the documented recovery
    drill had no correct target to run against."""
    compose = (Path(__file__).resolve().parents[3] / "docker-compose.yml").read_text(
        encoding="utf-8")
    assert "postgres:17-alpine" in compose
    assert "postgres:16-alpine" not in compose
    assert "POSTGRES_DB: ai_agent_control_tower" in compose
    # The connection string the api service uses must name the same database.
    assert "@db:5432/ai_agent_control_tower" in compose


def test_ac12_the_live_database_is_postgresql_17(db_session: Session) -> None:
    """The recovery proof runs against a real, correct target -- asserted
    against the server, not against a document describing it."""
    version = db_session.execute(text("SHOW server_version")).scalar()
    assert str(version).split(".")[0] == "17", version


def test_ac12_recovery_documents_the_major_version_upgrade_hazard() -> None:
    """Aligning the image is only half the fix. An existing checkout has a
    PostgreSQL 16 data directory in its named volume, and 17 refuses to start
    against it -- a first-run failure that looks like a broken repository
    unless it is written down."""
    recovery = (Path(__file__).resolve().parents[3] / "RECOVERY.md").read_text(encoding="utf-8")
    assert "act_pgdata" in recovery
    assert "17" in recovery


# --------------------------------------------------------------------------- #
# AC-13 -- execution authorization is unchanged
# --------------------------------------------------------------------------- #
def test_ac13_the_worker_changes_nothing_about_who_may_execute() -> None:
    """Structural: distributing execution must not touch authorization. If
    the fleet could widen or narrow who may execute, "the same authorized
    execution" would be an assertion rather than a fact."""
    source = Path(ExecutionWorker.__module__.replace(".", "/") + ".py")
    body = (Path(__file__).resolve().parents[2] / source).read_text(encoding="utf-8")
    for forbidden in ("AuthorizationGateway", "require_permission", "has_permission",
                      "UserRole", "rbac"):
        assert forbidden not in body, f"worker.py touches authorization ({forbidden})"


def test_ac13_a_worker_runs_each_tenants_execution_under_its_own_tenant(
    client: TestClient, admin: dict, db_session: Session,
) -> None:
    """The claim is deliberately global -- one pool serves every tenant by
    queue position -- and the execution stays scoped to its own organization
    regardless of which worker ran it."""
    _quiesce(db_session)
    setup = _setup(client, admin)
    (execution_id,) = _enqueue(db_session, setup, admin)

    worker = ExecutionWorker(worker_id=f"w-{uuid.uuid4().hex[:8]}")
    worker.start()
    assert worker.claim_and_run() == execution_id

    db_session.rollback()
    execution = db_session.get(AgentExecution, execution_id)
    assert execution.organization_id == uuid.UUID(admin["organization_id"])
    events = db_session.execute(select(RuntimeEvent).where(
        RuntimeEvent.execution_id == execution_id)).scalars().all()
    assert events and all(e.organization_id == execution.organization_id for e in events)


# --------------------------------------------------------------------------- #
# AC-14 -- permissions
# --------------------------------------------------------------------------- #
def _reviewer(client: TestClient, admin: dict) -> dict:
    """A user in the same organization without worker-management authority.

    Needed because SYSTEM_ROLE_PERMISSIONS grants ADMIN/SUPER_ADMIN the whole
    catalog, so the admin fixture can never demonstrate a permission denial --
    the same limitation Phase 3.7 documented for its force-rollback grant."""
    from tests.runtime.conftest import PASSWORD

    email = f"fleet_reviewer_{uuid.uuid4().hex[:10]}@example.com"
    r = client.post("/api/v1/identity/users", headers=admin["headers"], json={
        "email": email, "display_name": "Reviewer", "password": PASSWORD, "role": "REVIEWER",
        "organization_id": admin["organization_id"],
    })
    assert r.status_code in (200, 201), r.text
    tokens = client.post("/api/v1/auth/login",
                         json={"email": email, "password": PASSWORD}).json()
    return {"headers": {"Authorization": f"Bearer {tokens['access_token']}"}}


def _second_org(client: TestClient) -> dict:
    """A genuinely different tenant -- not another user in the same one."""
    from tests.runtime.conftest import PASSWORD

    email = f"fleet_other_{uuid.uuid4().hex[:10]}@example.com"
    assert client.post("/auth/register", json={
        "organization_name": "Other Fleet Org", "name": "Owner",
        "email": email, "password": PASSWORD,
    }).status_code == 201
    tokens = client.post("/api/v1/auth/login",
                         json={"email": email, "password": PASSWORD}).json()
    return {"headers": {"Authorization": f"Bearer {tokens['access_token']}"}}


def test_ac14_worker_management_requires_permission(
    client: TestClient, admin: dict, db_session: Session,
) -> None:
    _quiesce(db_session)
    fleet = WorkerFleetService(db_session)
    worker_id = f"w-{uuid.uuid4().hex[:8]}"
    fleet.register(worker_id)

    reviewer = _reviewer(client, admin)
    r = client.post(f"{RT}/fleet/workers/{worker_id}/drain", headers=reviewer["headers"])
    assert r.status_code == 403, r.text

    db_session.rollback()
    assert fleet.get_or_404(worker_id).status == "RUNNING", "the drain must not have happened"


def test_ac14_the_fleet_api_requires_authentication(client: TestClient) -> None:
    for path in (f"{RT}/fleet", f"{RT}/fleet/queue-depth"):
        assert client.get(path).status_code in (401, 403), path


def test_ac14_rolling_is_tenant_scoped(
    client: TestClient, admin: dict, db_session: Session,
) -> None:
    """A deployment in another organization is not found, not merely
    forbidden -- the same shape 3.6 and 3.7 use."""
    _quiesce(db_session)
    setup = _setup(client, admin)
    other = _second_org(client)
    r = client.post(f"{RT}/deployments/{setup['candidate_deployment']['id']}/strategy/rolling",
                    headers=other["headers"], json={})
    assert r.status_code == 404, r.text
    assert r.json()["error"]["code"] == "DEPLOYMENT_NOT_FOUND"


def test_ac14_no_route_can_dispatch_an_execution() -> None:
    """The safety property behind the fleet API's shape: if HTTP could run an
    execution, a caller could run agent work with no lease and no worker
    identity, defeating ``execution_locks``' unique constraint by never
    taking one."""
    from app.workers import routes as worker_routes

    source = Path(worker_routes.__file__).read_text(encoding="utf-8")
    body = source.split('"""', 2)[-1]
    for forbidden in ("claim_next", "run_once", "ExecutionWorkerService", "claim_and_run"):
        assert forbidden not in body, f"the fleet API can dispatch work ({forbidden})"


def test_ac14_registration_is_not_exposed_over_http() -> None:
    """Phantom capacity would make rolling derive real step weights from
    machines that do not exist."""
    from fastapi.routing import APIRoute

    from app.main import app

    worker_routes = [r for r in app.routes
                     if isinstance(r, APIRoute) and r.path.startswith(f"{RT}/fleet")]
    assert worker_routes, "the fleet API is not mounted"
    for route in worker_routes:
        assert "register" not in route.path, route.path


# --------------------------------------------------------------------------- #
# AC-15 -- rolling vs the kill switch and rollback
# --------------------------------------------------------------------------- #
def test_ac15_rolling_cannot_start_on_a_killed_agent(
    client: TestClient, admin: dict, db_session: Session,
) -> None:
    _quiesce(db_session)
    setup = _setup(client, admin)
    _register_workers(db_session, {"01-a": 1, "02-b": 1})
    assert client.post(f"{RT}/kill-switch/agents/{setup['agent']['id']}",
                       headers=admin["headers"],
                       json={"reason": "Incident."}).status_code == 200

    r = client.post(f"{RT}/deployments/{setup['candidate_deployment']['id']}/strategy/rolling",
                    headers=admin["headers"], json={"health_requirement": "NONE"})
    assert r.status_code == 423, r.text
    assert r.json()["error"]["code"] == "KILL_SWITCH_ACTIVE"
    assert _weights(db_session, setup, admin) == {}


def test_ac15_a_kill_switch_mid_rollout_stops_the_next_step(
    client: TestClient, admin: dict, db_session: Session,
) -> None:
    _quiesce(db_session)
    setup = _setup(client, admin)
    _register_workers(db_session, {"01-a": 1, "02-b": 1})
    plan = _start_rolling(client, admin, setup)
    assert _weights(db_session, setup, admin)[setup["candidate"]["id"]] == 50

    assert client.post(f"{RT}/kill-switch/agents/{setup['agent']['id']}",
                       headers=admin["headers"],
                       json={"reason": "Incident."}).status_code == 200

    r = client.post(f"{RT}/rollouts/{plan['id']}/advance", headers=admin["headers"])
    assert r.status_code in (423, 409), r.text
    # The vetoed version was not promoted.
    assert _weights(db_session, setup, admin)[setup["candidate"]["id"]] == 50

    db_session.rollback()
    agent = db_session.get(Agent, uuid.UUID(setup["agent"]["id"]))
    assert agent.lifecycle_status == "SUSPENDED", "automation must never lift a human's kill"


def test_ac15_rolling_honors_the_release_gate() -> None:
    """Structural: the gate check is the same 3.3 evaluation every other
    strategy runs, called from the one place rolling starts."""
    import inspect

    body = inspect.getsource(RollingDeploymentService.start)
    assert "assert_gate_passes" in body
    assert "assert_not_vetoed" in body
    # Veto before gate: a suspended agent must be refused for the reason it
    # was suspended, not for whatever the gate happens to say.
    assert body.index("assert_not_vetoed") < body.index("assert_gate_passes")


# --------------------------------------------------------------------------- #
# AC-16 -- no secrets in worker or rolling state
# --------------------------------------------------------------------------- #
def test_ac16_no_secret_material_in_worker_or_rolling_state(
    client: TestClient, admin: dict, db_session: Session,
) -> None:
    _quiesce(db_session)
    setup = _setup(client, admin)
    _register_workers(db_session, {"01-a": 1, "02-b": 1})
    plan = _start_rolling(client, admin, setup)

    db_session.rollback()
    blob = repr(db_session.get(RolloutPlan, uuid.UUID(plan["id"])).cohort_plan)
    blob += repr([(w.worker_id, w.hostname, w.cohort)
                  for w in WorkerFleetService(db_session).list_workers()])
    # Scoped to the events this phase emits. The organization's whole event
    # stream includes release-gate findings whose *codes* legitimately contain
    # the word "credential" (a preflight finding name, not a secret), so
    # asserting over everything would flag Phase 3.3's vocabulary rather than
    # this phase's data.
    events = db_session.execute(select(RuntimeEvent).where(
        RuntimeEvent.organization_id == uuid.UUID(admin["organization_id"]),
        RuntimeEvent.event_type.in_(
            ("WORKER_REGISTERED", "WORKER_DRAINING", "WORKER_STALE_RECOVERED",
             "DEPLOYMENT_STAGE_ADVANCED", "DEPLOYMENT_ROLLOUT_STARTED")))).scalars().all()
    blob += repr([e.payload for e in events])

    lowered = blob.lower()
    for marker in ("password", "secret", "api_key", "token", "credential", "private_key"):
        assert marker not in lowered, f"{marker} appears in worker/rolling state"


def test_ac16_the_worker_and_fleet_modules_never_read_credentials() -> None:
    root = Path(__file__).resolve().parents[2] / "app" / "workers"
    for path in root.rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        for forbidden in ("decrypt", "Fernet", "ProviderCredentialService", "SECRET_KEY"):
            assert forbidden not in source, f"{path.name} touches secret material ({forbidden})"


# --------------------------------------------------------------------------- #
# AC-19 -- no placeholders
# --------------------------------------------------------------------------- #
def test_ac19_no_placeholder_markers_in_the_new_code() -> None:
    """Built by concatenation so this test's own forbidden list does not match
    itself -- the trap this repository has now walked into seven times."""
    markers = ("TO" + "DO", "FIX" + "ME", "NotImplemented" + "Error",
               "@pytest.mark." + "skip", "@pytest.mark." + "xfail")
    root = Path(__file__).resolve().parents[2] / "app"
    targets = [root / "workers" / "fleet.py", root / "workers" / "worker.py",
               root / "workers" / "runner.py", root / "workers" / "routes.py",
               root / "runtime" / "deployment" / "rolling.py",
               root / "models" / "worker.py"]
    for path in targets:
        source = path.read_text(encoding="utf-8")
        for marker in markers:
            assert marker not in source, f"{path.name} contains {marker}"


# --------------------------------------------------------------------------- #
# The runner entrypoint
# --------------------------------------------------------------------------- #
def test_the_runner_runs_a_bounded_loop_and_leaves_the_fleet_cleanly(
    client: TestClient, admin: dict, db_session: Session,
) -> None:
    _quiesce(db_session)
    setup = _setup(client, admin)
    (execution_id,) = _enqueue(db_session, setup, admin)
    worker_id = f"runner-{uuid.uuid4().hex[:8]}"

    assert runner_module.main([
        "--worker-id", worker_id, "--max-ticks", "1", "--poll-interval", "0",
    ]) == 0

    db_session.rollback()
    row = WorkerFleetService(db_session).get_or_404(worker_id)
    assert row.status == "STOPPED", "the runner must always shut down gracefully"
    assert db_session.get(AgentExecution, execution_id).status == "SUCCEEDED"


def test_the_api_process_starts_no_worker() -> None:
    """An execution worker spends real money on model calls. That must be an
    explicit act of deployment, not a side effect of serving HTTP -- the same
    decision Phase 3.8 made for the scheduler."""
    source = (Path(__file__).resolve().parents[2] / "app" / "main.py").read_text(encoding="utf-8")
    assert "ExecutionWorker(" not in source
    assert "app.workers.worker" not in source
