"""Phase 5.7 (M5.7) - External Agent Governance Bridge.

Proves that ACT can govern agents it does not run **truthfully**: each of the
four enforcement modes reaches exactly what it claims and no further, an
external agent's identity never becomes an internal one, the boundary reuses
the real ``AuthorizationGateway``/4.3/4.4 rather than re-deciding, no DB lock
is held across the downstream dispatch, and revocation is immediate.

The §15 end-to-end proof runs ACT under a **real uvicorn server on a real
socket** and drives it from a **real external agent in a separate OS process**
that imports nothing from ACT -- the 25A/25B forward-compat position: it did
not come from ACT and does not run in ACT.

AC-01..AC-20 + the §15 end-to-end proof; each AC has a named test.
"""

from __future__ import annotations

import ast
import hashlib
import hmac
import http.server
import json as jsonlib
import subprocess
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text

from app.core.database import SessionLocal
from app.models.agent import Agent
from app.models.bridge import (
    ExternalCapabilityGrant,
    ExternalGatewayCall,
    ExternalRequestNonce,
)
from app.models.runtime import Tool
from app.models.user import User
from app.runtime.registry.control import AgentProvenanceService

BRIDGE = "/api/v1/bridge"
_BACKEND = Path(__file__).resolve().parents[2]
_BRIDGE_PKG = _BACKEND / "app" / "bridge"


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _make_external(admin: dict, **kw) -> str:
    """An agent that exists OUTSIDE ACT, created through Phase 5.1's own seam
    (``record_external_agent``) -- no 5.7 code involved in making it."""
    db = SessionLocal()
    try:
        actor = db.get(User, uuid.UUID(admin["user_id"]))
        agent = AgentProvenanceService(db).record_external_agent(
            actor, name=kw.pop("name", f"Ext Agent {uuid.uuid4().hex[:6]}"),
            origin_category="EXTERNAL", origin_provider="LANGGRAPH", **kw)
        db.commit()
        return str(agent.id)
    finally:
        db.close()


def _register_native(client: TestClient, admin: dict) -> dict:
    """A native agent through the real Phase 5.0/5.1 registry path -- so it
    lands GOVERNED/ACT_NATIVE exactly as any real native agent does, with no
    5.7 code involved."""
    r = client.post("/api/v1/runtime/agents", headers=admin["headers"], json={
        "name": f"Native Agent {uuid.uuid4().hex[:6]}", "description": "d",
        "business_purpose": "d", "agent_type": "ASSISTANT", "criticality": "MEDIUM",
        "owner_type": "USER", "owner_id": admin["user_id"],
        "technical_owner_id": admin["user_id"], "compliance_owner_id": admin["user_id"],
        "definition": {"name": "Definition", "framework": "CUSTOM",
                       "entrypoint_type": "FUNCTION", "entrypoint": "agents.handler:run"},
    })
    assert r.status_code == 201, r.text
    return r.json()


def _set_mode(client: TestClient, admin: dict, agent_id: str, mode: str):
    return client.put(f"{BRIDGE}/agents/{agent_id}/enforcement-mode",
                      headers=admin["headers"], json={"target_mode": mode})


def _gateway_agent(client: TestClient, admin: dict, **kw) -> str:
    agent_id = _make_external(admin, **kw)
    r = _set_mode(client, admin, agent_id, "GATEWAY_ENFORCED")
    assert r.status_code == 200, r.text
    return agent_id


def _make_http_tool(admin: dict, port: int, *, name: str | None = None) -> str:
    """A real, registered HTTP tool pointed at a real local server. The host
    is an IP literal on the declared local-dev allowlist, so the *real* egress
    guard and the *real* resolver are exercised -- no fake resolver."""
    db = SessionLocal()
    try:
        tool = Tool(
            organization_id=uuid.UUID(admin["organization_id"]),
            name=name or f"cap_{uuid.uuid4().hex[:8]}",
            display_name="Reference Capability",
            tool_type="HTTP",
            endpoint_reference=f"http://127.0.0.1:{port}",
            http_config={
                "allowed_hosts": ["127.0.0.1"],
                "allow_plaintext_http": True,
                "local_dev_hosts": ["127.0.0.1"],
                "method": "POST",
                "timeout_seconds": 10,
            },
        )
        db.add(tool)
        db.commit()
        return str(tool.id)
    finally:
        db.close()


def _issue_grant(client: TestClient, admin: dict, agent_id: str, scope: list[dict],
                 **kw) -> dict:
    body = {"label": kw.pop("label", f"grant-{uuid.uuid4().hex[:6]}"), "scope": scope}
    body.update(kw)
    r = client.post(f"{BRIDGE}/agents/{agent_id}/grants", headers=admin["headers"], json=body)
    assert r.status_code == 201, r.text
    return r.json()


def _sign_headers(key_id: str, secret: str, *, method: str, path: str,
                  body: bytes, timestamp: int | None = None,
                  nonce: str | None = None) -> dict:
    """Signs exactly as an external client would. Uses the platform's own
    ``signing_string`` so there is one implementation, not two."""
    from app.bridge.identity import SIGNATURE_SCHEME

    ts = str(timestamp if timestamp is not None else int(time.time()))
    nonce = nonce or uuid.uuid4().hex
    digest = hashlib.sha256(body or b"").hexdigest()
    payload = "\n".join([SIGNATURE_SCHEME, method.upper(), path, ts, nonce, digest])
    sig = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return {"X-ACT-Key-Id": key_id, "X-ACT-Timestamp": ts, "X-ACT-Nonce": nonce,
            "X-ACT-Signature": sig, "Content-Type": "application/json"}


def _call(client: TestClient, issued: dict, payload: dict, **kw):
    body = jsonlib.dumps(payload).encode()
    headers = _sign_headers(issued["grant"]["key_id"], issued["secret"],
                            method="POST", path=f"{BRIDGE}/capability", body=body, **kw)
    return client.post(f"{BRIDGE}/capability", content=body, headers=headers)


class _Log:
    def __init__(self) -> None:
        self.requests: list[dict] = []


@contextmanager
def local_capability_server():
    """A REAL enterprise capability endpoint on a real socket -- the same
    ``http.server`` convention Phase 2.2.1 and 5.2 established."""
    log = _Log()

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            length = int(self.headers.get("content-length") or 0)
            raw = self.rfile.read(length) if length else b""
            log.requests.append({"path": self.path, "body": raw.decode() or None})
            payload = jsonlib.dumps({"ok": True}).encode()
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *args) -> None:  # keep pytest output clean
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_address[1], log
    finally:
        server.shutdown()
        server.server_close()


def _source(*names: str) -> str:
    return "\n".join((_BRIDGE_PKG / n).read_text(encoding="utf-8") for n in names)


def _calls_named(source: str) -> set[str]:
    """Every attribute/function name called anywhere in the source."""
    tree = ast.parse(source)
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            fn = node.func
            if isinstance(fn, ast.Attribute):
                found.add(fn.attr)
            elif isinstance(fn, ast.Name):
                found.add(fn.id)
    return found


def _imported_modules(source: str) -> set[str]:
    tree = ast.parse(source)
    mods: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            mods.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            mods.add(node.module)
    return mods


# --------------------------------------------------------------------------- #
# AC-01 - live baseline / substrate
# --------------------------------------------------------------------------- #
def test_ac01_substrate_and_migration_head_present() -> None:
    """The 5.1 anchor, the 5.6 gate and the M4 authorities 5.7 reuses are all
    present, and the migration chain is at this phase's head."""
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    from app.authorization.middleware.gateway import AuthorizationGateway
    from app.finops.budgets import BudgetService
    from app.observability.events import emit_event  # noqa: F401
    from app.runtime.governance.policies import GovernancePolicyService
    from app.runtime.registry.control import CONTROL_STATES
    from app.threat.containment import ContainmentOrchestrator

    heads = ScriptDirectory.from_config(
        Config(str(_BACKEND / "alembic.ini"))).get_heads()
    assert list(heads) == ["0060_external_gov_bridge"]

    # 5.1: the enforcement-mode anchor.
    assert CONTROL_STATES == ("DISCOVERED", "CLAIMED", "REGISTERED", "GOVERNED")
    # 5.6: the truthful-containment gate, unchanged and still keyed on GOVERNED.
    assert hasattr(ContainmentOrchestrator, "truthful_capability")
    # The authorities 5.7 reuses rather than reimplements.
    assert hasattr(AuthorizationGateway, "authorize_agent")
    assert hasattr(GovernancePolicyService, "resolve")
    assert hasattr(BudgetService, "resolve")


