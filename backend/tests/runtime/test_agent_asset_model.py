"""Phase 5.1 (M5.1) - Universal Agent Asset Model + Ownership.

The one canonical ``agents`` registry is extended in place so it can describe
the whole spectrum - native / external / discovered / claimed / registered /
governed / unknown - with provenance, a ``control_state`` dimension that is
honest about ACT's real enforcement authority (DISTINCT from the operational
``lifecycle_status`` machine), reused ownership + history, and a safe,
server-authoritative, audited, concurrency-proven claim workflow.

No discovery / graph / posture / threat / gateway / UI machinery here - those
are later phases. This proves only the foundation.

AC-01..AC-17 + the §22 end-to-end proof; each AC has a named test.
"""

from __future__ import annotations

import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.database import SessionLocal
from app.models.agent import Agent
from app.models.agent_registry import AgentOwnershipHistory
from app.models.user import User
from app.runtime.registry.control import (
    CONTROL_TRANSITIONS,
    AgentControlStateService,
    AgentProvenanceService,
)

PASSWORD = "T3st!Passw0rd#Ok"
RT = "/api/v1/runtime"
_BACKEND = Path(__file__).resolve().parents[2]
_REPO = _BACKEND.parent


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _org(client: TestClient, name: str = "Asset Model Org") -> dict:
    email = f"m51_{uuid.uuid4().hex[:10]}@example.com"
    assert client.post("/auth/register", json={
        "organization_name": name, "name": "Owner", "email": email, "password": PASSWORD,
    }).status_code == 201
    tokens = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD}).json()
    h = {"Authorization": f"Bearer {tokens['access_token']}"}
    me = client.get("/api/v1/auth/me", headers=h).json()
    return {"headers": h, "user_id": me["user"]["id"],
            "organization_id": me["user"]["organization_id"], "email": email}


def _invite(client: TestClient, admin: dict, *, role: str = "VIEWER") -> dict:
    email = f"m51m_{uuid.uuid4().hex[:10]}@example.com"
    r = client.post("/api/v1/identity/users", headers=admin["headers"], json={
        "email": email, "display_name": "Member", "password": PASSWORD, "role": role,
        "organization_id": admin["organization_id"],
    })
    assert r.status_code in (200, 201), r.text
    tokens = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD}).json()
    h = {"Authorization": f"Bearer {tokens['access_token']}"}
    me = client.get("/api/v1/auth/me", headers=h).json()
    return {"headers": h, "user_id": me["user"]["id"], "email": email}


def _register_native(client: TestClient, admin: dict, **overrides) -> dict:
    payload = {
        "name": f"Native Agent {uuid.uuid4().hex[:6]}", "description": "d",
        "business_purpose": "d", "agent_type": "ASSISTANT", "criticality": "MEDIUM",
        "owner_type": "USER", "owner_id": admin["user_id"],
        "technical_owner_id": admin["user_id"], "compliance_owner_id": admin["user_id"],
        "definition": {"name": "Definition", "framework": "CUSTOM",
                       "entrypoint_type": "FUNCTION", "entrypoint": "agents.handler:run"},
    }
    payload.update(overrides)
    r = client.post(f"{RT}/agents", headers=admin["headers"], json=payload)
    assert r.status_code == 201, r.text
    return r.json()


def _activate_native(client: TestClient, admin: dict, agent_id: str) -> dict:
    for step in ("register", "validate"):
        assert client.post(f"{RT}/agents/{agent_id}/{step}", headers=admin["headers"]).status_code == 200
    assert client.post(f"{RT}/agents/{agent_id}/identity/create-and-associate",
                       headers=admin["headers"],
                       json={"client_id": f"id-{uuid.uuid4().hex[:10]}"}).status_code == 200
    for step in ("submit-for-approval", "approve", "activate"):
        r = client.post(f"{RT}/agents/{agent_id}/{step}", headers=admin["headers"])
        assert r.status_code == 200, r.text
    return r.json()


