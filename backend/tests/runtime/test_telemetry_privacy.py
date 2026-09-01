"""Phase 4.8 tests -- telemetry privacy, retention & access governance.

The weight is on the guarantees, not the plumbing. **Gate F** is access
governance, so the load-bearing tests are: content view is a distinct, stronger,
audited permission; secrets are scrubbed before persistence in *every* mode
including FULL_CONTENT; chain-of-thought is never captured in any mode; the
conservative default never resolves to FULL_CONTENT; retention deletes telemetry
while the execution row and financial/audit evidence survive; and nothing here
can stop an execution.

Content-bearing executions are written directly rather than driven through the
HTTP pipeline -- these tests need controlled payloads (a planted secret, a
planted reasoning block) at controlled timestamps, and driving that through the
pipeline would measure the pipeline.
"""

from __future__ import annotations

import ast
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.models.rbac import AuthorizationAudit
from app.models.runtime import (
    AgentExecution,
    Environment,
    ExecutionMessage,
    ToolCall,
    TraceContent,
)
from app.telemetry_privacy.modes import CaptureMode, coerce
from app.telemetry_privacy.policy import resolve_capture_mode
from app.telemetry_privacy.redaction import redact_for_capture
from tests.runtime.test_behavioral_signals import _agent_setup, _register_org

RT = "/api/v1/runtime"
TEL = "/api/v1/runtime/telemetry"
OBS = "/api/v1/observability"
PASSWORD = "T3st!Passw0rd#Ok"
APP_ROOT = Path(__file__).resolve().parents[2] / "app"

NOW = datetime(2026, 8, 20, 12, 0, tzinfo=timezone.utc)
SECRET = "sk-live-abc123def456ghi789jkl012mno345"


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _org_and_agent(client: TestClient):
    org = _register_org(client, f"Privacy Org {uuid.uuid4().hex[:6]}")
    setup = _agent_setup(client, org)
    return org, setup


def _seed_content_execution(db: Session, setup: dict, org: dict, *,
                            prompt: str = "Summarise the patient chart",
                            secret: str | None = SECRET,
                            reasoning: bool = True,
                            at: datetime = NOW) -> AgentExecution:
    """One SUCCEEDED execution carrying content in every domain location:
    ``input_payload`` / ``output_payload`` on the row, an ``execution_messages``
    transcript, and a ``tool_calls`` summary. Optionally plants a secret and a
    chain-of-thought block."""
    row = AgentExecution(
        organization_id=uuid.UUID(org["organization_id"]),
        agent_id=uuid.UUID(setup["agent"]["id"]),
        agent_version_id=uuid.UUID(setup["version"]["id"]),
        deployment_id=uuid.UUID(setup["deployment"]["id"]),
        trigger_type="API", status="SUCCEEDED", duration_ms=120,
        loop_iterations=1, termination_reason="COMPLETED",
        input_payload={"prompt": prompt,
                       "headers": {"authorization": f"Bearer {secret}"} if secret else {}},
        output_payload={"completion": "The chart shows stable vitals.",
                        "api_key": secret} if secret else {"completion": "ok"},
    )
    db.add(row)
    db.flush()

    assistant_content = "Final answer: vitals stable."
    msg_user = ExecutionMessage(execution_id=row.id, sequence=0, role="user",
                                content=prompt, loop_iteration=0)
    assistant_body = dict(execution_id=row.id, sequence=1, role="assistant",
                          content=assistant_content, loop_iteration=1)
    if reasoning:
        assistant_body["tool_calls_requested"] = {
            "thinking": "the user probably wants a terse summary; I will hide this",
            "calls": [],
        }
    msg_assistant = ExecutionMessage(**assistant_body)
    db.add_all([msg_user, msg_assistant])

    call = ToolCall(
        execution_id=row.id, agent_id=uuid.UUID(setup["agent"]["id"]),
        tool_id=uuid.uuid4(), action="EXECUTE", status="ALLOWED",
        input_summary={"query": prompt, "token": secret} if secret else {"query": prompt},
        output_summary={"rows": 3},
    )
    # tool_id FK -> tools; use a real tool instead.
    tool = _tool(setup, db, org)
    call.tool_id = tool
    db.add(call)
    db.flush()
    db.execute(text("UPDATE agent_executions SET created_at = :t WHERE id = :i"),
               {"t": at, "i": row.id})
    db.commit()
    return row


