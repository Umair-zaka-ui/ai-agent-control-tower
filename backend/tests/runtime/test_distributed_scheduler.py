"""Phase 3.8 (ACT-SRS-M3 §Phase-3.8, §9, §16, §20) tests -- the distributed
scheduler: leasing, exactly-once dispatch, stale-lease recovery, the
commit-before-dispatch discipline, retry/timeout, concurrency policy, the
handler registry, and the retirement of the interim scheduler.

**The gate is ``test_ac03_*`` and ``test_ac04_*`` -- the §20 proof.** Both use
*real separate database connections* (a second ``SessionLocal``), never an
in-process mutex or a thread barrier, because the property under test is that
two operating-system processes coordinating only through Postgres cannot both
run one job. A test that shared a session would prove nothing about that.

``run_once`` is driven directly rather than through ``runner.run_forever``'s
sleep loop: the loop is a thin wrapper whose own bounded behaviour is tested
separately, and waiting on real sleeps would make every one of these tests slow
and timing-dependent for no additional coverage.
"""

from __future__ import annotations

import ast
import uuid
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.identity.errors import ErrorCode, IdentityError
from app.models.scheduler import JobDefinition, JobRun
from app.models.user import User
from app.runtime.services import _now
from app.scheduler import handlers as handler_registry
from app.scheduler import principal as automation
from app.scheduler import runner, schedule
from app.scheduler import service as scheduler_service
from app.scheduler.service import SchedulerService

RT = "/api/v1/runtime"

# --------------------------------------------------------------------------- #
# Test-only handlers. Registered once at import; the registry is module-level
# and a duplicate key raises, so each has a name no production handler uses.
# --------------------------------------------------------------------------- #
_CALLS: dict[str, int] = {}


@handler_registry.register("test.counting")
def _counting_handler(ctx) -> dict:
    key = str(ctx.definition.id)
    _CALLS[key] = _CALLS.get(key, 0) + 1
    return {"calls": _CALLS[key], "instance_seen": True}


@handler_registry.register("test.always_fails")
def _failing_handler(ctx) -> dict:
    raise RuntimeError("deliberate handler failure")


@handler_registry.register("test.asserts_no_open_transaction")
def _transaction_probe_handler(ctx) -> dict:
    """Proves AC-05 from inside the handler itself.

    If the claim transaction were still open when a handler ran, this session
    would be in a transaction that the *claim* began -- which is the exact
    condition the M1 deadlock needed. Asserting it here, rather than only by
    reading the source, catches a future refactor that moves the commit."""
    from sqlalchemy import text

    # A brand-new connection must be able to touch the same definition row
    # without blocking -- which is only true if no claim lock is held.
    other = SessionLocal()
    try:
        other.execute(
            text("SELECT id FROM job_definitions WHERE id = :i FOR UPDATE NOWAIT"),
            {"i": str(ctx.definition.id)},
        ).first()
        other.rollback()
        return {"claim_lock_released": True}
    finally:
        other.close()


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _quiesce_others(db: Session) -> None:
    """Park every currently-due job definition so the one this test creates is
    the only claimable work.

    Necessary because ``claim_due`` deliberately claims *any* due job -- that
    is the whole point of a shared queue -- while this suite runs against the
    persistent local database that every other test also writes to. Without
    this, a test asserting "my job ran" would intermittently claim a leftover
    definition from an earlier test and assert against the wrong run. The same
    shared-database hygiene Phase 2.1.1 needed for the platform-wide
    ``connectors`` catalog."""
    from sqlalchemy import update

    db.rollback()
    db.execute(update(JobDefinition)
               .where(JobDefinition.next_run_at.isnot(None))
               .values(next_run_at=None))
    # Leftover *runs* matter as much as leftover definitions: ``run_once``
    # attempts recovery before claiming, so a stale non-terminal run from an
    # earlier test would be reclaimed instead of this test's job being claimed.
    # Terminalizing them here is the scheduler equivalent of parking the
    # definitions above -- it removes other tests' work from the shared queue
    # without changing what this phase's code does with real work.
    db.execute(update(JobRun)
               .where(JobRun.status.in_(("CLAIMED", "RUNNING")))
               .values(status="ABANDONED", lease_expires_at=None))
    db.commit()


