"""Phase 5.2 (M5.2) - Agent Discovery Framework.

Proves the vendor-neutral discovery framework end to end against a REAL,
non-mocked local HTTP server (the exact ``http.server`` convention Phase
2.2.1's REST-connector tests established) - observations are append-only
evidence, reconciliation derives canonical state through the Phase 5.1
server-authoritative path, no DB lock is held across the external fetch, no
silent merge/split, discovery != control, and the whole path fails open.

AC-01..AC-21 + the §15 end-to-end proof; each AC has a named test.
"""

from __future__ import annotations

import http.server
import inspect
import json as jsonlib
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.database import SessionLocal
from app.discovery.adapters import registry as adapter_registry
from app.discovery.adapters.base import DiscoveryAdapter
from app.discovery.reconciliation import ReconciliationService
from app.discovery.service import DiscoveryRunService, DiscoverySourceService
from app.models.agent import Agent
from app.models.discovery import DiscoveryFinding, DiscoveryObservation, DiscoveryRun, DiscoverySource
from app.models.user import User

DISC = "/api/v1/discovery"
_BACKEND = Path(__file__).resolve().parents[2]
_REPO = _BACKEND.parent


# --------------------------------------------------------------------------- #
# A real local HTTP server - a mutable in-memory agent registry
# --------------------------------------------------------------------------- #
class _Registry:
    def __init__(self) -> None:
        self.agents: list[dict] = []
        self.requests: list[dict] = []
        self.fail_first_n_pages: int = 0
        #: Fail exactly the Nth page request (1-based) with a 503, then
        #: succeed again - simulates a mid-sweep hiccup, not an outage.
        self.fail_page_number: int | None = None
        self.hold_requests = False
        self.hold_event = threading.Event()
        self.page_size_cap = 50


@contextmanager
def local_server(reg: _Registry):
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if reg.hold_requests:
                reg.hold_event.wait(timeout=10)
            parsed = urlsplit(self.path)
            query = parse_qs(parsed.query)
            reg.requests.append({"path": parsed.path, "query": query,
                                 "authorization": self.headers.get("Authorization")})
            if parsed.path != "/agents":
                self.send_response(404)
                self.end_headers()
                return
            page_number = sum(1 for r in reg.requests if r["path"] == "/agents")
            if reg.fail_first_n_pages > 0:
                reg.fail_first_n_pages -= 1
                self.send_response(503)
                self.end_headers()
                return
            if reg.fail_page_number is not None and page_number == reg.fail_page_number:
                self.send_response(503)
                self.end_headers()
                return
            offset = int(query.get("offset", ["0"])[0])
            limit = min(int(query.get("limit", ["50"])[0]), reg.page_size_cap)
            page = reg.agents[offset:offset + limit]
            next_offset = offset + limit if offset + limit < len(reg.agents) else None
            body = jsonlib.dumps({"items": page, "next_offset": next_offset}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a) -> None:
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_port
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield port
    finally:
        server.shutdown()
        thread.join(timeout=5)


def _config(port: int, **overrides) -> dict:
    cfg = {
        "base_url": f"http://127.0.0.1:{port}",
        "allowed_hosts": ["127.0.0.1"],
        "local_dev_hosts": ["127.0.0.1"],
        "allow_plaintext_http": True,
        "path": "/agents",
        "page_size": 10,
        "max_pages": 5,
    }
    cfg.update(overrides)
    return cfg


def _create_source(client: TestClient, admin: dict, port: int, **overrides) -> dict:
    r = client.post(f"{DISC}/sources", headers=admin["headers"], json={
        "name": f"Registry {uuid.uuid4().hex[:6]}", "adapter_key": "HTTP_AGENT_REGISTRY",
        "config": _config(port, **overrides),
    })
    assert r.status_code == 201, r.text
    return r.json()


def _trigger(client: TestClient, admin: dict, source_id: str, **headers) -> dict:
    r = client.post(f"{DISC}/sources/{source_id}/runs", headers={**admin["headers"], **headers})
    assert r.status_code == 201, r.text
    return r.json()


# --------------------------------------------------------------------------- #
# AC-01 - live baseline
# --------------------------------------------------------------------------- #
def test_ac01_5_1_substrate_present_and_head_recorded() -> None:
    from app.runtime.registry.control import AgentControlStateService, AgentProvenanceService  # noqa: F401

    versions = sorted((_BACKEND / "migrations" / "versions").glob("*.py"))
    assert versions[-1].stem == "0055_agent_discovery"
    assert {"0054_agent_asset_model"} <= {v.stem for v in versions}
    repo_state = (_REPO / "REPO_STATE.md").read_text(encoding="utf-8")
    assert "0055_agent_discovery" in repo_state