def _tool(setup: dict, db: Session, org: dict) -> uuid.UUID:
    from app.models.runtime import Tool

    t = Tool(organization_id=uuid.UUID(org["organization_id"]),
             name=f"tool-{uuid.uuid4().hex[:8]}", display_name="T",
             tool_type="FUNCTION", description="d",
             input_schema={"type": "object", "properties": {}})
    db.add(t)
    db.flush()
    return t.id


def _set_capture(client: TestClient, org: dict, mode: str, **scope) -> dict:
    r = client.post(f"{TEL}/capture-policies", headers=org["headers"],
                    json={"mode": mode, **scope})
    assert r.status_code == 201, r.text
    return r.json()


def _content(client: TestClient, org: dict, execution_id) -> "tuple[int, dict]":
    r = client.get(f"{OBS}/traces/{execution_id}/content", headers=org["headers"])
    return r.status_code, (r.json() if r.content else {})


def _make_role(client: TestClient, admin: dict, permissions: list[str]) -> str:
    r = client.post("/api/v1/roles", headers=admin["headers"], json={
        "name": f"ROLE_TP_{uuid.uuid4().hex[:8].upper()}", "permissions": permissions})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _invite(client: TestClient, admin: dict) -> dict:
    email = f"tpm_{uuid.uuid4().hex[:10]}@example.com"
    r = client.post("/api/v1/identity/users", headers=admin["headers"], json={
        "email": email, "display_name": "M", "password": PASSWORD, "role": "VIEWER",
        "organization_id": admin["organization_id"]})
    assert r.status_code in (200, 201), r.text
    tokens = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD}).json()
    h = {"Authorization": f"Bearer {tokens['access_token']}"}
    me = client.get("/api/v1/auth/me", headers=h).json()
    return {"headers": h, "user_id": me["user"]["id"], "organization_id": admin["organization_id"]}


def _assign(client: TestClient, admin: dict, user_id: str, role_id: str) -> None:
    r = client.post("/api/v1/role-assignments", headers=admin["headers"], json={
        "user_id": user_id, "role_id": role_id, "scope": "ORGANIZATION"})
    assert r.status_code == 201, r.text


def _audits(db: Session, event: str, org_id: str) -> list[AuthorizationAudit]:
    return list(db.execute(
        select(AuthorizationAudit).where(
            AuthorizationAudit.event_type == event,
            AuthorizationAudit.organization_id == uuid.UUID(org_id))
    ).scalars())


# =========================================================================== #
# AC-01 -- capture policy resolves per scope, precedence deterministic
# =========================================================================== #
def test_ac01_resolution_precedence_is_deterministic_and_explained(
        client: TestClient, db_session: Session) -> None:
    org, setup = _org_and_agent(client)
    agent_id = setup["agent"]["id"]

    # tenant-wide FULL_CONTENT, then an agent-scoped REDACTED_CONTENT on top.
    _set_capture(client, org, "FULL_CONTENT")
    _set_capture(client, org, "REDACTED_CONTENT", agent_id=agent_id)

    r = client.get(f"{TEL}/effective-mode", headers=org["headers"],
                   params={"agent_id": agent_id})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["mode"] == "REDACTED_CONTENT"          # agent beats tenant
    assert body["source"] == "policy"
    assert "classification > agent > environment > tenant" in body["precedence"]
    assert body["reason"]
    assert len(body["considered"]) == 2

    # a different agent still sees the tenant default
    other = client.get(f"{TEL}/effective-mode", headers=org["headers"],
                       params={"agent_id": str(uuid.uuid4())}).json()
    assert other["mode"] == "FULL_CONTENT"