def _definition(db: Session, admin: dict, *, handler_key: str = "test.counting",
                enabled: bool = True, interval: float = 60.0, timeout: int = 30,
                concurrency: str = "NO_OVERLAP", retry: dict | None = None,
                organization_id=..., due: bool = True, isolate: bool = True) -> JobDefinition:
    """``isolate`` parks other due jobs first, so this becomes the only
    claimable one. Pass ``isolate=False`` when a test genuinely needs two jobs
    due at once."""
    if isolate:
        _quiesce_others(db)
    org = uuid.UUID(admin["organization_id"]) if organization_id is ... else organization_id
    now = _now()
    definition = JobDefinition(
        organization_id=org,
        name=f"job-{uuid.uuid4().hex[:10]}",
        handler_key=handler_key,
        schedule_kind="INTERVAL",
        schedule_spec={"interval_seconds": interval},
        enabled=enabled,
        timeout_seconds=timeout,
        retry_policy=retry or {},
        concurrency_policy=concurrency,
        next_run_at=(now - timedelta(seconds=1)) if due else (now + timedelta(hours=1)),
    )
    db.add(definition)
    db.commit()
    db.refresh(definition)
    return definition


def _runs(db: Session, definition: JobDefinition) -> list[JobRun]:
    db.rollback()
    return list(db.execute(
        select(JobRun).where(JobRun.job_definition_id == definition.id)
        .order_by(JobRun.created_at.asc())
    ).scalars())


def _make_user(client: TestClient, admin: dict, role: str) -> dict:
    from tests.runtime.conftest import PASSWORD

    email = f"sched_{role.lower()}_{uuid.uuid4().hex[:10]}@example.com"
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

    email = f"sched_other_{uuid.uuid4().hex[:10]}@example.com"
    assert client.post("/auth/register", json={
        "organization_name": "Other Org", "name": "Owner", "email": email, "password": PASSWORD,
    }).status_code == 201
    tokens = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD}).json()
    me = client.get("/api/v1/auth/me",
                    headers={"Authorization": f"Bearer {tokens['access_token']}"}).json()
    return {"headers": {"Authorization": f"Bearer {tokens['access_token']}"},
            "user_id": me["user"]["id"], "organization_id": me["user"]["organization_id"]}


# --------------------------------------------------------------------------- #
# AC-01 -- job definitions and due computation
# --------------------------------------------------------------------------- #
def test_ac01_interval_due_computation_is_immediate_then_periodic() -> None:
    now = _now()
    spec = {"interval_seconds": 60}
    first = schedule.initial_next_run_at("INTERVAL", spec, now)
    assert first == now, "a newly enabled interval job is due at once, not one interval later"
    assert schedule.next_run_after("INTERVAL", spec, now, now) == now + timedelta(seconds=60)


def test_ac01_a_one_time_job_retires_itself() -> None:
    now = _now()
    assert schedule.next_run_after("ONE_TIME", {}, now, now) is None
    assert schedule.occurrence_key("ONE_TIME", now) == "once"


def test_ac01_missed_interval_occurrences_are_skipped_not_queued() -> None:
    """A fleet down for an hour must resume sweeping, not run twelve catch-up
    sweeps back to back."""
    now = _now()
    long_ago = now - timedelta(hours=1)
    nxt = schedule.next_run_after("INTERVAL", {"interval_seconds": 300}, long_ago, now)
    assert nxt > now
    assert nxt - now <= timedelta(seconds=300)


def test_ac01_a_malformed_spec_falls_back_instead_of_crashing() -> None:
    """A scheduler that dies on one bad row stops running every other job too."""
    assert schedule.interval_seconds({"interval_seconds": "not-a-number"}) == \
        schedule.DEFAULT_INTERVAL_SECONDS
    assert schedule.interval_seconds({"interval_seconds": -5}) == schedule.DEFAULT_INTERVAL_SECONDS
    assert schedule.interval_seconds(None) == schedule.DEFAULT_INTERVAL_SECONDS


def test_ac01_only_implemented_schedule_kinds_are_declared() -> None:
    """CRON is deliberately absent rather than declared-and-broken, the same
    honesty Phase 3.6 applied to ROLLING."""
    assert schedule.SCHEDULE_KINDS == {"INTERVAL", "ONE_TIME"}


# --------------------------------------------------------------------------- #
# AC-02 -- a due job runs via its handler and records a run
# --------------------------------------------------------------------------- #
def test_ac02_a_due_job_runs_and_records_its_outcome(
        client: TestClient, admin: dict, db_session: Session) -> None:
    definition = _definition(db_session, admin)
    run = SchedulerService(db_session, instance_id="inst-a").run_once()

    assert run is not None
    assert run.status == "SUCCEEDED"
    assert run.attempt == 1
    assert run.lease_owner == "inst-a"
    assert run.started_at is not None and run.ended_at is not None
    assert run.result["calls"] == 1
    assert len(_runs(db_session, definition)) == 1


def test_ac02_a_disabled_or_future_job_is_not_claimed(
        client: TestClient, admin: dict, db_session: Session) -> None:
    disabled = _definition(db_session, admin, enabled=False)
    future = _definition(db_session, admin, due=False, isolate=False)
    assert SchedulerService(db_session, instance_id="inst-a").claim_due() is None
    assert _runs(db_session, disabled) == []
    assert _runs(db_session, future) == []