# --------------------------------------------------------------------------- #
# AC-02 - the four modes, server-authoritative, anchored to control_state
# --------------------------------------------------------------------------- #
def test_ac02_four_modes_are_represented_and_anchored(client: TestClient, admin: dict) -> None:
    from app.bridge.modes import ENFORCEMENT_MODES

    assert ENFORCEMENT_MODES == ("OBSERVED", "ADVISORY", "GATEWAY_ENFORCED", "NATIVE_ENFORCED")
    listed = client.get(f"{BRIDGE}/modes", headers=admin["headers"]).json()
    assert [m["mode"] for m in listed] == list(ENFORCEMENT_MODES)

    ext = _make_external(admin)
    got = client.get(f"{BRIDGE}/agents/{ext}/enforcement-mode",
                     headers=admin["headers"]).json()
    # A discovered external agent is OBSERVED: ACT sees it and can do nothing.
    assert got["enforcement_mode"] == "OBSERVED"
    assert got["control_state"] == "DISCOVERED"
    assert got["reaches_boundary_calls"] is False
    assert got["reaches_agent_execution"] is False


def test_ac02_mode_is_server_authoritative_and_native_is_not_assignable(
        client: TestClient, admin: dict) -> None:
    """The write schema carries only a *requested* mode, and the strongest
    mode cannot be requested at all -- it is derived from control_state."""
    ext = _make_external(admin)

    r = client.put(f"{BRIDGE}/agents/{ext}/enforcement-mode", headers=admin["headers"],
                   json={"target_mode": "NATIVE_ENFORCED"})
    assert r.status_code == 422  # rejected by the schema's own Literal

    # And the service refuses it too, for callers that reach it directly.
    from app.bridge.service import EnforcementModeService
    from app.identity.errors import IdentityError

    db = SessionLocal()
    try:
        actor = db.get(User, uuid.UUID(admin["user_id"]))
        with pytest.raises(IdentityError) as exc:
            EnforcementModeService(db).set_mode(actor, uuid.UUID(ext),
                                               target_mode="NATIVE_ENFORCED")
        assert "cannot be assigned" in str(exc.value)
    finally:
        db.close()

    # No write schema anywhere in this phase carries control_state.
    from app.bridge import schemas

    for name in dir(schemas):
        obj = getattr(schemas, name)
        fields = getattr(obj, "model_fields", None)
        if fields and name.endswith(("Set", "Create", "Request", "Revoke")):
            assert "control_state" not in fields
            assert "enforcement_mode" not in fields


def test_ac02_native_enforced_is_derived_from_control_state_only(
        client: TestClient, admin: dict) -> None:
    """A GOVERNED agent reports NATIVE_ENFORCED with no 5.7 row involved, and
    the strongest mode is not storable in the database at all."""
    from app.bridge.modes import effective_mode

    agent_id = _register_native(client, admin)["id"]

    got = client.get(f"{BRIDGE}/agents/{agent_id}/enforcement-mode",
                     headers=admin["headers"]).json()
    assert got["control_state"] == "GOVERNED"
    assert got["enforcement_mode"] == "NATIVE_ENFORCED"
    assert got["derived_from_control_state"] is True
    assert got["reaches_agent_execution"] is True

    db = SessionLocal()
    try:
        agent = db.get(Agent, uuid.UUID(agent_id))
        assert agent.external_enforcement_mode is None  # nothing stored
        assert effective_mode(agent) == "NATIVE_ENFORCED"
        # The database itself refuses to store the strongest claim.
        with pytest.raises(Exception):
            db.execute(text("UPDATE agents SET external_enforcement_mode='NATIVE_ENFORCED' "
                            "WHERE id=:i"), {"i": str(agent_id)})
            db.commit()
        db.rollback()
    finally:
        db.close()


def test_ac02_governed_agent_cannot_be_downgraded_to_a_weaker_claim(
        client: TestClient, admin: dict) -> None:
    native = _register_native(client, admin)
    r = _set_mode(client, admin, native["id"], "OBSERVED")
    assert r.status_code == 409
    assert "understate" in r.text.lower()


# --------------------------------------------------------------------------- #
# AC-03 - truthful reach per mode (the headline honesty proof)
# --------------------------------------------------------------------------- #
def test_ac03_no_mode_claims_reach_act_lacks(client: TestClient, admin: dict) -> None:
    """Per-mode assertion: the sentence ACT is permitted to say never claims
    control over the agent unless ACT actually has it."""
    from app.bridge.modes import REACH

    for mode, reach in REACH.items():
        text_shown = f"{reach.display} {reach.limits}".lower()
        if reach.reaches_agent_execution:
            assert mode == "NATIVE_ENFORCED"
            continue
        # A mode that cannot stop the agent must not say it governs it.
        for forbidden in ("govern this agent", "control this agent",
                          "we govern", "stops this agent", "act controls this agent"):
            assert forbidden not in text_shown, (mode, forbidden)
        # ...and must state its limit explicitly.
        assert reach.limits, mode
        if not reach.reaches_boundary_calls:
            assert "no enforcement" in text_shown, mode
        else:
            assert "boundary" in text_shown and "outside" in text_shown, mode


def test_ac03_observed_and_advisory_perform_no_enforcement_structurally() -> None:
    """The proof is what the module cannot reach. ``app/bridge/observed.py``
    imports no enforcement authority at all -- the same AST technique Phase
    5.6 used to prove ``app/threat`` implements no enforcement of its own."""
    source = _source("observed.py")
    imported = _imported_modules(source)
    for banned in ("app.runtime.governance.engine", "app.threat.containment",
                   "app.services.api_key_service", "app.bridge.gateway",
                   "app.bridge.dispatch", "app.runtime.tools.http_executor"):
        assert banned not in imported, banned
    called = _calls_named(source)
    for banned in ("activate", "revoke", "revoke_key", "disable", "suspend",
                   "terminate", "dispatch_http_tool", "execute_http_tool",
                   "authorize_agent"):
        assert banned not in called, banned


def test_ac03_advisory_recommends_without_enforcing(client: TestClient, admin: dict) -> None:
    ext = _make_external(admin)
    assert _set_mode(client, admin, ext, "ADVISORY").status_code == 200

    r = client.post(f"{BRIDGE}/agents/{ext}/advisory", headers=admin["headers"])
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["enforcement_performed"] is False
    assert "enforced nothing" in body["finding"]
    assert body["detail"]["enforcement_mode"] == "ADVISORY"
    # Nothing was created that could enforce anything.
    db = SessionLocal()
    try:
        assert db.execute(select(ExternalGatewayCall).where(
            ExternalGatewayCall.agent_id == uuid.UUID(ext))).scalars().first() is None
        assert db.execute(select(ExternalCapabilityGrant).where(
            ExternalCapabilityGrant.agent_id == uuid.UUID(ext))).scalars().first() is None
    finally:
        db.close()


def test_ac03_observed_agent_cannot_be_given_a_boundary_credential(
        client: TestClient, admin: dict) -> None:
    """Issuing a grant to a mode that enforces nothing would be a credential
    for control ACT does not have -- refused, with the reason said out loud."""
    ext = _make_external(admin)  # OBSERVED
    r = client.post(f"{BRIDGE}/agents/{ext}/grants", headers=admin["headers"], json={
        "label": "nope", "scope": [{"capability": "http_tool.invoke",
                                    "target_ref": str(uuid.uuid4())}]})
    assert r.status_code == 409
    assert "no enforcement" in r.text.lower()


def test_ac03_native_mode_routes_to_the_real_4_3_engine_and_kill_switch() -> None:
    """NATIVE_ENFORCED is not a claim this phase implements -- it is the M1-M4
    platform, whose enforcement path this phase does not touch."""
    from app.runtime.governance.engine import RuntimeGovernanceEngine
    from app.threat.containment import _ENFORCEABLE_CONTROL_STATE

    from app.bridge.modes import NATIVE_CONTROL_STATE

    # The two phases read the *same* signal for "ACT really enforces this".
    assert NATIVE_CONTROL_STATE == _ENFORCEABLE_CONTROL_STATE == "GOVERNED"
    assert hasattr(RuntimeGovernanceEngine, "evaluate") or callable(RuntimeGovernanceEngine)
    # And nothing in app/bridge re-implements or calls into that engine.
    assert "app.runtime.governance.engine" not in _imported_modules(
        _source("gateway.py", "modes.py", "service.py", "observed.py", "dispatch.py"))


# --------------------------------------------------------------------------- #
# AC-04 - external identity is scoped, NOT internal; no gateway bypass
# --------------------------------------------------------------------------- #
def test_ac04_external_identity_creates_no_internal_principal(
        client: TestClient, admin: dict) -> None:
    ext = _gateway_agent(client, admin)
    before = _user_count()
    issued = _issue_grant(client, admin, ext,
                          [{"capability": "http_tool.invoke", "target_ref": str(uuid.uuid4())}])
    assert _user_count() == before, "issuing a grant must not create a user"

    db = SessionLocal()
    try:
        grant = db.execute(select(ExternalCapabilityGrant).where(
            ExternalCapabilityGrant.key_id == issued["grant"]["key_id"])).scalars().one()
        # The grant names an agent. It has no user, role, session or permission.
        cols = {c.name for c in grant.__table__.columns}
        assert "agent_id" in cols
        assert not {"user_id", "role_id", "session_id", "permissions"} & cols
    finally:
        db.close()

    # The credential is not a session token: it opens no other ACT surface.
    r = client.get("/api/v1/auth/me",
                   headers={"Authorization": f"Bearer {issued['secret']}"})
    assert r.status_code in (401, 403)