def test_ac01_all_four_modes_are_representable(client: TestClient) -> None:
    org, _ = _org_and_agent(client)
    for mode, cls in (("METADATA_ONLY", "PII"), ("REDACTED_CONTENT", "PHI"),
                      ("FULL_CONTENT", "INTERNAL"), ("DISABLED", "RESTRICTED")):
        p = _set_capture(client, org, mode, classification=cls)
        assert p["mode"] == mode


# =========================================================================== #
# AC-02 -- conservative default; misconfig fails toward less
# =========================================================================== #
def test_ac02_production_defaults_conservative_never_full_content(
        client: TestClient, db_session: Session) -> None:
    org, setup = _org_and_agent(client)
    env = Environment(organization_id=uuid.UUID(org["organization_id"]),
                      name="PROD-4-8", display_name="Prod", is_production=True, policy={})
    db_session.add(env)
    db_session.commit()

    got = resolve_capture_mode(db_session, organization_id=uuid.UUID(org["organization_id"]),
                               environment_id=env.id)
    assert got.mode is CaptureMode.METADATA_ONLY
    assert got.source == "conservative-default"
    assert "production" in got.reason


def test_ac02_sensitive_classification_defaults_conservative(
        client: TestClient, db_session: Session) -> None:
    org, _ = _org_and_agent(client)
    got = resolve_capture_mode(db_session,
                               organization_id=uuid.UUID(org["organization_id"]),
                               classification="PHI")
    assert got.mode is CaptureMode.METADATA_ONLY
    assert got.source == "conservative-default"


def test_ac02_a_malformed_stored_mode_coerces_toward_metadata_only() -> None:
    assert coerce("GARBAGE") is CaptureMode.METADATA_ONLY
    assert coerce(None) is CaptureMode.METADATA_ONLY
    assert coerce("FULL_CONTENT") is CaptureMode.FULL_CONTENT


def test_ac02_no_policy_anywhere_is_metadata_only(
        client: TestClient, db_session: Session) -> None:
    org, _ = _org_and_agent(client)
    got = resolve_capture_mode(db_session,
                               organization_id=uuid.UUID(org["organization_id"]))
    assert got.mode is CaptureMode.METADATA_ONLY
    assert "opt-in" in got.reason


# =========================================================================== #
# AC-03 -- each mode's capture behaviour
# =========================================================================== #
def test_ac03_metadata_only_captures_no_content(
        client: TestClient, db_session: Session) -> None:
    org, setup = _org_and_agent(client)
    execution = _seed_content_execution(db_session, setup, org)

    code, body = _content(client, org, execution.id)
    assert code == 200, body
    view = body["traces"][0]
    assert view["mode"] == "METADATA_ONLY"
    assert view["captured"] is False
    assert view["items"] == []
    # nothing was written to the governed store
    assert db_session.execute(
        select(func.count()).select_from(TraceContent)
        .where(TraceContent.execution_id == execution.id)).scalar_one() == 0


def test_ac03_disabled_captures_nothing(
        client: TestClient, db_session: Session) -> None:
    org, setup = _org_and_agent(client)
    _set_capture(client, org, "DISABLED")
    execution = _seed_content_execution(db_session, setup, org)

    code, body = _content(client, org, execution.id)
    assert code == 200
    view = body["traces"][0]
    assert view["mode"] == "DISABLED"
    assert view["captured"] is False
    assert "DISABLED" in view["note"]
    assert db_session.execute(
        select(func.count()).select_from(TraceContent)
        .where(TraceContent.execution_id == execution.id)).scalar_one() == 0


