"""Phase 5.6a.1 tests — HTTP tool execution, the executor, and the
end-to-end egress-controlled pipeline.

Every server this file talks to is a real ``http.server`` bound to
``127.0.0.1`` on an OS-assigned ephemeral port (AC-34 — no test makes a
real outbound call to a non-local host). SSRF address-vector coverage
itself lives in ``test_egress_guard.py`` (AC-01..08, AC-10, isolated, no
network at all, AC-26); this file covers the executor's own mechanics
(redirects, size cap, timeout, connection pinning) and the full pipeline
(credential injection, redaction, snapshot-freezing, audit events).
"""

from __future__ import annotations

import http.server
import json as jsonlib
import threading
import time
import uuid
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.runtime import AgentVersionSnapshot, RuntimeEvent, ToolCall, ToolCredential
from app.runtime.tools import egress_guard
from app.runtime.tools.egress_guard import EgressPolicy
from app.runtime.tools.http_executor import execute_http_tool
from app.runtime.services import ToolCredentialService

PASSWORD = "T3st!Passw0rd#Ok"
RT = "/api/v1/runtime"
_FAKE_SECRET = "sk-test-fake-tool-credential-abcdef"


# --------------------------------------------------------------------------- #
# A real local HTTP server, bound to 127.0.0.1 on an ephemeral port
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


def _json_ok_handler(log: _RequestLog):
    class Handler(http.server.BaseHTTPRequestHandler):
        def _handle(self) -> None:
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length) if length else b""
            log.requests.append({
                "method": self.command, "path": self.path,
                "host": self.headers.get("Host"), "authorization": self.headers.get("Authorization"),
                "body": body,
            })
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"ok": true, "received_path": "%s"}' % self.path.encode())

        def do_GET(self) -> None: self._handle()
        def do_POST(self) -> None: self._handle()
        def log_message(self, *a) -> None: pass

    return Handler


def _redirect_handler(target: str):
    def factory(log: _RequestLog):
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                log.requests.append({"path": self.path})
                self.send_response(302)
                self.send_header("Location", target)
                self.end_headers()

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
                for _ in range(80):  # 80 * 64KiB = 5MiB total available, far past any cap used below
                    self.wfile.write(chunk)
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass  # the client is expected to abort mid-stream once its cap is hit

        def log_message(self, *a) -> None: pass

    return Handler


def _slow_handler(delay_seconds: float):
    def factory(log: _RequestLog):
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                time.sleep(delay_seconds)
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"too slow")

            def log_message(self, *a) -> None: pass

        return Handler
    return factory


def _fake_resolver(mapping: dict[str, list[str]]):
    def _resolve(host: str) -> list[str]:
        return mapping.get(host, [])
    return _resolve


# --------------------------------------------------------------------------- #
# Executor-level tests (direct calls to execute_http_tool) — AC-09, AC-18..20
# --------------------------------------------------------------------------- #
def test_success_against_a_local_fixture_server() -> None:
    """AC-13 (executor level)."""
    with local_server(_json_ok_handler) as (port, log):
        policy = EgressPolicy(allowed_hosts=frozenset({"api.example.com"}), allow_plaintext_http=True,
                              local_dev_hosts=frozenset({"api.example.com"}))
        result = execute_http_tool(
            method="GET", base_url=f"http://api.example.com:{port}", path="/widgets/1",
            policy=policy, resolver=_fake_resolver({"api.example.com": ["127.0.0.1"]}), verify=False,
        )
    assert result.success is True
    assert result.status == 200
    assert len(log.requests) == 1
    assert log.requests[0]["path"] == "/widgets/1"