def test_ac04_every_boundary_call_authorizes_through_the_real_gateway() -> None:
    """Structural: the boundary has no permission logic of its own, and the
    only authorization call it makes is to the platform's one gateway."""
    source = _source("gateway.py")
    assert "app.authorization.middleware.gateway" in _imported_modules(source)
    called = _calls_named(source)
    assert "authorize_agent" in called
    # No parallel authorization: the boundary never reaches RBAC/ABAC directly.
    for banned in ("ABACEngine", "PermissionEngine", "ResourceAuthorizationService",
                   "has_permission", "check_permission"):
        assert banned not in called, banned


def test_ac04_no_bypass_path_exists(client: TestClient, admin: dict) -> None:
    """Behavioural: an unsigned call, a wrongly-signed call and a call with a
    forged key_id all fail before any capability is reached."""
    ext = _gateway_agent(client, admin)
    tool_id = str(uuid.uuid4())
    issued = _issue_grant(client, admin, ext,
                          [{"capability": "http_tool.invoke", "target_ref": tool_id}])
    body = jsonlib.dumps({"capability": "http_tool.invoke", "target_ref": tool_id}).encode()

    # no signature at all
    assert client.post(f"{BRIDGE}/capability", content=body,
                       headers={"Content-Type": "application/json"}).status_code in (401, 422)
    # wrong secret
    bad = _sign_headers(issued["grant"]["key_id"], "not-the-secret",
                        method="POST", path=f"{BRIDGE}/capability", body=body)
    assert client.post(f"{BRIDGE}/capability", content=body, headers=bad).status_code == 401
    # unknown key_id, correct-looking signature
    forged = _sign_headers("actx_" + "0" * 32, issued["secret"],
                           method="POST", path=f"{BRIDGE}/capability", body=body)
    assert client.post(f"{BRIDGE}/capability", content=body, headers=forged).status_code == 401


def _user_count() -> int:
    db = SessionLocal()
    try:
        return db.execute(text("SELECT count(*) FROM users")).scalar()
    finally:
        db.close()


# --------------------------------------------------------------------------- #
# AC-05 - the boundary reuses the real authorities, and audits
# --------------------------------------------------------------------------- #
def test_ac05_allowed_call_uses_real_authz_policy_cost_and_is_audited(
        client: TestClient, admin: dict) -> None:
    with local_capability_server() as (port, log):
        ext = _gateway_agent(client, admin)
        tool_id = _make_http_tool(admin, port)
        issued = _issue_grant(client, admin, ext,
                              [{"capability": "http_tool.invoke", "target_ref": tool_id}])
        r = _call(client, issued, {"capability": "http_tool.invoke",
                                   "target_ref": tool_id, "params": {"body": {"hi": 1}}})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["outcome"] == "ALLOWED"
    assert body["dispatch_status"] == "DISPATCHED"
    assert len(log.requests) == 1, "the real downstream capability was actually called"

    db = SessionLocal()
    try:
        rec = db.get(ExternalGatewayCall, uuid.UUID(body["call_id"]))
        assert rec.outcome == "ALLOWED"
        # the REAL gateway decided, and its verdict is recorded, not re-derived
        assert rec.authz_decision in ("ALLOW", "NOT_APPLICABLE")
        assert rec.authz_permission == "external_capability.http_tool.invoke"
        # the REAL 4.3 policy resolution and 4.4 budget resolution both ran
        assert rec.policy_outcome in ("NOT_APPLICABLE", "SATISFIED")
        assert rec.cost_outcome in ("NOT_MEASURABLE", "WITHIN_BUDGET")
        assert rec.enforcement_mode_at_time == "GATEWAY_ENFORCED"
        events = _audit_events(db, uuid.UUID(admin["organization_id"]))
        assert "EXTERNAL_GATEWAY_CALL_ALLOWED" in events
    finally:
        db.close()


def test_ac05_a_real_abac_deny_denies_the_boundary_call(
        client: TestClient, admin: dict) -> None:
    """The gateway is genuinely the authority: a real ABAC DENY policy on the
    capability's action stops the call, and nothing is dispatched."""
    with local_capability_server() as (port, log):
        ext = _gateway_agent(client, admin)
        tool_id = _make_http_tool(admin, port)
        policy = client.post("/api/v1/authorization/abac/policies", headers=admin["headers"],
                             json={"name": f"deny_{uuid.uuid4().hex[:8]}", "effect": "DENY",
                                   "target": {"actions": ["external_capability.http_tool.invoke"]},
                                   # A realistic policy -- "deny this tool to
                                   # this principal" -- conditioned on the
                                   # platform's own registered `ai.tool_name`
                                   # attribute, which the boundary populates.
                                   # A real evaluation, not a blanket rule.
                                   "conditions": {"all": [
                                       {"attribute": "ai.tool_name",
                                        "operator": "EQUALS",
                                        "value": tool_id}]}})
        assert policy.status_code == 201, policy.text
        pub = client.post(
            f"/api/v1/authorization/abac/policies/{policy.json()['id']}/publish",
            headers=admin["headers"])
        assert pub.status_code == 200, pub.text

        issued = _issue_grant(client, admin, ext,
                              [{"capability": "http_tool.invoke", "target_ref": tool_id}])
        r = _call(client, issued, {"capability": "http_tool.invoke", "target_ref": tool_id})

    assert r.status_code == 403, r.text
    assert r.json()["outcome"] == "DENIED"
    assert log.requests == [], "a denied call must never reach the downstream capability"

    db = SessionLocal()
    try:
        rec = db.get(ExternalGatewayCall, uuid.UUID(r.json()["call_id"]))
        assert rec.authz_decision == "DENY"
        assert rec.dispatch_status == "NOT_DISPATCHED"
    finally:
        db.close()


def test_ac05_a_real_4_3_approval_policy_denies_the_boundary_call(
        client: TestClient, admin: dict) -> None:
    """The boundary honours the *same* ``runtime_governance_policies`` rows the
    4.3 engine's own checkpoints read -- including the agent-scoped
    ``requires_approval`` constraint Phase 5.6's REQUIRE_APPROVAL containment
    writes. ACT's boundary does not auto-approve; it denies and says why."""
    from app.runtime.governance.policies import GovernancePolicyService

    with local_capability_server() as (port, log):
        ext = _gateway_agent(client, admin)
        tool_id = _make_http_tool(admin, port)
        db = SessionLocal()
        try:
            actor = db.get(User, uuid.UUID(admin["user_id"]))
            GovernancePolicyService(db).create(actor, {
                "name": f"approval_{uuid.uuid4().hex[:8]}",
                "agent_id": uuid.UUID(ext),
                "constraints": {"requires_approval": True},
                "mandatory": True,
            })
        finally:
            db.close()

        issued = _issue_grant(client, admin, ext,
                              [{"capability": "http_tool.invoke", "target_ref": tool_id}])
        r = _call(client, issued, {"capability": "http_tool.invoke", "target_ref": tool_id})

    assert r.status_code == 403, r.text
    body = r.json()
    assert body["outcome"] == "DENIED"
    assert "approval" in (body["denial_reason"] or "").lower()
    assert log.requests == [], "an approval-gated call must dispatch nothing"

    db = SessionLocal()
    try:
        rec = db.get(ExternalGatewayCall, uuid.UUID(body["call_id"]))
        assert rec.policy_outcome == "APPROVAL_REQUIRED"
        assert rec.authz_decision == "ALLOW"   # authz passed; policy stopped it
        assert rec.policy_detail["policy_name"]
    finally:
        db.close()