def test_ac03_full_content_captures_content_with_secrets_scrubbed(
        client: TestClient, db_session: Session) -> None:
    org, setup = _org_and_agent(client)
    _set_capture(client, org, "FULL_CONTENT")
    execution = _seed_content_execution(db_session, setup, org)

    code, body = _content(client, org, execution.id)
    assert code == 200
    view = body["traces"][0]
    assert view["mode"] == "FULL_CONTENT"
    assert view["captured"] is True
    blob = repr(view["items"])
    assert SECRET not in blob                      # secret scrubbed
    assert "REDACTED" in blob
    assert "vitals stable" in blob                 # business content kept
    assert any(i["secret_scrubbed"] for i in view["items"])


def test_ac03_redacted_content_masks_before_persist(
        client: TestClient, db_session: Session) -> None:
    org, setup = _org_and_agent(client)
    _set_capture(client, org, "REDACTED_CONTENT")
    execution = _seed_content_execution(db_session, setup, org,
                                        prompt="Summarise the patient chart in detail")
    _content(client, org, execution.id)

    rows = list(db_session.execute(
        select(TraceContent).where(TraceContent.execution_id == execution.id)).scalars())
    assert rows
    blob = repr([r.body for r in rows])
    assert SECRET not in blob
    assert "patient chart" not in blob             # sensitive-named field masked
    assert any(r.redacted for r in rows)
    assert all(r.mode_applied == "REDACTED_CONTENT" for r in rows)


# =========================================================================== #
# AC-04 -- secret scrub before persistence in EVERY content mode
# =========================================================================== #
def test_ac04_no_secret_persisted_in_any_content_mode(
        client: TestClient, db_session: Session) -> None:
    for mode in ("REDACTED_CONTENT", "FULL_CONTENT"):
        org, setup = _org_and_agent(client)
        _set_capture(client, org, mode)
        execution = _seed_content_execution(db_session, setup, org)
        _content(client, org, execution.id)

        rows = list(db_session.execute(
            select(TraceContent).where(TraceContent.execution_id == execution.id)).scalars())
        assert rows, mode
        serialized = repr([r.body for r in rows])
        assert SECRET not in serialized, mode
        assert "Bearer sk-" not in serialized, mode


def test_ac04_redaction_pipeline_unit_scrubs_before_masking() -> None:
    payload = {"prompt": "hello", "authorization": f"Bearer {SECRET}"}
    full = redact_for_capture(payload, mode="FULL_CONTENT")
    assert SECRET not in repr(full.body)
    assert full.secret_scrubbed is True
    redacted = redact_for_capture(payload, mode="REDACTED_CONTENT")
    assert SECRET not in repr(redacted.body)
    assert redacted.redacted is True


# =========================================================================== #
# AC-05 -- chain-of-thought is never captured, in any mode
# =========================================================================== #
def test_ac05_no_chain_of_thought_in_any_mode(
        client: TestClient, db_session: Session) -> None:
    for mode in ("REDACTED_CONTENT", "FULL_CONTENT"):
        org, setup = _org_and_agent(client)
        _set_capture(client, org, mode)
        execution = _seed_content_execution(db_session, setup, org, reasoning=True)
        _content(client, org, execution.id)

        rows = list(db_session.execute(
            select(TraceContent).where(TraceContent.execution_id == execution.id)).scalars())
        blob = repr([r.body for r in rows])
        assert "thinking" not in blob, mode
        assert "hide this" not in blob, mode


def test_ac05_structural_no_mode_admits_reasoning() -> None:
    """The §7 floor is a property of the pipeline, not a mode toggle:
    ``strip_reasoning`` runs first in ``redact_for_capture`` regardless of
    mode."""
    src = (APP_ROOT / "telemetry_privacy" / "redaction.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "redact_for_capture")
    calls = [n.func.id for n in ast.walk(fn)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)]
    assert calls[0] == "strip_reasoning"