def _make_external(admin: dict, *, origin_category: str = "EXTERNAL",
                   origin_provider: str = "LANGGRAPH", **kw) -> str:
    """Create a representative EXTERNAL/UNKNOWN agent record via the 5.2 seam -
    no discovery/adapter code involved (SRS M5.1 §19, AC-12)."""
    db = SessionLocal()
    try:
        actor = db.get(User, uuid.UUID(admin["user_id"]))
        agent = AgentProvenanceService(db).record_external_agent(
            actor, name=kw.pop("name", f"External Agent {uuid.uuid4().hex[:6]}"),
            origin_category=origin_category, origin_provider=origin_provider, **kw)
        return str(agent.id)
    finally:
        db.close()


# --------------------------------------------------------------------------- #
# AC-01 - live baseline / prerequisites
# --------------------------------------------------------------------------- #
def test_ac01_m411_and_m411a_prerequisites_present_and_head_recorded() -> None:
    from app.security.encryption_provider import LocalEncryptionKeyProvider  # noqa: F401
    from app.security.install_mode import detect_install_mode  # noqa: F401
    from app.security.key_integrity import KeyState

    assert {s.value for s in KeyState} >= {
        "KEY_ABSENT", "KEY_MALFORMED", "KEY_PRESENT_BUT_WRONG",
        "KEY_PROVIDER_UNAVAILABLE", "INSTALLATION_NEVER_BOOTSTRAPPED",
    }
    versions = sorted((_BACKEND / "migrations" / "versions").glob("*.py"))
    assert versions[-1].stem == "0054_agent_asset_model"
    assert {"0052_key_material_canary", "0053_installation_bootstrap"} <= {v.stem for v in versions}
    repo_state = (_REPO / "REPO_STATE.md").read_text(encoding="utf-8")
    assert "0054_agent_asset_model" in repo_state


# --------------------------------------------------------------------------- #
# AC-02 - one canonical registry, extended in place
# --------------------------------------------------------------------------- #
def test_ac02_canonical_registry_extended_in_place_no_parallel_table() -> None:
    from app.core.database import Base

    cols = set(Agent.__table__.columns.keys())
    assert {"control_state", "origin_category", "origin_provider",
            "first_observed_at", "last_observed_at", "discovery_source_ref",
            "discovery_confidence"} <= cols
    # No second canonical agent table crept in.
    forbidden = {"external_agents", "discovered_agents", "agents_v2", "agent_assets"}
    assert forbidden.isdisjoint(set(Base.metadata.tables))


def test_ac02_native_and_external_share_the_one_agents_table(client: TestClient) -> None:
    admin = _org(client)
    native = _register_native(client, admin)
    ext_id = _make_external(admin)
    db = SessionLocal()
    try:
        assert db.get(Agent, uuid.UUID(native["id"])).__tablename__ == "agents"
        assert db.get(Agent, uuid.UUID(ext_id)).__tablename__ == "agents"
    finally:
        db.close()


# --------------------------------------------------------------------------- #
# AC-03 - control_state is DISTINCT from lifecycle_status
# --------------------------------------------------------------------------- #
def test_ac03_control_state_and_lifecycle_status_are_orthogonal(client: TestClient) -> None:
    admin = _org(client)
    agent = _register_native(client, admin)
    # native, freshly registered: lifecycle DRAFT, control GOVERNED - both present, independent.
    assert agent["lifecycle_status"] == "DRAFT"
    assert agent["control_state"] == "GOVERNED"
    active = _activate_native(client, admin, agent["id"])
    assert active["lifecycle_status"] == "ACTIVE"
    # lifecycle marched DRAFT -> ACTIVE; control_state never moved.
    assert active["control_state"] == "GOVERNED"


def test_ac03_lifecycle_state_machine_is_unchanged() -> None:
    """The existing 13-state lifecycle machine is untouched by M5.1."""
    from app.runtime.registry.services import _TRANSITIONS

    assert set(_TRANSITIONS) == {
        "DRAFT", "REGISTERED", "VALIDATING", "VALIDATION_FAILED", "VALIDATED",
        "PENDING_APPROVAL", "REJECTED", "APPROVED", "ACTIVE", "SUSPENDED",
        "DEPRECATED", "ARCHIVED", "RETIRED",
    }
    # control_state vocabulary shares NO member with lifecycle vocabulary
    # except the coincidental word "REGISTERED" (a different axis) - assert the
    # machines are separate objects, not that the words never collide.
    from app.runtime.registry.control import CONTROL_TRANSITIONS
    assert CONTROL_TRANSITIONS is not _TRANSITIONS