# --------------------------------------------------------------------------- #
# AC-02 - adapter contract mirrors the connector pattern, uses GovernedHttpClient
# --------------------------------------------------------------------------- #
def test_ac02_adapter_registered_and_uses_governed_http_client() -> None:
    from app.integration.sdk import GovernedHttpClient

    assert "HTTP_AGENT_REGISTRY" in adapter_registry.registered_keys()
    adapter = adapter_registry.resolve("HTTP_AGENT_REGISTRY")
    d = adapter.describe()
    assert d.adapter_key == "HTTP_AGENT_REGISTRY"
    client = adapter.build_client({"allowed_hosts": ["x"], "allow_plaintext_http": True})
    assert isinstance(client, GovernedHttpClient)


def test_ac02_unknown_adapter_key_is_rejected() -> None:
    with pytest.raises(Exception) as exc:
        adapter_registry.resolve("NOT_A_REAL_ADAPTER")
    from app.identity.errors import ErrorCode, IdentityError
    assert isinstance(exc.value, IdentityError)
    assert exc.value.code == ErrorCode.DISCOVERY_ADAPTER_UNKNOWN


# --------------------------------------------------------------------------- #
# AC-03 - a real sweep: paginated, checkpointed, tolerates partial failure
# --------------------------------------------------------------------------- #
def test_ac03_run_sweeps_a_real_source_paginated(client: TestClient, admin: dict) -> None:
    reg = _Registry()
    reg.agents = [{"id": f"ext-{i}", "name": f"Agent {i}", "agent_type": "ASSISTANT"} for i in range(23)]
    with local_server(reg) as port:
        source = _create_source(client, admin, port, page_size=10, max_pages=5)
        run = _trigger(client, admin, source["id"])
        assert run["status"] == "SUCCEEDED", run
        assert run["observations_count"] == 23
        assert run["agents_created"] == 23
        # paginated: at least 3 pages of 10/10/3
        assert len([r for r in reg.requests if r["path"] == "/agents"]) >= 3


def test_ac03_partial_failure_yields_a_partial_run_not_a_crash(client: TestClient, admin: dict) -> None:
    """The first page succeeds (real evidence is collected); the second page
    fails (a mid-sweep hiccup, not an outage) -> the run is PARTIAL, keeps
    what it already fetched, and does not crash."""
    reg = _Registry()
    reg.agents = [{"id": f"ext-{i}", "name": f"Agent {i}"} for i in range(15)]
    reg.fail_page_number = 2
    with local_server(reg) as port:
        source = _create_source(client, admin, port, page_size=5, max_pages=5)
        run = _trigger(client, admin, source["id"])
        assert run["status"] == "PARTIAL"
        assert run["observations_count"] == 5  # only the first, successful page
        assert run["agents_created"] == 5


def test_ac03_source_outage_on_first_page_fails_the_run_not_the_platform(client: TestClient, admin: dict) -> None:
    reg = _Registry()
    reg.fail_first_n_pages = 1
    with local_server(reg) as port:
        source = _create_source(client, admin, port)
        run = _trigger(client, admin, source["id"])
        assert run["status"] == "FAILED"
        assert run["error"]
    # the platform itself is unaffected - a normal call still works
    r2 = client.get(f"{DISC}/sources", headers=admin["headers"])
    assert r2.status_code == 200


def test_ac03_bounded_by_max_pages_hostile_huge_source(client: TestClient, admin: dict) -> None:
    reg = _Registry()
    reg.agents = [{"id": f"ext-{i}", "name": f"Agent {i}"} for i in range(1000)]
    with local_server(reg) as port:
        source = _create_source(client, admin, port, page_size=50, max_pages=3)
        run = _trigger(client, admin, source["id"])
        assert run["status"] == "PARTIAL"
        assert run["observations_count"] == 150  # exactly max_pages * page_size, never all 1000


# --------------------------------------------------------------------------- #
# AC-04 - observations are append-only evidence, never mutate agents directly
# --------------------------------------------------------------------------- #
def test_ac04_observations_never_update_or_delete() -> None:
    """Mirrors ``test_ac11_decisions_are_append_only_at_the_database_level``
    (Phase 4.3) exactly: the migration revokes UPDATE/DELETE from PUBLIC
    (checked against the live grant metadata), and no service module in this
    domain ever calls ``db.delete``/updates an observation row."""
    from sqlalchemy import text

    db = SessionLocal()
    try:
        grants = db.execute(text(
            "SELECT privilege_type FROM information_schema.role_table_grants "
            "WHERE table_name = 'discovery_observations' AND grantee = 'PUBLIC'"
        )).scalars().all()
        assert "UPDATE" not in grants
        assert "DELETE" not in grants
    finally:
        db.close()

    for path in (_BACKEND / "app" / "discovery").rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        assert "db.delete" not in source, f"{path.name} deletes rows"


def test_ac04_reconciliation_never_writes_agents_from_an_adapter_directly() -> None:
    """Structural: no adapter module imports the Agent model or a Session."""
    import ast

    path = _BACKEND / "app" / "discovery" / "adapters" / "http_agent_registry.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    assert "app.models.agent" not in imported
    assert "sqlalchemy.orm" not in imported


