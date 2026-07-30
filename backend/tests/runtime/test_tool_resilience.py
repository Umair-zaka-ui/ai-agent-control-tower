"""Phase 5.6a.2 tests — tool schema validation & resilience.

Every server this file talks to is a real ``http.server`` bound to
``127.0.0.1`` on an OS-assigned ephemeral port (AC-31 — no test makes a
real outbound call to a non-local host), matching
``test_http_tool_execution.py``'s own convention exactly. Retry/backoff
tests inject ``time.sleep`` (AC-17) — never a real sleep.
"""

from __future__ import annotations

import http.server
import threading
import uuid
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.runtime import AgentVersionSnapshot, RuntimeEvent, Tool, ToolCall
from app.runtime import services as services_module
from app.runtime.providers.types import RETRYABLE_PROVIDER_ERROR_CLASSES, ProviderErrorClass
from app.runtime.services import _classify_tool_execution_failure, _tool_schema_violation
from app.runtime.tools import egress_guard
from app.runtime.tools.concurrency import ToolConcurrencyLimitExceeded, track as track_concurrency
from app.runtime.tools.egress_guard import EgressDecision
from app.runtime.tools.http_executor import HttpExecutionResult

PASSWORD = "T3st!Passw0rd#Ok"
RT = "/api/v1/runtime"


# --------------------------------------------------------------------------- #
# A real local HTTP server, bound to 127.0.0.1 on an ephemeral port —
# copied from test_http_tool_execution.py's own convention.
# --------------------------------------------------------------------------- #
class _RequestLog:
    def __init__(self) -> None:
        self.requests: list[dict] = []


@contextmanager
def local_server(handler_factory):
    log = _RequestLog()
    handler_cls = handler_factory(log)
    server = http.server.HTTPServer(("127.0.0.1", 0), handler_cls)
    port = server.server_port
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield port, log
    finally:
        server.shutdown()
        thread.join(timeout=5)


def _json_response(handler: http.server.BaseHTTPRequestHandler, status: int, body: bytes,
                   *, headers: dict[str, str] | None = None) -> None:
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    for name, value in (headers or {}).items():
        handler.send_header(name, value)
    handler.end_headers()
    handler.wfile.write(body)


def _json_ok_handler(log: _RequestLog):
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            log.requests.append({"path": self.path})
            _json_response(self, 200, b'{"ok": true, "count": 3}')

        def log_message(self, *a) -> None: pass

    return Handler


def _flaky_then_ok_handler(fail_times: int, *, failure_status: int = 503):
    """Fails with ``failure_status`` for the first ``fail_times`` requests,
    then returns 200 — the fixture behind every retry test."""
    state = {"n": 0}

    def factory(log: _RequestLog):
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                state["n"] += 1
                log.requests.append({"path": self.path, "attempt": state["n"]})
                if state["n"] <= fail_times:
                    _json_response(self, failure_status, b'{"error": "try again"}')
                else:
                    _json_response(self, 200, b'{"ok": true}')

            def log_message(self, *a) -> None: pass

        return Handler

    return factory


def _always_fails_handler(status: int = 503):
    def factory(log: _RequestLog):
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                log.requests.append({"path": self.path})
                _json_response(self, status, b'{"error": "down"}')

            def log_message(self, *a) -> None: pass

        return Handler

    return factory


def _rate_limited_then_ok_handler(retry_after_seconds: float):
    state = {"n": 0}

    def factory(log: _RequestLog):
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                state["n"] += 1
                log.requests.append({"path": self.path})
                if state["n"] == 1:
                    _json_response(self, 429, b'{"error": "rate limited"}',
                                   headers={"Retry-After": str(retry_after_seconds)})
                else:
                    _json_response(self, 200, b'{"ok": true}')

            def log_message(self, *a) -> None: pass

        return Handler

    return factory