def test_redirect_to_internal_host_is_denied() -> None:
    """AC-09 — a redirect chain from an allowlisted host terminating at an
    internal host is denied."""
    with local_server(_redirect_handler("http://internal.local/secret")) as (port, log):
        policy = EgressPolicy(allowed_hosts=frozenset({"good.example.com"}), allow_plaintext_http=True,
                              local_dev_hosts=frozenset({"good.example.com"}))
        resolver = _fake_resolver({"good.example.com": ["127.0.0.1"], "internal.local": ["10.0.0.9"]})
        result = execute_http_tool(
            method="GET", base_url=f"http://good.example.com:{port}", path="/start",
            policy=policy, resolver=resolver, verify=False,
        )
    assert result.success is False
    assert result.egress_decision.allowed is False
    assert result.egress_decision.host == "internal.local"


def test_redirect_depth_cap_is_enforced() -> None:
    """ACT-TLX-FR-007's depth cap: a redirect chain that stays on the
    allowlisted host but loops past the configured maximum is stopped."""
    with local_server(_redirect_handler("/start")) as (port, log):  # redirects to itself, forever
        policy = EgressPolicy(allowed_hosts=frozenset({"good.example.com"}), allow_plaintext_http=True,
                              local_dev_hosts=frozenset({"good.example.com"}), max_redirects=2)
        resolver = _fake_resolver({"good.example.com": ["127.0.0.1"]})
        result = execute_http_tool(
            method="GET", base_url=f"http://good.example.com:{port}", path="/start",
            policy=policy, resolver=resolver, verify=False,
        )
    assert result.success is False
    assert result.error == "REDIRECT_DEPTH_EXCEEDED"
    assert len(log.requests) == 3  # the original request plus exactly max_redirects follow-ups


def test_denied_request_never_reaches_the_server() -> None:
    """AC-18 — allowlist evaluation happens before any request is issued."""
    with local_server(_json_ok_handler) as (port, log):
        policy = EgressPolicy(allowed_hosts=frozenset({"only-this-host.example.com"}))
        result = execute_http_tool(
            method="GET", base_url=f"http://not-allowlisted.example.com:{port}", path="/",
            policy=policy, resolver=_fake_resolver({}), verify=False,
        )
    assert result.success is False
    assert len(log.requests) == 0, "the server must never have received a request for a denied target"


def test_oversized_response_aborts_transfer_without_buffering_everything() -> None:
    """AC-19 — the server has 5 MiB available; the cap is 4 KiB. The
    executor must stop reading shortly after the cap, not after the whole
    5 MiB."""
    with local_server(_oversized_handler) as (port, log):
        policy = EgressPolicy(allowed_hosts=frozenset({"api.example.com"}), allow_plaintext_http=True,
                              local_dev_hosts=frozenset({"api.example.com"}))
        result = execute_http_tool(
            method="GET", base_url=f"http://api.example.com:{port}", path="/big",
            policy=policy, resolver=_fake_resolver({"api.example.com": ["127.0.0.1"]}),
            max_response_bytes=4096, verify=False,
        )
    assert result.truncated is True
    assert result.success is False
    # Stopped within a small number of chunks past the cap -- nowhere near
    # the 5 MiB the server was prepared to send.
    assert result.response_bytes < 4096 + 65536 * 2


def test_call_exceeding_timeout_is_terminated() -> None:
    """AC-20."""
    with local_server(_slow_handler(2.0)) as (port, log):
        policy = EgressPolicy(allowed_hosts=frozenset({"api.example.com"}), allow_plaintext_http=True,
                              local_dev_hosts=frozenset({"api.example.com"}))
        start = time.monotonic()
        result = execute_http_tool(
            method="GET", base_url=f"http://api.example.com:{port}", path="/slow",
            policy=policy, resolver=_fake_resolver({"api.example.com": ["127.0.0.1"]}),
            timeout_seconds=0.2, verify=False,
        )
        elapsed = time.monotonic() - start
    assert result.success is False
    assert result.error == "TIMEOUT"
    assert elapsed < 1.9, "the call must not have waited for the server's full 2s delay"