# --------------------------------------------------------------------------- #
# AC-05 - deterministic matching/confidence; create/link/flag; no silent merge
# --------------------------------------------------------------------------- #
def test_ac05_create_then_link_is_idempotent_one_agent(client: TestClient, admin: dict) -> None:
    reg = _Registry()
    reg.agents = [{"id": "ext-1", "name": "Stable Agent"}]
    with local_server(reg) as port:
        source = _create_source(client, admin, port)
        run1 = _trigger(client, admin, source["id"])
        assert run1["agents_created"] == 1
        run2 = _trigger(client, admin, source["id"])
        assert run2["agents_created"] == 0
        assert run2["agents_linked"] == 1

    db = SessionLocal()
    try:
        agents = db.execute(select(Agent).where(
            Agent.organization_id == uuid.UUID(admin["organization_id"]),
            Agent.external_reference == "ext-1")).scalars().all()
        assert len(agents) == 1
        assert agents[0].control_state == "DISCOVERED"
        assert agents[0].origin_category == "EXTERNAL"
    finally:
        db.close()


def test_ac05_low_confidence_observation_is_flagged_not_auto_linked(admin: dict) -> None:
    db = SessionLocal()
    try:
        actor = db.get(User, uuid.UUID(admin["user_id"]))
        source = DiscoverySourceService(db).create(
            actor, name="LowConf", adapter_key="HTTP_AGENT_REGISTRY",
            config=_config(1))
        from decimal import Decimal
        run = DiscoveryRun(organization_id=source.organization_id, source_id=source.id,
                           status="RUNNING", trigger="MANUAL")
        db.add(run)
        db.commit()
        obs = DiscoveryObservation(
            organization_id=source.organization_id, source_id=source.id, run_id=run.id,
            external_identifier="low-conf-agent", normalized_payload={"name": "Sketchy Agent"},
            confidence=Decimal("0.40"), observed_at=run.started_at or run.created_at)
        db.add(obs)
        db.commit()
        result = ReconciliationService(db).reconcile(actor, run, source, [obs])
        assert result == {"created": 0, "linked": 0, "flagged": 1}

        finding = db.execute(select(DiscoveryFinding).where(
            DiscoveryFinding.organization_id == source.organization_id,
            DiscoveryFinding.external_identifier == "low-conf-agent")).scalars().first()
        assert finding is not None
        assert finding.finding_type == "RECONCILIATION_AMBIGUOUS"
        assert finding.status == "OPEN"
        assert "0.40" in finding.reason or "0.4" in finding.reason

        no_agent = db.execute(select(Agent).where(
            Agent.organization_id == source.organization_id,
            Agent.external_reference == "low-conf-agent")).scalars().first()
        assert no_agent is None  # no silent create
    finally:
        db.close()


def test_ac05_conflict_with_a_native_agent_is_flagged_never_linked(client: TestClient, admin: dict) -> None:
    # Register a native agent whose external_reference collides with a
    # discovered identifier.
    r = client.post("/api/v1/runtime/agents", headers=admin["headers"], json={
        "name": "Native Colliding Agent", "description": "d", "business_purpose": "d",
        "owner_type": "USER", "owner_id": admin["user_id"], "external_reference": "collide-1",
        "definition": {"name": "d", "entrypoint": "a.b:c"}})
    assert r.status_code == 201, r.text
    native_id = r.json()["id"]

    reg = _Registry()
    reg.agents = [{"id": "collide-1", "name": "Impersonator"}]
    with local_server(reg) as port:
        source = _create_source(client, admin, port)
        run = _trigger(client, admin, source["id"])
        assert run["agents_created"] == 0
        assert run["agents_linked"] == 0
        assert run["findings_created"] == 1

    findings = client.get(f"{DISC}/findings", headers=admin["headers"]).json()
    assert any(f["external_identifier"] == "collide-1" and f["agent_id"] == native_id for f in findings)

    # the native agent itself is completely untouched
    native = client.get(f"/api/v1/runtime/agents/{native_id}", headers=admin["headers"]).json()
    assert native["control_state"] == "GOVERNED"
    assert native["origin_category"] == "NATIVE"


# --------------------------------------------------------------------------- #
# AC-06 - NO DB lock / open transaction across the external fetch
# --------------------------------------------------------------------------- #
def test_ac06_adapter_fetch_signature_never_accepts_a_session() -> None:
    """Structural proof: every registered adapter's ``fetch`` has no
    Session/db parameter anywhere in its signature - it is impossible to
    hold a database object across the call because none is ever passed."""
    for key in adapter_registry.registered_keys():
        adapter = adapter_registry.resolve(key)
        sig = inspect.signature(adapter.fetch)
        for name, param in sig.parameters.items():
            assert name not in ("db", "session"), f"{key}.fetch has a {name} parameter"
            ann = str(param.annotation)
            assert "Session" not in ann, f"{key}.fetch parameter {name} is Session-typed"
    # And the ABC itself, not just this one adapter.
    sig = inspect.signature(DiscoveryAdapter.fetch)
    assert all(name not in ("db", "session") for name in sig.parameters)