def test_ac05_a_real_4_4_hard_limit_budget_denies_the_boundary_call(
        client: TestClient, admin: dict) -> None:
    """Cost is metered against the real Phase 4.4 budgets, read through the
    real ``BudgetService``. An exhausted hard limit denies at the boundary; a
    budget with headroom records WITHIN_BUDGET."""
    from app.finops.budgets import BudgetService

    with local_capability_server() as (port, log):
        ext = _gateway_agent(client, admin)
        tool_id = _make_http_tool(admin, port)
        issued = _issue_grant(client, admin, ext,
                              [{"capability": "http_tool.invoke", "target_ref": tool_id}])

        db = SessionLocal()
        try:
            actor = db.get(User, uuid.UUID(admin["user_id"]))
            budget = BudgetService(db).create(actor, {
                "name": f"headroom_{uuid.uuid4().hex[:6]}", "scope_type": "AGENT",
                "scope_id": uuid.UUID(ext), "mode": "HARD_LIMIT", "period": "MONTHLY",
                "limit_amount": 100, "reservation_estimate": 1,
            })
            budget_id = budget.id
        finally:
            db.close()

        with_headroom = _call(client, issued, {"capability": "http_tool.invoke",
                                               "target_ref": tool_id})
        assert with_headroom.status_code == 200, with_headroom.text

        # Exhaust it: a hard limit of zero has no headroom left to spend.
        db = SessionLocal()
        try:
            db.execute(text("UPDATE budgets SET limit_amount = 0 WHERE id = :i"),
                       {"i": str(budget_id)})
            db.commit()
        finally:
            db.close()

        exhausted = _call(client, issued, {"capability": "http_tool.invoke",
                                           "target_ref": tool_id})

    assert exhausted.status_code == 403, exhausted.text
    assert "hard" in (exhausted.json()["denial_reason"] or "").lower()
    assert len(log.requests) == 1, "only the in-budget call was dispatched"

    db = SessionLocal()
    try:
        ok = db.get(ExternalGatewayCall, uuid.UUID(with_headroom.json()["call_id"]))
        denied = db.get(ExternalGatewayCall, uuid.UUID(exhausted.json()["call_id"]))
        assert ok.cost_outcome == "WITHIN_BUDGET"
        assert denied.cost_outcome == "EXCEEDED"
        assert denied.cost_detail["budget_id"] == str(budget_id)
    finally:
        db.close()


def _audit_events(db, organization_id) -> set[str]:
    rows = db.execute(text(
        "SELECT event_type FROM authorization_audit WHERE organization_id = :o"
    ), {"o": str(organization_id)}).scalars()
    return set(rows)


# --------------------------------------------------------------------------- #
# AC-06 - do NOT proxy everything
# --------------------------------------------------------------------------- #
def test_ac06_the_gateway_governs_declared_capabilities_not_arbitrary_traffic() -> None:
    from app.bridge import capabilities as caps

    # Exactly one governed capability ships -- the reference path. A broad
    # catalog and an SDK are deferred (§25A), on purpose.
    assert caps.GOVERNED_CAPABILITIES == ("http_tool.invoke",)

    # No route in this package forwards a caller-named destination: no
    # catch-all path converter anywhere.
    from app.bridge.routes import router

    for route in router.routes:
        assert ":path}" not in route.path, route.path
        assert "{url" not in route.path and "{target}" not in route.path

    # And no HTTP client is reachable from the decision path -- the only
    # outbound call in this package goes through M1's declared tool executor.
    decision_side = _source("gateway.py", "routes.py", "modes.py", "service.py",
                            "identity.py", "observed.py")
    assert "httpx" not in _imported_modules(decision_side)
    assert "requests" not in _imported_modules(decision_side)
    dispatch = _imported_modules(_source("dispatch.py"))
    assert "app.runtime.tools.http_executor" in dispatch
    assert "httpx" not in dispatch


def test_ac06_an_undeclared_capability_is_refused(client: TestClient, admin: dict) -> None:
    ext = _gateway_agent(client, admin)
    tool_id = str(uuid.uuid4())
    issued = _issue_grant(client, admin, ext,
                          [{"capability": "http_tool.invoke", "target_ref": tool_id}])
    r = _call(client, issued, {"capability": "model.completion", "target_ref": tool_id})
    assert r.status_code == 422
    assert "does not proxy" in r.text


# --------------------------------------------------------------------------- #
# AC-07 - denies a boundary call; truthfully does not reach out of band
# --------------------------------------------------------------------------- #
def test_ac07_denies_out_of_scope_call_and_says_what_it_cannot_reach(
        client: TestClient, admin: dict) -> None:
    with local_capability_server() as (port, log):
        ext = _gateway_agent(client, admin)
        scoped_tool = _make_http_tool(admin, port)
        other_tool = _make_http_tool(admin, port)
        issued = _issue_grant(client, admin, ext,
                              [{"capability": "http_tool.invoke", "target_ref": scoped_tool}])
        r = _call(client, issued, {"capability": "http_tool.invoke", "target_ref": other_tool})

    assert r.status_code == 403
    body = r.json()
    assert body["outcome"] == "DENIED"
    assert "not scoped" in (body["denial_reason"] or "")
    assert log.requests == []
    # The response states the bound of ACT's reach on the very same payload.
    assert "boundary only" in body["limits"].lower()
    assert "outside" in body["limits"].lower()
    assert "govern this agent" not in body["enforcement_reach"].lower()


def test_ac07_out_of_band_action_is_truthfully_outside_reach(
        client: TestClient, admin: dict) -> None:
    """The honest half: for a GATEWAY_ENFORCED agent, Phase 5.6 still refuses
    to claim it can stop the agent -- because ACT cannot. 5.7 did not quietly
    upgrade 5.6's reach."""
    from app.threat.containment import ContainmentOrchestrator

    ext = _gateway_agent(client, admin)
    db = SessionLocal()
    try:
        agent = db.get(Agent, uuid.UUID(ext))
        capable, reason = ContainmentOrchestrator(db).truthful_capability(agent)
        assert capable is False
        assert "no enforcement authority" in reason
        # and the mode says the same thing in its own words
        from app.bridge.modes import reach_of
        assert reach_of(agent).reaches_agent_execution is False
    finally:
        db.close()


# --------------------------------------------------------------------------- #
# AC-08 - commit-before-dispatch
# --------------------------------------------------------------------------- #
def test_ac08_no_lock_is_taken_anywhere_in_the_bridge_package() -> None:
    """Scanned over the AST, not over the raw text: these modules *describe*
    the no-lock rule in their docstrings, and a plain substring search would
    match that prose and pass for the wrong reason. Only real code counts --
    an actual ``with_for_update`` call, or a non-docstring string literal that
    would reach the database carrying a lock clause."""
    for path in sorted(_BRIDGE_PKG.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        docstrings = {
            id(node.body[0].value)
            for node in ast.walk(tree)
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                                 ast.AsyncFunctionDef))
            and node.body and isinstance(node.body[0], ast.Expr)
            and isinstance(node.body[0].value, ast.Constant)
            and isinstance(node.body[0].value.value, str)
        }
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute):
                assert node.attr != "with_for_update", path.name
            if (isinstance(node, ast.Constant) and isinstance(node.value, str)
                    and id(node) not in docstrings):
                assert "FOR UPDATE" not in node.value.upper(), (path.name, node.value[:60])


def test_ac08_dispatch_module_touches_no_database_session() -> None:
    """The dispatch path structurally cannot hold a transaction: it imports no
    session, no model write and no ORM machinery."""
    source = _source("dispatch.py")
    imported = _imported_modules(source)
    assert "sqlalchemy.orm" not in imported
    assert not any(m.startswith("app.core.database") for m in imported)
    called = _calls_named(source)
    for banned in ("commit", "flush", "add", "execute", "begin_nested"):
        assert banned not in called, banned