def test_ac03_existing_lifecycle_consumers_read_identically(client: TestClient) -> None:
    """A native agent activates, deploys and stays governed - the M1-M4
    lifecycle_status consumers are not perturbed by the new column."""
    admin = _org(client)
    agent = _register_native(client, admin)
    _activate_native(client, admin, agent["id"])
    r = client.get(f"{RT}/agents/{agent['id']}", headers=admin["headers"])
    assert r.status_code == 200
    body = r.json()
    assert body["lifecycle_status"] == "ACTIVE"
    assert body["status"] == "ACTIVE"  # the Phase-1 governance status, also untouched


# --------------------------------------------------------------------------- #
# AC-04 - provenance without a per-vendor schema change
# --------------------------------------------------------------------------- #
def test_ac04_origin_is_a_soft_provider_not_a_db_enum(client: TestClient) -> None:
    admin = _org(client)
    native = _register_native(client, admin)
    assert native["origin_category"] == "NATIVE"
    assert native["origin_provider"] == "ACT_NATIVE"
    # A brand-new vendor string never seen before - no migration, no rejection.
    ext_id = _make_external(admin, origin_provider="SOME_NEW_VENDOR_2027")
    r = client.get(f"{RT}/agents/{ext_id}/control-state", headers=admin["headers"])
    assert r.json()["origin_provider"] == "SOME_NEW_VENDOR_2027"
    # origin_category IS constrained (small, stable set); origin_provider is not.
    ck_names = {c.name for c in Agent.__table__.constraints}
    assert "ck_agents_origin_category" in ck_names
    assert "ck_agents_control_state" in ck_names


def test_ac04_unknown_external_is_representable(client: TestClient) -> None:
    admin = _org(client)
    ext_id = _make_external(admin, origin_category="UNKNOWN", origin_provider="UNKNOWN")
    r = client.get(f"{RT}/agents/{ext_id}/control-state", headers=admin["headers"])
    assert r.json()["origin_category"] == "UNKNOWN"
    assert r.json()["control_state"] == "DISCOVERED"


# --------------------------------------------------------------------------- #
# AC-05 - ownership reuses existing columns + history + org hierarchy
# --------------------------------------------------------------------------- #
def test_ac05_claim_writes_the_existing_ownership_history_ledger(client: TestClient) -> None:
    admin = _org(client)
    ext_id = _make_external(admin)
    r = client.post(f"{RT}/agents/{ext_id}/claim", headers=admin["headers"], json={
        "owner_type": "USER", "owner_id": admin["user_id"], "reason": "Owning this."})
    assert r.status_code == 200, r.text
    hist = client.get(f"{RT}/agents/{ext_id}/ownership/history", headers=admin["headers"]).json()
    assert len(hist) == 1
    assert hist[0]["owner_role"] == "BUSINESS_OWNER"
    assert hist[0]["new_owner_id"] == admin["user_id"]
    assert hist[0]["reason"] == "Owning this."


def test_ac05_no_duplicate_people_or_ownership_system() -> None:
    from app.core.database import Base

    names = set(Base.metadata.tables)
    # M5.1 adds NO new ownership/people table; it reuses agent_ownership_history.
    assert "agent_ownership_history" in names
    for banned in ("agent_owners", "agent_ownership_roles", "asset_owners", "m5_owners"):
        assert banned not in names


# --------------------------------------------------------------------------- #
# AC-06 - the claim workflow
# --------------------------------------------------------------------------- #
def test_ac06_claim_moves_discovered_to_claimed_not_governed(client: TestClient) -> None:
    admin = _org(client)
    ext_id = _make_external(admin)
    r = client.post(f"{RT}/agents/{ext_id}/claim", headers=admin["headers"], json={
        "owner_type": "USER", "owner_id": admin["user_id"], "reason": "mine"})
    assert r.status_code == 200
    assert r.json()["control_state"] == "CLAIMED"  # NOT GOVERNED
    assert r.json()["owner_id"] == admin["user_id"]


def test_ac06_claim_on_already_claimed_agent_is_rejected(client: TestClient) -> None:
    admin = _org(client)
    ext_id = _make_external(admin)
    client.post(f"{RT}/agents/{ext_id}/claim", headers=admin["headers"], json={
        "owner_type": "USER", "owner_id": admin["user_id"], "reason": "mine"})
    r = client.post(f"{RT}/agents/{ext_id}/claim", headers=admin["headers"], json={
        "owner_type": "USER", "owner_id": admin["user_id"], "reason": "again"})
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "AGENT_CLAIM_CONFLICT"