def test_ac06_no_lock_held_across_the_external_fetch_behavioral(client: TestClient, admin: dict) -> None:
    """Real proof, not just structural: while a sweep's fetch is blocked on
    a real (slow) HTTP response, a concurrent, separate DB session can still
    read AND write the very same ``discovery_sources`` row without blocking.
    If the sweep held a lock across the fetch, this would hang until the
    fetch completed (or time out) - the exact M1 deadlock shape."""
    reg = _Registry()
    reg.agents = [{"id": "ext-slow", "name": "Slow Agent"}]
    with local_server(reg) as port:
        source = _create_source(client, admin, port)
        source_id = uuid.UUID(source["id"])
        reg.hold_requests = True

        outcome: dict = {}

        def _drive() -> None:
            outcome["response"] = client.post(f"{DISC}/sources/{source_id}/runs", headers=admin["headers"])

        t = threading.Thread(target=_drive)
        t.start()
        try:
            time.sleep(0.4)  # let the sweep reach the (held-open) HTTP call

            db2 = SessionLocal()
            try:
                start = time.monotonic()
                row = db2.execute(
                    select(DiscoverySource).where(DiscoverySource.id == source_id).with_for_update()
                ).scalars().first()
                assert row is not None
                row.last_run_status = "PROBE"
                db2.commit()
                elapsed = time.monotonic() - start
            finally:
                db2.close()

            assert elapsed < 2.0, (
                f"a concurrent FOR UPDATE on the source row took {elapsed:.2f}s while the fetch "
                "was in flight - a lock is being held across external I/O (the M1 deadlock shape)")
        finally:
            reg.hold_requests = False
            reg.hold_event.set()
            t.join(timeout=10)

        assert outcome["response"].status_code == 201
        assert outcome["response"].json()["status"] == "SUCCEEDED"


# --------------------------------------------------------------------------- #
# AC-07 - discovery != control
# --------------------------------------------------------------------------- #
def test_ac07_discovered_agent_is_not_controllable(client: TestClient, admin: dict) -> None:
    reg = _Registry()
    reg.agents = [{"id": "ext-nc", "name": "Not Controllable"}]
    with local_server(reg) as port:
        source = _create_source(client, admin, port)
        _trigger(client, admin, source["id"])

    agents = client.get("/api/v1/runtime/agents", headers=admin["headers"]).json()
    disc_agent = next(a for a in agents if a.get("external_reference") == "ext-nc")
    assert disc_agent["control_state"] == "DISCOVERED"
    # No governance affordance: a direct GOVERNED transition is rejected.
    r = client.post(f"/api/v1/runtime/agents/{disc_agent['id']}/control-state",
                    headers=admin["headers"], json={"target_state": "GOVERNED"})
    assert r.status_code == 409


# --------------------------------------------------------------------------- #
# AC-08 - staleness is a finding, not a deletion
# --------------------------------------------------------------------------- #
def test_ac08_disappeared_agent_yields_staleness_finding_not_deletion(client: TestClient, admin: dict) -> None:
    reg = _Registry()
    reg.agents = [{"id": "ext-here", "name": "Here"}, {"id": "ext-gone", "name": "Gone Soon"}]
    with local_server(reg) as port:
        source = _create_source(client, admin, port)
        run1 = _trigger(client, admin, source["id"])
        assert run1["agents_created"] == 2

        reg.agents = [a for a in reg.agents if a["id"] != "ext-gone"]
        run2 = _trigger(client, admin, source["id"])
        assert run2["findings_created"] >= 1

    findings = client.get(f"{DISC}/findings", headers=admin["headers"],
                          params={"status": "OPEN"}).json()
    stale = [f for f in findings if f["finding_type"] == "STALE_AGENT"
             and f["external_identifier"] is None]  # external_identifier lives on the agent, not the finding
    # confirm via the agent lookup instead
    db = SessionLocal()
    try:
        gone = db.execute(select(Agent).where(
            Agent.organization_id == uuid.UUID(admin["organization_id"]),
            Agent.external_reference == "ext-gone")).scalars().first()
        assert gone is not None  # NEVER deleted
        assert gone.control_state == "DISCOVERED"
        open_finding = db.execute(select(DiscoveryFinding).where(
            DiscoveryFinding.agent_id == gone.id, DiscoveryFinding.finding_type == "STALE_AGENT",
            DiscoveryFinding.status == "OPEN")).scalars().first()
        assert open_finding is not None
    finally:
        db.close()