# =========================================================================== #
# AC-06 -- runtime.trace.content.view is distinct and strictly stronger
# =========================================================================== #
def test_ac06_metadata_view_does_not_grant_content(
        client: TestClient, db_session: Session) -> None:
    org, setup = _org_and_agent(client)
    _set_capture(client, org, "FULL_CONTENT")
    execution = _seed_content_execution(db_session, setup, org)

    member = _invite(client, org)
    _assign(client, org, member["user_id"],
            _make_role(client, org, ["runtime.telemetry.view"]))

    # metadata trace: allowed
    assert client.get(f"{OBS}/executions/{execution.id}/trace",
                      headers=member["headers"]).status_code == 200
    # content: forbidden, with the distinct code -- and the trace exists, so 403 not 404
    r = client.get(f"{OBS}/traces/{execution.id}/content", headers=member["headers"])
    assert r.status_code == 403, r.text
    assert r.json()["error"]["code"] == "TRACE_CONTENT_ACCESS_DENIED"

    # grant the content permission -> now allowed
    _assign(client, org, member["user_id"],
            _make_role(client, org, ["runtime.trace.content.view"]))
    assert client.get(f"{OBS}/traces/{execution.id}/content",
                      headers=member["headers"]).status_code == 200


def test_ac06_the_permission_is_registered_and_not_read_only() -> None:
    from app.services.rbac_service import PERMISSION_CATALOG, _READ_ONLY

    assert "runtime.trace.content.view" in PERMISSION_CATALOG
    assert "runtime.telemetry_policy.manage" in PERMISSION_CATALOG
    # not folded into the ambient read-only bundle -- a grant is deliberate
    assert "runtime.trace.content.view" not in _READ_ONLY
    src = (APP_ROOT / "telemetry_privacy" / "routes.py").read_text(encoding="utf-8")
    assert '_CONTENT_VIEW = "runtime.trace.content.view"' in src
    assert "user_has_permission(db, actor, _CONTENT_VIEW)" in src


def test_ac06_execute_permission_alone_cannot_read_content(
        client: TestClient, db_session: Session) -> None:
    org, setup = _org_and_agent(client)
    _set_capture(client, org, "FULL_CONTENT")
    execution = _seed_content_execution(db_session, setup, org)

    member = _invite(client, org)
    _assign(client, org, member["user_id"],
            _make_role(client, org, ["runtime.execution.create", "runtime.execution.view"]))
    r = client.get(f"{OBS}/traces/{execution.id}/content", headers=member["headers"])
    assert r.status_code in (403,)


# =========================================================================== #
# AC-07 -- every content view is audited (access, not payload)
# =========================================================================== #
def test_ac07_every_content_view_is_audited(
        client: TestClient, db_session: Session) -> None:
    org, setup = _org_and_agent(client)
    _set_capture(client, org, "FULL_CONTENT")
    execution = _seed_content_execution(db_session, setup, org)

    before = len(_audits(db_session, "RUNTIME_TRACE_CONTENT_VIEWED", org["organization_id"]))
    for _ in range(2):
        assert client.get(f"{OBS}/traces/{execution.id}/content",
                          headers=org["headers"]).status_code == 200
    rows = _audits(db_session, "RUNTIME_TRACE_CONTENT_VIEWED", org["organization_id"])
    assert len(rows) == before + 2

    latest = max(rows, key=lambda r: r.created_at)
    meta = latest.meta or {}
    assert str(execution.id) in repr(meta)
    # the audit records the access, never the payload
    assert SECRET not in repr(meta)
    assert "vitals stable" not in repr(meta)