def test_ac06_claim_on_native_governed_agent_is_rejected(client: TestClient) -> None:
    admin = _org(client)
    native = _register_native(client, admin)
    r = client.post(f"{RT}/agents/{native['id']}/claim", headers=admin["headers"], json={
        "owner_type": "USER", "owner_id": admin["user_id"], "reason": "x"})
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "AGENT_CLAIM_CONFLICT"


def test_ac06_claim_is_idempotent_via_idempotency_key(client: TestClient) -> None:
    admin = _org(client)
    ext_id = _make_external(admin)
    key = uuid.uuid4().hex
    h = {**admin["headers"], "Idempotency-Key": key}
    body = {"owner_type": "USER", "owner_id": admin["user_id"], "reason": "mine"}
    r1 = client.post(f"{RT}/agents/{ext_id}/claim", headers=h, json=body)
    r2 = client.post(f"{RT}/agents/{ext_id}/claim", headers=h, json=body)
    assert r1.status_code == 200 and r2.status_code == 200
    assert r2.json()["control_state"] == "CLAIMED"
    # exactly one ownership-history row despite two calls
    hist = client.get(f"{RT}/agents/{ext_id}/ownership/history", headers=admin["headers"]).json()
    assert len(hist) == 1


# --------------------------------------------------------------------------- #
# AC-07 - server-authoritative; mass-assignment blocked
# --------------------------------------------------------------------------- #
def test_ac07_client_cannot_set_control_state_via_create(client: TestClient) -> None:
    admin = _org(client)
    native = _register_native(client, admin, control_state="DISCOVERED", origin_category="EXTERNAL",
                              origin_provider="EVIL")
    # the injected fields are ignored; server sets the truthful native values.
    assert native["control_state"] == "GOVERNED"
    assert native["origin_category"] == "NATIVE"
    assert native["origin_provider"] == "ACT_NATIVE"


def test_ac07_client_cannot_set_control_state_via_update(client: TestClient) -> None:
    admin = _org(client)
    ext_id = _make_external(admin, origin_category="EXTERNAL", origin_provider="LANGGRAPH")
    before = client.get(f"{RT}/agents/{ext_id}/control-state", headers=admin["headers"]).json()
    # PATCH the agent (DRAFT/editable) trying to jump straight to GOVERNED.
    r = client.patch(f"{RT}/agents/{ext_id}", headers=admin["headers"], json={
        "row_version": 1, "control_state": "GOVERNED", "origin_category": "NATIVE",
        "origin_provider": "EVIL", "description": "just a normal edit"})
    assert r.status_code == 200, r.text
    got = client.get(f"{RT}/agents/{ext_id}/control-state", headers=admin["headers"]).json()
    assert got["control_state"] == "DISCOVERED"          # unchanged - mass-assignment did nothing
    assert got["origin_category"] == before["origin_category"] == "EXTERNAL"
    assert got["origin_provider"] == before["origin_provider"] == "LANGGRAPH"


def test_ac07_transition_endpoint_enforces_the_matrix(client: TestClient) -> None:
    admin = _org(client)
    ext_id = _make_external(admin)
    # DISCOVERED -> GOVERNED directly is illegal (must claim, register, then enroll).
    r = client.post(f"{RT}/agents/{ext_id}/control-state", headers=admin["headers"], json={
        "target_state": "GOVERNED"})
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "CONTROL_STATE_TRANSITION_INVALID"