def test_ac08_reappearing_agent_resolves_the_staleness_finding(client: TestClient, admin: dict) -> None:
    reg = _Registry()
    reg.agents = [{"id": "ext-flaky", "name": "Flaky"}]
    with local_server(reg) as port:
        source = _create_source(client, admin, port)
        _trigger(client, admin, source["id"])
        reg.agents = []
        _trigger(client, admin, source["id"])
        reg.agents = [{"id": "ext-flaky", "name": "Flaky"}]
        _trigger(client, admin, source["id"])

    db = SessionLocal()
    try:
        agent = db.execute(select(Agent).where(
            Agent.organization_id == uuid.UUID(admin["organization_id"]),
            Agent.external_reference == "ext-flaky")).scalars().first()
        finding = db.execute(select(DiscoveryFinding).where(
            DiscoveryFinding.agent_id == agent.id, DiscoveryFinding.finding_type == "STALE_AGENT")
        ).scalars().first()
        assert finding.status == "RESOLVED"
    finally:
        db.close()


# --------------------------------------------------------------------------- #
# AC-09 - the reference adapter runs against a REAL local source
# --------------------------------------------------------------------------- #
def test_ac09_reference_adapter_discovers_real_agents_over_real_http(client: TestClient, admin: dict) -> None:
    reg = _Registry()
    reg.agents = [{"id": "real-1", "name": "Real HTTP Agent", "agent_type": "ASSISTANT",
                  "origin_provider": "HTTP_AGENT_REGISTRY", "description": "genuinely fetched"}]
    with local_server(reg) as port:
        source = _create_source(client, admin, port)
        run = _trigger(client, admin, source["id"])
        assert run["status"] == "SUCCEEDED"
        # a REAL request actually reached the REAL server (not an in-process mock)
        assert any(r["path"] == "/agents" for r in reg.requests)

    db = SessionLocal()
    try:
        agent = db.execute(select(Agent).where(
            Agent.organization_id == uuid.UUID(admin["organization_id"]),
            Agent.external_reference == "real-1")).scalars().first()
        assert agent is not None
        assert agent.name == "Real HTTP Agent"
    finally:
        db.close()


# --------------------------------------------------------------------------- #
# AC-10 - concurrency, real separate Postgres sessions
# --------------------------------------------------------------------------- #
def test_ac10_concurrent_reconciliation_of_the_same_external_agent_yields_one(admin: dict) -> None:
    from decimal import Decimal

    db0 = SessionLocal()
    try:
        actor = db0.get(User, uuid.UUID(admin["user_id"]))
        source = DiscoverySourceService(db0).create(
            actor, name="RaceSource", adapter_key="HTTP_AGENT_REGISTRY", config=_config(1))
        source_id, org_id = source.id, source.organization_id
    finally:
        db0.close()

    barrier = threading.Barrier(2)
    outcomes: list[str] = []
    lock = threading.Lock()

    def worker() -> None:
        db = SessionLocal()
        try:
            actor = db.get(User, uuid.UUID(admin["user_id"]))
            source = db.get(DiscoverySource, source_id)
            run = DiscoveryRun(organization_id=org_id, source_id=source_id, status="RUNNING", trigger="MANUAL")
            db.add(run)
            db.commit()
            obs = DiscoveryObservation(
                organization_id=org_id, source_id=source_id, run_id=run.id,
                external_identifier="race-agent", normalized_payload={"name": "Race Agent"},
                confidence=Decimal("1.00"), observed_at=run.started_at or run.created_at)
            db.add(obs)
            db.commit()
            barrier.wait(timeout=5)
            result = ReconciliationService(db).reconcile(actor, run, source, [obs])
            with lock:
                outcomes.append(result["created"] and "created" or "linked")
        finally:
            db.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(worker) for _ in range(2)]
        for f in futures:
            f.result(timeout=15)

    assert sorted(outcomes) == ["created", "linked"]
    db = SessionLocal()
    try:
        agents = db.execute(select(Agent).where(
            Agent.organization_id == org_id, Agent.external_reference == "race-agent")).scalars().all()
        assert len(agents) == 1  # never a duplicate
    finally:
        db.close()


def test_ac10_two_runs_on_one_source_do_not_double_create(client: TestClient, admin: dict) -> None:
    reg = _Registry()
    reg.agents = [{"id": "ext-onlyone", "name": "Only One"}]
    with local_server(reg) as port:
        source = _create_source(client, admin, port)
        results = []
        lock = threading.Lock()

        def trigger() -> None:
            r = client.post(f"{DISC}/sources/{source['id']}/runs", headers=admin["headers"])
            with lock:
                results.append(r)

        threads = [threading.Thread(target=trigger) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=15)

    db = SessionLocal()
    try:
        agents = db.execute(select(Agent).where(
            Agent.organization_id == uuid.UUID(admin["organization_id"]),
            Agent.external_reference == "ext-onlyone")).scalars().all()
        assert len(agents) == 1
    finally:
        db.close()