# =========================================================================== #
# AC-08 / AC-09 -- retention per class, idempotent, spares domain truth
# =========================================================================== #
def test_ac08_expired_content_is_purged_execution_row_survives(
        client: TestClient, db_session: Session) -> None:
    org, setup = _org_and_agent(client)
    _set_capture(client, org, "FULL_CONTENT")
    old = _seed_content_execution(db_session, setup, org,
                                  at=datetime.now(timezone.utc) - timedelta(days=400))
    _content(client, org, old.id)
    # age the trace_content rows past the 30-day default
    db_session.execute(text("UPDATE trace_content SET created_at = :t WHERE execution_id = :i"),
                       {"t": datetime.now(timezone.utc) - timedelta(days=400), "i": old.id})
    db_session.commit()
    assert db_session.execute(
        select(func.count()).select_from(TraceContent)
        .where(TraceContent.execution_id == old.id)).scalar_one() > 0

    r = client.post(f"{TEL}/retention/run", headers=org["headers"])
    assert r.status_code == 200, r.text
    summary = r.json()
    assert summary["total_deleted"] >= 1

    # content gone, execution row intact
    assert db_session.execute(
        select(func.count()).select_from(TraceContent)
        .where(TraceContent.execution_id == old.id)).scalar_one() == 0
    assert db_session.get(AgentExecution, old.id) is not None
    db_session.expire_all()
    assert db_session.execute(
        select(func.count()).select_from(ExecutionMessage)
        .where(ExecutionMessage.execution_id == old.id)).scalar_one() > 0


def test_ac08_retention_is_per_class_with_evidence_classes_retain_only(
        client: TestClient) -> None:
    org, _ = _org_and_agent(client)
    r = client.get(f"{TEL}/retention-policies", headers=org["headers"])
    assert r.status_code == 200
    eff = r.json()
    assert set(eff) == {"trace_content", "trace_metadata", "metrics_aggregate",
                        "alert_history", "governance_decision", "financial_record"}
    assert eff["financial_record"]["retain_only"] is True
    assert eff["governance_decision"]["retain_only"] is True
    assert eff["trace_content"]["retention_days"] < eff["financial_record"]["retention_days"]

    # cannot set a financial floor below a year
    bad = client.post(f"{TEL}/retention-policies", headers=org["headers"],
                      json={"telemetry_class": "financial_record", "retention_days": 5})
    assert bad.status_code == 422
    ok = client.post(f"{TEL}/retention-policies", headers=org["headers"],
                     json={"telemetry_class": "trace_content", "retention_days": 3})
    assert ok.status_code == 200


def test_ac09_retention_run_is_idempotent(
        client: TestClient, db_session: Session) -> None:
    org, setup = _org_and_agent(client)
    _set_capture(client, org, "FULL_CONTENT")
    old = _seed_content_execution(db_session, setup, org)
    _content(client, org, old.id)
    db_session.execute(text("UPDATE trace_content SET created_at = :t WHERE execution_id = :i"),
                       {"t": datetime.now(timezone.utc) - timedelta(days=999), "i": old.id})
    db_session.commit()

    first = client.post(f"{TEL}/retention/run", headers=org["headers"]).json()
    second = client.post(f"{TEL}/retention/run", headers=org["headers"]).json()
    assert first["total_deleted"] >= 1
    assert second["total_deleted"] == 0


def test_ac09_no_scheduler_is_built() -> None:
    pkg = APP_ROOT / "telemetry_privacy"
    for path in pkg.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        assert "APScheduler" not in names and "BackgroundScheduler" not in names, path.name
        for n in ast.walk(tree):
            if isinstance(n, ast.Attribute):
                assert n.attr not in {"add_job", "start_scheduler"}, path.name


# =========================================================================== #
# AC-10 -- the mandatory §31 privacy set
# =========================================================================== #
def test_ac10_privacy_set_restricted_content(
        client: TestClient, db_session: Session) -> None:
    org, setup = _org_and_agent(client)
    _set_capture(client, org, "FULL_CONTENT")
    execution = _seed_content_execution(db_session, setup, org)
    member = _invite(client, org)
    _assign(client, org, member["user_id"],
            _make_role(client, org, ["runtime.telemetry.view"]))
    assert client.get(f"{OBS}/traces/{execution.id}/content",
                      headers=member["headers"]).status_code == 403


def test_ac10_privacy_set_cross_tenant_trace_is_404(
        client: TestClient, db_session: Session) -> None:
    org_a, setup_a = _org_and_agent(client)
    _set_capture(client, org_a, "FULL_CONTENT")
    execution = _seed_content_execution(db_session, setup_a, org_a)

    org_b = _register_org(client, "Stranger Privacy Org")
    r = client.get(f"{OBS}/traces/{execution.id}/content", headers=org_b["headers"])
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "TRACE_NOT_FOUND"