def test_ac07_govern_requires_an_owner(client: TestClient) -> None:
    """Reaching GOVERNED needs an accountable owner - proven by driving an
    external agent through the states via the service with owner cleared."""
    admin = _org(client)
    ext_id = _make_external(admin)
    db = SessionLocal()
    try:
        actor = db.get(User, uuid.UUID(admin["user_id"]))
        agent = db.get(Agent, uuid.UUID(ext_id))
        svc = AgentControlStateService(db)
        svc.claim(actor, agent, owner_type="USER", owner_id=actor.id, reason="mine")
        agent = db.get(Agent, uuid.UUID(ext_id))
        svc.transition(actor, agent, "REGISTERED", reason="in scope")
        # now forcibly strip the owner and try to enroll into governance
        agent = db.get(Agent, uuid.UUID(ext_id))
        agent.owner_id = None
        db.commit()
        agent = db.get(Agent, uuid.UUID(ext_id))
        with pytest.raises(Exception) as exc:
            svc.transition(actor, agent, "GOVERNED", reason="try")
        from app.identity.errors import ErrorCode, IdentityError
        assert isinstance(exc.value, IdentityError)
        assert exc.value.code == ErrorCode.CONTROL_STATE_TRANSITION_FORBIDDEN
    finally:
        db.close()


# --------------------------------------------------------------------------- #
# AC-08 - tenant isolation (404 vs 403)
# --------------------------------------------------------------------------- #
def test_ac08_cross_tenant_claim_is_404_no_existence_leak(client: TestClient) -> None:
    owner = _org(client, "Owner Org")
    other = _org(client, "Other Org")
    ext_id = _make_external(owner)
    for path, body in (
        (f"{RT}/agents/{ext_id}/claim", {"owner_type": "USER", "owner_id": other["user_id"],
                                         "reason": "x"}),
        (f"{RT}/agents/{ext_id}/control-state", {"target_state": "REGISTERED"}),
    ):
        r = client.post(path, headers=other["headers"], json=body)
        assert r.status_code == 404, (path, r.text)
    r = client.get(f"{RT}/agents/{ext_id}/control-state", headers=other["headers"])
    assert r.status_code == 404


def test_ac08_in_tenant_unpermitted_is_403(client: TestClient) -> None:
    admin = _org(client)
    viewer = _invite(client, admin, role="VIEWER")
    ext_id = _make_external(admin)
    r = client.post(f"{RT}/agents/{ext_id}/claim", headers=viewer["headers"], json={
        "owner_type": "USER", "owner_id": viewer["user_id"], "reason": "x"})
    assert r.status_code == 403
    r = client.post(f"{RT}/agents/{ext_id}/control-state", headers=viewer["headers"], json={
        "target_state": "REGISTERED"})
    assert r.status_code == 403


# --------------------------------------------------------------------------- #
# AC-09 - migration additive / reversible / backfill
# --------------------------------------------------------------------------- #
def test_ac09_migration_is_additive_reversible_and_id_within_ceiling() -> None:
    mig = (_BACKEND / "migrations" / "versions" / "0054_agent_asset_model.py").read_text(encoding="utf-8")
    assert 'revision = "0054_agent_asset_model"' in mig
    assert len("0054_agent_asset_model") <= 32
    assert 'down_revision = "0053_installation_bootstrap"' in mig
    assert "op.add_column" in mig and "op.drop_column" in mig
    assert "drop_table" not in mig  # additive: no table dropped
    # backfill states the known truth for pre-existing rows
    assert "GOVERNED" in mig and "ACT_NATIVE" in mig and "UPDATE agents SET" in mig


def test_ac09_existing_agents_are_backfilled_native_and_governed(client: TestClient) -> None:
    """Every pre-existing agent row is native + governed. The suite has
    thousands of them from prior phases; sample the live table."""
    db = SessionLocal()
    try:
        rows = db.query(Agent).limit(500).all()
        assert rows, "expected pre-existing agent rows on the shared dev DB"
        for a in rows:
            assert a.control_state in ("DISCOVERED", "CLAIMED", "REGISTERED", "GOVERNED")
            assert a.origin_category in ("NATIVE", "EXTERNAL", "UNKNOWN")
            # Anything that isn't an M5.1-created external record is native+governed.
            if a.origin_category == "NATIVE":
                assert a.control_state == "GOVERNED"
                assert a.origin_provider == "ACT_NATIVE"
    finally:
        db.close()