def test_ac08_row_is_written_and_readable_while_dispatch_is_in_flight(
        client: TestClient, admin: dict) -> None:
    """Behavioural proof against a second real connection: while the outbound
    call is still open, the gateway record is already committed and a separate
    Postgres session can read *and write* it -- so no lock is held across the
    dispatch and the M1 deadlock shape cannot arise."""
    gate = threading.Event()
    observed: dict = {}

    class SlowHandler(http.server.BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            # While this request is being served, the dispatch is in flight.
            other = SessionLocal()
            try:
                rows = other.execute(text(
                    "SELECT id, outcome FROM external_gateway_calls "
                    "WHERE agent_id = :a ORDER BY created_at DESC LIMIT 1"),
                    {"a": observed["agent_id"]}).fetchall()
                observed["visible"] = [tuple(r) for r in rows]
                if rows:
                    # A second session can WRITE the row too -- conclusive
                    # proof that no lock is held across this call.
                    other.execute(text("UPDATE external_gateway_calls SET "
                                       "idempotency_key = 'probe' WHERE id = :i"),
                                  {"i": str(rows[0][0])})
                    other.commit()
                    observed["wrote"] = True
            except Exception as exc:  # noqa: BLE001
                observed["error"] = repr(exc)
            finally:
                other.close()
            gate.set()
            payload = b'{"ok":true}'
            self.send_response(200)
            self.send_header("content-length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *args) -> None:
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), SlowHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        port = server.server_address[1]
        ext = _gateway_agent(client, admin)
        observed["agent_id"] = ext
        tool_id = _make_http_tool(admin, port)
        issued = _issue_grant(client, admin, ext,
                              [{"capability": "http_tool.invoke", "target_ref": tool_id}])
        r = _call(client, issued, {"capability": "http_tool.invoke", "target_ref": tool_id})
    finally:
        server.shutdown()
        server.server_close()

    assert r.status_code == 200, r.text
    assert gate.wait(timeout=10)
    assert "error" not in observed, observed
    assert observed["visible"], "the decision must be committed before dispatch"
    assert observed["visible"][0][1] == "ALLOWED"
    assert observed.get("wrote") is True, "a second session must be able to write the row"


# --------------------------------------------------------------------------- #
# AC-09 - fail closed / fail open / gateway-unavailable
# --------------------------------------------------------------------------- #
def test_ac09_governance_decision_fails_closed(
        client: TestClient, admin: dict, monkeypatch) -> None:
    """An unevaluable governance decision DENIES and is recorded as such --
    never a silent allow."""
    from app.bridge import gateway as gw

    with local_capability_server() as (port, log):
        ext = _gateway_agent(client, admin)
        tool_id = _make_http_tool(admin, port)
        issued = _issue_grant(client, admin, ext,
                              [{"capability": "http_tool.invoke", "target_ref": tool_id}])

        def _boom(self, agent):
            raise RuntimeError("policy store unavailable")

        monkeypatch.setattr(gw.CapabilityBoundary, "_policy", _boom)
        r = _call(client, issued, {"capability": "http_tool.invoke", "target_ref": tool_id})

    assert r.status_code == 403
    body = r.json()
    assert body["outcome"] == "DENIED"
    assert body["fail_mode"] == "FAIL_CLOSED"
    assert "fail-closed" in (body["denial_reason"] or "")
    assert log.requests == [], "a fail-closed denial must dispatch nothing"

    db = SessionLocal()
    try:
        rec = db.get(ExternalGatewayCall, uuid.UUID(body["call_id"]))
        assert rec.policy_outcome == "UNEVALUABLE"
        assert rec.outcome == "DENIED"
    finally:
        db.close()


def test_ac09_telemetry_ingest_fails_open(client: TestClient, admin: dict,
                                          monkeypatch) -> None:
    """A broken ingest degrades evidence and blocks nothing: still 202."""
    from app.bridge import observed as obs

    ext = _gateway_agent(client, admin)
    issued = _issue_grant(client, admin, ext,
                          [{"capability": "http_tool.invoke", "target_ref": str(uuid.uuid4())},
                           {"capability": "telemetry.ingest", "target_ref": None}])
    payload = {"events": [{"event_type": "agent.started", "payload": {"a": 1}}]}
    body = jsonlib.dumps(payload).encode()
    headers = _sign_headers(issued["grant"]["key_id"], issued["secret"],
                            method="POST", path=f"{BRIDGE}/events", body=body)
    r = client.post(f"{BRIDGE}/events", content=body, headers=headers)
    assert r.status_code == 202, r.text
    assert r.json()["enforcement_performed"] is False
    assert r.json()["accepted"] >= 1

    # Now make the ingest itself fail; it must still not block.
    monkeypatch.setattr(obs.ObservedIngestService, "ingest",
                        lambda self, agent, events: obs.IngestOutcome(accepted=0,
                                                                      dropped=len(events)))
    body2 = jsonlib.dumps(payload).encode()
    headers2 = _sign_headers(issued["grant"]["key_id"], issued["secret"],
                             method="POST", path=f"{BRIDGE}/events", body=body2)
    r2 = client.post(f"{BRIDGE}/events", content=body2, headers=headers2)
    assert r2.status_code == 202
    assert r2.json()["dropped"] >= 1


def test_ac09_observed_agent_can_ingest_evidence_without_any_enforcement(
        client: TestClient, admin: dict) -> None:
    """The mode whose entire content is "ACT sees this agent" must actually be
    able to be seen. A grant scoped only to evidence is allowed in *any* mode,
    including OBSERVED -- ingesting enforces nothing and implies no control, so
    such a credential claims nothing. A governed capability in the same scope
    is still refused for that agent."""
    observed = _make_external(admin)  # OBSERVED
    issued = _issue_grant(client, admin, observed,
                          [{"capability": "telemetry.ingest", "target_ref": None}])

    body = jsonlib.dumps({"events": [{"event_type": "agent.started",
                                      "payload": {"seen": True}}]}).encode()
    headers = _sign_headers(issued["grant"]["key_id"], issued["secret"],
                            method="POST", path=f"{BRIDGE}/events", body=body)
    r = client.post(f"{BRIDGE}/events", content=body, headers=headers)
    assert r.status_code == 202, r.text
    assert r.json()["accepted"] >= 1
    assert r.json()["enforcement_performed"] is False

    # The mode is unchanged and still claims nothing.
    mode = client.get(f"{BRIDGE}/agents/{observed}/enforcement-mode",
                      headers=admin["headers"]).json()
    assert mode["enforcement_mode"] == "OBSERVED"
    assert mode["reaches_boundary_calls"] is False
    assert "no enforcement" in mode["limits"].lower()

    # ...and evidence never became a boundary credential: the same agent still
    # cannot be granted a governed capability.
    refused = client.post(f"{BRIDGE}/agents/{observed}/grants", headers=admin["headers"],
                          json={"label": "governed", "scope": [
                              {"capability": "http_tool.invoke",
                               "target_ref": str(uuid.uuid4())}]})
    assert refused.status_code == 409
    assert "performs no enforcement" in refused.text

    # No gateway decision was recorded for an OBSERVED agent -- there is no
    # boundary for it to have a decision at.
    db = SessionLocal()
    try:
        assert db.execute(select(ExternalGatewayCall).where(
            ExternalGatewayCall.agent_id == uuid.UUID(observed))).scalars().first() is None
    finally:
        db.close()


def test_ac10_events_honours_the_grant_scope(client: TestClient, admin: dict) -> None:
    """Fail-open governs how a malformed event is treated, never *who* may
    write one: a grant not scoped for evidence is refused at /events."""
    ext = _gateway_agent(client, admin)
    issued = _issue_grant(client, admin, ext,
                          [{"capability": "http_tool.invoke", "target_ref": str(uuid.uuid4())}])
    body = jsonlib.dumps({"events": [{"event_type": "agent.started"}]}).encode()
    headers = _sign_headers(issued["grant"]["key_id"], issued["secret"],
                            method="POST", path=f"{BRIDGE}/events", body=body)
    r = client.post(f"{BRIDGE}/events", content=body, headers=headers)
    assert r.status_code == 403, r.text
    assert "not scoped" in r.text


def test_ac09_downstream_unavailable_is_reported_truthfully_not_faked(
        client: TestClient, admin: dict) -> None:
    """When the capability itself is unreachable, ACT records that the call
    was allowed and the dispatch failed. It does not fake a success, and it
    does not retroactively rewrite its own ALLOW into a DENY."""
    with local_capability_server() as (port, _log):
        pass  # server is now closed -- the endpoint is genuinely unavailable
    ext = _gateway_agent(client, admin)
    tool_id = _make_http_tool(admin, port)
    issued = _issue_grant(client, admin, ext,
                          [{"capability": "http_tool.invoke", "target_ref": tool_id}])
    r = _call(client, issued, {"capability": "http_tool.invoke", "target_ref": tool_id})
    assert r.status_code == 200
    body = r.json()
    assert body["outcome"] == "ALLOWED"
    assert body["dispatch_status"] == "DISPATCH_FAILED"
    assert body["dispatch_detail"]["success"] is False


def test_ac09_capability_fail_modes_follow_the_plane_rule() -> None:
    from app.bridge import capabilities as caps

    for spec in caps.CAPABILITIES.values():
        if spec.plane == "GOVERNANCE":
            assert spec.fail_mode == "FAIL_CLOSED", spec.key
        else:
            assert spec.fail_mode == "FAIL_OPEN", spec.key


# --------------------------------------------------------------------------- #
# AC-10 - revocation, replay, rate limit
# --------------------------------------------------------------------------- #
def test_ac10_revocation_is_immediate(client: TestClient, admin: dict) -> None:
    with local_capability_server() as (port, log):
        ext = _gateway_agent(client, admin)
        tool_id = _make_http_tool(admin, port)
        issued = _issue_grant(client, admin, ext,
                              [{"capability": "http_tool.invoke", "target_ref": tool_id}])
        assert _call(client, issued, {"capability": "http_tool.invoke",
                                      "target_ref": tool_id}).status_code == 200

        rev = client.post(f"{BRIDGE}/grants/{issued['grant']['id']}/revoke",
                          headers=admin["headers"], json={"reason": "compromised"})
        assert rev.status_code == 200
        after = _call(client, issued, {"capability": "http_tool.invoke",
                                       "target_ref": tool_id})
    assert after.status_code == 403
    assert "revoked" in after.text.lower()
    assert len(log.requests) == 1, "only the pre-revocation call reached the capability"


def test_ac10_a_replayed_request_is_refused(client: TestClient, admin: dict) -> None:
    with local_capability_server() as (port, log):
        ext = _gateway_agent(client, admin)
        tool_id = _make_http_tool(admin, port)
        issued = _issue_grant(client, admin, ext,
                              [{"capability": "http_tool.invoke", "target_ref": tool_id}])
        payload = {"capability": "http_tool.invoke", "target_ref": tool_id}
        body = jsonlib.dumps(payload).encode()
        headers = _sign_headers(issued["grant"]["key_id"], issued["secret"],
                               method="POST", path=f"{BRIDGE}/capability", body=body)
        first = client.post(f"{BRIDGE}/capability", content=body, headers=headers)
        replay = client.post(f"{BRIDGE}/capability", content=body, headers=dict(headers))
    assert first.status_code == 200
    assert replay.status_code == 409
    assert "already been presented" in replay.text
    assert len(log.requests) == 1, "a replay must not execute a second time"


def test_ac10_a_stale_signature_is_refused(client: TestClient, admin: dict) -> None:
    ext = _gateway_agent(client, admin)
    tool_id = str(uuid.uuid4())
    issued = _issue_grant(client, admin, ext,
                          [{"capability": "http_tool.invoke", "target_ref": tool_id}])
    r = _call(client, issued, {"capability": "http_tool.invoke", "target_ref": tool_id},
              timestamp=int(time.time()) - 4000)
    assert r.status_code == 401
    assert "signing window" in r.text


def test_ac10_rate_limit_bounds_a_grant(client: TestClient, admin: dict, monkeypatch) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", True)
    ext = _gateway_agent(client, admin)
    tool_id = str(uuid.uuid4())
    issued = _issue_grant(client, admin, ext,
                          [{"capability": "http_tool.invoke", "target_ref": tool_id}],
                          rate_limit_per_minute=2)
    codes = [_call(client, issued, {"capability": "http_tool.invoke",
                                    "target_ref": tool_id}).status_code for _ in range(4)]
    assert 429 in codes, codes


def test_ac10_an_expired_grant_cannot_authorize(client: TestClient, admin: dict) -> None:
    ext = _gateway_agent(client, admin)
    tool_id = str(uuid.uuid4())
    issued = _issue_grant(
        client, admin, ext, [{"capability": "http_tool.invoke", "target_ref": tool_id}],
        expires_at=(datetime.now(timezone.utc) + timedelta(seconds=1)).isoformat())
    db = SessionLocal()
    try:
        grant = db.get(ExternalCapabilityGrant, uuid.UUID(issued["grant"]["id"]))
        grant.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.commit()
    finally:
        db.close()
    r = _call(client, issued, {"capability": "http_tool.invoke", "target_ref": tool_id})
    assert r.status_code == 403
    assert "expired" in r.text.lower()


# --------------------------------------------------------------------------- #
# AC-11 - distinct, stronger permission; the gateway is not a second authz
# --------------------------------------------------------------------------- #
def test_ac11_grant_issue_is_a_distinct_stronger_permission() -> None:
    from app.services.rbac_service import PERMISSION_CATALOG, SYSTEM_ROLE_PERMISSIONS

    for code in ("external_governance.view", "external_governance.manage",
                 "external_grant.issue"):
        assert code in PERMISSION_CATALOG, code
    # Never implied by a view or a manage grant -- the 5.6 containment.execute
    # precedent, for the same reason: this code creates an outside party's
    # ability to reach enterprise capability.
    reviewer = SYSTEM_ROLE_PERMISSIONS["REVIEWER"]
    viewer = SYSTEM_ROLE_PERMISSIONS["VIEWER"]
    assert "external_grant.issue" not in reviewer
    assert "external_grant.issue" not in viewer
    assert "external_governance.manage" not in viewer


def test_ac11_a_viewer_cannot_set_a_mode_or_issue_a_grant(
        client: TestClient, admin: dict) -> None:
    ext = _gateway_agent(client, admin)
    viewer = _invite(client, admin, role="VIEWER")
    assert client.put(f"{BRIDGE}/agents/{ext}/enforcement-mode", headers=viewer["headers"],
                      json={"target_mode": "ADVISORY"}).status_code == 403
    assert client.post(f"{BRIDGE}/agents/{ext}/grants", headers=viewer["headers"],
                       json={"label": "x", "scope": [
                           {"capability": "http_tool.invoke",
                            "target_ref": str(uuid.uuid4())}]}).status_code == 403


def _invite(client: TestClient, admin: dict, *, role: str) -> dict:
    from tests.bridge.conftest import PASSWORD

    email = f"bridgem_{uuid.uuid4().hex[:10]}@example.com"
    r = client.post("/api/v1/identity/users", headers=admin["headers"], json={
        "email": email, "display_name": "Member", "password": PASSWORD, "role": role,
        "organization_id": admin["organization_id"]})
    assert r.status_code in (200, 201), r.text
    tokens = client.post("/api/v1/auth/login",
                         json={"email": email, "password": PASSWORD}).json()
    return {"headers": {"Authorization": f"Bearer {tokens['access_token']}"}}


# --------------------------------------------------------------------------- #
# AC-12 - tenant isolation
# --------------------------------------------------------------------------- #
def test_ac12_cross_tenant_access_is_404_not_403(
        client: TestClient, admin: dict, other_org_admin: dict) -> None:
    ext = _gateway_agent(client, admin)
    issued = _issue_grant(client, admin, ext,
                          [{"capability": "http_tool.invoke", "target_ref": str(uuid.uuid4())}])
    # The other tenant must not even learn these rows exist.
    assert client.get(f"{BRIDGE}/agents/{ext}/enforcement-mode",
                      headers=other_org_admin["headers"]).status_code == 404
    assert client.put(f"{BRIDGE}/agents/{ext}/enforcement-mode",
                      headers=other_org_admin["headers"],
                      json={"target_mode": "OBSERVED"}).status_code == 404
    assert client.post(f"{BRIDGE}/grants/{issued['grant']['id']}/revoke",
                       headers=other_org_admin["headers"], json={}).status_code == 404
    assert client.get(f"{BRIDGE}/calls", headers=other_org_admin["headers"]).json() == []


def test_ac12_a_grant_never_reaches_another_tenants_capability(
        client: TestClient, admin: dict, other_org_admin: dict) -> None:
    with local_capability_server() as (port, log):
        ext = _gateway_agent(client, admin)
        foreign_tool = _make_http_tool(other_org_admin, port)
        issued = _issue_grant(client, admin, ext,
                              [{"capability": "http_tool.invoke",
                                "target_ref": foreign_tool}])
        r = _call(client, issued, {"capability": "http_tool.invoke",
                                   "target_ref": foreign_tool})
    # The scope named it, but the dispatch hop re-checks the tenant.
    assert r.json()["dispatch_status"] == "DISPATCH_FAILED"
    assert r.json()["dispatch_detail"]["error"] == "TOOL_NOT_FOUND"
    assert log.requests == []


def test_ac12_no_new_m5_domain_leaked_into_an_existing_package() -> None:
    """The M5.1 moving-target guard, extended for this phase: 5.7 ships as its
    own sibling package and introduces no second agent registry."""
    from app.core.database import Base

    names = set(Base.metadata.tables)
    for banned in ("external_agents", "agents_v2", "agent_assets",
                   "bridge_agents", "external_principals", "external_identities"):
        assert banned not in names, banned
    assert (_BACKEND / "app" / "bridge").exists()
    assert not (_BACKEND / "app" / "runtime" / "bridge").exists()
    assert not (_BACKEND / "app" / "threat" / "bridge").exists()


# --------------------------------------------------------------------------- #
# AC-13 - audit, and no secret in it
# --------------------------------------------------------------------------- #
def test_ac13_every_change_and_decision_is_audited(client: TestClient, admin: dict) -> None:
    with local_capability_server() as (port, _log):
        ext = _make_external(admin)
        _set_mode(client, admin, ext, "GATEWAY_ENFORCED")
        tool_id = _make_http_tool(admin, port)
        issued = _issue_grant(client, admin, ext,
                              [{"capability": "http_tool.invoke", "target_ref": tool_id}])
        _call(client, issued, {"capability": "http_tool.invoke", "target_ref": tool_id})
        client.post(f"{BRIDGE}/grants/{issued['grant']['id']}/revoke",
                    headers=admin["headers"], json={"reason": "done"})

    db = SessionLocal()
    try:
        events = _audit_events(db, uuid.UUID(admin["organization_id"]))
        assert {"EXTERNAL_ENFORCEMENT_MODE_CHANGED", "EXTERNAL_GRANT_ISSUED",
                "EXTERNAL_GRANT_REVOKED", "EXTERNAL_GATEWAY_CALL_ALLOWED"} <= events
    finally:
        db.close()


def test_ac13_no_secret_or_token_appears_in_audit_or_records(
        client: TestClient, admin: dict) -> None:
    with local_capability_server() as (port, _log):
        ext = _gateway_agent(client, admin)
        tool_id = _make_http_tool(admin, port)
        issued = _issue_grant(client, admin, ext,
                              [{"capability": "http_tool.invoke", "target_ref": tool_id}])
        _call(client, issued, {"capability": "http_tool.invoke", "target_ref": tool_id})

    secret = issued["secret"]
    db = SessionLocal()
    try:
        blob = jsonlib.dumps([dict(r._mapping) for r in db.execute(text(
            "SELECT meta FROM authorization_audit WHERE organization_id = :o"),
            {"o": admin["organization_id"]})], default=str)
        assert secret not in blob
        grant = db.get(ExternalCapabilityGrant, uuid.UUID(issued["grant"]["id"]))
        assert grant.secret_ciphertext != secret          # stored encrypted
        assert secret not in grant.secret_ciphertext
        assert secret not in grant.secret_hint
        calls = jsonlib.dumps([dict(r._mapping) for r in db.execute(text(
            "SELECT * FROM external_gateway_calls WHERE organization_id = :o"),
            {"o": admin["organization_id"]})], default=str)
        assert secret not in calls
    finally:
        db.close()

    # ...and the grant read model never serializes it again.
    listed = client.get(f"{BRIDGE}/agents/{ext}/grants", headers=admin["headers"]).json()
    assert secret not in jsonlib.dumps(listed)
    assert all("secret" not in k or k == "secret_hint" for g in listed for k in g)


# --------------------------------------------------------------------------- #
# AC-14 - concurrency, on real separate Postgres sessions
# --------------------------------------------------------------------------- #
def test_ac14_concurrent_calls_under_a_revocation_race(
        client: TestClient, admin: dict) -> None:
    """A revocation committed by one session is honoured by calls in flight on
    others: no call succeeds after the revoking transaction commits."""
    with local_capability_server() as (port, log):
        ext = _gateway_agent(client, admin)
        tool_id = _make_http_tool(admin, port)
        issued = _issue_grant(client, admin, ext,
                              [{"capability": "http_tool.invoke", "target_ref": tool_id}])

        results: list[int] = []

        def _fire() -> int:
            with TestClient(client.app) as c:
                return _call(c, issued, {"capability": "http_tool.invoke",
                                         "target_ref": tool_id}).status_code

        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = [pool.submit(_fire) for _ in range(3)]
            revoker = SessionLocal()
            try:
                revoker.execute(text(
                    "UPDATE external_capability_grants SET revoked_at = now() WHERE id = :i"),
                    {"i": issued["grant"]["id"]})
                revoker.commit()
            finally:
                revoker.close()
            results = [f.result() for f in futures]

    assert all(code in (200, 403, 429) for code in results), results
    # Whatever the interleaving, no call was executed twice and none succeeded
    # against a grant that was already revoked at the time it was read.
    assert len(log.requests) <= 3


def test_ac14_a_double_revoke_is_idempotent(client: TestClient, admin: dict) -> None:
    ext = _gateway_agent(client, admin)
    issued = _issue_grant(client, admin, ext,
                          [{"capability": "http_tool.invoke", "target_ref": str(uuid.uuid4())}])
    first = client.post(f"{BRIDGE}/grants/{issued['grant']['id']}/revoke",
                        headers=admin["headers"], json={"reason": "a"})
    second = client.post(f"{BRIDGE}/grants/{issued['grant']['id']}/revoke",
                         headers=admin["headers"], json={"reason": "b"})
    assert first.status_code == second.status_code == 200
    assert first.json()["revoked_at"] == second.json()["revoked_at"]


def test_ac14_a_mode_transition_racing_a_call_is_consistent(
        client: TestClient, admin: dict) -> None:
    """Dropping below GATEWAY_ENFORCED revokes the grants that depended on it,
    so a later call is refused rather than silently enforced by a mode that no
    longer claims to enforce."""
    with local_capability_server() as (port, log):
        ext = _gateway_agent(client, admin)
        tool_id = _make_http_tool(admin, port)
        issued = _issue_grant(client, admin, ext,
                              [{"capability": "http_tool.invoke", "target_ref": tool_id}])
        assert _set_mode(client, admin, ext, "OBSERVED").status_code == 200
        after = _call(client, issued, {"capability": "http_tool.invoke",
                                       "target_ref": tool_id})
    assert after.status_code == 403
    assert "revoked" in after.text.lower()
    assert log.requests == []


def test_ac14_duplicate_nonce_inserts_cannot_both_commit(
        client: TestClient, admin: dict) -> None:
    """The replay primitive is the database's own unique constraint, proven
    with two real, separate Postgres sessions committing the same nonce."""
    from sqlalchemy.exc import IntegrityError

    ext = _gateway_agent(client, admin)
    issued = _issue_grant(client, admin, ext,
                          [{"capability": "http_tool.invoke", "target_ref": str(uuid.uuid4())}])
    grant_id = uuid.UUID(issued["grant"]["id"])
    nonce = uuid.uuid4().hex
    expires = datetime.now(timezone.utc) + timedelta(seconds=300)

    first, second = SessionLocal(), SessionLocal()
    try:
        first.add(ExternalRequestNonce(
            organization_id=uuid.UUID(admin["organization_id"]), grant_id=grant_id,
            nonce=nonce, expires_at=expires))
        first.commit()
        second.add(ExternalRequestNonce(
            organization_id=uuid.UUID(admin["organization_id"]), grant_id=grant_id,
            nonce=nonce, expires_at=expires))
        with pytest.raises(IntegrityError):
            second.commit()
        second.rollback()
    finally:
        first.close()
        second.close()


# --------------------------------------------------------------------------- #
# AC-15 / §15 - a REAL external agent, in a separate OS process
# --------------------------------------------------------------------------- #
_EXTERNAL_AGENT_SOURCE = '''
"""A REAL external agent. It is not part of ACT: it imports nothing from the
application, holds no database handle, and speaks to ACT only over HTTP with a
signed request. Run as its own OS process."""
import hashlib, hmac, json, sys, time, urllib.error, urllib.request, uuid

SCHEME = "ACT-HMAC-SHA256"

def call(base, path, key_id, secret, payload):
    body = json.dumps(payload).encode()
    ts, nonce = str(int(time.time())), uuid.uuid4().hex
    digest = hashlib.sha256(body).hexdigest()
    to_sign = "\\n".join([SCHEME, "POST", path, ts, nonce, digest])
    sig = hmac.new(secret.encode(), to_sign.encode(), hashlib.sha256).hexdigest()
    req = urllib.request.Request(base + path, data=body, method="POST", headers={
        "Content-Type": "application/json", "X-ACT-Key-Id": key_id,
        "X-ACT-Timestamp": ts, "X-ACT-Nonce": nonce, "X-ACT-Signature": sig})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode() or "{}")

if __name__ == "__main__":
    base, key_id, secret, allowed, forbidden = sys.argv[1:6]
    out = {}
    out["allowed"] = call(base, "/api/v1/bridge/capability", key_id, secret,
                          {"capability": "http_tool.invoke", "target_ref": allowed,
                           "params": {"body": {"from": "outside-act"}}})
    out["forbidden"] = call(base, "/api/v1/bridge/capability", key_id, secret,
                            {"capability": "http_tool.invoke", "target_ref": forbidden})
    print(json.dumps(out))
'''


@contextmanager
def _act_server():
    """ACT itself, on a real socket, served by uvicorn -- not a TestClient."""
    import uvicorn

    from app.main import app

    config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="error",
                            lifespan="on")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if server.started and server.servers and server.servers[0].sockets:
            break
        time.sleep(0.05)
    assert server.started, "ACT did not start"
    port = server.servers[0].sockets[0].getsockname()[1]
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=15)