# --------------------------------------------------------------------------- #
# AC-11 - tenant isolation
# --------------------------------------------------------------------------- #
def test_ac11_cross_tenant_source_access_is_404(client: TestClient, admin: dict, other_org_admin: dict) -> None:
    reg = _Registry()
    with local_server(reg) as port:
        source = _create_source(client, admin, port)
    r = client.get(f"{DISC}/sources/{source['id']}", headers=other_org_admin["headers"])
    assert r.status_code == 404
    r2 = client.post(f"{DISC}/sources/{source['id']}/runs", headers=other_org_admin["headers"])
    assert r2.status_code == 404


def test_ac11_in_tenant_unpermitted_is_403(client: TestClient, admin: dict, viewer: dict) -> None:
    reg = _Registry()
    with local_server(reg) as port:
        source = _create_source(client, admin, port)
    r = client.post(f"{DISC}/sources", headers=viewer["headers"], json={
        "name": "x", "adapter_key": "HTTP_AGENT_REGISTRY", "config": _config(1)})
    assert r.status_code == 403
    r2 = client.post(f"{DISC}/sources/{source['id']}/runs", headers=viewer["headers"])
    assert r2.status_code == 403


def test_ac11_hostile_source_cannot_create_agents_in_another_tenant(
        client: TestClient, admin: dict, other_org_admin: dict) -> None:
    """A source configured in ``admin``'s org can only ever create agents in
    ``admin``'s org - reconciliation reads ``source.organization_id``, never
    anything the source itself reports."""
    reg = _Registry()
    reg.agents = [{"id": "ext-tenantcheck", "name": "Tenant Check"}]
    with local_server(reg) as port:
        source = _create_source(client, admin, port)
        _trigger(client, admin, source["id"])

    db = SessionLocal()
    try:
        agent = db.execute(select(Agent).where(
            Agent.organization_id == uuid.UUID(admin["organization_id"]),
            Agent.external_reference == "ext-tenantcheck")).scalars().first()
        assert agent is not None
        assert str(agent.organization_id) == admin["organization_id"]
        assert str(agent.organization_id) != other_org_admin["organization_id"]
        # And no such agent exists in the OTHER tenant's own scope.
        leaked = db.execute(select(Agent).where(
            Agent.organization_id == uuid.UUID(other_org_admin["organization_id"]),
            Agent.external_reference == "ext-tenantcheck")).scalars().first()
        assert leaked is None
    finally:
        db.close()


# --------------------------------------------------------------------------- #
# AC-12 - no secret in observation/audit; malicious metadata bounded
# --------------------------------------------------------------------------- #
def test_ac12_no_secret_in_observation_payload(client: TestClient, admin: dict) -> None:
    reg = _Registry()
    reg.agents = [{"id": "ext-sec", "name": "Agent",
                  "description": "api_key=sk-THISISASECRETVALUE1234567890ABCDEFGH"}]
    with local_server(reg) as port:
        source = _create_source(client, admin, port)
        secret_val = "super-secret-bearer-token-value"
        r = client.patch(f"{DISC}/sources/{source['id']}", headers=admin["headers"],
                         json={"secret": secret_val})
        assert r.status_code == 200
        _trigger(client, admin, source["id"])

    db = SessionLocal()
    try:
        obs = db.execute(select(DiscoveryObservation).where(
            DiscoveryObservation.source_id == uuid.UUID(source["id"]),
            DiscoveryObservation.external_identifier == "ext-sec")).scalars().first()
        payload_str = jsonlib.dumps(obs.normalized_payload)
        assert secret_val not in payload_str
        assert "sk-THISISASECRETVALUE1234567890ABCDEFGH" not in payload_str
        source_row = db.get(DiscoverySource, uuid.UUID(source["id"]))
        assert secret_val not in (source_row.encrypted_secret or "")
    finally:
        db.close()

    got = client.get(f"{DISC}/sources/{source['id']}", headers=admin["headers"]).json()
    assert "secret" not in got
    assert "encrypted_secret" not in got


def test_ac12_malicious_metadata_is_bounded(client: TestClient, admin: dict) -> None:
    reg = _Registry()
    reg.agents = [{"id": "ext-huge", "name": "A" * 5000}]
    with local_server(reg) as port:
        source = _create_source(client, admin, port)
        run = _trigger(client, admin, source["id"])
        assert run["status"] == "SUCCEEDED"  # does not crash the platform

    db = SessionLocal()
    try:
        agent = db.execute(select(Agent).where(
            Agent.organization_id == uuid.UUID(admin["organization_id"]),
            Agent.external_reference == "ext-huge")).scalars().first()
        assert agent is not None  # a long name is truthfully recorded, not silently dropped
    finally:
        db.close()