def _oversized_handler(log: _RequestLog):
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            log.requests.append({"path": self.path})
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.end_headers()
            chunk = b"x" * 65536
            try:
                for _ in range(80):
                    self.wfile.write(chunk)
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass

        def log_message(self, *a) -> None: pass

    return Handler


def _slow_handler(delay_seconds: float):
    def factory(log: _RequestLog):
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                import time as _time
                _time.sleep(delay_seconds)
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"too slow")

            def log_message(self, *a) -> None: pass

        return Handler

    return factory


# --------------------------------------------------------------------------- #
# HTTP helpers for the full pipeline — local copies, matching this
# directory's established convention (see test_http_tool_execution.py).
# --------------------------------------------------------------------------- #
def _register_org(client: TestClient, org_name: str = "Tool Resilience Org") -> dict:
    email = f"toolresil_{uuid.uuid4().hex[:10]}@example.com"
    assert client.post("/auth/register", json={
        "organization_name": org_name, "name": "Owner", "email": email, "password": PASSWORD,
    }).status_code == 201
    tokens = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD}).json()
    h = {"Authorization": f"Bearer {tokens['access_token']}"}
    me = client.get("/api/v1/auth/me", headers=h).json()
    return {"headers": h, "user_id": me["user"]["id"], "organization_id": me["user"]["organization_id"]}