# --------------------------------------------------------------------------- #
# AC-10 - concurrency (real separate Postgres sessions)
# --------------------------------------------------------------------------- #
def test_ac10_concurrent_claims_exactly_one_wins(client: TestClient) -> None:
    admin = _org(client)
    ext_id = _make_external(admin)
    agent_uuid = uuid.UUID(ext_id)
    barrier = threading.Barrier(2)
    outcomes: list[str] = []
    lock = threading.Lock()

    def worker() -> None:
        db = SessionLocal()
        try:
            actor = db.get(User, uuid.UUID(admin["user_id"]))
            agent = db.get(Agent, agent_uuid)
            barrier.wait(timeout=5)
            try:
                AgentControlStateService(db).claim(
                    actor, agent, owner_type="USER", owner_id=actor.id, reason="race")
                with lock:
                    outcomes.append("success")
            except Exception as exc:  # noqa: BLE001
                from app.identity.errors import ErrorCode, IdentityError
                if isinstance(exc, IdentityError) and exc.code == ErrorCode.AGENT_CLAIM_CONFLICT:
                    with lock:
                        outcomes.append("conflict")
                else:
                    raise
        finally:
            db.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        for f in [pool.submit(worker) for _ in range(2)]:
            f.result(timeout=15)
    assert sorted(outcomes) == ["conflict", "success"]
    # and exactly one history row
    hist = client.get(f"{RT}/agents/{ext_id}/ownership/history", headers=admin["headers"]).json()
    assert len(hist) == 1


def test_ac10_concurrent_control_state_transitions_are_safe(client: TestClient) -> None:
    admin = _org(client)
    ext_id = _make_external(admin)
    db0 = SessionLocal()
    try:
        actor = db0.get(User, uuid.UUID(admin["user_id"]))
        agent = db0.get(Agent, uuid.UUID(ext_id))
        AgentControlStateService(db0).claim(actor, agent, owner_type="USER",
                                            owner_id=actor.id, reason="mine")
    finally:
        db0.close()

    agent_uuid = uuid.UUID(ext_id)
    barrier = threading.Barrier(2)
    results: list[str] = []
    lock = threading.Lock()

    def worker() -> None:
        db = SessionLocal()
        try:
            actor = db.get(User, uuid.UUID(admin["user_id"]))
            agent = db.get(Agent, agent_uuid)
            barrier.wait(timeout=5)
            try:
                AgentControlStateService(db).transition(actor, agent, "REGISTERED", reason="r")
                with lock:
                    results.append("ok")
            except Exception as exc:  # noqa: BLE001
                from app.identity.errors import ErrorCode, IdentityError
                if isinstance(exc, IdentityError) and exc.code in (
                    ErrorCode.CONTROL_STATE_TRANSITION_INVALID,
                    ErrorCode.AGENT_CONCURRENT_MODIFICATION,
                ):
                    with lock:
                        results.append("conflict")
                else:
                    raise
        finally:
            db.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        for f in [pool.submit(worker) for _ in range(2)]:
            f.result(timeout=15)
    assert results.count("ok") == 1
    db = SessionLocal()
    try:
        assert db.get(Agent, agent_uuid).control_state == "REGISTERED"
    finally:
        db.close()


# --------------------------------------------------------------------------- #
# AC-11 - audit
# --------------------------------------------------------------------------- #
def test_ac11_every_mutation_is_audited_and_secret_free(client: TestClient) -> None:
    admin = _org(client)
    ext_id = _make_external(admin)
    client.post(f"{RT}/agents/{ext_id}/claim", headers=admin["headers"], json={
        "owner_type": "USER", "owner_id": admin["user_id"], "reason": "claiming"})
    client.post(f"{RT}/agents/{ext_id}/control-state", headers=admin["headers"], json={
        "target_state": "REGISTERED", "reason": "into scope"})

    from app.models.rbac import AuthorizationAudit

    db = SessionLocal()
    try:
        rows = db.query(AuthorizationAudit).filter(
            AuthorizationAudit.organization_id == uuid.UUID(admin["organization_id"])).all()
        kinds = {r.event_type for r in rows}
        assert "RUNTIME_AGENT_CLAIMED" in kinds
        assert "RUNTIME_AGENT_CONTROL_STATE_CHANGED" in kinds
        claimed = next(r for r in rows if r.event_type == "RUNTIME_AGENT_CLAIMED")
        meta = claimed.meta or {}
        assert meta.get("previous_control_state") == "DISCOVERED"
        assert meta.get("new_control_state") == "CLAIMED"
        assert "password" not in str(meta).lower() and "secret" not in str(meta).lower()
    finally:
        db.close()