def test_ac10_privacy_set_metadata_only_and_disabled(
        client: TestClient, db_session: Session) -> None:
    org, setup = _org_and_agent(client)
    execution = _seed_content_execution(db_session, setup, org)
    # metadata-only (default)
    _, body = _content(client, org, execution.id)
    assert body["traces"][0]["items"] == []
    # disabled
    _set_capture(client, org, "DISABLED")
    _, body = _content(client, org, execution.id)
    assert body["traces"][0]["captured"] is False
    assert db_session.execute(
        select(func.count()).select_from(TraceContent)
        .where(TraceContent.execution_id == execution.id)).scalar_one() == 0


# =========================================================================== #
# AC-11 -- 404 vs 403 discipline
# =========================================================================== #
def test_ac11_in_tenant_without_content_permission_is_403(
        client: TestClient, db_session: Session) -> None:
    org, setup = _org_and_agent(client)
    _set_capture(client, org, "FULL_CONTENT")
    execution = _seed_content_execution(db_session, setup, org)
    member = _invite(client, org)
    _assign(client, org, member["user_id"],
            _make_role(client, org, ["runtime.telemetry.view"]))
    r = client.get(f"{OBS}/traces/{execution.id}/content", headers=member["headers"])
    assert r.status_code == 403


def test_ac11_nonexistent_trace_is_404(client: TestClient) -> None:
    org, _ = _org_and_agent(client)
    r = client.get(f"{OBS}/traces/{uuid.uuid4()}/content", headers=org["headers"])
    assert r.status_code == 404


# =========================================================================== #
# AC-12 -- capture policy change is permissioned + audited
# =========================================================================== #
def test_ac12_capture_policy_change_is_audited(
        client: TestClient, db_session: Session) -> None:
    org, _ = _org_and_agent(client)
    before = len(_audits(db_session, "RUNTIME_TELEMETRY_POLICY_CHANGED", org["organization_id"]))
    policy = _set_capture(client, org, "FULL_CONTENT")
    client.patch(f"{TEL}/capture-policies/{policy['id']}", headers=org["headers"],
                 json={"mode": "REDACTED_CONTENT"})
    client.delete(f"{TEL}/capture-policies/{policy['id']}", headers=org["headers"])
    rows = _audits(db_session, "RUNTIME_TELEMETRY_POLICY_CHANGED", org["organization_id"])
    assert len(rows) == before + 3


def test_ac12_management_requires_manage_permission(client: TestClient) -> None:
    org, _ = _org_and_agent(client)
    member = _invite(client, org)
    _assign(client, org, member["user_id"],
            _make_role(client, org, ["runtime.telemetry_policy.view"]))
    # view works
    assert client.get(f"{TEL}/capture-policies", headers=member["headers"]).status_code == 200
    # write does not
    assert client.post(f"{TEL}/capture-policies", headers=member["headers"],
                       json={"mode": "FULL_CONTENT"}).status_code == 403


# =========================================================================== #
# AC-13 -- non-gating; planes stay separate
# =========================================================================== #
def test_ac13_capture_and_retention_are_non_gating() -> None:
    """No module in app/telemetry_privacy references an execution-state
    mutation, a kill switch, or a governance engine."""
    pkg = APP_ROOT / "telemetry_privacy"
    forbidden_names = {"KillSwitchService", "GovernanceEngine", "RuntimeGovernanceEngine",
                       "EnforcementService"}
    forbidden_attrs = {"_set_execution_status", "activate", "enforce", "stop_execution",
                       "halt", "kill"}
    for path in pkg.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                assert node.id not in forbidden_names, f"{path.name}: {node.id}"
            if isinstance(node, ast.Attribute):
                assert node.attr not in forbidden_attrs, f"{path.name}: {node.attr}"