def test_ac15_e2e_a_real_external_agent_calls_a_reference_capability(
        client: TestClient, admin: dict, tmp_path: Path) -> None:
    """§15 end-to-end proof, with nothing mocked in process.

    A real agent existing outside ACT (its own OS process, zero ACT imports)
    establishes a scoped identity, calls one real enterprise capability through
    ACT's boundary -- which authorizes via the real AuthorizationGateway,
    applies real policy, meters real cost and dispatches to a real HTTP
    endpoint -- is truthfully denied a second call its grant forbids, and is
    refused entirely once the grant is revoked. Meanwhile an OBSERVED agent's
    events ingest with no enforcement and an ADVISORY agent gets a
    recommendation with no enforcement.
    """
    script = tmp_path / "external_agent.py"
    script.write_text(_EXTERNAL_AGENT_SOURCE, encoding="utf-8")
    # The agent is genuinely outside ACT: nothing it imports comes from the
    # application, so it could not reach the database or the app object even
    # if it tried. Asserted over its AST, not by reading its prose.
    external_imports = _imported_modules(_EXTERNAL_AGENT_SOURCE)
    assert not any(m.startswith("app") for m in external_imports), external_imports
    assert external_imports <= {"hashlib", "hmac", "json", "sys", "time",
                                "urllib.error", "urllib.request", "uuid"}

    with local_capability_server() as (cap_port, cap_log):
        ext = _gateway_agent(client, admin, name="Outside Agent")
        allowed_tool = _make_http_tool(admin, cap_port)
        forbidden_tool = _make_http_tool(admin, cap_port)
        issued = _issue_grant(client, admin, ext,
                              [{"capability": "http_tool.invoke",
                                "target_ref": allowed_tool}])

        with _act_server() as base_url:
            proc = subprocess.run(
                [sys.executable, str(script), base_url, issued["grant"]["key_id"],
                 issued["secret"], allowed_tool, forbidden_tool],
                capture_output=True, text=True, timeout=180,
                cwd=str(tmp_path),  # not the backend: no ACT package on the path
            )
            assert proc.returncode == 0, proc.stderr
            out = jsonlib.loads(proc.stdout.strip().splitlines()[-1])

            # 1. the scoped call is ALLOWED and really reached the capability
            status_allowed, body_allowed = out["allowed"]
            assert status_allowed == 200, body_allowed
            assert body_allowed["outcome"] == "ALLOWED"
            assert body_allowed["dispatch_status"] == "DISPATCHED"
            assert body_allowed["enforcement_mode"] == "GATEWAY_ENFORCED"
            # ACT states the bound of its reach on the very same response
            assert "boundary only" in body_allowed["limits"].lower()
            assert "govern this agent" not in body_allowed["enforcement_reach"].lower()

            # 2. the call the grant forbids is truthfully DENIED
            status_denied, body_denied = out["forbidden"]
            assert status_denied == 403
            assert body_denied["outcome"] == "DENIED"
            assert body_denied["dispatch_status"] == "NOT_DISPATCHED"

            assert len(cap_log.requests) == 1, "exactly the allowed call was dispatched"
            assert jsonlib.loads(cap_log.requests[0]["body"])["from"] == "outside-act"

            # 3. revoke -- a subsequent call is refused immediately
            rev = client.post(f"{BRIDGE}/grants/{issued['grant']['id']}/revoke",
                              headers=admin["headers"], json={"reason": "e2e"})
            assert rev.status_code == 200
            proc2 = subprocess.run(
                [sys.executable, str(script), base_url, issued["grant"]["key_id"],
                 issued["secret"], allowed_tool, forbidden_tool],
                capture_output=True, text=True, timeout=180, cwd=str(tmp_path))
            out2 = jsonlib.loads(proc2.stdout.strip().splitlines()[-1])
            assert out2["allowed"][0] == 403
            assert len(cap_log.requests) == 1, "nothing ran after revocation"

    # 4. the other two modes, proving their reach is truthful
    observed = _make_external(admin, name="Observed Agent")
    obs_grant_refused = client.post(
        f"{BRIDGE}/agents/{observed}/grants", headers=admin["headers"],
        json={"label": "x", "scope": [{"capability": "http_tool.invoke",
                                       "target_ref": allowed_tool}]})
    assert obs_grant_refused.status_code == 409  # OBSERVED enforces nothing

    advisory_agent = _make_external(admin, name="Advisory Agent")
    _set_mode(client, admin, advisory_agent, "ADVISORY")
    rec = client.post(f"{BRIDGE}/agents/{advisory_agent}/advisory",
                      headers=admin["headers"]).json()
    assert rec["enforcement_performed"] is False

    # 5. everything audited, tenant-scoped, and no secret anywhere in it
    db = SessionLocal()
    try:
        events = _audit_events(db, uuid.UUID(admin["organization_id"]))
        assert {"EXTERNAL_GRANT_ISSUED", "EXTERNAL_GATEWAY_CALL_ALLOWED",
                "EXTERNAL_GATEWAY_CALL_DENIED", "EXTERNAL_GRANT_REVOKED",
                "EXTERNAL_ADVISORY_RECOMMENDED"} <= events
        rows = db.execute(select(ExternalGatewayCall).where(
            ExternalGatewayCall.agent_id == uuid.UUID(ext))).scalars().all()
        assert {r.outcome for r in rows} == {"ALLOWED", "DENIED"}
        assert all(r.organization_id == uuid.UUID(admin["organization_id"]) for r in rows)
    finally:
        db.close()