def _register_agent(client: TestClient, admin: dict) -> dict:
    r = client.post(f"{RT}/agents", headers=admin["headers"], json={
        "name": f"Resilience Agent {uuid.uuid4().hex[:6]}", "agent_type": "ASSISTANT", "criticality": "MEDIUM",
        "description": "A test agent.", "business_purpose": "Exercise tool schema validation & resilience.",
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


def _create_http_tool(client: TestClient, admin: dict, *, endpoint: str, http_config: dict,
                      input_schema: dict | None = None, output_schema: dict | None = None,
                      name: str | None = None) -> dict:
    payload = {
        "name": name or f"resil_tool_{uuid.uuid4().hex[:8]}", "display_name": "Resilience Tool", "tool_type": "HTTP",
        "endpoint_reference": endpoint, "http_config": http_config,
    }
    if input_schema is not None:
        payload["input_schema"] = input_schema
    if output_schema is not None:
        payload["output_schema"] = output_schema
    r = client.post(f"{RT}/tools", headers=admin["headers"], json=payload)
    assert r.status_code == 201, r.text
    return r.json()


def _assign_tool(client: TestClient, admin: dict, agent_id: str, tool_id: str) -> dict:
    r = client.post(f"{RT}/agents/{agent_id}/tools", headers=admin["headers"], json={
        "tool_id": tool_id, "allowed_actions": ["EXECUTE", "READ"],
    })
    assert r.status_code == 201, r.text
    return r.json()


def _publish_version(client: TestClient, admin: dict, agent_id: str, *, tool_ids: list[str]) -> dict:
    r = client.post(f"{RT}/agents/{agent_id}/versions", headers=admin["headers"], json={
        "model_configuration": {"provider": "MOCK", "model": "mock-model"}, "tool_ids": tool_ids,
    })
    assert r.status_code == 201, r.text
    version = r.json()
    for step in ("validate", "approve", "publish"):
        r = client.post(f"{RT}/agents/{agent_id}/versions/{version['id']}/{step}", headers=admin["headers"])
        assert r.status_code == 200, r.text
    return r.json()


def _deploy(client: TestClient, admin: dict, agent_id: str, version_id: str) -> dict:
    r = client.post(f"{RT}/deployments", headers=admin["headers"], params={"agent_id": agent_id}, json={
        "agent_version_id": version_id, "environment": "DEVELOPMENT",
    })
    assert r.status_code == 201, r.text
    deployment = r.json()
    r = client.post(f"{RT}/deployments/{deployment['id']}/deploy", headers=admin["headers"])
    assert r.status_code == 200, r.text
    return r.json()


def _ready_agent_with_http_tool(client: TestClient, admin: dict, *, endpoint: str, http_config: dict,
                                input_schema: dict | None = None, output_schema: dict | None = None) -> dict:
    agent = _register_agent(client, admin)
    _activate_agent(client, admin, agent["id"])
    tool = _create_http_tool(client, admin, endpoint=endpoint, http_config=http_config,
                             input_schema=input_schema, output_schema=output_schema)
    _assign_tool(client, admin, agent["id"], tool["id"])
    version = _publish_version(client, admin, agent["id"], tool_ids=[tool["id"]])
    deployment = _deploy(client, admin, agent["id"], version["id"])
    return {"agent": agent, "tool": tool, "version": version, "deployment": deployment}


def _run_execution(client: TestClient, admin: dict, agent_id: str, *, calls: list[dict]) -> dict:
    r = client.post(f"{RT}/executions", headers=admin["headers"], json={
        "agent_id": agent_id, "input_payload": {"tool_calls": calls},
    })
    assert r.status_code == 201, r.text
    return r.json()


def _one_call(tool_name: str, *, action: str = "READ", params: dict | None = None) -> list[dict]:
    return [{"tool_name": tool_name, "action": action, "params": params or {}}]


def _http_config(port: int, *, host: str = "api.example.com", idempotent: bool | None = None,
                 timeout_seconds: float | None = None, max_response_bytes: int | None = None) -> dict:
    config: dict = {
        "allowed_hosts": [host], "allow_plaintext_http": True, "local_dev_hosts": [host],
    }
    if idempotent is not None:
        config["idempotent"] = idempotent
    if timeout_seconds is not None:
        config["timeout_seconds"] = timeout_seconds
    if max_response_bytes is not None:
        config["max_response_bytes"] = max_response_bytes
    return config


@pytest.fixture(autouse=True)
def _patch_default_resolver(monkeypatch):
    def _resolve(host: str) -> list[str]:
        return ["127.0.0.1"]
    monkeypatch.setattr(egress_guard, "_default_resolve", _resolve)


def _no_real_sleep(monkeypatch) -> None:
    """``time.sleep`` is patched on the exact module object ``services.py``
    calls it on — matching ``test_error_taxonomy_and_resilience.py``'s own
    convention. **Not** autouse: ``time`` is one process-wide module
    object, so patching its ``sleep`` attribute would also neuter
    ``_slow_handler``'s own (real, needed) delay in the timeout tests,
    which run in a background thread sharing the same module. Called
    explicitly only by the tests that actually retry."""
    monkeypatch.setattr(services_module.time, "sleep", lambda *_: None)


_OBJECT_SCHEMA = {
    "type": "object", "required": ["order_id"], "properties": {"order_id": {"type": "integer"}},
}


# --------------------------------------------------------------------------- #
# Schema validation — AC-01..07
# --------------------------------------------------------------------------- #
def test_valid_arguments_pass_and_the_tool_executes(client: TestClient) -> None:
    """AC-01."""
    with local_server(_json_ok_handler) as (port, log):
        org = _register_org(client)
        setup = _ready_agent_with_http_tool(client, org, endpoint=f"http://api.example.com:{port}",
                                            http_config=_http_config(port), input_schema=_OBJECT_SCHEMA)
        execution = _run_execution(client, org, setup["agent"]["id"],
                                   calls=_one_call(setup["tool"]["name"], params={"order_id": 42}))
    assert execution["status"] == "SUCCEEDED"
    assert len(log.requests) == 1


def test_invalid_arguments_rejected_with_no_outbound_call(client: TestClient, db_session: Session) -> None:
    """AC-02."""
    with local_server(_json_ok_handler) as (port, log):
        org = _register_org(client)
        setup = _ready_agent_with_http_tool(client, org, endpoint=f"http://api.example.com:{port}",
                                            http_config=_http_config(port), input_schema=_OBJECT_SCHEMA)
        # Missing the required `order_id` -- violates the declared schema.
        execution = _run_execution(client, org, setup["agent"]["id"],
                                   calls=_one_call(setup["tool"]["name"], params={"wrong_field": "x"}))
    assert execution["status"] == "SUCCEEDED", "a failed tool call must not abort the execution (AC-20)"
    assert len(log.requests) == 0, "an invalid call must never reach the server"

    row = db_session.execute(select(ToolCall).where(ToolCall.execution_id == uuid.UUID(execution["id"]))).scalars().one()
    assert row.status == "FAILED"
    assert row.error_code == "TOOL_SCHEMA_INVALID"


def test_rejection_carries_a_structured_model_readable_violation(client: TestClient, db_session: Session) -> None:
    """AC-03."""
    import json as jsonlib

    with local_server(_json_ok_handler):
        org = _register_org(client)
        setup = _ready_agent_with_http_tool(client, org, endpoint="https://api.example.com",
                                            http_config=_http_config(0), input_schema=_OBJECT_SCHEMA)
        execution = _run_execution(client, org, setup["agent"]["id"],
                                   calls=_one_call(setup["tool"]["name"], params={}))
    row = db_session.execute(select(ToolCall).where(ToolCall.execution_id == uuid.UUID(execution["id"]))).scalars().one()
    violation = jsonlib.loads(row.validation_error)
    assert "order_id" in violation["message"] or "order_id" in str(violation.get("path"))
    assert isinstance(violation["path"], list)


def test_input_validation_precedes_egress_evaluation(client: TestClient, db_session: Session) -> None:
    """AC-04 — a call with both invalid arguments *and* a target the
    allowlist would also have denied must be rejected for the schema
    violation, never even reaching the egress guard: the recorded
    ``egress_decision`` must stay unset."""
    org = _register_org(client)
    config = _http_config(9999, host="only-this-host-is-allowed.example.com")
    setup = _ready_agent_with_http_tool(
        client, org, endpoint="https://not-allowlisted.example.com", http_config=config,
        input_schema=_OBJECT_SCHEMA,
    )
    execution = _run_execution(client, org, setup["agent"]["id"],
                               calls=_one_call(setup["tool"]["name"], params={}))
    assert execution["status"] == "SUCCEEDED"
    row = db_session.execute(select(ToolCall).where(ToolCall.execution_id == uuid.UUID(execution["id"]))).scalars().one()
    assert row.error_code == "TOOL_SCHEMA_INVALID"
    assert row.egress_decision is None, "the egress guard must never have run"


def test_response_validated_against_declared_output_schema(client: TestClient, db_session: Session) -> None:
    """AC-05 — the fixture server's body (`{"ok": true, "count": 3}`)
    violates a schema requiring an integer `total`."""
    output_schema = {"type": "object", "required": ["total"], "properties": {"total": {"type": "integer"}}}
    with local_server(_json_ok_handler) as (port, log):
        org = _register_org(client)
        setup = _ready_agent_with_http_tool(client, org, endpoint=f"http://api.example.com:{port}",
                                            http_config=_http_config(port), output_schema=output_schema)
        execution = _run_execution(client, org, setup["agent"]["id"], calls=_one_call(setup["tool"]["name"]))
    assert execution["status"] == "SUCCEEDED"
    assert len(log.requests) == 1, "the request IS issued -- output validation only runs after a response arrives"
    row = db_session.execute(select(ToolCall).where(ToolCall.execution_id == uuid.UUID(execution["id"]))).scalars().one()
    assert row.status == "FAILED"
    assert row.error_code == "TOOL_SCHEMA_INVALID"
    assert row.validation_error is not None


def test_no_output_schema_skips_validation_rather_than_failing(client: TestClient, db_session: Session) -> None:
    """AC-06."""
    with local_server(_json_ok_handler) as (port, log):
        org = _register_org(client)
        setup = _ready_agent_with_http_tool(client, org, endpoint=f"http://api.example.com:{port}",
                                            http_config=_http_config(port))
        execution = _run_execution(client, org, setup["agent"]["id"], calls=_one_call(setup["tool"]["name"]))
    assert execution["status"] == "SUCCEEDED"
    row = db_session.execute(select(ToolCall).where(ToolCall.execution_id == uuid.UUID(execution["id"]))).scalars().one()
    assert row.status == "ALLOWED"


def test_schema_validation_reuses_jsonschema_not_a_new_library() -> None:
    """AC-07 — the exact same ``jsonschema.ValidationError`` machinery the
    pre-existing agent-level ``_validate_schema`` uses, not a hand-rolled
    or newly-added validator."""
    import jsonschema

    instance, schema = {"order_id": "not-an-integer"}, _OBJECT_SCHEMA
    violation = _tool_schema_violation(instance, schema)
    assert violation is not None
    with pytest.raises(jsonschema.ValidationError) as exc_info:
        jsonschema.validate(instance=instance, schema=schema)
    assert violation["message"] == exc_info.value.message


# --------------------------------------------------------------------------- #
# Caps — AC-08..11
# --------------------------------------------------------------------------- #
def test_per_tool_response_size_limit_aborts_transfer(client: TestClient, db_session: Session) -> None:
    """AC-08 — the server has 5 MiB available; the per-tool cap is 4 KiB."""
    with local_server(_oversized_handler) as (port, log):
        org = _register_org(client)
        setup = _ready_agent_with_http_tool(
            client, org, endpoint=f"http://api.example.com:{port}",
            http_config=_http_config(port, max_response_bytes=4096),
        )
        execution = _run_execution(client, org, setup["agent"]["id"], calls=_one_call(setup["tool"]["name"]))
    assert execution["status"] == "SUCCEEDED"
    row = db_session.execute(select(ToolCall).where(ToolCall.execution_id == uuid.UUID(execution["id"]))).scalars().one()
    assert row.status == "FAILED"
    assert row.error_code == "TOOL_RESPONSE_TOO_LARGE"
    assert row.response_bytes < 4096 + 65536 * 2, "must not have buffered anywhere near the full 5 MiB"


def test_per_tool_timeout_terminates_a_slow_call(client: TestClient, db_session: Session) -> None:
    """AC-09."""
    with local_server(_slow_handler(2.0)) as (port, log):
        org = _register_org(client)
        setup = _ready_agent_with_http_tool(
            client, org, endpoint=f"http://api.example.com:{port}",
            http_config=_http_config(port, timeout_seconds=0.2),
        )
        execution = _run_execution(client, org, setup["agent"]["id"], calls=_one_call(setup["tool"]["name"]))
    assert execution["status"] == "SUCCEEDED"
    row = db_session.execute(select(ToolCall).where(ToolCall.execution_id == uuid.UUID(execution["id"]))).scalars().one()
    assert row.status == "FAILED"
    assert row.error_code == "TOOL_TIMEOUT"
    assert row.error_class == "TIMEOUT"


def test_size_and_timeout_are_read_from_the_frozen_snapshot(client: TestClient, db_session: Session) -> None:
    """AC-10 — widening a tool's timeout *after* a version is published
    must not affect that already-published version's enforcement (mirrors
    ``test_allowlist_is_read_from_frozen_snapshot_not_mutable_tool_state``
    from 5.6a.1's own test suite)."""
    with local_server(_slow_handler(2.0)) as (port, log):
        org = _register_org(client)
        setup = _ready_agent_with_http_tool(
            client, org, endpoint=f"http://api.example.com:{port}",
            http_config=_http_config(port, timeout_seconds=0.2),
        )

        tool_row = db_session.get(Tool, uuid.UUID(setup["tool"]["id"]))
        tool_row.http_config = {**tool_row.http_config, "timeout_seconds": 30.0}
        tool_row.timeout_seconds = 30
        db_session.commit()

        execution = _run_execution(client, org, setup["agent"]["id"], calls=_one_call(setup["tool"]["name"]))
    row = db_session.execute(select(ToolCall).where(ToolCall.execution_id == uuid.UUID(execution["id"]))).scalars().one()
    assert row.error_code == "TOOL_TIMEOUT", "the frozen (short) timeout must still govern, not the widened live value"

    snapshot = db_session.execute(
        select(AgentVersionSnapshot).where(AgentVersionSnapshot.agent_version_id == uuid.UUID(setup["version"]["id"]))
    ).scalars().one()
    frozen_config = snapshot.snapshot["runtime"]["tool_configs"][setup["tool"]["id"]]["http_config"]
    assert frozen_config["timeout_seconds"] == 0.2


def test_concurrency_ceiling_is_enforced() -> None:
    """AC-11 — a direct test against the concurrency tracker: today's
    strictly-sequential ``tool_calls`` loop never contends this in
    production (see ``concurrency.py``'s own module docstring), so this is
    exercised with real threads instead."""
    execution_id = uuid.uuid4()
    limit = 2
    all_entered = threading.Event()
    hold = threading.Event()
    entered = {"n": 0}
    lock = threading.Lock()

    def holder() -> None:
        with track_concurrency(execution_id, limit=limit):
            with lock:
                entered["n"] += 1
                if entered["n"] == limit:
                    all_entered.set()
            hold.wait(timeout=5)

    threads = [threading.Thread(target=holder) for _ in range(limit)]
    for t in threads:
        t.start()
    assert all_entered.wait(timeout=5), "both holder threads should have acquired a slot"

    with pytest.raises(ToolConcurrencyLimitExceeded):
        with track_concurrency(execution_id, limit=limit):
            pass  # pragma: no cover -- must never be entered

    hold.set()
    for t in threads:
        t.join(timeout=5)

    with track_concurrency(execution_id, limit=limit):
        pass  # slots released -- a fresh attempt now succeeds


# --------------------------------------------------------------------------- #
# Resilience — reuse of the 5.7a.4 taxonomy — AC-12..20
# --------------------------------------------------------------------------- #
def test_tool_failure_is_classified_into_the_shared_provider_taxonomy() -> None:
    """AC-12 — the exact same ``ProviderErrorClass`` enum, not a parallel
    tool-specific one."""
    decision = EgressDecision(True, None, "api.example.com", 443, "https", "127.0.0.1")

    rate_limited = HttpExecutionResult(success=False, egress_decision=decision, status=429)
    error_class, error_code = _classify_tool_execution_failure(rate_limited)
    assert error_class is ProviderErrorClass.RATE_LIMITED
    assert isinstance(error_class, ProviderErrorClass)
    assert error_class in RETRYABLE_PROVIDER_ERROR_CLASSES
    assert error_code == "TOOL_EXECUTION_FAILED"

    unavailable = HttpExecutionResult(success=False, egress_decision=decision, status=503)
    assert _classify_tool_execution_failure(unavailable)[0] is ProviderErrorClass.PROVIDER_UNAVAILABLE

    bad_request = HttpExecutionResult(success=False, egress_decision=decision, status=400)
    assert _classify_tool_execution_failure(bad_request)[0] is ProviderErrorClass.INVALID_REQUEST
    assert _classify_tool_execution_failure(bad_request)[0] not in RETRYABLE_PROVIDER_ERROR_CLASSES

    timeout = HttpExecutionResult(success=False, egress_decision=decision, error="TIMEOUT")
    cls, code = _classify_tool_execution_failure(timeout)
    assert cls is ProviderErrorClass.TIMEOUT
    assert code == "TOOL_TIMEOUT"

    too_large = HttpExecutionResult(success=False, egress_decision=decision, error="RESPONSE_TOO_LARGE")
    cls, code = _classify_tool_execution_failure(too_large)
    assert cls is ProviderErrorClass.UNKNOWN
    assert code == "TOOL_RESPONSE_TOO_LARGE"
    assert cls not in RETRYABLE_PROVIDER_ERROR_CLASSES


def test_idempotent_tool_retries_on_transient_failure_and_can_succeed(
        client: TestClient, db_session: Session, monkeypatch) -> None:
    """AC-13, AC-18 (attempt recording)."""
    _no_real_sleep(monkeypatch)
    with local_server(_flaky_then_ok_handler(2)) as (port, log):
        org = _register_org(client)
        setup = _ready_agent_with_http_tool(
            client, org, endpoint=f"http://api.example.com:{port}",
            http_config=_http_config(port, idempotent=True),
        )
        execution = _run_execution(client, org, setup["agent"]["id"], calls=_one_call(setup["tool"]["name"]))
    assert execution["status"] == "SUCCEEDED"
    assert len(log.requests) == 3, "two failures plus the eventual success"

    rows = db_session.execute(
        select(ToolCall).where(ToolCall.execution_id == uuid.UUID(execution["id"])).order_by(ToolCall.attempt_number)
    ).scalars().all()
    assert [r.attempt_number for r in rows] == [1, 2, 3]
    assert rows[0].status == "FAILED" and rows[0].error_class == "PROVIDER_UNAVAILABLE"
    assert rows[1].status == "FAILED" and rows[1].error_class == "PROVIDER_UNAVAILABLE"
    assert rows[2].status == "ALLOWED"


def test_non_idempotent_tool_does_not_retry_on_transient_failure(
        client: TestClient, db_session: Session) -> None:
    """AC-14."""
    with local_server(_flaky_then_ok_handler(2)) as (port, log):
        org = _register_org(client)
        setup = _ready_agent_with_http_tool(
            client, org, endpoint=f"http://api.example.com:{port}",
            http_config=_http_config(port, idempotent=False),
        )
        execution = _run_execution(client, org, setup["agent"]["id"], calls=_one_call(setup["tool"]["name"]))
    assert execution["status"] == "SUCCEEDED", "a failed tool call must not abort the execution"
    assert len(log.requests) == 1, "the single failing attempt must never be retried"
    row = db_session.execute(select(ToolCall).where(ToolCall.execution_id == uuid.UUID(execution["id"]))).scalars().one()
    assert row.status == "FAILED"
    assert row.attempt_number == 1


def test_undeclared_idempotency_defaults_to_non_retryable(client: TestClient, db_session: Session) -> None:
    """AC-15 — `idempotent` is entirely absent from `http_config`, not
    explicitly set to `false`."""
    with local_server(_flaky_then_ok_handler(2)) as (port, log):
        org = _register_org(client)
        setup = _ready_agent_with_http_tool(
            client, org, endpoint=f"http://api.example.com:{port}",
            http_config=_http_config(port),  # no `idempotent` key at all
        )
        assert "idempotent" not in setup["tool"]["http_config"]
        execution = _run_execution(client, org, setup["agent"]["id"], calls=_one_call(setup["tool"]["name"]))
    assert execution["status"] == "SUCCEEDED"
    assert len(log.requests) == 1


def test_idempotency_governed_by_declaration_not_http_method(client: TestClient, db_session: Session) -> None:
    """AC-16 — a `READ` action (maps to `GET`, conventionally "safe") that
    is explicitly declared non-idempotent still must not retry."""
    with local_server(_flaky_then_ok_handler(2)) as (port, log):
        org = _register_org(client)
        setup = _ready_agent_with_http_tool(
            client, org, endpoint=f"http://api.example.com:{port}",
            http_config=_http_config(port, idempotent=False),
        )
        execution = _run_execution(client, org, setup["agent"]["id"],
                                   calls=_one_call(setup["tool"]["name"], action="READ"))
    assert execution["status"] == "SUCCEEDED"
    assert len(log.requests) == 1, "GET is not itself authority for a retry -- the declaration governs"


def test_retry_backoff_honors_retry_after_with_no_real_sleep(
        client: TestClient, db_session: Session, monkeypatch) -> None:
    """AC-17."""
    captured: list[float] = []
    monkeypatch.setattr(services_module.time, "sleep", lambda seconds: captured.append(seconds))

    with local_server(_rate_limited_then_ok_handler(2.5)) as (port, log):
        org = _register_org(client)
        setup = _ready_agent_with_http_tool(
            client, org, endpoint=f"http://api.example.com:{port}",
            http_config=_http_config(port, idempotent=True),
        )
        execution = _run_execution(client, org, setup["agent"]["id"], calls=_one_call(setup["tool"]["name"]))
    assert execution["status"] == "SUCCEEDED"
    assert len(log.requests) == 2
    assert captured == [2.5], "the target's own Retry-After must win over computed backoff, verbatim"


def test_circuit_opens_after_threshold_and_fails_fast(
        client: TestClient, db_session: Session, monkeypatch) -> None:
    """AC-19."""
    monkeypatch.setattr(settings, "TOOL_CIRCUIT_FAILURE_THRESHOLD", 1)
    with local_server(_always_fails_handler()) as (port, log):
        org = _register_org(client)
        setup = _ready_agent_with_http_tool(
            client, org, endpoint=f"http://api.example.com:{port}",
            http_config=_http_config(port, idempotent=False),
        )
        execution = _run_execution(client, org, setup["agent"]["id"], calls=[
            {"tool_name": setup["tool"]["name"], "action": "READ", "params": {}},
            {"tool_name": setup["tool"]["name"], "action": "READ", "params": {}},
        ])
    assert execution["status"] == "SUCCEEDED"
    assert len(log.requests) == 1, "the second call must fail fast, without ever reaching the server"

    rows = db_session.execute(
        select(ToolCall).where(ToolCall.execution_id == uuid.UUID(execution["id"])).order_by(ToolCall.created_at)
    ).scalars().all()
    assert len(rows) == 2
    assert rows[0].status == "FAILED" and rows[0].egress_decision == "ALLOWED"
    assert rows[1].status == "FAILED" and rows[1].egress_decision is None, "never reached the egress guard at all"
    assert rows[1].error_class == "PROVIDER_UNAVAILABLE"


def test_failed_tool_call_returns_structured_error_and_execution_still_succeeds(
        client: TestClient, db_session: Session) -> None:
    """AC-20."""
    with local_server(_flaky_then_ok_handler(1)) as (port, log):
        org = _register_org(client)
        setup = _ready_agent_with_http_tool(
            client, org, endpoint=f"http://api.example.com:{port}",
            http_config=_http_config(port, idempotent=False),
        )
        execution = _run_execution(client, org, setup["agent"]["id"], calls=_one_call(setup["tool"]["name"]))
    assert execution["status"] == "SUCCEEDED", "one failed tool call must not abort the whole execution"
    row = db_session.execute(select(ToolCall).where(ToolCall.execution_id == uuid.UUID(execution["id"]))).scalars().one()
    assert row.status == "FAILED"
    assert row.error_code is not None and row.error_class is not None

    events = db_session.execute(
        select(RuntimeEvent).where(RuntimeEvent.execution_id == uuid.UUID(execution["id"]),
                                   RuntimeEvent.event_type == "RUNTIME_TOOL_FAILED")
    ).scalars().all()
    assert len(events) == 1


# --------------------------------------------------------------------------- #
# Integrity — AC-21..24 (unchanged behavior, verified by the pre-existing
# suites listed below, cited here rather than duplicated)
# --------------------------------------------------------------------------- #
# AC-21 -- backend/tests/authorization/test_runtime.py's FUNCTION/echo tests.
# AC-22 -- backend/tests/runtime/test_http_tool_execution.py (unmodified) and
#          backend/tests/runtime/test_egress_guard.py (unmodified).
# AC-23 -- test_http_tool_execution.py::test_unimplemented_action_still_fails_tool_action_not_allowed.
# AC-24 -- unchanged: ToolGatewayService.invoke still authorizes through the
#          same AgentTool/assignment lookups and _frozen_tool_entry (renamed
#          from _frozen_http_config, same snapshot-read discipline) before
#          any dispatch.