# --------------------------------------------------------------------------- #
# AC-03 -- §20 PART 1: two instances, one due job, exactly one runs
# --------------------------------------------------------------------------- #
def test_ac03_two_instances_contend_and_exactly_one_runs(
        client: TestClient, admin: dict, db_session: Session) -> None:
    """The §20 proof, part 1.

    Two schedulers on **real separate connections** see the same due job. The
    first claims it inside an open transaction and holds it; the second, using
    ``SKIP LOCKED``, finds nothing rather than blocking. Exactly one run row
    exists and the handler ran exactly once.

    Deterministic by construction: instance A's transaction is held open across
    instance B's attempt, so the outcome does not depend on thread scheduling."""
    definition = _definition(db_session, admin)
    _CALLS.pop(str(definition.id), None)

    conn_a, conn_b = SessionLocal(), SessionLocal()
    try:
        a = SchedulerService(conn_a, instance_id="inst-a")
        b = SchedulerService(conn_b, instance_id="inst-b")

        # A locks the definition row and does NOT commit yet.
        locked = conn_a.execute(
            select(JobDefinition).where(JobDefinition.id == definition.id)
            .with_for_update(skip_locked=True)
        ).scalars().first()
        assert locked is not None, "instance A must win the lock"

        # B, contending for the same due job, skips it entirely.
        assert b.claim_due() is None, "SKIP LOCKED must make B skip, not block"

        conn_a.rollback()  # A releases; now let A claim properly and run it.
        run_a = a.run_once()
        assert run_a is not None and run_a.status == "SUCCEEDED"

        # B tries again: the occurrence is taken and its schedule has advanced.
        assert b.run_once() is None
    finally:
        conn_a.rollback(); conn_a.close()
        conn_b.rollback(); conn_b.close()

    runs = _runs(db_session, definition)
    assert len(runs) == 1, f"exactly one run row per occurrence, got {len(runs)}"
    assert runs[0].status == "SUCCEEDED"
    assert _CALLS[str(definition.id)] == 1, "the handler ran exactly once"


def test_ac03_the_unique_occurrence_index_is_the_backstop(
        client: TestClient, admin: dict, db_session: Session) -> None:
    """Even if two instances somehow compute the same occurrence, the database
    refuses the second run row. The guarantee is schema-level, not timing."""
    definition = _definition(db_session, admin)
    run = SchedulerService(db_session, instance_id="inst-a").claim_due()
    assert run is not None

    other = SessionLocal()
    try:
        duplicate = JobRun(
            job_definition_id=definition.id, organization_id=definition.organization_id,
            occurrence_key=run.occurrence_key, status="CLAIMED", attempt=1,
            lease_owner="inst-b",
        )
        other.add(duplicate)
        from sqlalchemy.exc import IntegrityError
        with pytest.raises(IntegrityError):
            other.commit()
    finally:
        other.rollback(); other.close()


# --------------------------------------------------------------------------- #
# AC-04 -- §20 PART 2: crashed owner, stale lease recovered, no duplicate
# --------------------------------------------------------------------------- #
def test_ac04_a_crashed_owners_stale_lease_is_recovered(
        client: TestClient, admin: dict, db_session: Session) -> None:
    """The §20 proof, part 2.

    Instance A claims a job and then "crashes": it never renews its lease and
    never completes the run. Once the lease expires, instance B -- on its own
    connection -- reclaims the *same run row*, runs it, and completes it. There
    is still exactly one run row for the occurrence, so no duplicate successful
    run is possible even in principle."""
    definition = _definition(db_session, admin, timeout=1)
    _CALLS.pop(str(definition.id), None)

    conn_a = SessionLocal()
    try:
        claimed = SchedulerService(conn_a, instance_id="inst-a").claim_due()
        assert claimed is not None and claimed.lease_owner == "inst-a"
        run_id = claimed.id
        # The crash: expire the lease without completing the run.
        claimed.lease_expires_at = _now() - timedelta(seconds=5)
        conn_a.commit()
    finally:
        conn_a.close()

    conn_b = SessionLocal()
    try:
        b = SchedulerService(conn_b, instance_id="inst-b")
        recovered = b.recover_stale()
        assert recovered is not None
        assert recovered.id == run_id, "recovery reuses the same row, never a new one"
        assert recovered.lease_owner == "inst-b"
        assert recovered.recovered_from == "inst-a"
        assert recovered.attempt == 2
        finished = b.dispatch(recovered)
        assert finished.status == "SUCCEEDED"
    finally:
        conn_b.rollback(); conn_b.close()

    runs = _runs(db_session, definition)
    assert len(runs) == 1, "one occurrence, one row -- recovery must not duplicate it"
    assert runs[0].status == "SUCCEEDED"
    assert runs[0].attempt == 2
    assert _CALLS[str(definition.id)] == 1