def test_connection_is_pinned_to_the_validated_ip_not_a_fresh_lookup() -> None:
    """The executor-level half of rebinding defense (ACT-TLX-FR-006): a
    resolver that would answer differently on a second call is only ever
    consulted once per request -- the connection reaches the server via
    the *first* (validated) answer, proving there is no second DNS lookup
    for a rebinding attacker to win between validation and connect."""
    calls = {"n": 0}

    def rebinding_resolver(host: str) -> list[str]:
        calls["n"] += 1
        return ["127.0.0.1"] if calls["n"] == 1 else ["10.0.0.9"]

    with local_server(_json_ok_handler) as (port, log):
        policy = EgressPolicy(allowed_hosts=frozenset({"api.example.com"}), allow_plaintext_http=True,
                              local_dev_hosts=frozenset({"api.example.com"}))
        result = execute_http_tool(
            method="GET", base_url=f"http://api.example.com:{port}", path="/",
            policy=policy, resolver=rebinding_resolver, verify=False,
        )
    assert result.success is True
    assert calls["n"] == 1, "resolver must be consulted exactly once per request, not re-resolved at connect time"
    assert len(log.requests) == 1


# --------------------------------------------------------------------------- #
# HTTP helpers for the full pipeline (local copies, matching this
# directory's established convention)
# --------------------------------------------------------------------------- #
def _register_org(client: TestClient, org_name: str = "HTTP Tools Org") -> dict:
    email = f"httptool_{uuid.uuid4().hex[:10]}@example.com"
    assert client.post("/auth/register", json={
        "organization_name": org_name, "name": "Owner", "email": email, "password": PASSWORD,
    }).status_code == 201
    tokens = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD}).json()
    h = {"Authorization": f"Bearer {tokens['access_token']}"}
    me = client.get("/api/v1/auth/me", headers=h).json()
    return {"headers": h, "user_id": me["user"]["id"], "organization_id": me["user"]["organization_id"]}


def _invite_member(client: TestClient, admin: dict, *, role: str = "VIEWER") -> dict:
    email = f"httptoolm_{uuid.uuid4().hex[:10]}@example.com"
    r = client.post("/api/v1/identity/users", headers=admin["headers"], json={
        "email": email, "display_name": "Member", "password": PASSWORD, "role": role,
        "organization_id": admin["organization_id"],
    })
    assert r.status_code in (200, 201), r.text
    tokens = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD}).json()
    return {"headers": {"Authorization": f"Bearer {tokens['access_token']}"}}