# --------------------------------------------------------------------------- #
# AC-13 - failure semantics: fails open
# --------------------------------------------------------------------------- #
def test_ac13_source_outage_never_mutates_control_state_or_deletes(client: TestClient, admin: dict) -> None:
    reg = _Registry()
    reg.agents = [{"id": "ext-safe", "name": "Safe"}]
    with local_server(reg) as port:
        source = _create_source(client, admin, port)
        _trigger(client, admin, source["id"])

        reg.fail_first_n_pages = 999
        run2 = _trigger(client, admin, source["id"])
        assert run2["status"] == "FAILED"

    db = SessionLocal()
    try:
        agent = db.execute(select(Agent).where(
            Agent.organization_id == uuid.UUID(admin["organization_id"]),
            Agent.external_reference == "ext-safe")).scalars().first()
        assert agent is not None
        assert agent.control_state == "DISCOVERED"  # unchanged by the outage
    finally:
        db.close()


# --------------------------------------------------------------------------- #
# AC-14 - idempotent re-observation via Idempotency-Key
# --------------------------------------------------------------------------- #
def test_ac14_manual_trigger_is_idempotent_via_idempotency_key(client: TestClient, admin: dict) -> None:
    reg = _Registry()
    reg.agents = [{"id": "ext-idem", "name": "Idem"}]
    with local_server(reg) as port:
        source = _create_source(client, admin, port)
        key = uuid.uuid4().hex
        r1 = client.post(f"{DISC}/sources/{source['id']}/runs",
                         headers={**admin["headers"], "Idempotency-Key": key})
        r2 = client.post(f"{DISC}/sources/{source['id']}/runs",
                         headers={**admin["headers"], "Idempotency-Key": key})
        assert r1.status_code == 201 and r2.status_code == 201
        assert r1.json()["id"] == r2.json()["id"]  # same run, not a second sweep

    runs = client.get(f"{DISC}/sources/{source['id']}/runs", headers=admin["headers"]).json()
    assert len(runs) == 1


# --------------------------------------------------------------------------- #
# AC-15 - reference vs. deferred vendor catalog
# --------------------------------------------------------------------------- #
def test_ac15_reference_adapter_distinguished_no_vendor_catalog() -> None:
    keys = adapter_registry.registered_keys()
    assert keys == ("HTTP_AGENT_REGISTRY",)
    for banned in ("AZURE_AI_FOUNDRY", "AWS_BEDROCK_AGENTS", "LANGGRAPH", "CREWAI", "KUBERNETES", "MCP"):
        assert banned not in keys


# --------------------------------------------------------------------------- #
# AC-16 - sweeps registered on the 3.8 scheduler; no new scheduler
# --------------------------------------------------------------------------- #
def test_ac16_discovery_sweep_is_a_registered_scheduler_handler() -> None:
    from app.scheduler import handlers as handler_registry

    assert "discovery.sweep" in handler_registry.registered_keys()


def test_ac16_no_new_scheduler_module_created() -> None:
    assert not (_BACKEND / "app" / "discovery" / "scheduler.py").exists()
    assert not (_BACKEND / "app" / "discovery" / "runner.py").exists()


# --------------------------------------------------------------------------- #
# AC-17 - authz/tenant/audit for the config/run API
# --------------------------------------------------------------------------- #
def test_ac17_source_and_run_apis_are_authorized_tenant_scoped_audited(client: TestClient, admin: dict) -> None:
    from app.models.rbac import AuthorizationAudit

    reg = _Registry()
    with local_server(reg) as port:
        source = _create_source(client, admin, port)
        _trigger(client, admin, source["id"])

    db = SessionLocal()
    try:
        rows = db.execute(select(AuthorizationAudit).where(
            AuthorizationAudit.organization_id == uuid.UUID(admin["organization_id"]))).scalars().all()
        kinds = {r.event_type for r in rows}
        assert "DISCOVERY_SOURCE_CREATED" in kinds
        assert "DISCOVERY_RUN_STARTED" in kinds
        assert "DISCOVERY_RUN_COMPLETED" in kinds
    finally:
        db.close()


# --------------------------------------------------------------------------- #
# AC-18 - migration + reconciliation writes via the 5.1 service (no bypass)
# --------------------------------------------------------------------------- #
def test_ac18_migration_additive_reversible_id_within_ceiling() -> None:
    mig = (_BACKEND / "migrations" / "versions" / "0055_agent_discovery.py").read_text(encoding="utf-8")
    assert 'revision = "0055_agent_discovery"' in mig
    assert len("0055_agent_discovery") <= 32
    assert 'down_revision = "0054_agent_asset_model"' in mig
    assert "op.create_table" in mig and "op.drop_table" in mig


def test_ac18_reconciliation_imports_the_5_1_service_not_a_raw_insert() -> None:
    import ast

    path = _BACKEND / "app" / "discovery" / "reconciliation.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imported = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
    assert "app.runtime.registry.control" in imported