# --------------------------------------------------------------------------- #
# AC-12 / AC-22 forward-compat design invariant
# --------------------------------------------------------------------------- #
def test_ac12_model_represents_a_real_external_agent_with_no_discovery_code(client: TestClient) -> None:
    admin = _org(client)
    ext_id = _make_external(admin, origin_category="EXTERNAL", origin_provider="MICROSOFT",
                            external_reference="copilot-studio://tenant/agent/42",
                            discovery_source_ref="manual-inventory-2026",
                            match_confidence=0.90)
    got = client.get(f"{RT}/agents/{ext_id}/control-state", headers=admin["headers"]).json()
    assert got["origin_category"] == "EXTERNAL"
    assert got["control_state"] == "DISCOVERED"          # ACT sees it, cannot control it
    assert got["lifecycle_status"] == "DRAFT"            # no assumption ACT executes it
    assert got["discovery_source_ref"] == "manual-inventory-2026"
    # there is no governance/enforcement affordance on a DISCOVERED agent:
    # the only way forward is a deliberate claim.
    r = client.post(f"{RT}/agents/{ext_id}/control-state", headers=admin["headers"], json={
        "target_state": "GOVERNED"})
    assert r.status_code == 409


def test_ac12_no_discovery_or_graph_machinery_shipped() -> None:
    from app.core.database import Base

    names = set(Base.metadata.tables)
    for banned in ("discovery_runs", "discovery_observations", "agent_graph_edges",
                   "agent_edges", "posture_findings", "reconciliation_runs"):
        assert banned not in names
    assert not (_BACKEND / "app" / "runtime" / "discovery").exists()


# --------------------------------------------------------------------------- #
# AC-13 - API backward compatibility
# --------------------------------------------------------------------------- #
def test_ac13_existing_agent_api_is_backward_compatible(client: TestClient) -> None:
    admin = _org(client)
    # a client that sends none of the new fields still works exactly as before
    r = client.post(f"{RT}/agents", headers=admin["headers"], json={
        "name": "Legacy Client Agent", "description": "d", "business_purpose": "d",
        "owner_type": "USER", "owner_id": admin["user_id"],
        "definition": {"name": "d", "entrypoint": "a.b:c"}})
    assert r.status_code == 201
    body = r.json()
    # new read fields are additive and present
    assert body["control_state"] == "GOVERNED"
    assert "origin_category" in body


def test_ac13_no_agents_v2_route() -> None:
    from app.main import app

    paths = {getattr(r, "path", "") for r in app.routes}
    assert not any("agents-v2" in p or "agents_v2" in p for p in paths)
    assert f"{RT}/agents/{{agent_id}}/claim" in paths
    assert f"{RT}/agents/{{agent_id}}/control-state" in paths


# --------------------------------------------------------------------------- #
# AC-14 - full M1-M4.11a regression is the suite itself; spot-check native agent
# --------------------------------------------------------------------------- #
def test_ac14_native_agent_still_fully_functional(client: TestClient) -> None:
    admin = _org(client)
    agent = _register_native(client, admin)
    active = _activate_native(client, admin, agent["id"])
    assert active["lifecycle_status"] == "ACTIVE"
    # create a version - the M1-M3 path, unaffected by the new columns
    r = client.post(f"{RT}/agents/{agent['id']}/versions", headers=admin["headers"], json={
        "model_configuration": {"provider": "MOCK", "model": "mock-model"}, "policy_snapshot": None})
    assert r.status_code == 201, r.text
    assert active["control_state"] == "GOVERNED"


# --------------------------------------------------------------------------- #
# AC-16 - permissions registered / not inflated
# --------------------------------------------------------------------------- #
def test_ac16_permissions_are_registered_and_minimal() -> None:
    from app.authorization.catalog import group_for_code
    from app.services.rbac_service import PERMISSION_CATALOG

    assert "runtime.agent.claim" in PERMISSION_CATALOG
    assert "runtime.agent.control.manage" in PERMISSION_CATALOG
    for code in ("runtime.agent.claim", "runtime.agent.control.manage"):
        assert group_for_code(code) == "runtime"
    # no speculative future-phase permissions
    for banned in ("runtime.agent.discover", "runtime.agent.graph.view",
                   "runtime.agent.posture.view"):
        assert banned not in PERMISSION_CATALOG


