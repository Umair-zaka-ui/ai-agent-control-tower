"""Phase 5.6a.3 tests — the model-driven tool invocation loop.

No test depends on a live model or a non-local network host (AC-31/32):
every model turn replays a committed or inline fixture through
``OpenAICompatibleProvider``'s ``httpx.MockTransport`` (never a real
socket); every HTTP tool call reaches a real ``http.server`` bound to
``127.0.0.1`` on an ephemeral port, exactly matching
``test_http_tool_execution.py``/``test_tool_resilience.py``'s own
convention. Termination-cap tests inject a fake ``time.monotonic`` clock
or a tiny token budget — never a real wait.
"""

from __future__ import annotations

import http.server
import json as jsonlib
import threading
import time
import uuid
from contextlib import contextmanager

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.runtime import AgentExecution, ExecutionMessage, RuntimeEvent, Tool, ToolCall
from app.runtime import services as services_module
from app.runtime.providers.openai_compatible import OpenAICompatibleProvider
from app.runtime.tools import egress_guard
from tests.runtime.conftest import load_fixture

PASSWORD = "T3st!Passw0rd#Ok"
RT = "/api/v1/runtime"


# --------------------------------------------------------------------------- #
# Model transport helpers — a stateful, sequenced MockTransport reused
# across every test in this file (local copy of the established pattern).
# --------------------------------------------------------------------------- #
def _sequenced_transport(*responses):
    """Each element of ``responses`` is either a fixture filename (str,
    loaded via ``load_fixture``) or an already-built dict body. Returns the
    Nth response for the Nth ``/chat/completions`` call this process
    makes; the last response repeats for any call beyond the sequence."""
    state = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        index = min(state["n"], len(responses) - 1)
        state["n"] += 1
        body = responses[index]
        if isinstance(body, str):
            body = load_fixture(body)
        return httpx.Response(200, json=body, request=request)

    return httpx.MockTransport(handler)


def _tool_call_response(pairs: list[tuple[str, str, dict]], *, response_id: str = "chatcmpl-loop") -> dict:
    """Builds a raw OpenAI-compatible ``tool_calls`` response body for
    ``pairs`` of ``(call_id, tool_name, arguments_dict)`` — used for
    scenarios no committed fixture covers (repeated calls, parallel
    batches, an always-different argument each turn)."""
    return {
        "id": response_id, "object": "chat.completion", "created": 1718000000,
        "model": "llama3",
        "choices": [{
            "index": 0,
            "message": {
                "role": "assistant", "content": None,
                "tool_calls": [
                    {"id": call_id, "type": "function",
                    "function": {"name": name, "arguments": jsonlib.dumps(args)}}
                    for call_id, name, args in pairs
                ],
            },
            "finish_reason": "tool_calls",
        }],
        "usage": {"prompt_tokens": 40, "completion_tokens": 10, "total_tokens": 50},
    }


def _final_answer_response(content: str = "Here is your final answer.") -> dict:
    return {
        "id": "chatcmpl-loop-final", "object": "chat.completion", "created": 1718000099,
        "model": "llama3",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 60, "completion_tokens": 20, "total_tokens": 80},
    }


@pytest.fixture(autouse=True)
def _patch_default_resolver(monkeypatch):
    monkeypatch.setattr(egress_guard, "_default_resolve", lambda host: ["127.0.0.1"])


def _use_transport(monkeypatch, transport: httpx.MockTransport) -> None:
    monkeypatch.setattr(OpenAICompatibleProvider, "_build_default_transport", lambda self: transport)


# --------------------------------------------------------------------------- #
# A real local HTTP server for the one HTTP-tool (egress-guarded) scenario
# — local copy of test_http_tool_execution.py's/test_tool_resilience.py's
# own convention.
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


def _weather_handler(log: _RequestLog):
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            log.requests.append({"path": self.path, "t": time.monotonic()})
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"ok": true, "temperature_f": 58}')

        def log_message(self, *a) -> None: pass

    return Handler


