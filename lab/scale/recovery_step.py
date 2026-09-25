"""One recovery scenario per interpreter (settings, engine and key ring bind at
import). Invoked by ``recovery.py``:

    python lab/scale/recovery_step.py <step> <dbname> <keys_dir> [extra-json]

Prints exactly one JSON line. Never prints a secret: plaintext test secrets
travel only in the V9_EXPECT environment variable between lab processes and
are compared, never echoed.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import labenv  # noqa: E402

STEP, DBNAME, KEYS = sys.argv[1], sys.argv[2], Path(sys.argv[3])
EXTRA = json.loads(sys.argv[4]) if len(sys.argv) > 4 else {}
EXPECT = json.loads(os.environ.get("V9_EXPECT") or "{}")
settings = labenv.activate(DBNAME, keys_dir=KEYS, extra_env=EXTRA.get("env"))

import app.main  # noqa: E402,F401
from sqlalchemy import text  # noqa: E402

from app.core.database import SessionLocal  # noqa: E402

PASSWORD = "V9-Synthetic-Passw0rd!"


def unwrap(body):
    return body.get("data", body) if isinstance(body, dict) else body


def emit(d: dict) -> None:
    print("V9JSON " + json.dumps(d, default=str), flush=True)


def keydir_listing() -> list[str]:
    return sorted(p.name for p in KEYS.glob("*")) if KEYS.exists() else []


def marker_and_canary(db) -> dict:
    m = db.execute(text("SELECT active_key_fingerprint, recorded_via FROM installation_bootstrap")).all()
    c = db.execute(text("SELECT purpose, key_fingerprint FROM key_material_canary ORDER BY purpose")).all()
    return {"marker": [list(r) for r in m], "canary": [list(r) for r in c]}


def err(exc: Exception) -> dict:
    return {"type": type(exc).__name__, "code": getattr(exc, "code", None),
            "message": str(getattr(exc, "message", exc))[:240]}


# --------------------------------------------------------------------------- #
if STEP == "bootstrap":
    from app.security.bootstrap import bootstrap_key_material
    db = SessionLocal()
    res = bootstrap_key_material(db)
    db.commit()
    emit({"encryption_fingerprint": res.encryption_fingerprint, "adopted_existing_key": res.adopted_existing_key,
          "signing_key_id": res.signing_key_id, "signing_key_version": res.signing_key_version,
          "keys": keydir_listing(), **marker_and_canary(db)})

elif STEP == "seed":
    from fastapi.testclient import TestClient
    from app.discovery.service import DiscoverySourceService
    from app.main import app
    from app.models.user import User
    from app.runtime.providers.credential_crypto import encrypt_secret, mask_hint
    from app.runtime.versioning.attestation import AttestationService
    from app.services import auth_service
    db = SessionLocal()
    user = auth_service.register_organization(db, organization_name="V9 recovery tenant", name="Rec Admin",
                                              email="v9-rec@lab.example", password=PASSWORD)
    db.commit()
    org = str(user.organization_id)
    s1, s2, s3 = (f"v9-synthetic-secret-{uuid.uuid4().hex}" for _ in range(3))
    pc_id, tool_id, tc_id = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
    db.execute(text("INSERT INTO provider_credentials (id, organization_id, provider, encrypted_secret, secret_hint, status, "
                    "created_at, updated_at) VALUES (:id, :o, 'OPENAI', :c, :h, 'ACTIVE', now(), now())"),
               {"id": pc_id, "o": org, "c": encrypt_secret(s1), "h": mask_hint(s1)})
    db.execute(text("INSERT INTO tools (id, organization_id, name, display_name, tool_type, risk_level, side_effect_level, "
                    "data_classification, requires_approval, timeout_seconds, enabled, created_at, updated_at) VALUES "
                    "(:id, :o, 'rec-tool', 'rec-tool', 'FUNCTION', 'MEDIUM', 'NONE', 'INTERNAL', false, 30, true, now(), now())"),
               {"id": tool_id, "o": org})
    db.execute(text("INSERT INTO tool_credentials (id, organization_id, tool_id, encrypted_secret, secret_hint, status, "
                    "created_at, updated_at) VALUES (:id, :o, :t, :c, :h, 'ACTIVE', now(), now())"),
               {"id": tc_id, "o": org, "t": tool_id, "c": encrypt_secret(s2), "h": mask_hint(s2)})
    db.commit()
    actor = db.get(User, user.id)
    src = DiscoverySourceService(db).create(actor, name="rec-source", adapter_key="HTTP_AGENT_REGISTRY",
                                            config={"base_url": "http://127.0.0.1:1", "allowed_hosts": ["127.0.0.1"],
                                                    "local_dev_hosts": ["127.0.0.1"], "allow_plaintext_http": True},
                                            secret=s3)
    # a signed, published version through the product's own API path (publish -> build_and_sign)
    client = TestClient(app)
    tok = unwrap(client.post("/api/v1/auth/login", json={"email": "v9-rec@lab.example", "password": PASSWORD}).json())
    H = {"Authorization": f"Bearer {tok['access_token']}"}
    RT = "/api/v1/runtime"
    r = client.post(f"{RT}/agents", headers=H, json={
        "name": "Recovery Native Agent", "agent_type": "ASSISTANT", "criticality": "MEDIUM",
        "description": "V9 recovery signing subject.", "business_purpose": "Prove signatures survive restore.",
        "owner_type": "USER", "owner_id": str(user.id), "technical_owner_id": str(user.id),
        "compliance_owner_id": str(user.id),
        "definition": {"name": "Definition", "framework": "CUSTOM", "entrypoint_type": "FUNCTION",
                       "entrypoint": "agents.handler:run"}})
    assert r.status_code == 201, r.text
    agent_id = unwrap(r.json())["id"]
    steps = {}
    for step in ("register", "validate"):
        steps[step] = client.post(f"{RT}/agents/{agent_id}/{step}", headers=H).status_code
    steps["identity"] = client.post(f"{RT}/agents/{agent_id}/identity/create-and-associate", headers=H,
                                    json={"client_id": f"agent-identity-{uuid.uuid4().hex[:10]}"}).status_code
    for step in ("submit-for-approval", "approve", "activate"):
        steps[step] = client.post(f"{RT}/agents/{agent_id}/{step}", headers=H).status_code
    r = client.post(f"{RT}/agents/{agent_id}/versions", headers=H,
                    json={"model_configuration": {"provider": "MOCK", "model": "mock-model"}})
    assert r.status_code == 201, r.text
    ver_id = unwrap(r.json())["id"]
    for step in ("validate", "approve", "publish"):
        steps[f"version_{step}"] = client.post(f"{RT}/agents/{agent_id}/versions/{ver_id}/{step}", headers=H).status_code
    db2 = SessionLocal()
    from app.models.runtime import AgentVersion
    ver = db2.get(AgentVersion, uuid.UUID(ver_id))
    ver_check = AttestationService(db2).verify(ver)
    sig_count = db2.execute(text("SELECT count(*) FROM agent_version_signatures WHERE agent_version_id=:v"), {"v": ver_id}).scalar()
    emit({"org_id": org, "admin_email": "v9-rec@lab.example", "agent_id": agent_id, "version_id": ver_id,
          "provider_credential_id": pc_id, "tool_credential_id": tc_id, "source_id": str(src.id),
          "steps": steps, "signature_rows": sig_count, "signature_valid_before_backup": bool(ver_check.get("valid")),
          "secrets": {"s1": s1, "s2": s2, "s3": s3}, **marker_and_canary(db2)})

elif STEP == "backup":
    from app.security.backup import create_key_material_archive, verify_key_material_archive
    dest = Path(EXTRA["dest"])
    man = create_key_material_archive(dest)
    problems = verify_key_material_archive(dest)
    emit({"artifacts": [a["name"] for a in man["artifacts"]], "encryption_present": man["encryption"]["present"],
          "fingerprint": man["encryption"].get("fingerprint"), "archive_problems": problems})

elif STEP == "restore_keys":
    from app.security.backup import restore_key_material_archive
    restored = restore_key_material_archive(Path(EXTRA["archive"]))
    emit({"restored": [p.name for p in restored], "keys": keydir_listing()})

elif STEP == "verify_with_key":
    from fastapi.testclient import TestClient
    from app.discovery.service import DiscoverySourceService
    from app.main import app
    from app.models.discovery import DiscoverySource
    from app.models.runtime import AgentVersion
    from app.runtime.providers.credential_crypto import decrypt_secret
    from app.runtime.versioning.attestation import AttestationService
    from app.security.install_mode import detect_install_mode
    from app.security.key_integrity import verify_key_material
    db = SessionLocal()
    rep = verify_key_material(db)
    mode = detect_install_mode(db)
    c1 = db.execute(text("SELECT encrypted_secret FROM provider_credentials WHERE id=:i"), {"i": EXPECT["provider_credential_id"]}).scalar()
    c2 = db.execute(text("SELECT encrypted_secret FROM tool_credentials WHERE id=:i"), {"i": EXPECT["tool_credential_id"]}).scalar()
    src = db.get(DiscoverySource, uuid.UUID(EXPECT["source_id"]))
    d1 = decrypt_secret(c1) == EXPECT["secrets"]["s1"]
    d2 = decrypt_secret(c2) == EXPECT["secrets"]["s2"]
    d3 = DiscoverySourceService(db).resolve_secret(src) == EXPECT["secrets"]["s3"]
    ver = db.get(AgentVersion, uuid.UUID(EXPECT["version_id"]))
    hist = AttestationService(db).verify(ver)
    # new signing continues: publish another version through the API
    client = TestClient(app)
    tok = unwrap(client.post("/api/v1/auth/login", json={"email": EXPECT["admin_email"], "password": PASSWORD}).json())
    H = {"Authorization": f"Bearer {tok['access_token']}"}
    RT = "/api/v1/runtime"
    r = client.post(f"{RT}/agents/{EXPECT['agent_id']}/versions", headers=H,
                    json={"model_configuration": {"provider": "MOCK", "model": "mock-model-2"}})
    new_ok, new_valid, new_steps = r.status_code == 201, None, {}
    if new_ok:
        vid = unwrap(r.json())["id"]
        for step in ("validate", "approve", "publish"):
            new_steps[step] = client.post(f"{RT}/agents/{EXPECT['agent_id']}/versions/{vid}/{step}", headers=H).status_code
        db3 = SessionLocal()
        nv = db3.get(AgentVersion, uuid.UUID(vid))
        new_valid = bool(AttestationService(db3).verify(nv).get("valid"))
    emit({"integrity": {"install_mode": rep.install_mode, "encryption": rep.encryption, "signing": rep.signing},
          "install_mode": mode.mode.value, "marker": mode.bootstrap_marker,
          "decrypt_provider_credential": d1, "decrypt_tool_credential": d2, "decrypt_discovery_source_secret": d3,
          "historical_signature_valid": bool(hist.get("valid")), "historical_snapshot_intact": hist.get("snapshot_intact"),
          "new_version_published": new_ok, "new_publish_steps": new_steps, "new_signature_valid": new_valid,
          "keys": keydir_listing()})

elif STEP == "verify_without_key":
    from app.security.bootstrap import bootstrap_key_material
    from app.security.errors import KeyMaterialError
    from app.security.install_mode import detect_install_mode
    from app.security.key_integrity import verify_key_material
    db = SessionLocal()
    before = marker_and_canary(db)
    out = {"keys_before": keydir_listing(), "install_mode": detect_install_mode(db).mode.value}
    try:
        verify_key_material(db)
        out["verify"] = "NO ERROR (silent!)"
    except Exception as exc:  # noqa: BLE001
        out["verify"] = err(exc)
    db.rollback()
    try:
        verify_key_material(db, allow_bootstrap=True)
        out["verify_allow_bootstrap"] = "NO ERROR (silent!)"
    except Exception as exc:  # noqa: BLE001
        out["verify_allow_bootstrap"] = err(exc)
    db.rollback()
    try:
        bootstrap_key_material(db)
        out["bootstrap"] = "NO ERROR (silent regeneration!)"
    except Exception as exc:  # noqa: BLE001
        out["bootstrap"] = err(exc)
    db.rollback()
    try:
        from app.runtime.providers.credential_crypto import decrypt_secret
        c1 = db.execute(text("SELECT encrypted_secret FROM provider_credentials LIMIT 1")).scalar()
        decrypt_secret(c1)
        out["decrypt"] = "NO ERROR (decrypted without key!)"
    except Exception as exc:  # noqa: BLE001
        out["decrypt"] = err(exc)
    db.rollback()
    after = marker_and_canary(SessionLocal())
    out.update({"keys_after": keydir_listing(), "key_file_created": len(keydir_listing()) > 0,
                "marker_canary_unchanged": before == after, "state_after": after,
                "silent_identity_reset": len(keydir_listing()) > 0 or before != after})
    emit(out)

elif STEP == "verify_variant":
    from app.security.key_integrity import verify_key_material
    db = SessionLocal()
    before = marker_and_canary(db)
    out = {"variant": EXTRA["variant"], "keys": keydir_listing()}
    try:
        rep = verify_key_material(db)
        out["verify"] = {"NO ERROR": rep.encryption}
    except Exception as exc:  # noqa: BLE001
        out["verify"] = err(exc)
    db.rollback()
    out["marker_canary_unchanged"] = before == marker_and_canary(SessionLocal())
    out["loud"] = isinstance(out["verify"], dict) and "type" in out["verify"]
    emit(out)

elif STEP == "marker_only":
    from app.security.encryption_provider import get_encryption_key_provider
    from app.security.install_mode import detect_install_mode
    from app.security.installation import record_bootstrap
    from app.security.key_integrity import verify_encryption_material
    db = SessionLocal()
    provider = get_encryption_key_provider()
    record_bootstrap(db, provider, recorded_via="bootstrap")
    db.commit()
    rep = detect_install_mode(db)
    out = {"install_mode": rep.mode.value, "marker": rep.bootstrap_marker, "encrypted_tables": list(rep.encrypted_state_tables),
           "signed_tables": list(rep.signed_state_tables)}
    for name, kw in (("verify", {}), ("verify_allow_bootstrap", {"allow_bootstrap": True})):
        try:
            out[name] = {"NO ERROR": verify_encryption_material(db, **kw)}
        except Exception as exc:  # noqa: BLE001
            out[name] = err(exc)
        db.rollback()
    emit(out)

elif STEP == "seed_transient":
    db = SessionLocal()
    now = datetime.now(timezone.utc)
    for i in range(3):
        db.execute(text("INSERT INTO worker_registrations (id, worker_id, cohort, status, concurrency, active_count, heartbeat_at, "
                        "registered_at) VALUES (:id, :w, 'default', 'RUNNING', 2, 1, :h, :h)"),
                   {"id": str(uuid.uuid4()), "w": f"v9-worker-{i}", "h": now})
    ex = [r[0] for r in db.execute(text("SELECT id FROM agent_executions LIMIT 2")).all()]
    for i, eid in enumerate(ex):
        db.execute(text("INSERT INTO execution_locks (id, execution_id, worker_id, acquired_at, expires_at, heartbeat_at) VALUES "
                        "(:id, :e, :w, :a, :x, :a)"),
                   {"id": str(uuid.uuid4()), "e": eid, "w": f"v9-worker-{i}", "a": now - timedelta(minutes=10),
                    "x": now - timedelta(minutes=1)})
    db.commit()
    emit({"workers_seeded": 3, "expired_locks_seeded": len(ex), "seeded_at": now.isoformat()})

elif STEP == "durable_snapshot":
    db = SessionLocal()
    tables = ("organizations", "users", "agents", "control_graph_edges", "discovery_sources", "discovery_runs",
              "discovery_observations", "discovery_findings", "posture_findings", "threat_findings", "policies",
              "runtime_governance_policies", "external_capability_grants", "external_gateway_calls",
              "assurance_evidence_bundles", "assurance_evaluations", "budgets", "budget_reservations", "runtime_alerts",
              "worker_registrations", "execution_locks", "resources", "tools", "agent_executions", "agent_versions",
              "delegations", "agent_ownership_history", "signing_keys", "agent_version_signatures",
              "key_material_canary", "installation_bootstrap")
    snap = {}
    t0 = time.perf_counter()
    for t in tables:
        n = db.execute(text(f"SELECT count(*) FROM {t}")).scalar()
        h = db.execute(text(f"SELECT md5(string_agg(x::text, '|' ORDER BY x::text)) FROM {t} x")).scalar() if n else None
        snap[t] = {"count": n, "md5": h}
    open_alerts = db.execute(text("SELECT count(*) FROM runtime_alerts WHERE status='OPEN'")).scalar()
    budget_sum = db.execute(text("SELECT coalesce(sum(limit_amount),0) FROM budgets")).scalar()
    open_findings = db.execute(text("SELECT count(*) FROM posture_findings WHERE status='OPEN'")).scalar()
    extra = {}
    if EXTRA.get("manifest"):
        from app.graph.blast_radius import BlastRadiusService
        from app.models.user import User
        mp = Path(EXTRA["manifest"])
        if not mp.is_absolute():
            mp = labenv.ROOT / mp
        m = json.loads(mp.read_text(encoding="utf-8"))["measured"]
        actor = db.get(User, uuid.UUID(m["admin_id"]))
        res = BlastRadiusService(db).agents_reaching(actor, node_type="RESOURCE", node_id=uuid.UUID(m["hub_resource"]), max_depth=16)
        extra = {"hub_blast_radius_agents": len(res["agents"]), "hub_incomplete": res["incomplete"]}
        db.rollback()
    emit({"tables": snap, "open_alerts": open_alerts, "budget_limit_sum": str(budget_sum), "open_posture_findings": open_findings,
          "snapshot_seconds": round(time.perf_counter() - t0, 1), **extra})

elif STEP == "phantom_workers":
    from app.runtime.services import ExecutionWorkerService
    from app.workers.fleet import WorkerFleetService
    db = SessionLocal()
    fleet = WorkerFleetService(db)
    live_before = [w.worker_id for w in fleet.list_workers()]
    stale = [w.worker_id for w in fleet.stale_workers()]
    reaped = fleet.reap_stale_workers()
    db.commit()
    live_after = [w.worker_id for w in fleet.list_workers()]
    locks_before = db.execute(text("SELECT count(*) FROM execution_locks")).scalar()
    reaped_locks = ExecutionWorkerService(db).reap_expired_locks()
    db.commit()
    locks_after = db.execute(text("SELECT count(*) FROM execution_locks")).scalar()
    emit({"live_before_reap": live_before, "stale_detected": stale, "reaped": reaped, "live_after_reap": live_after,
          "stale_after_seconds": settings.WORKER_STALE_AFTER_SECONDS, "locks_before": locks_before,
          "expired_locks_reaped": reaped_locks, "locks_after": locks_after,
          "no_phantom_live_worker": len(live_after) == 0})

else:
    raise SystemExit(f"unknown step {STEP}")