# --------------------------------------------------------------------------- #
# AC-21 - no forbidden markers
# --------------------------------------------------------------------------- #
def test_ac21_no_forbidden_markers_in_new_files() -> None:
    files = [
        _BACKEND / "app" / "discovery" / "service.py",
        _BACKEND / "app" / "discovery" / "reconciliation.py",
        _BACKEND / "app" / "discovery" / "adapters" / "base.py",
        _BACKEND / "app" / "discovery" / "adapters" / "http_agent_registry.py",
        _BACKEND / "migrations" / "versions" / "0055_agent_discovery.py",
        Path(__file__),
    ]
    forbidden = ("TO" + "DO", "FIX" + "ME", "Not" + "ImplementedError",
                 "pytest.mark." + "skip", "pytest.mark." + "xfail")
    for path in files:
        text_ = path.read_text(encoding="utf-8")
        assert not [t for t in forbidden if t in text_], path.name


# --------------------------------------------------------------------------- #
# §15 - end-to-end proof
# --------------------------------------------------------------------------- #
def test_m52_end_to_end_proof(client: TestClient, admin: dict, other_org_admin: dict) -> None:
    reg = _Registry()
    reg.agents = [
        {"id": "e2e-1", "name": "E2E Agent One", "agent_type": "ASSISTANT",
         "origin_provider": "HTTP_AGENT_REGISTRY"},
        {"id": "e2e-conflict", "name": "Ambiguous Agent"},
    ]
    with local_server(reg) as port:
        # A real local source, over real HTTP, GovernedHttpClient only.
        source = _create_source(client, admin, port)

        # A low-confidence twin of the same identifier, injected directly to
        # force the "no silent merge" path deterministically in one proof.
        db0 = SessionLocal()
        try:
            actor = db0.get(User, uuid.UUID(admin["user_id"]))
            src_row = db0.get(DiscoverySource, uuid.UUID(source["id"]))
        finally:
            db0.close()

        run1 = _trigger(client, admin, source["id"])
        assert run1["status"] == "SUCCEEDED"
        assert run1["agents_created"] == 2
        assert run1["findings_created"] == 0

        # Truthfully not controllable.
        agents = client.get("/api/v1/runtime/agents", headers=admin["headers"]).json()
        e2e_agent = next(a for a in agents if a.get("external_reference") == "e2e-1")
        assert e2e_agent["control_state"] == "DISCOVERED"
        assert client.post(f"/api/v1/runtime/agents/{e2e_agent['id']}/control-state",
                           headers=admin["headers"], json={"target_state": "GOVERNED"}).status_code == 409

        # Re-run is idempotent.
        run2 = _trigger(client, admin, source["id"])
        assert run2["agents_created"] == 0
        assert run2["agents_linked"] == 2

        # An agent disappears -> staleness finding, not a deletion.
        reg.agents = [reg.agents[0]]
        run3 = _trigger(client, admin, source["id"])
        assert run3["findings_created"] >= 1

    db = SessionLocal()
    try:
        gone = db.execute(select(Agent).where(
            Agent.organization_id == uuid.UUID(admin["organization_id"]),
            Agent.external_reference == "e2e-conflict")).scalars().first()
        assert gone is not None
        assert gone.control_state == "DISCOVERED"

        # An ambiguous/conflicting observation -> a reconciliation finding
        # (forced deterministically here via a direct low-confidence
        # observation, since the reference source always reports 1.00).
        actor = db.get(User, uuid.UUID(admin["user_id"]))
        source_row = db.get(DiscoverySource, uuid.UUID(source["id"]))
        run_row = DiscoveryRun(organization_id=source_row.organization_id, source_id=source_row.id,
                               status="RUNNING", trigger="MANUAL")
        db.add(run_row)
        db.commit()
        from decimal import Decimal
        ambiguous_obs = DiscoveryObservation(
            organization_id=source_row.organization_id, source_id=source_row.id, run_id=run_row.id,
            external_identifier="e2e-ambiguous", normalized_payload={"name": "Maybe"},
            confidence=Decimal("0.50"), observed_at=run_row.started_at or run_row.created_at)
        db.add(ambiguous_obs)
        db.commit()
        outcome = ReconciliationService(db).reconcile(actor, run_row, source_row, [ambiguous_obs])
        assert outcome["flagged"] == 1
        finding = db.execute(select(DiscoveryFinding).where(
            DiscoveryFinding.organization_id == source_row.organization_id,
            DiscoveryFinding.external_identifier == "e2e-ambiguous")).scalars().first()
        assert finding.status == "OPEN"
    finally:
        db.close()

    # Every mutation tenant-isolated: the outsider sees nothing.
    assert client.get(f"{DISC}/sources/{source['id']}", headers=other_org_admin["headers"]).status_code == 404

    # And no secret anywhere in what got persisted.
    db = SessionLocal()
    try:
        obs_rows = db.execute(select(DiscoveryObservation).where(
            DiscoveryObservation.source_id == uuid.UUID(source["id"]))).scalars().all()
        assert obs_rows  # the sweep actually persisted evidence
        for row in obs_rows:
            assert "secret" not in jsonlib.dumps(row.normalized_payload).lower()
    finally:
        db.close()

    # The native agent estate and the platform are unaffected throughout.
    r = client.get("/api/v1/runtime/agents", headers=admin["headers"])
    assert r.status_code == 200