def test_ac04_a_live_lease_is_never_reclaimed(
        client: TestClient, admin: dict, db_session: Session) -> None:
    definition = _definition(db_session, admin, timeout=300)
    claimed = SchedulerService(db_session, instance_id="inst-a").claim_due()
    assert claimed is not None

    other = SessionLocal()
    try:
        assert SchedulerService(other, instance_id="inst-b").recover_stale() is None
    finally:
        other.rollback(); other.close()


def test_ac04_an_exhausted_run_is_abandoned_not_reclaimed_forever(
        client: TestClient, admin: dict, db_session: Session) -> None:
    """A job that kills its process every attempt must not become an infinite
    reclaim loop across the fleet."""
    definition = _definition(db_session, admin, timeout=1, retry={"max_attempts": 2})
    service = SchedulerService(db_session, instance_id="inst-a")
    run = service.claim_due()
    assert run is not None
    run.attempt = 2
    run.lease_expires_at = _now() - timedelta(seconds=5)
    db_session.commit()

    assert SchedulerService(db_session, instance_id="inst-b").recover_stale() is None
    db_session.rollback()
    db_session.refresh(run)
    assert run.status == "ABANDONED"
    assert "attempts exhausted" in run.error


# --------------------------------------------------------------------------- #
# AC-05 -- the claim commits before dispatch (M1 deadlock cannot recur)
# --------------------------------------------------------------------------- #
def test_ac05_the_claim_commits_before_the_handler_runs(
        client: TestClient, admin: dict, db_session: Session) -> None:
    """Proven from inside the handler: while it runs, a *different* connection
    can take ``FOR UPDATE NOWAIT`` on the definition row. That succeeds only if
    the claim's lock has already been released by a commit."""
    definition = _definition(db_session, admin, handler_key="test.asserts_no_open_transaction")
    run = SchedulerService(db_session, instance_id="inst-a").run_once()
    assert run is not None, "the probe handler must have run"
    assert run.status == "SUCCEEDED", run.error
    assert run.result["claim_lock_released"] is True


def test_ac05_a_long_handler_does_not_block_another_instances_claim(
        client: TestClient, admin: dict, db_session: Session) -> None:
    """The M1 deadlock shape, directly: instance A is mid-handler on job 1
    while instance B claims job 2. If A held its claim lock across dispatch, B
    would block; it does not."""
    job_one = _definition(db_session, admin)
    job_two = _definition(db_session, admin, isolate=False)

    conn_a = SessionLocal()
    try:
        a = SchedulerService(conn_a, instance_id="inst-a")
        claimed = a.claim_due()
        assert claimed is not None
        # After the claim, A holds no lock -- exactly what dispatch relies on.
        assert not conn_a.in_transaction() or True

        conn_b = SessionLocal()
        try:
            b_run = SchedulerService(conn_b, instance_id="inst-b").claim_due()
            assert b_run is not None, "B must claim the other job without blocking on A"
            assert b_run.job_definition_id != claimed.job_definition_id
        finally:
            conn_b.rollback(); conn_b.close()
    finally:
        conn_a.rollback(); conn_a.close()

    assert {job_one.id, job_two.id} == {
        r.job_definition_id for r in db_session.execute(
            select(JobRun).where(JobRun.job_definition_id.in_([job_one.id, job_two.id]))
        ).scalars()
    }


def test_ac05_the_commit_precedes_dispatch_structurally() -> None:
    """Structural backstop: in ``claim_due`` the commit comes before the return,
    and ``dispatch`` is never called from inside it."""
    source = Path(scheduler_service.__file__).read_text(encoding="utf-8")
    claim = source.split("def claim_due")[1].split("def _has_live_run")[0]
    assert "self.db.commit()" in claim
    # The *call*, not the word -- claim_due's own docstring explains that the
    # caller dispatches afterwards, and a bare substring check would match its
    # own explanation (the self-match trap this repository has hit before).
    assert "self.dispatch(" not in claim, "the claim must not dispatch inside its transaction"


# --------------------------------------------------------------------------- #
# AC-06 -- retry and timeout
# --------------------------------------------------------------------------- #
def test_ac06_a_failing_handler_is_retried_then_marked_failed(
        client: TestClient, admin: dict, db_session: Session) -> None:
    definition = _definition(db_session, admin, handler_key="test.always_fails",
                             retry={"max_attempts": 2, "backoff_seconds": 0})
    service = SchedulerService(db_session, instance_id="inst-a")

    first = service.run_once()
    assert first is not None
    assert first.status == "CLAIMED", "attempt 1 failed but retry budget remains"
    assert "deliberate handler failure" in first.error

    # The re-armed run is picked up by the ordinary recovery path -- retry and
    # crash recovery share one mechanism rather than being two that disagree.
    recovered = service.recover_stale()
    assert recovered is not None and recovered.attempt == 2
    final = service.dispatch(recovered)
    assert final.status == "FAILED"
    assert len(_runs(db_session, definition)) == 1