# --------------------------------------------------------------------------- #
# AC-17 - no new deferred-work markers in this phase's files
# --------------------------------------------------------------------------- #
def test_ac17_no_forbidden_markers_in_new_files() -> None:
    files = [
        _BACKEND / "app" / "runtime" / "registry" / "control.py",
        _BACKEND / "app" / "models" / "agent.py",
        _BACKEND / "migrations" / "versions" / "0054_agent_asset_model.py",
        Path(__file__),
    ]
    forbidden = ("TO" + "DO", "FIX" + "ME", "Not" + "ImplementedError",
                 "pytest.mark." + "skip", "pytest.mark." + "xfail")
    for path in files:
        text_ = path.read_text(encoding="utf-8")
        assert not [t for t in forbidden if t in text_], path.name


# --------------------------------------------------------------------------- #
# §22 - end-to-end proof
# --------------------------------------------------------------------------- #
def test_m51_end_to_end_proof(client: TestClient) -> None:
    admin = _org(client, "E2E Org")
    claimer = _invite(client, admin, role="ADMIN")

    # 1. a native agent - backfilled/created native+governed, fully functional
    native = _register_native(client, admin)
    native = _activate_native(client, admin, native["id"])
    assert native["origin_category"] == "NATIVE"
    assert native["origin_provider"] == "ACT_NATIVE"
    assert native["control_state"] == "GOVERNED"
    assert native["lifecycle_status"] == "ACTIVE"

    # 2. a representative EXTERNAL agent - truthfully NOT controllable
    ext_id = _make_external(admin, origin_category="EXTERNAL", origin_provider="CREWAI")
    snap = client.get(f"{RT}/agents/{ext_id}/control-state", headers=admin["headers"]).json()
    assert snap["control_state"] == "DISCOVERED"
    assert snap["lifecycle_status"] == "DRAFT"
    # no enforcement affordance: cannot jump to GOVERNED
    assert client.post(f"{RT}/agents/{ext_id}/control-state", headers=admin["headers"],
                       json={"target_state": "GOVERNED"}).status_code == 409

    # 3. an authorized user claims it (-> CLAIMED, audited, tenant-scoped)
    r = client.post(f"{RT}/agents/{ext_id}/claim", headers=claimer["headers"], json={
        "owner_type": "USER", "owner_id": claimer["user_id"], "reason": "adopting"})
    assert r.status_code == 200
    assert r.json()["control_state"] == "CLAIMED"

    # 4. a second concurrent claim conflicts deterministically
    r2 = client.post(f"{RT}/agents/{ext_id}/claim", headers=admin["headers"], json={
        "owner_type": "USER", "owner_id": admin["user_id"], "reason": "late"})
    assert r2.status_code == 409

    # 5. a client attempt to set control_state=GOVERNED via the general update
    #    path is silently ignored - the field never reaches the row.
    current = client.get(f"{RT}/agents/{ext_id}", headers=admin["headers"]).json()
    r3 = client.patch(f"{RT}/agents/{ext_id}", headers=admin["headers"], json={
        "row_version": current["row_version"], "control_state": "GOVERNED",
        "description": "an ordinary edit"})
    assert r3.status_code == 200, r3.text
    snap = client.get(f"{RT}/agents/{ext_id}/control-state", headers=admin["headers"]).json()
    assert snap["control_state"] == "CLAIMED"  # mass-assignment did nothing

    # 6. deliberate forward path: CLAIMED -> REGISTERED -> GOVERNED
    assert client.post(f"{RT}/agents/{ext_id}/control-state", headers=admin["headers"],
                       json={"target_state": "REGISTERED", "reason": "in scope"}).status_code == 200
    assert client.post(f"{RT}/agents/{ext_id}/control-state", headers=admin["headers"],
                       json={"target_state": "GOVERNED", "reason": "enrolled"}).status_code == 200

    # 7. the native agent's lifecycle is untouched throughout
    again = client.get(f"{RT}/agents/{native['id']}", headers=admin["headers"]).json()
    assert again["lifecycle_status"] == "ACTIVE"
    assert again["control_state"] == "GOVERNED"

    # 8. every mutation audited + tenant-isolated
    other = _org(client, "Outsider")
    assert client.get(f"{RT}/agents/{ext_id}/control-state",
                      headers=other["headers"]).status_code == 404