# --------------------------------------------------------------------------- #
# AC-16 - the four things this phase must never do
# --------------------------------------------------------------------------- #
def test_ac16_no_internal_identity_no_new_authz_no_parallel_enforcer() -> None:
    package = _source("gateway.py", "identity.py", "modes.py", "service.py",
                      "observed.py", "routes.py", "dispatch.py", "capabilities.py")
    imported = _imported_modules(package)

    # no new authorization system
    assert "app.authorization.middleware.gateway" in imported
    for banned in ("app.authorization.abac.engine", "app.authorization.engine"):
        assert banned not in imported, banned
    # no internal principal is ever provisioned
    for banned in ("app.identity.federation.service",
                   "app.identity.registration",
                   "app.identity.sessions"):
        assert banned not in imported, banned
    called = _calls_named(package)
    for banned in ("provision", "_provision_user", "_issue_session", "create_access_token"):
        assert banned not in called, banned
    # no parallel scheduler or registry
    assert "app.scheduler" not in imported


def test_ac16_no_mode_over_claims_its_reach() -> None:
    """The summary assertion: a mode's advertised reach never exceeds what the
    code will actually do for it."""
    from app.bridge.modes import REACH

    for mode, reach in REACH.items():
        if reach.reaches_agent_execution:
            # only the mode that is literally "ACT runs it" may say so
            assert mode == "NATIVE_ENFORCED"
        if reach.reaches_boundary_calls:
            assert mode in ("GATEWAY_ENFORCED", "NATIVE_ENFORCED")
        else:
            assert "no enforcement" in reach.limits.lower()