def _delayed_weather_handler(delay_by_path: dict[str, float]):
    def factory(log: _RequestLog):
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                start = time.monotonic()
                delay = next((d for p, d in delay_by_path.items() if p in self.path), 0.0)
                time.sleep(delay)
                log.requests.append({"path": self.path, "start": start, "end": time.monotonic()})
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"ok": true}')

            def log_message(self, *a) -> None: pass

        return Handler

    return factory


def _status_by_path_handler(status_by_path: dict[str, int], *, delay: float = 0.0):
    def factory(log: _RequestLog):
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                if delay:
                    time.sleep(delay)
                status = next((s for p, s in status_by_path.items() if p in self.path), 200)
                log.requests.append({"path": self.path})
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"ok": true}' if status < 400 else b'{"error": "boom"}')

            def log_message(self, *a) -> None: pass

        return Handler

    return factory


def _always_fails_handler(log: _RequestLog):
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            log.requests.append({"path": self.path})
            self.send_response(503)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"error": "down"}')

        def log_message(self, *a) -> None: pass

    return Handler


# --------------------------------------------------------------------------- #
# HTTP helpers for the full pipeline — local copies, matching this
# directory's established convention.
# --------------------------------------------------------------------------- #
def _register_org(client: TestClient, org_name: str = "Tool Loop Org") -> dict:
    email = f"toolloop_{uuid.uuid4().hex[:10]}@example.com"
    assert client.post("/auth/register", json={
        "organization_name": org_name, "name": "Owner", "email": email, "password": PASSWORD,
    }).status_code == 201
    tokens = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD}).json()
    h = {"Authorization": f"Bearer {tokens['access_token']}"}
    me = client.get("/api/v1/auth/me", headers=h).json()
    return {"headers": h, "user_id": me["user"]["id"], "organization_id": me["user"]["organization_id"]}