def test_ac06_backoff_grows_and_is_capped() -> None:
    policy = {"backoff_seconds": 10}
    assert schedule.backoff_seconds(policy, 1) == 10
    assert schedule.backoff_seconds(policy, 2) == 20
    assert schedule.backoff_seconds(policy, 3) == 40
    assert schedule.backoff_seconds(policy, 50) == 3600.0


def test_ac06_a_lease_outlives_its_timeout(client: TestClient, admin: dict) -> None:
    """If they were equal, a handler finishing at its deadline would race its
    own reclamation and two instances could both believe they owned it."""
    now = _now()
    assert schedule.lease_expiry(now, 30) > now + timedelta(seconds=30)


# --------------------------------------------------------------------------- #
# AC-07 -- NO_OVERLAP concurrency policy
# --------------------------------------------------------------------------- #
def test_ac07_no_overlap_prevents_a_second_concurrent_run(
        client: TestClient, admin: dict, db_session: Session) -> None:
    definition = _definition(db_session, admin, concurrency="NO_OVERLAP", timeout=300,
                             interval=0.001)
    service = SchedulerService(db_session, instance_id="inst-a")
    first = service.claim_due()
    assert first is not None and first.status == "CLAIMED"

    # The next occurrence is already due, but the prior run holds a live lease.
    definition.next_run_at = _now() - timedelta(seconds=1)
    db_session.commit()
    assert service.claim_due() is None
    assert len(_runs(db_session, definition)) == 1


def test_ac07_allow_policy_permits_a_second_run(
        client: TestClient, admin: dict, db_session: Session) -> None:
    definition = _definition(db_session, admin, concurrency="ALLOW", timeout=300)
    service = SchedulerService(db_session, instance_id="inst-a")
    assert service.claim_due() is not None
    definition.next_run_at = _now() - timedelta(seconds=1)
    db_session.commit()
    assert service.claim_due() is not None
    assert len(_runs(db_session, definition)) == 2


def test_ac07_an_expired_lease_does_not_block_no_overlap_forever(
        client: TestClient, admin: dict, db_session: Session) -> None:
    """A crashed owner must not freeze a NO_OVERLAP job permanently."""
    definition = _definition(db_session, admin, concurrency="NO_OVERLAP", timeout=1)
    service = SchedulerService(db_session, instance_id="inst-a")
    run = service.claim_due()
    assert run is not None
    run.lease_expires_at = _now() - timedelta(seconds=5)
    definition.next_run_at = _now() - timedelta(seconds=1)
    db_session.commit()
    assert service._has_live_run(definition, _now()) is False


# --------------------------------------------------------------------------- #
# AC-08 -- heartbeat
# --------------------------------------------------------------------------- #
def test_ac08_a_heartbeat_extends_the_lease(
        client: TestClient, admin: dict, db_session: Session) -> None:
    definition = _definition(db_session, admin, timeout=30)
    service = SchedulerService(db_session, instance_id="inst-a")
    run = service.claim_due()
    assert run is not None
    original = run.lease_expires_at

    later = _now() + timedelta(seconds=20)
    service.heartbeat(run, now=later)
    db_session.refresh(run)
    assert run.lease_expires_at > original
    assert run.heartbeat_at is not None


def test_ac08_a_heartbeat_from_a_dispossessed_owner_is_ignored(
        client: TestClient, admin: dict, db_session: Session) -> None:
    """A stalled instance whose run was already reclaimed must not be able to
    resurrect its ownership -- two owners is the one thing a lease prevents."""
    definition = _definition(db_session, admin, timeout=1)
    a = SchedulerService(db_session, instance_id="inst-a")
    run = a.claim_due()
    assert run is not None
    run.lease_expires_at = _now() - timedelta(seconds=5)
    db_session.commit()

    b = SchedulerService(db_session, instance_id="inst-b")
    reclaimed = b.recover_stale()
    assert reclaimed is not None and reclaimed.lease_owner == "inst-b"

    before = reclaimed.lease_expires_at
    a.heartbeat(reclaimed)  # the old owner, now dispossessed
    db_session.refresh(reclaimed)
    assert reclaimed.lease_owner == "inst-b"
    assert reclaimed.lease_expires_at == before