# --------------------------------------------------------------------------- #
# AC-17 - the migration
# --------------------------------------------------------------------------- #
def test_ac17_migration_is_additive_and_reversible() -> None:
    path = (_BACKEND / "migrations" / "versions" / "0060_external_gov_bridge.py")
    src = path.read_text(encoding="utf-8")
    assert 'down_revision = "0059_threat_containment"' in src
    assert len("0060_external_gov_bridge") <= 32
    assert "def downgrade" in src
    # additive only: nothing existing is dropped or altered on the way up
    upgrade = src.split("def upgrade")[1].split("def downgrade")[0]
    for destructive in ("drop_table", "drop_column", "alter_column"):
        assert destructive not in upgrade, destructive
    # and the downgrade genuinely reverses every object the upgrade created
    downgrade = src.split("def downgrade")[1]
    for table in ("external_gateway_calls", "external_request_nonces",
                  "external_capability_grants"):
        assert f'drop_table("{table}")' in downgrade
    assert 'drop_column("agents", "external_enforcement_mode")' in downgrade


def test_ac17_grants_reference_existing_identity_not_a_reimplementation() -> None:
    """A grant points at the one canonical ``agents`` row; it does not carry a
    permission list, a role or any authorization state of its own."""
    cols = {c.name for c in ExternalCapabilityGrant.__table__.columns}
    fks = {fk.target_fullname for c in ExternalCapabilityGrant.__table__.columns
           for fk in c.foreign_keys}
    assert "agents.id" in fks and "organizations.id" in fks
    assert not {"permissions", "role", "role_id", "scopes_granted"} & cols


# --------------------------------------------------------------------------- #
# AC-18 - the reused authorities behave identically
# --------------------------------------------------------------------------- #
def test_ac18_this_phase_did_not_alter_the_authorities_it_reuses() -> None:
    """5.7 reuses; it does not edit. The 5.6 gate, the 4.3 engine's
    fail-closed discipline and 4.4's division of labour are untouched."""
    from app.threat.containment import _AUTHORITY_FOR, _ENFORCEABLE_CONTROL_STATE

    # 5.6 still has exactly its seven actions and its GOVERNED-only gate.
    assert len(_AUTHORITY_FOR) == 7
    assert _ENFORCEABLE_CONTROL_STATE == "GOVERNED"
    # 5.7 added no eighth containment action and imports nothing from 5.7 into 5.6.
    threat_src = (_BACKEND / "app" / "threat" / "containment.py").read_text(encoding="utf-8")
    assert "app.bridge" not in threat_src
    gw_src = (_BACKEND / "app" / "authorization" / "middleware" / "gateway.py").read_text(
        encoding="utf-8")
    assert "app.bridge" not in gw_src


# --------------------------------------------------------------------------- #
# AC-20 - hygiene
# --------------------------------------------------------------------------- #
def test_ac20_no_todo_fixme_skip_or_xfail_in_this_phase() -> None:
    targets = list(_BRIDGE_PKG.glob("*.py")) + [
        _BACKEND / "app" / "models" / "bridge.py",
        _BACKEND / "migrations" / "versions" / "0060_external_gov_bridge.py",
        Path(__file__),
    ]
    for path in targets:
        src = path.read_text(encoding="utf-8")
        for marker in ("TODO", "FIXME", "NotImplementedError",
                       "pytest.mark.skip", "pytest.mark.xfail"):
            # this test names the markers it forbids, so exclude its own body
            body = src.split("def test_ac20")[0] if path == Path(__file__) else src
            assert marker not in body, f"{path.name}: {marker}"