def _register_agent(client: TestClient, admin: dict, *, name: str | None = None) -> dict:
    r = client.post(f"{RT}/agents", headers=admin["headers"], json={
        "name": name or f"Loop Agent {uuid.uuid4().hex[:6]}", "agent_type": "ASSISTANT", "criticality": "MEDIUM",
        "description": "A test agent.", "business_purpose": "Exercise the model-driven tool loop.",
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


_WEATHER_INPUT_SCHEMA = {
    "type": "object", "required": ["location"], "properties": {"location": {"type": "string"}},
}


def _create_function_tool(client: TestClient, admin: dict, *, name: str = "get_weather") -> dict:
    r = client.post(f"{RT}/tools", headers=admin["headers"], json={
        "name": name, "display_name": "Get Weather", "tool_type": "FUNCTION",
        "description": "Look up the current weather for a location.",
        "input_schema": _WEATHER_INPUT_SCHEMA,
    })
    assert r.status_code == 201, r.text
    return r.json()


def _create_http_tool(client: TestClient, admin: dict, *, endpoint: str, port: int, host: str,
                      idempotent: bool = True, name: str = "get_weather") -> dict:
    r = client.post(f"{RT}/tools", headers=admin["headers"], json={
        "name": name, "display_name": "Get Weather", "tool_type": "HTTP", "endpoint_reference": endpoint,
        "description": "Look up the current weather for a location.",
        "input_schema": {"type": "object", "properties": {"path": {"type": "string"}}},
        "http_config": {
            "allowed_hosts": [host], "allow_plaintext_http": True, "local_dev_hosts": [host],
            "idempotent": idempotent, "method": "GET",
        },
    })
    assert r.status_code == 201, r.text
    return r.json()


def _assign_tool(client: TestClient, admin: dict, agent_id: str, tool_id: str) -> dict:
    r = client.post(f"{RT}/agents/{agent_id}/tools", headers=admin["headers"], json={
        "tool_id": tool_id, "allowed_actions": ["EXECUTE", "READ"],
    })
    assert r.status_code == 201, r.text
    return r.json()


def _publish_version(client: TestClient, admin: dict, agent_id: str, *, tool_ids: list[str] | None = None,
                     model_configuration: dict | None = None) -> dict:
    r = client.post(f"{RT}/agents/{agent_id}/versions", headers=admin["headers"], json={
        "model_configuration": model_configuration or {"provider": "OPENAI_COMPATIBLE", "model": "llama3"},
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


def _ready_agent(client: TestClient, admin: dict, *, tool_ids: list[str] | None = None,
                 assign_tool_ids: list[str] | None = None,
                 model_configuration: dict | None = None, name: str | None = None) -> dict:
    agent = _register_agent(client, admin, name=name)
    _activate_agent(client, admin, agent["id"])
    for tool_id in (assign_tool_ids if assign_tool_ids is not None else (tool_ids or [])):
        _assign_tool(client, admin, agent["id"], tool_id)
    version = _publish_version(client, admin, agent["id"], tool_ids=tool_ids, model_configuration=model_configuration)
    deployment = _deploy(client, admin, agent["id"], version["id"])
    return {"agent": agent, "version": version, "deployment": deployment}


def _run_execution(client: TestClient, admin: dict, agent_id: str, *, input_payload: dict | None = None) -> dict:
    r = client.post(f"{RT}/executions", headers=admin["headers"], json={
        "agent_id": agent_id, "input_payload": input_payload or {"question": "What's the weather in New York?"},
    })
    assert r.status_code == 201, r.text
    return r.json()


def _messages(db_session: Session, execution_id: str) -> list[ExecutionMessage]:
    return list(db_session.execute(
        select(ExecutionMessage).where(ExecutionMessage.execution_id == uuid.UUID(execution_id))
        .order_by(ExecutionMessage.sequence)
    ).scalars())


def _tool_calls(db_session: Session, execution_id: str) -> list[ToolCall]:
    return list(db_session.execute(
        select(ToolCall).where(ToolCall.execution_id == uuid.UUID(execution_id)).order_by(ToolCall.created_at)
    ).scalars())


# --------------------------------------------------------------------------- #
# The loop — AC-01, AC-03, AC-06
# --------------------------------------------------------------------------- #
def test_full_loop_runs_tool_and_produces_final_answer(client: TestClient, db_session: Session, monkeypatch) -> None:
    """AC-01, AC-03, AC-06."""
    _use_transport(monkeypatch, _sequenced_transport("single_tool_call.json", "multi_turn_with_tool_message.json"))
    org = _register_org(client)
    tool = _create_function_tool(client, org)
    setup = _ready_agent(client, org, tool_ids=[tool["id"]])

    execution = _run_execution(client, org, setup["agent"]["id"])

    assert execution["status"] == "SUCCEEDED"
    assert execution["loop_iterations"] == 2
    assert execution["termination_reason"] == "COMPLETED"
    assert "58" in execution["output_payload"]["result"] or "cloudy" in execution["output_payload"]["result"]
    assert set(execution["output_payload"]) == {"result", "echo"}  # AC-06 -- unchanged shape
    assert set(execution["model_usage"]) >= {
        "provider", "model", "input_tokens", "output_tokens", "total_tokens",
        "token_accounting_complete", "finish_reason", "tool_calls",
    }

    rows = _tool_calls(db_session, execution["id"])
    assert len(rows) == 1
    assert rows[0].status == "ALLOWED"
    assert rows[0].loop_iteration == 1

    msgs = _messages(db_session, execution["id"])
    assert [m.role for m in msgs] == ["user", "assistant", "tool", "assistant"]
    assert msgs[1].tool_calls_requested[0]["name"] == "get_weather"
    assert msgs[2].tool_call_id == msgs[1].tool_calls_requested[0]["id"]


def test_single_turn_execution_unaffected_by_the_loop(client: TestClient, db_session: Session) -> None:
    """AC-02 -- MOCK, no tools bound: the loop runs exactly one iteration
    and never offers a tool (MOCK never supports them either way)."""
    org = _register_org(client)
    setup = _ready_agent(client, org, model_configuration={"provider": "MOCK", "model": "mock-model"})
    execution = _run_execution(client, org, setup["agent"]["id"], input_payload={"question": "hello"})

    assert execution["status"] == "SUCCEEDED"
    assert execution["loop_iterations"] == 1
    assert execution["termination_reason"] == "COMPLETED"
    assert execution["tool_usage"] == {"calls": 0}


# --------------------------------------------------------------------------- #
# Tool binding / authorization — AC-04, AC-05, AC-07
# --------------------------------------------------------------------------- #
def test_tool_named_by_model_absent_from_snapshot_is_rejected(
        client: TestClient, db_session: Session, monkeypatch) -> None:
    """AC-04 -- no tool at all is bound to this version."""
    _use_transport(monkeypatch, _sequenced_transport("single_tool_call.json"))
    org = _register_org(client)
    setup = _ready_agent(client, org)  # no tool_ids at all

    execution = _run_execution(client, org, setup["agent"]["id"])
    assert execution["status"] == "FAILED"
    assert execution["error_code"] == "TOOL_NOT_BOUND_TO_VERSION"
    assert execution["termination_reason"] == "TOOL_DENIED"


def test_every_loop_tool_call_passes_through_established_authorization(
        client: TestClient, db_session: Session, monkeypatch) -> None:
    """AC-05 -- the tool exists in this version's frozen tools_snapshot
    (so it passes the loop's own TOOL_NOT_BOUND_TO_VERSION check) but was
    never assigned to the agent via the pre-existing AgentTool path --
    ToolGatewayService.invoke()'s own, unbypassed assignment check must
    still reject it with TOOL_NOT_ASSIGNED."""
    _use_transport(monkeypatch, _sequenced_transport("single_tool_call.json"))
    org = _register_org(client)
    tool = _create_function_tool(client, org)
    setup = _ready_agent(client, org, tool_ids=[tool["id"]], assign_tool_ids=[])  # bound, never assigned

    execution = _run_execution(client, org, setup["agent"]["id"])
    assert execution["status"] == "FAILED"
    assert execution["error_code"] == "TOOL_NOT_ASSIGNED"


def test_agent_cannot_invoke_another_agent_through_the_loop(
        client: TestClient, db_session: Session, monkeypatch) -> None:
    """AC-07 -- §10.4. There is no mechanism for the model to name another
    agent as a "tool" at all: tools_snapshot only ever contains Tool ids,
    never Agent ids, so a model naming a real second agent's identifier is
    simply an unbound tool name, rejected exactly like any other."""
    other_agent = _register_agent(client, _register_org(client), name="other-agent-should-be-unreachable")
    org = _register_org(client)
    _use_transport(monkeypatch, _sequenced_transport(
        _tool_call_response([("call_1", other_agent["name"], {"location": "New York"})])))
    setup = _ready_agent(client, org)  # no tools bound at all

    execution = _run_execution(client, org, setup["agent"]["id"])
    assert execution["status"] == "FAILED"
    assert execution["error_code"] == "TOOL_NOT_BOUND_TO_VERSION"


# --------------------------------------------------------------------------- #
# Termination — AC-08..13
# --------------------------------------------------------------------------- #
def test_iteration_cap_terminates_with_max_iterations(
        client: TestClient, db_session: Session, monkeypatch) -> None:
    """AC-08."""
    monkeypatch.setattr(settings, "TOOL_LOOP_MAX_ITERATIONS", 2)
    responses = [_tool_call_response([(f"call_{i}", "get_weather", {"location": f"City {i}"})]) for i in range(5)]
    _use_transport(monkeypatch, _sequenced_transport(*responses))
    org = _register_org(client)
    tool = _create_function_tool(client, org)
    setup = _ready_agent(client, org, tool_ids=[tool["id"]])

    execution = _run_execution(client, org, setup["agent"]["id"])
    assert execution["status"] == "FAILED"
    assert execution["error_code"] == "TOOL_LOOP_LIMIT_EXCEEDED"
    assert execution["termination_reason"] == "MAX_ITERATIONS"
    assert execution["loop_iterations"] == 2


def test_token_budget_terminates_with_token_budget(
        client: TestClient, db_session: Session, monkeypatch) -> None:
    """AC-09."""
    monkeypatch.setattr(settings, "TOOL_LOOP_MAX_TOTAL_TOKENS", 10)
    responses = [_tool_call_response([(f"call_{i}", "get_weather", {"location": f"City {i}"})]) for i in range(5)]
    _use_transport(monkeypatch, _sequenced_transport(*responses))
    org = _register_org(client)
    tool = _create_function_tool(client, org)
    setup = _ready_agent(client, org, tool_ids=[tool["id"]])

    execution = _run_execution(client, org, setup["agent"]["id"])
    assert execution["status"] == "FAILED"
    assert execution["error_code"] == "TOOL_LOOP_LIMIT_EXCEEDED"
    assert execution["termination_reason"] == "TOKEN_BUDGET"


def test_wall_clock_cap_terminates_with_wall_clock(
        client: TestClient, db_session: Session, monkeypatch) -> None:
    """AC-10 -- injected fake clock, no real wait (AC-32)."""
    monkeypatch.setattr(settings, "TOOL_LOOP_MAX_WALL_CLOCK_SECONDS", 5.0)
    clock = {"t": 0.0}
    monkeypatch.setattr(services_module.time, "monotonic", lambda: clock["t"])

    def handler(request: httpx.Request) -> httpx.Response:
        clock["t"] += 100.0  # "the call took a very long time"
        body = _tool_call_response([("call_x", "get_weather", {"location": "City"})])
        return httpx.Response(200, json=body, request=request)

    _use_transport(monkeypatch, httpx.MockTransport(handler))
    org = _register_org(client)
    tool = _create_function_tool(client, org)
    setup = _ready_agent(client, org, tool_ids=[tool["id"]])

    execution = _run_execution(client, org, setup["agent"]["id"])
    assert execution["status"] == "FAILED"
    assert execution["error_code"] == "TOOL_LOOP_LIMIT_EXCEEDED"
    assert execution["termination_reason"] == "WALL_CLOCK"


def test_repeated_identical_call_terminates_before_executing_the_duplicate(
        client: TestClient, db_session: Session, monkeypatch) -> None:
    """AC-11 -- terminates on iteration 2, well before the (default, 10)
    iteration cap; the duplicate call is never actually executed."""
    _use_transport(monkeypatch, _sequenced_transport("single_tool_call.json", "single_tool_call.json"))
    org = _register_org(client)
    tool = _create_function_tool(client, org)
    setup = _ready_agent(client, org, tool_ids=[tool["id"]])

    execution = _run_execution(client, org, setup["agent"]["id"])
    assert execution["status"] == "FAILED"
    assert execution["error_code"] == "TOOL_LOOP_LIMIT_EXCEEDED"
    assert execution["termination_reason"] == "REPEATED_CALL"
    assert execution["loop_iterations"] < settings.TOOL_LOOP_MAX_ITERATIONS

    rows = _tool_calls(db_session, execution["id"])
    assert len(rows) == 1, "the repeated (2nd) call must never have been executed"


def test_always_failing_tool_with_a_persistent_model_terminates_bounded(
        client: TestClient, db_session: Session, monkeypatch) -> None:
    """AC-13 -- a model that keeps retrying an always-failing tool (with
    different arguments each time, so REPEATED_CALL doesn't intervene)
    still terminates, in bounded iterations and bounded requests."""
    monkeypatch.setattr(settings, "TOOL_LOOP_MAX_ITERATIONS", 3)
    responses = [_tool_call_response([(f"call_{i}", "get_weather", {"location": f"City {i}"})]) for i in range(10)]
    _use_transport(monkeypatch, _sequenced_transport(*responses))

    with local_server(_always_fails_handler) as (port, log):
        org = _register_org(client)
        tool = _create_http_tool(client, org, endpoint=f"http://api.example.com:{port}",
                                 port=port, host="api.example.com", idempotent=False)
        setup = _ready_agent(client, org, tool_ids=[tool["id"]])
        execution = _run_execution(client, org, setup["agent"]["id"])

    assert execution["status"] == "FAILED"
    assert execution["termination_reason"] == "MAX_ITERATIONS"
    assert execution["loop_iterations"] == 3
    assert len(log.requests) <= 3, "bounded requests to the always-failing tool"


# --------------------------------------------------------------------------- #
# Parallel tool calls — AC-14..18
# --------------------------------------------------------------------------- #
def test_multiple_independent_tool_calls_execute_concurrently(
        client: TestClient, db_session: Session, monkeypatch) -> None:
    """AC-14, AC-15 -- 4 parallel calls against a ceiling of 2, each
    handler holding for a moment so contention is genuine and
    deterministic; two succeed, two hit the ceiling and fail (a
    structured FAILED result, not an abort)."""
    monkeypatch.setattr(settings, "TOOL_MAX_CONCURRENT_REQUESTS_PER_EXECUTION", 2)
    body = _tool_call_response([
        ("call_1", "get_weather", {"path": "/w1"}), ("call_2", "get_weather", {"path": "/w2"}),
        ("call_3", "get_weather", {"path": "/w3"}), ("call_4", "get_weather", {"path": "/w4"}),
    ])
    _use_transport(monkeypatch, _sequenced_transport(body, _final_answer_response()))

    with local_server(_delayed_weather_handler({"/w1": 0.3, "/w2": 0.3, "/w3": 0.3, "/w4": 0.3})) as (port, log):
        org = _register_org(client)
        tool = _create_http_tool(client, org, endpoint=f"http://api.example.com:{port}",
                                 port=port, host="api.example.com", idempotent=True)
        setup = _ready_agent(client, org, tool_ids=[tool["id"]])
        execution = _run_execution(client, org, setup["agent"]["id"])

    assert execution["status"] == "SUCCEEDED", "the ceiling rejections are FAILED, not execution-aborting"
    rows = _tool_calls(db_session, execution["id"])
    assert len(rows) == 4
    allowed = [r for r in rows if r.status == "ALLOWED"]
    concurrency_limited = [r for r in rows if r.error_code == "TOOL_CONCURRENCY_LIMIT_EXCEEDED"]
    assert len(allowed) == 2, "exactly the ceiling's worth of calls actually reached the server"
    assert len(concurrency_limited) == 2, "the excess calls fail fast on the concurrency ceiling"
    assert len(log.requests) == 2


def test_parallel_results_reassemble_in_model_expected_order(
        client: TestClient, db_session: Session, monkeypatch) -> None:
    """AC-16 -- call 1 is deliberately the slowest; the transcript's tool
    messages must still come back in call-id (submission) order, not
    completion order."""
    body = _tool_call_response([
        ("call_1", "get_weather", {"path": "/slow"}), ("call_2", "get_weather", {"path": "/fast"}),
    ])
    _use_transport(monkeypatch, _sequenced_transport(body, _final_answer_response()))

    with local_server(_delayed_weather_handler({"/slow": 0.4, "/fast": 0.05})) as (port, log):
        org = _register_org(client)
        tool = _create_http_tool(client, org, endpoint=f"http://api.example.com:{port}",
                                 port=port, host="api.example.com", idempotent=True)
        setup = _ready_agent(client, org, tool_ids=[tool["id"]])
        execution = _run_execution(client, org, setup["agent"]["id"])

    assert execution["status"] == "SUCCEEDED"
    msgs = [m for m in _messages(db_session, execution["id"]) if m.role == "tool"]
    assert [m.tool_call_id for m in msgs] == ["call_1", "call_2"], (
        "results must reassemble in submission order regardless of completion order"
    )


def test_one_failed_parallel_call_does_not_abort_the_others(
        client: TestClient, db_session: Session, monkeypatch) -> None:
    """AC-17."""
    body = _tool_call_response([
        ("call_1", "get_weather", {"path": "/ok"}), ("call_2", "get_weather", {"path": "/broken"}),
    ])
    _use_transport(monkeypatch, _sequenced_transport(body, _final_answer_response()))

    with local_server(_status_by_path_handler({"/broken": 500})) as (port, log):
        org = _register_org(client)
        tool = _create_http_tool(client, org, endpoint=f"http://api.example.com:{port}",
                                 port=port, host="api.example.com", idempotent=True)
        setup = _ready_agent(client, org, tool_ids=[tool["id"]])
        execution = _run_execution(client, org, setup["agent"]["id"])

    assert execution["status"] == "SUCCEEDED"
    rows = {r.target_path: r for r in _tool_calls(db_session, execution["id"])}
    assert rows["/ok"].status == "ALLOWED"
    assert rows["/broken"].status == "FAILED"
    assert rows["/broken"].error_class == "PROVIDER_UNAVAILABLE"


def test_non_idempotent_tools_are_not_run_in_parallel(
        client: TestClient, db_session: Session, monkeypatch) -> None:
    """AC-18 -- two calls to a tool declared non-idempotent must run
    sequentially: total elapsed time is at least the sum of both delays,
    proving no real overlap (a genuinely parallel pair would finish in
    roughly max(), not sum())."""
    body = _tool_call_response([
        ("call_1", "get_weather", {"path": "/a"}), ("call_2", "get_weather", {"path": "/b"}),
    ])
    _use_transport(monkeypatch, _sequenced_transport(body, _final_answer_response()))

    with local_server(_delayed_weather_handler({"/a": 0.25, "/b": 0.25})) as (port, log):
        org = _register_org(client)
        tool = _create_http_tool(client, org, endpoint=f"http://api.example.com:{port}",
                                 port=port, host="api.example.com", idempotent=False)
        setup = _ready_agent(client, org, tool_ids=[tool["id"]])
        start = time.monotonic()
        execution = _run_execution(client, org, setup["agent"]["id"])
        elapsed = time.monotonic() - start

    assert execution["status"] == "SUCCEEDED"
    assert elapsed >= 0.45, "non-idempotent calls must run sequentially, not overlap"
    assert len(log.requests) == 2


# --------------------------------------------------------------------------- #
# Transcript & accounting — AC-19, AC-20, AC-21, AC-22
# --------------------------------------------------------------------------- #
def test_failed_tool_result_is_appended_and_visible_to_the_next_turn(
        client: TestClient, db_session: Session, monkeypatch) -> None:
    """AC-21 -- a schema-invalid call (missing the required `location`)
    fails without ever reaching the tool, and the structured failure is
    what the next model turn actually receives as content."""
    bad_call = _tool_call_response([("call_1", "get_weather", {"wrong_field": "x"})])
    _use_transport(monkeypatch, _sequenced_transport(bad_call, _final_answer_response("Sorry, I could not look it up.")))
    org = _register_org(client)
    tool = _create_function_tool(client, org)
    setup = _ready_agent(client, org, tool_ids=[tool["id"]])

    execution = _run_execution(client, org, setup["agent"]["id"])
    assert execution["status"] == "SUCCEEDED"

    tool_message = next(m for m in _messages(db_session, execution["id"]) if m.role == "tool")
    payload = jsonlib.loads(tool_message.content)
    assert payload["error_code"] == "TOOL_SCHEMA_INVALID"


def test_each_iteration_records_its_own_tokens_cost_and_duration(
        client: TestClient, db_session: Session, monkeypatch) -> None:
    """AC-19, AC-20, AC-22."""
    _use_transport(monkeypatch, _sequenced_transport("single_tool_call.json", "multi_turn_with_tool_message.json"))
    org = _register_org(client)
    tool = _create_function_tool(client, org)
    setup = _ready_agent(client, org, tool_ids=[tool["id"]])

    execution = _run_execution(client, org, setup["agent"]["id"])
    assert execution["loop_iterations"] == 2
    assert execution["termination_reason"] == "COMPLETED"

    msgs = _messages(db_session, execution["id"])
    assistant_msgs = [m for m in msgs if m.role == "assistant"]
    assert len(assistant_msgs) == 2
    for m in assistant_msgs:
        assert m.prompt_tokens is not None and m.completion_tokens is not None and m.total_tokens is not None
        assert m.duration_ms is not None
        assert m.cost_amount is not None  # MOCK-less OPENAI_COMPATIBLE with no pricing row -> 0.0, still not None

    # every row is present, gapless sequence, in order
    assert [m.sequence for m in msgs] == list(range(len(msgs)))

    events = db_session.execute(
        select(RuntimeEvent).where(RuntimeEvent.execution_id == uuid.UUID(execution["id"]),
                                   RuntimeEvent.event_type == "RUNTIME_LOOP_TERMINATED")
    ).scalars().all()
    assert len(events) == 1
    assert events[0].severity == "INFO"


# --------------------------------------------------------------------------- #
# The milestone gate — AC-33
# --------------------------------------------------------------------------- #
def test_end_to_end_registered_versioned_agent_calls_model_and_real_tool(
        client: TestClient, db_session: Session, monkeypatch) -> None:
    """AC-33 -- a registered, versioned, signed, authorized agent receives
    a prompt, calls a real (fixtured) model, the model requests a real
    HTTP tool, the tool executes through the egress guard against a real
    local server, the result feeds back, the model produces a final
    answer, and the whole exchange is audited with per-turn cost."""
    with local_server(_weather_handler) as (port, log):
        _use_transport(monkeypatch, _sequenced_transport(
            _tool_call_response([("call_1", "get_weather", {"path": "/weather/new-york"})]),
            _final_answer_response("It's 58°F in New York right now."),
        ))
        org = _register_org(client)
        tool = _create_http_tool(client, org, endpoint=f"http://api.example.com:{port}",
                                 port=port, host="api.example.com", idempotent=True)
        setup = _ready_agent(client, org, tool_ids=[tool["id"]])
        # The version was validated/approved/published (signed, per Phase
        # 5.2.4) and deployed (authorized) by _ready_agent already.
        execution = _run_execution(client, org, setup["agent"]["id"],
                                   input_payload={"question": "What's the weather in New York?"})

    assert execution["status"] == "SUCCEEDED"
    assert "58" in execution["output_payload"]["result"]
    assert execution["loop_iterations"] == 2
    assert execution["termination_reason"] == "COMPLETED"
    assert log.requests and log.requests[0]["path"] == "/weather/new-york"

    rows = _tool_calls(db_session, execution["id"])
    assert len(rows) == 1
    assert rows[0].status == "ALLOWED"
    assert rows[0].egress_decision == "ALLOWED"
    assert rows[0].target_host == "api.example.com"

    msgs = _messages(db_session, execution["id"])
    assert [m.role for m in msgs] == ["user", "assistant", "tool", "assistant"]
    assert all(m.cost_amount is not None for m in msgs if m.role == "assistant")

    version = db_session.execute(
        select(Tool).where(Tool.id == uuid.UUID(tool["id"]))
    ).scalars().one()
    assert version is not None  # the tool genuinely exists and was the one actually invoked