def _register_agent(client: TestClient, admin: dict) -> dict:
    r = client.post(f"{RT}/agents", headers=admin["headers"], json={
        "name": f"HTTP Tool Agent {uuid.uuid4().hex[:6]}", "agent_type": "ASSISTANT", "criticality": "MEDIUM",
        "description": "A test agent.", "business_purpose": "Exercise HTTP tool execution in tests.",
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
                      name: str | None = None) -> dict:
    r = client.post(f"{RT}/tools", headers=admin["headers"], json={
        "name": name or f"http_tool_{uuid.uuid4().hex[:8]}", "display_name": "HTTP Tool", "tool_type": "HTTP",
        "endpoint_reference": endpoint, "http_config": http_config,
    })
    assert r.status_code == 201, r.text
    return r.json()


def _assign_tool(client: TestClient, admin: dict, agent_id: str, tool_id: str,
                 allowed_actions: list[str] | None = None) -> dict:
    r = client.post(f"{RT}/agents/{agent_id}/tools", headers=admin["headers"], json={
        "tool_id": tool_id, "allowed_actions": allowed_actions or ["EXECUTE", "READ"],
    })
    assert r.status_code == 201, r.text
    return r.json()


def _publish_version(client: TestClient, admin: dict, agent_id: str, *, tool_ids: list[str] | None = None) -> dict:
    r = client.post(f"{RT}/agents/{agent_id}/versions", headers=admin["headers"], json={
        "model_configuration": {"provider": "MOCK", "model": "mock-model"},
        "tool_ids": tool_ids or [],
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
                                assign: bool = True, include_in_snapshot: bool = True) -> dict:
    agent = _register_agent(client, admin)
    _activate_agent(client, admin, agent["id"])
    tool = _create_http_tool(client, admin, endpoint=endpoint, http_config=http_config)
    if assign:
        _assign_tool(client, admin, agent["id"], tool["id"])
    version = _publish_version(client, admin, agent["id"], tool_ids=[tool["id"]] if include_in_snapshot else [])
    deployment = _deploy(client, admin, agent["id"], version["id"])
    return {"agent": agent, "tool": tool, "version": version, "deployment": deployment}


def _run_execution(client: TestClient, admin: dict, agent_id: str, *, tool_name: str, action: str = "READ",
                   params: dict | None = None) -> dict:
    r = client.post(f"{RT}/executions", headers=admin["headers"], json={
        "agent_id": agent_id,
        "input_payload": {"tool_calls": [{"tool_name": tool_name, "action": action, "params": params or {}}]},
    })
    assert r.status_code == 201, r.text
    return r.json()


def _http_config(port: int, *, host: str = "api.example.com", requires_credential: bool = False,
                 sensitive_headers: list[str] | None = None) -> dict:
    return {
        "allowed_hosts": [host], "allow_plaintext_http": True, "local_dev_hosts": [host],
        "requires_credential": requires_credential,
        "sensitive_headers": sensitive_headers or ["Authorization"],
        "max_response_bytes": 1_048_576,
    }


@pytest.fixture(autouse=True)
def _patch_default_resolver(monkeypatch):
    """Every full-pipeline test in this file uses ``127.0.0.1`` local
    servers reached through a made-up hostname (matching how a tool
    declaration would name a real API host) -- ``ToolGatewayService``
    always calls ``execute_http_tool`` with no explicit resolver, so the
    module-level default is patched here, once, for the whole file."""
    def _resolve(host: str) -> list[str]:
        return ["127.0.0.1"]
    monkeypatch.setattr(egress_guard, "_default_resolve", _resolve)


# --------------------------------------------------------------------------- #
# Full pipeline — AC-11, AC-12, AC-13, AC-15, AC-21
# --------------------------------------------------------------------------- #
def test_full_execution_records_egress_allowed_and_http_metadata(client: TestClient, db_session: Session) -> None:
    """AC-13, AC-21 (full pipeline)."""
    with local_server(_json_ok_handler) as (port, log):
        org = _register_org(client)
        setup = _ready_agent_with_http_tool(client, org, endpoint=f"http://api.example.com:{port}",
                                            http_config=_http_config(port))
        execution = _run_execution(client, org, setup["agent"]["id"], tool_name=setup["tool"]["name"],
                                   action="READ", params={"path": "/orders/42"})

    assert execution["status"] == "SUCCEEDED"
    calls = client.get(f"{RT}/executions/{execution['id']}/tool-calls", headers=org["headers"]).json()
    assert len(calls) == 1
    call = calls[0]
    assert call["status"] == "ALLOWED"
    assert call["egress_decision"] == "ALLOWED"
    assert call["target_host"] == "api.example.com"
    assert call["target_path"] == "/orders/42"
    assert call["http_method"] == "GET"
    assert call["http_status"] == 200
    assert call["duration_ms"] is not None
    assert call["response_bytes"] is not None and call["response_bytes"] > 0
    assert log.requests[0]["path"] == "/orders/42"


def test_egress_denial_writes_decision_and_reason_and_fails_the_execution(client: TestClient,
                                                                          db_session: Session) -> None:
    """AC-11 — every denial writes ``egress_decision = DENIED`` with the
    rule that fired."""
    org = _register_org(client)
    config = _http_config(9999, host="only-this-host-is-allowed.example.com")
    config["allow_plaintext_http"] = False  # isolate the allowlist rule from the scheme rule
    setup = _ready_agent_with_http_tool(
        client, org, endpoint="https://not-allowlisted.example.com", http_config=config,
    )
    execution = _run_execution(client, org, setup["agent"]["id"], tool_name=setup["tool"]["name"])

    assert execution["status"] == "FAILED"
    assert execution["error_code"] == "TOOL_EGRESS_DENIED"
    row = db_session.execute(select(ToolCall).where(ToolCall.execution_id == uuid.UUID(execution["id"]))).scalars().one()
    assert row.status == "DENIED"
    assert row.egress_decision == "DENIED"
    assert row.egress_denied_reason == "HOST_NOT_ALLOWLISTED"


def test_egress_denial_emits_the_security_severity_event(client: TestClient, db_session: Session) -> None:
    """AC-12."""
    org = _register_org(client)
    setup = _ready_agent_with_http_tool(
        client, org, endpoint="http://not-allowlisted.example.com",
        http_config=_http_config(9999, host="only-this-host-is-allowed.example.com"),
    )
    execution = _run_execution(client, org, setup["agent"]["id"], tool_name=setup["tool"]["name"])
    assert execution["status"] == "FAILED"

    events = db_session.execute(
        select(RuntimeEvent).where(RuntimeEvent.execution_id == uuid.UUID(execution["id"]),
                                   RuntimeEvent.event_type == "RUNTIME_TOOL_EGRESS_DENIED")
    ).scalars().all()
    assert len(events) == 1
    assert events[0].severity == "CRITICAL"


def test_unimplemented_action_still_fails_tool_action_not_allowed(client: TestClient) -> None:
    """AC-15 — a tool type that is neither FUNCTION nor HTTP still fails
    closed, unchanged."""
    org = _register_org(client)
    agent = _register_agent(client, org)
    _activate_agent(client, org, agent["id"])
    tool = client.post(f"{RT}/tools", headers=org["headers"], json={
        "name": "db_tool", "display_name": "Database Tool", "tool_type": "DATABASE",
    }).json()
    _assign_tool(client, org, agent["id"], tool["id"])
    version = _publish_version(client, org, agent["id"], tool_ids=[tool["id"]])
    _deploy(client, org, agent["id"], version["id"])

    execution = _run_execution(client, org, agent["id"], tool_name="db_tool")
    assert execution["status"] in ("FAILED", "DEAD_LETTERED")
    assert execution["error_code"] == "TOOL_ACTION_NOT_ALLOWED"


# --------------------------------------------------------------------------- #
# Immutability — AC-16, AC-28
# --------------------------------------------------------------------------- #
def test_allowlist_is_read_from_frozen_snapshot_not_mutable_tool_state(
    client: TestClient, db_session: Session) -> None:
    """AC-16 — widening a tool's allowlist *after* a version is published
    must not affect that already-published version's enforcement."""
    with local_server(_json_ok_handler) as (port, log):
        org = _register_org(client)
        setup = _ready_agent_with_http_tool(client, org, endpoint=f"http://api.example.com:{port}",
                                            http_config=_http_config(port, host="api.example.com"))

        # Widen the *live* tool's allowlist to something else entirely --
        # a real attempt to smuggle a new host into an already-signed version.
        from app.models.runtime import Tool
        tool_row = db_session.get(Tool, uuid.UUID(setup["tool"]["id"]))
        tool_row.http_config = {**tool_row.http_config, "allowed_hosts": ["attacker.example.net"]}
        db_session.commit()

        # The already-published version must still only ever permit the
        # host that was frozen into its snapshot at publish time.
        execution = _run_execution(client, org, setup["agent"]["id"], tool_name=setup["tool"]["name"],
                                   params={"path": "/still-works"})
    assert execution["status"] == "SUCCEEDED"
    assert log.requests[0]["path"] == "/still-works"

    snapshot = db_session.execute(
        select(AgentVersionSnapshot).where(AgentVersionSnapshot.agent_version_id == uuid.UUID(setup["version"]["id"]))
    ).scalars().one()
    frozen_hosts = snapshot.snapshot["runtime"]["tool_configs"][setup["tool"]["id"]]["http_config"]["allowed_hosts"]
    assert frozen_hosts == ["api.example.com"]
    assert "attacker.example.net" not in frozen_hosts


def test_tool_not_in_published_snapshot_is_rejected(client: TestClient) -> None:
    """AC-28 — a tool assigned to the agent but never included in the
    published version's ``tools_snapshot`` has no frozen policy to read
    and is rejected outright."""
    org = _register_org(client)
    setup = _ready_agent_with_http_tool(
        client, org, endpoint="http://api.example.com", http_config=_http_config(9999),
        include_in_snapshot=False,  # assigned, but never frozen into the version
    )
    execution = _run_execution(client, org, setup["agent"]["id"], tool_name=setup["tool"]["name"])
    assert execution["status"] in ("FAILED", "DEAD_LETTERED")
    assert execution["error_code"] == "TOOL_ACTION_NOT_ALLOWED"


# --------------------------------------------------------------------------- #
# Credentials & redaction — AC-22, AC-23, AC-24, AC-25
# --------------------------------------------------------------------------- #
def test_credential_resolved_at_execution_time_and_injected(client: TestClient, db_session: Session) -> None:
    """AC-22."""
    with local_server(_json_ok_handler) as (port, log):
        org = _register_org(client)
        setup = _ready_agent_with_http_tool(
            client, org, endpoint=f"http://api.example.com:{port}",
            http_config=_http_config(port, requires_credential=True),
        )
        ToolCredentialService(db_session).store(
            _Actor(org["user_id"]), uuid.UUID(org["organization_id"]), uuid.UUID(setup["tool"]["id"]), _FAKE_SECRET)
        db_session.commit()

        execution = _run_execution(client, org, setup["agent"]["id"], tool_name=setup["tool"]["name"])
    assert execution["status"] == "SUCCEEDED"
    assert log.requests[0]["authorization"] == f"Bearer {_FAKE_SECRET}"


class _Actor:
    def __init__(self, user_id: str) -> None:
        self.id = uuid.UUID(user_id)


def test_no_credential_value_anywhere_in_tool_calls_logs_or_events(
    client: TestClient, db_session: Session, caplog) -> None:
    """AC-23."""
    with local_server(_json_ok_handler) as (port, log):
        org = _register_org(client)
        setup = _ready_agent_with_http_tool(
            client, org, endpoint=f"http://api.example.com:{port}",
            http_config=_http_config(port, requires_credential=True),
        )
        ToolCredentialService(db_session).store(
            _Actor(org["user_id"]), uuid.UUID(org["organization_id"]), uuid.UUID(setup["tool"]["id"]), _FAKE_SECRET)
        db_session.commit()

        with caplog.at_level("DEBUG"):
            execution = _run_execution(client, org, setup["agent"]["id"], tool_name=setup["tool"]["name"])
    assert execution["status"] == "SUCCEEDED"
    assert _FAKE_SECRET not in caplog.text

    row = db_session.execute(select(ToolCall).where(ToolCall.execution_id == uuid.UUID(execution["id"]))).scalars().one()
    assert _FAKE_SECRET not in jsonlib.dumps(row.input_summary or {})
    assert _FAKE_SECRET not in jsonlib.dumps(row.output_summary or {})

    events = db_session.execute(
        select(RuntimeEvent).where(RuntimeEvent.execution_id == uuid.UUID(execution["id"]))
    ).scalars().all()
    for event in events:
        assert _FAKE_SECRET not in jsonlib.dumps(event.payload or {})


def test_sensitive_headers_redacted_in_audit_record(client: TestClient, db_session: Session) -> None:
    """AC-24."""
    with local_server(_json_ok_handler) as (port, log):
        org = _register_org(client)
        setup = _ready_agent_with_http_tool(
            client, org, endpoint=f"http://api.example.com:{port}",
            http_config=_http_config(port, requires_credential=True),
        )
        ToolCredentialService(db_session).store(
            _Actor(org["user_id"]), uuid.UUID(org["organization_id"]), uuid.UUID(setup["tool"]["id"]), _FAKE_SECRET)
        db_session.commit()

        execution = _run_execution(client, org, setup["agent"]["id"], tool_name=setup["tool"]["name"])
    assert execution["status"] == "SUCCEEDED"
    # The real request really did carry it...
    assert log.requests[0]["authorization"] == f"Bearer {_FAKE_SECRET}"

    row = db_session.execute(select(ToolCall).where(ToolCall.execution_id == uuid.UUID(execution["id"]))).scalars().one()
    recorded_headers = (row.input_summary or {}).get("_request_headers", {})
    assert recorded_headers.get("Authorization") == "***REDACTED***"


def test_snapshot_contains_no_credential_value(client: TestClient, db_session: Session) -> None:
    """AC-25 — the frozen snapshot only ever carries the *fact* that a
    credential is required, never the secret."""
    org = _register_org(client)
    setup = _ready_agent_with_http_tool(
        client, org, endpoint="http://api.example.com",
        http_config=_http_config(9999, requires_credential=True),
    )
    ToolCredentialService(db_session).store(
        _Actor(org["user_id"]), uuid.UUID(org["organization_id"]), uuid.UUID(setup["tool"]["id"]), _FAKE_SECRET)
    db_session.commit()

    snapshot = db_session.execute(
        select(AgentVersionSnapshot).where(AgentVersionSnapshot.agent_version_id == uuid.UUID(setup["version"]["id"]))
    ).scalars().one()
    blob = jsonlib.dumps(snapshot.snapshot, default=str)
    assert _FAKE_SECRET not in blob
    assert snapshot.snapshot["runtime"]["tool_configs"][setup["tool"]["id"]]["http_config"]["requires_credential"] is True


# --------------------------------------------------------------------------- #
# Integrity — AC-27
# --------------------------------------------------------------------------- #
def test_authorization_gateway_runs_before_tool_execution(client: TestClient, monkeypatch) -> None:
    """AC-27 — an unauthorized execution request never reaches the tool
    gateway at all (queueing, and therefore the worker, is never reached
    for a denied request)."""
    from app.runtime.services import ToolGatewayService

    calls: list[str] = []
    original = ToolGatewayService.invoke

    def _spy(self, *args, **kwargs):
        calls.append("invoked")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(ToolGatewayService, "invoke", _spy)

    org = _register_org(client)
    setup = _ready_agent_with_http_tool(client, org, endpoint="http://api.example.com",
                                        http_config=_http_config(9999))
    viewer = _invite_member(client, org, role="VIEWER")

    r = client.post(f"{RT}/executions", headers=viewer["headers"], json={
        "agent_id": setup["agent"]["id"],
        "input_payload": {"tool_calls": [{"tool_name": setup["tool"]["name"], "action": "READ", "params": {}}]},
    })
    assert r.status_code == 403, r.text
    assert calls == [], "the tool gateway ran despite authorization denying the request first"


# --------------------------------------------------------------------------- #
# AC-33 — no new TODO/FIXME/NotImplementedError/skip/xfail
# --------------------------------------------------------------------------- #
def test_no_new_todo_or_skip_markers_in_this_phases_files() -> None:
    """AC-33."""
    from pathlib import Path

    backend_dir = Path(__file__).resolve().parents[2]
    files = [
        backend_dir / "app" / "runtime" / "tools" / "egress_guard.py",
        backend_dir / "app" / "runtime" / "tools" / "http_executor.py",
        backend_dir / "app" / "runtime" / "services.py",
        backend_dir / "app" / "runtime" / "routes.py",
        backend_dir / "app" / "runtime" / "schemas.py",
        backend_dir / "app" / "models" / "runtime.py",
        backend_dir / "app" / "runtime" / "versioning" / "snapshot.py",
        backend_dir / "migrations" / "versions" / "0030_http_tool_egress.py",
    ]
    forbidden = ("TODO", "FIXME", "NotImplementedError", "pytest.mark.skip", "pytest.mark.xfail")
    for path in files:
        text = path.read_text(encoding="utf-8")
        hits = [token for token in forbidden if token in text]
        assert not hits, f"{path.name} contains forbidden marker(s): {hits}"