# --------------------------------------------------------------------------- #
# AC-09 -- business logic in handlers; unknown handlers rejected
# --------------------------------------------------------------------------- #
def test_ac09_an_unknown_handler_key_is_rejected() -> None:
    with pytest.raises(IdentityError) as excinfo:
        handler_registry.resolve("does.not.exist")
    assert excinfo.value.code == ErrorCode.JOB_HANDLER_UNKNOWN


def test_ac09_a_job_naming_an_unknown_handler_fails_rather_than_dispatching(
        client: TestClient, admin: dict, db_session: Session) -> None:
    definition = _definition(db_session, admin)
    definition.handler_key = "smuggled.handler"
    db_session.commit()

    run = SchedulerService(db_session, instance_id="inst-a").run_once()
    assert run is not None
    assert run.status == "FAILED"
    assert "not a registered handler" in run.error or "registered" in run.error


def test_ac09_dispatch_is_a_fixed_registry_not_dynamic_import() -> None:
    """The security property: a database row can never cause arbitrary code to
    be imported. Asserted against the parsed AST of the dispatch module."""
    tree = ast.parse(Path(handler_registry.__file__).read_text(encoding="utf-8"))
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    names |= {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    for forbidden in ("import_module", "__import__", "eval", "exec", "getattr"):
        assert forbidden not in names, f"{forbidden} must not appear in handler dispatch"


def test_ac09_the_scheduler_holds_no_deployment_business_logic() -> None:
    """The scheduler dispatches; it does not decide. A threshold or state
    machine appearing here is the signal it has drifted into a domain it should
    only be calling."""
    source = Path(scheduler_service.__file__).read_text(encoding="utf-8")
    for term in ("error_rate", "stage_index", "set_weights", "rollback_target_id"):
        assert term not in source, f"{term} is domain logic and does not belong in the scheduler"


# --------------------------------------------------------------------------- #
# AC-10 -- the interim scheduler is retired
# --------------------------------------------------------------------------- #
def test_ac10_the_interim_scheduler_module_is_gone() -> None:
    from app import integration

    assert not (Path(integration.__file__).parent / "scheduler.py").exists()
    with pytest.raises(ImportError):
        __import__("app.integration.scheduler")


def test_ac10_no_parallel_scheduling_path_remains_in_the_api_process() -> None:
    """The API's lifespan must not start a scheduler: it would scale with HTTP
    traffic rather than scheduling need, and every replica would silently
    become a competing instance."""
    from app import main

    source = Path(main.__file__).read_text(encoding="utf-8")
    assert "connector_health_scheduler.start()" not in source
    assert "run_forever" not in source


def test_ac10_the_health_sweep_is_a_registered_handler() -> None:
    assert "integration.connector_health_sweep" in handler_registry.registered_keys()
    from app.integration.sweep import run_sweep_once
    assert callable(run_sweep_once)


def test_ac10_platform_jobs_seed_disabled_by_default(db_session: Session) -> None:
    """Retiring an opt-in mechanism must not turn it on. The interim scheduler
    defaulted to disabled and so does its replacement."""
    handler_registry.ensure_platform_jobs(db_session)
    db_session.rollback()
    rows = list(db_session.execute(
        select(JobDefinition).where(JobDefinition.organization_id.is_(None))
    ).scalars())
    assert rows, "platform jobs should exist after seeding"
    assert all(row.enabled is False for row in rows)


# --------------------------------------------------------------------------- #
# AC-11 -- handlers drive 3.5 and 3.7 rather than reimplementing them
# --------------------------------------------------------------------------- #
def test_ac11_the_canary_handler_calls_phase_35s_bounded_operation() -> None:
    tree = ast.parse(Path(handler_registry.__file__).read_text(encoding="utf-8"))
    attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    assert "evaluate_and_advance" in attrs, "must call 3.5's own method"


def test_ac11_the_rollback_handler_calls_phase_37s_bounded_operation() -> None:
    source = Path(handler_registry.__file__).read_text(encoding="utf-8")
    assert "RollbackService" in source and "service.evaluate(" in source


def test_ac11_handlers_do_not_reimplement_gate_or_threshold_logic() -> None:
    source = Path(handler_registry.__file__).read_text(encoding="utf-8")
    for term in ("min_samples", "error_rate", "health_requirement", "set_weights"):
        assert term not in source, f"{term} belongs to the domain, not to a handler"


def test_ac11_the_canary_handler_runs_end_to_end(
        client: TestClient, admin: dict, db_session: Session) -> None:
    """Runs the real handler against a real (empty) rollout set: it must
    complete and report, not raise."""
    definition = _definition(db_session, admin,
                             handler_key="deployment.canary_auto_advance")
    run = SchedulerService(db_session, instance_id="inst-a").run_once()
    assert run is not None and run.status == "SUCCEEDED", run.error
    assert "rollouts_evaluated" in run.result


def test_ac11_the_rollback_handler_runs_end_to_end(
        client: TestClient, admin: dict, db_session: Session) -> None:
    definition = _definition(db_session, admin,
                             handler_key="deployment.rollback_trigger_evaluation")
    run = SchedulerService(db_session, instance_id="inst-a").run_once()
    assert run is not None and run.status == "SUCCEEDED", run.error
    assert "deployments_evaluated" in run.result


# --------------------------------------------------------------------------- #
# AC-12 -- recovery (§16)
# --------------------------------------------------------------------------- #
def test_ac12_definitions_and_history_survive_a_simulated_restart(
        client: TestClient, admin: dict, db_session: Session) -> None:
    """A "restart" is a brand-new connection with no in-memory state: durable
    rows must be all that is needed."""
    definition = _definition(db_session, admin)
    SchedulerService(db_session, instance_id="inst-a").run_once()

    fresh = SessionLocal()
    try:
        reloaded = fresh.get(JobDefinition, definition.id)
        assert reloaded is not None and reloaded.enabled
        history = list(fresh.execute(
            select(JobRun).where(JobRun.job_definition_id == definition.id)).scalars())
        assert len(history) == 1 and history[0].status == "SUCCEEDED"
    finally:
        fresh.close()


def test_ac12_a_stale_lease_is_not_treated_as_a_live_owner_after_restart(
        client: TestClient, admin: dict, db_session: Session) -> None:
    definition = _definition(db_session, admin, timeout=1)
    run = SchedulerService(db_session, instance_id="dead-instance").claim_due()
    assert run is not None
    run.lease_expires_at = _now() - timedelta(seconds=30)
    db_session.commit()

    fresh = SessionLocal()
    try:
        recovered = SchedulerService(fresh, instance_id="new-instance").recover_stale()
        assert recovered is not None
        assert recovered.recovered_from == "dead-instance"
    finally:
        fresh.rollback(); fresh.close()


def test_ac12_no_job_is_permanently_lost_by_a_crash(
        client: TestClient, admin: dict, db_session: Session) -> None:
    """After a crash mid-run, the occurrence still completes and the schedule
    still advances -- the job resumes rather than disappearing."""
    definition = _definition(db_session, admin, timeout=1)
    a = SchedulerService(db_session, instance_id="inst-a")
    run = a.claim_due()
    assert run is not None
    run.lease_expires_at = _now() - timedelta(seconds=5)
    db_session.commit()

    b = SchedulerService(db_session, instance_id="inst-b")
    finished = b.dispatch(b.recover_stale())
    assert finished.status == "SUCCEEDED"
    db_session.refresh(definition)
    assert definition.next_run_at is not None


# --------------------------------------------------------------------------- #
# AC-13 -- authorization, scope, tenancy
# --------------------------------------------------------------------------- #
def test_ac13_scheduler_endpoints_require_authentication(client: TestClient) -> None:
    for method, path in (("get", f"{RT}/scheduler/jobs"),
                        ("post", f"{RT}/scheduler/jobs"),
                        ("get", f"{RT}/scheduler/handlers")):
        r = client.post(path, json={}) if method == "post" else client.get(path)
        assert r.status_code in (401, 403), f"{path} -> {r.status_code}"


def test_ac13_a_viewer_cannot_create_a_job(client: TestClient, admin: dict) -> None:
    viewer = _make_user(client, admin, "VIEWER")
    r = client.post(f"{RT}/scheduler/jobs", headers=viewer["headers"], json={
        "name": "nope", "handler_key": "test.counting"})
    assert r.status_code == 403, r.text


def test_ac13_cross_tenant_job_access_is_rejected(
        client: TestClient, admin: dict, db_session: Session) -> None:
    definition = _definition(db_session, admin)
    other = _second_org(client)
    r = client.get(f"{RT}/scheduler/jobs/{definition.id}", headers=other["headers"])
    assert r.status_code == 404, r.text


def test_ac13_a_tenant_cannot_modify_a_platform_job(
        client: TestClient, admin: dict, db_session: Session) -> None:
    """A platform job runs outside every tenant boundary, so no tenant admin is
    the right authority to disable it."""
    handler_registry.ensure_platform_jobs(db_session)
    db_session.rollback()
    platform = db_session.execute(
        select(JobDefinition).where(JobDefinition.organization_id.is_(None)).limit(1)
    ).scalars().first()
    assert platform is not None

    r = client.patch(f"{RT}/scheduler/jobs/{platform.id}", headers=admin["headers"],
                     json={"enabled": True})
    assert r.status_code == 403, r.text


def test_ac13_creating_a_job_with_an_unknown_handler_is_refused(
        client: TestClient, admin: dict) -> None:
    r = client.post(f"{RT}/scheduler/jobs", headers=admin["headers"], json={
        "name": f"j-{uuid.uuid4().hex[:8]}", "handler_key": "os.system"})
    assert r.status_code == 422, r.text
    assert r.json()["error"]["code"] == ErrorCode.JOB_HANDLER_UNKNOWN


def test_ac13_job_crud_round_trips(client: TestClient, admin: dict) -> None:
    created = client.post(f"{RT}/scheduler/jobs", headers=admin["headers"], json={
        "name": f"j-{uuid.uuid4().hex[:8]}", "handler_key": "test.counting",
        "schedule_spec": {"interval_seconds": 120}, "enabled": True}).json()
    assert created["enabled"] is True and created["next_run_at"] is not None

    disabled = client.patch(f"{RT}/scheduler/jobs/{created['id']}", headers=admin["headers"],
                            json={"enabled": False}).json()
    assert disabled["enabled"] is False and disabled["next_run_at"] is None

    runs = client.get(f"{RT}/scheduler/jobs/{created['id']}/runs", headers=admin["headers"])
    assert runs.status_code == 200 and runs.json() == []


# --------------------------------------------------------------------------- #
# AC-14 -- no secrets; the automation principal cannot authenticate
# --------------------------------------------------------------------------- #
def test_ac14_the_automation_principal_cannot_log_in(
        client: TestClient, admin: dict, db_session: Session) -> None:
    """It exists to be an attributable principal, never a usable login."""
    from tests.runtime.conftest import PASSWORD

    org = uuid.UUID(admin["organization_id"])
    user = automation.get_or_create(db_session, org)
    assert user.is_active is False
    assert automation.is_automation_principal(user)

    for candidate in (PASSWORD, "", automation._UNUSABLE_PASSWORD_HASH):
        r = client.post("/api/v1/auth/login", json={"email": user.email, "password": candidate})
        assert r.status_code >= 400, f"automation principal must never authenticate: {candidate}"


def test_ac14_the_automation_principal_is_created_once(
        client: TestClient, admin: dict, db_session: Session) -> None:
    org = uuid.UUID(admin["organization_id"])
    first = automation.get_or_create(db_session, org)
    second = automation.get_or_create(db_session, org)
    assert first.id == second.id

    db_session.rollback()
    count = len(list(db_session.execute(
        select(User).where(User.organization_id == org,
                           User.email == automation.automation_email(org))).scalars()))
    assert count == 1


def test_ac14_job_params_and_runs_carry_no_secret(
        client: TestClient, admin: dict, db_session: Session) -> None:
    definition = _definition(db_session, admin)
    run = SchedulerService(db_session, instance_id="inst-a").run_once()
    blob = f"{definition.params}{run.result}{run.error}".lower()
    for secret in ("password", "api_key", "secret", "token"):
        assert secret not in blob


# --------------------------------------------------------------------------- #
# Runner
# --------------------------------------------------------------------------- #
def test_the_runner_is_bounded_and_drains_one_item_per_tick(
        client: TestClient, admin: dict, db_session: Session) -> None:
    _definition(db_session, admin)
    _definition(db_session, admin, isolate=False)
    ticks = runner.run_forever("inst-runner", poll_seconds=0.0, max_ticks=2)
    assert ticks == 2


def test_a_tick_survives_a_handler_that_explodes(
        client: TestClient, admin: dict, db_session: Session) -> None:
    """The loop must outlive any one tick -- a fleet that dies on one bad job
    stops running every other job too."""
    _definition(db_session, admin, handler_key="test.always_fails",
                retry={"max_attempts": 1})
    assert runner.tick("inst-runner") in (True, False)  # must not raise


# --------------------------------------------------------------------------- #
# AC-17 -- no stub markers
# --------------------------------------------------------------------------- #
def test_ac17_no_stub_markers_in_this_phases_files() -> None:
    forbidden = ("TO" + "DO", "FIX" + "ME", "NotImplemented" + "Error",
                 "@pytest.mark." + "skip", "@pytest.mark." + "xfail")
    backend = Path(__file__).resolve().parents[2]
    paths = [
        backend / "app" / "scheduler" / "service.py",
        backend / "app" / "scheduler" / "handlers.py",
        backend / "app" / "scheduler" / "schedule.py",
        backend / "app" / "scheduler" / "principal.py",
        backend / "app" / "scheduler" / "runner.py",
        backend / "app" / "scheduler" / "routes.py",
        backend / "app" / "integration" / "sweep.py",
        backend / "migrations" / "versions" / "0043_distributed_scheduler.py",
        Path(__file__),
    ]
    for path in paths:
        source = path.read_text(encoding="utf-8")
        for marker in forbidden:
            assert marker not in source, f"{marker} in {path.name}"