def test_ac13_retention_only_deletes_telemetry_tables() -> None:
    """The sweep's `_delete_ids` dispatch table names only telemetry models;
    no domain-truth or audit model is reachable by a delete."""
    from app.telemetry_privacy import retention

    src = (APP_ROOT / "telemetry_privacy" / "retention.py").read_text(encoding="utf-8")
    # the module imports exactly these models, all telemetry-plane
    assert "from app.models.runtime import RuntimeAlert, RuntimeEvent, SLOEvaluation, TraceContent" in src
    for forbidden in ("AgentExecution", "ExecutionMessage", "AuthorizationAudit",
                      "RuntimeGovernanceDecision", "Budget"):
        assert forbidden not in src, forbidden
    assert retention.RETAIN_ONLY_CLASSES == {"governance_decision", "financial_record"}


# =========================================================================== #
# AC-14 -- tenant isolation; no secret in policy/audit
# =========================================================================== #
def test_ac14_policies_are_tenant_isolated(client: TestClient) -> None:
    org_a, _ = _org_and_agent(client)
    p = _set_capture(client, org_a, "FULL_CONTENT")
    org_b = _register_org(client, "Other TP Org")
    assert client.get(f"{TEL}/capture-policies", headers=org_b["headers"]).json() == []
    assert client.get(f"{TEL}/capture-policies/{p['id']}",
                      headers=org_b["headers"]).status_code == 404
    # b's effective mode is unaffected by a's FULL_CONTENT policy
    assert client.get(f"{TEL}/effective-mode", headers=org_b["headers"]).json()["mode"] == "METADATA_ONLY"


def test_ac14_no_secret_reaches_a_policy_or_its_audit(
        client: TestClient, db_session: Session) -> None:
    org, _ = _org_and_agent(client)
    # classification is a closed vocabulary -- a secret-shaped value is rejected
    r = client.post(f"{TEL}/capture-policies", headers=org["headers"],
                    json={"mode": "FULL_CONTENT", "classification": f"Bearer {SECRET}"})
    assert r.status_code == 422


# =========================================================================== #
# AC-15 -- the wider suite is unchanged (spot check the 4.1/4.2 invariants)
# =========================================================================== #
def test_ac15_metadata_trace_endpoints_still_metadata_only(
        client: TestClient, db_session: Session) -> None:
    org, setup = _org_and_agent(client)
    _set_capture(client, org, "FULL_CONTENT")
    execution = _seed_content_execution(db_session, setup, org)
    r = client.get(f"{OBS}/executions/{execution.id}/trace", headers=org["headers"])
    assert r.status_code == 200
    assert SECRET not in r.text
    assert "vitals stable" not in r.text          # 4.2 stays metadata-only


# =========================================================================== #
# AC-16 -- retention run touches only this tenant
# =========================================================================== #
def test_ac16_retention_run_is_tenant_scoped(
        client: TestClient, db_session: Session) -> None:
    org_a, setup_a = _org_and_agent(client)
    _set_capture(client, org_a, "FULL_CONTENT")
    a_exec = _seed_content_execution(db_session, setup_a, org_a)
    _content(client, org_a, a_exec.id)

    org_b = _register_org(client, "Untouched TP Org")
    client.post(f"{TEL}/retention/run", headers=org_b["headers"])
    # a's fresh content is still there
    assert db_session.execute(
        select(func.count()).select_from(TraceContent)
        .where(TraceContent.execution_id == a_exec.id)).scalar_one() > 0


# =========================================================================== #
# AC-18 -- no new TODO / FIXME / skip / xfail
# =========================================================================== #
def test_ac18_no_todo_or_skip_markers_in_the_package() -> None:
    pkg = APP_ROOT / "telemetry_privacy"
    for path in pkg.glob("*.py"):
        text_ = path.read_text(encoding="utf-8")
        for marker in ("TODO", "FIXME", "NotImplementedError", "xfail", "@pytest.mark.skip"):
            assert marker not in text_, f"{path.name}: {marker}"
