"""Phase 5.7a.4 tests — error taxonomy, retry, circuit breaking.

Four groups, matching the build prompt's own acceptance-criteria groupings:
classification (AC-01..05), retry (AC-06..14), circuit breaking & timeouts
(AC-15..18), integrity (AC-19..23, 27 — AC-24..26, 28 are suite-level,
proven by the full-suite run cited in the phase summary, not here).

Every test replays a committed fixture or a small inline transport through
``httpx.MockTransport`` — no test depends on a live endpoint (AC-24). Every
backoff/retry test injects the delay (monkeypatches ``time.sleep``), never
sleeping for real (AC-28).
"""

from __future__ import annotations

import uuid

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.runtime import AgentExecution, ExecutionAttempt
from app.runtime import services as services_module
from app.runtime.providers.errors import ProviderRequestFailedError
from app.runtime.providers.mock import MockProvider
from app.runtime.providers.openai_compatible import OpenAICompatibleProvider, _scrub
from app.runtime.providers.types import ModelMessage, ModelRequest, ProviderErrorClass
from app.runtime.services import (
    ModelGatewayService,
    _circuit_before_call,
    _circuit_record_failure,
    _circuit_record_success,
    _provider_backoff_delay,
)
from tests.runtime.conftest import load_fixture, load_sse_fixture, replay_sse_transport, replay_transport

PASSWORD = "T3st!Passw0rd#Ok"
RT = "/api/v1/runtime"


def _unique_provider_name() -> str:
    """Every direct (non-execution-level) retry/circuit-breaker test uses
    its own throwaway provider identifier — the circuit breaker is
    process-wide, module-level state (``ACT-MDL-FR-067``'s deliberate
    design), so sharing a key across tests (in particular the literal
    ``"OPENAI_COMPATIBLE"`` every execution-level test also uses) would
    make one test's failure history leak into another's expectations."""
    return f"TEST_PROVIDER_{uuid.uuid4().hex[:8]}"


def _sequenced_transport(*steps) -> tuple[httpx.MockTransport, list]:
    """Returns a transport that serves ``steps`` in order, one per request
    (the last step repeats once exhausted), plus the list of requests
    actually received. Each step is either a dict describing a response
    (``{"status": int, "json": dict, "headers": dict | None}``) or a
    callable ``(request) -> httpx.Response`` that may raise instead."""
    calls: list[httpx.Request] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        step = steps[min(len(calls) - 1, len(steps) - 1)]
        if callable(step):
            return step(request)
        return httpx.Response(step.get("status", 200), json=step.get("json", {}),
                              headers=step.get("headers"), request=request)

    return httpx.MockTransport(_handler), calls


def _raise_connect_error(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError("simulated connection refused", request=request)


def _raise_read_timeout(request: httpx.Request) -> httpx.Response:
    raise httpx.ReadTimeout("simulated read timeout", request=request)


# --------------------------------------------------------------------------- #
# HTTP helpers (local copies, matching this directory's established
# convention of not importing fixtures across test modules)
# --------------------------------------------------------------------------- #
def _register_org(client: TestClient) -> dict:
    email = f"resil_{uuid.uuid4().hex[:10]}@example.com"
    assert client.post("/auth/register", json={
        "organization_name": "Resilience Org", "name": "Owner", "email": email, "password": PASSWORD,
    }).status_code == 201
    tokens = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD}).json()
    h = {"Authorization": f"Bearer {tokens['access_token']}"}
    me = client.get("/api/v1/auth/me", headers=h).json()
    return {"headers": h, "user_id": me["user"]["id"], "organization_id": me["user"]["organization_id"]}


def _register_agent(client: TestClient, admin: dict) -> dict:
    r = client.post(f"{RT}/agents", headers=admin["headers"], json={
        "name": f"Resilience Agent {uuid.uuid4().hex[:6]}", "agent_type": "ASSISTANT", "criticality": "MEDIUM",
        "description": "A test agent.", "business_purpose": "Exercise error taxonomy/resilience in tests.",
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


def _publish_version(client: TestClient, admin: dict, agent_id: str, *, model_configuration: dict) -> dict:
    r = client.post(f"{RT}/agents/{agent_id}/versions", headers=admin["headers"], json={
        "model_configuration": model_configuration,
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


def _ready_agent(client: TestClient, admin: dict, *, model_configuration: dict) -> dict:
    agent = _register_agent(client, admin)
    _activate_agent(client, admin, agent["id"])
    version = _publish_version(client, admin, agent["id"], model_configuration=model_configuration)
    deployment = _deploy(client, admin, agent["id"], version["id"])
    return {"agent": agent, "version": version, "deployment": deployment}


def _run_execution(client: TestClient, admin: dict, agent_id: str, *, input_payload: dict | None = None) -> dict:
    r = client.post(f"{RT}/executions", headers=admin["headers"], json={
        "agent_id": agent_id, "input_payload": input_payload or {"question": "hello"},
    })
    assert r.status_code == 201, r.text
    return r.json()


# --------------------------------------------------------------------------- #
# Classification — AC-01, AC-02
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("fixture_name,status_code,expected_class", [
    ("error_rate_limited.json", 429, ProviderErrorClass.RATE_LIMITED),
    ("error_server_error.json", 500, ProviderErrorClass.PROVIDER_UNAVAILABLE),
    ("error_context_length_exceeded.json", 400, ProviderErrorClass.CONTEXT_LENGTH_EXCEEDED),
    ("error_content_filtered.json", 400, ProviderErrorClass.CONTENT_FILTERED),
    ("error_authentication_failed.json", 401, ProviderErrorClass.AUTHENTICATION_FAILED),
    ("error_invalid_request.json", 400, ProviderErrorClass.INVALID_REQUEST),
    ("error_unrecognizable.json", 418, ProviderErrorClass.UNKNOWN),
])
def test_status_based_fixtures_classify_correctly(fixture_name, status_code, expected_class) -> None:
    """AC-01 — seven of the nine fixtures; the remaining two (connection
    refused, read timeout) are transport-level, not status-based, and are
    exercised by the two tests immediately below."""
    provider = OpenAICompatibleProvider(transport=replay_transport(fixture_name, status_code=status_code))
    with pytest.raises(ProviderRequestFailedError) as exc_info:
        provider.complete(ModelRequest(messages=(ModelMessage(role="user", content="hi"),)))
    assert exc_info.value.error_class == expected_class


def test_connection_refused_classifies_as_provider_unavailable() -> None:
    """AC-01 — ``error_connection_refused.json`` (documentation-only, see
    the fixtures README) is exercised via a transport that raises directly,
    since a connection-refused failure has no HTTP response body at all."""
    provider = OpenAICompatibleProvider(transport=httpx.MockTransport(_raise_connect_error))
    with pytest.raises(ProviderRequestFailedError) as exc_info:
        provider.complete(ModelRequest(messages=(ModelMessage(role="user", content="hi"),)))
    assert exc_info.value.error_class == ProviderErrorClass.PROVIDER_UNAVAILABLE


def test_read_timeout_classifies_as_timeout() -> None:
    """AC-01 — ``error_read_timeout.json`` (documentation-only, see the
    fixtures README), same reasoning as connection-refused above."""
    provider = OpenAICompatibleProvider(transport=httpx.MockTransport(_raise_read_timeout))
    with pytest.raises(ProviderRequestFailedError) as exc_info:
        provider.complete(ModelRequest(messages=(ModelMessage(role="user", content="hi"),)))
    assert exc_info.value.error_class == ProviderErrorClass.TIMEOUT


def test_unrecognizable_failure_maps_to_unknown_not_a_guessed_neighbor() -> None:
    """AC-02 — a 418 status with a body shape this adapter has never seen
    documented anywhere must not be coerced into any of the seven named
    classes."""
    provider = OpenAICompatibleProvider(transport=replay_transport("error_unrecognizable.json", status_code=418))
    with pytest.raises(ProviderRequestFailedError) as exc_info:
        provider.complete(ModelRequest(messages=(ModelMessage(role="user", content="hi"),)))
    assert exc_info.value.error_class == ProviderErrorClass.UNKNOWN


# --------------------------------------------------------------------------- #
# Classification — AC-03, AC-04, AC-05
# --------------------------------------------------------------------------- #
def test_taxonomy_enum_names_no_provider() -> None:
    """AC-03."""
    vocab = ("openai", "anthropic", "claude", "gpt", "azure", "bedrock", "gemini", "cohere", "mistral")
    names = [ProviderErrorClass.__name__] + [member.name for member in ProviderErrorClass]
    lowered = [name.lower() for name in names]
    hits = [word for word in vocab for name in lowered if word in name]
    assert not hits, f"ProviderErrorClass names a provider: {hits} (in {names})"


def test_scrub_redacts_api_key_from_text() -> None:
    """AC-04."""
    text = "provider said: token sk-super-secret-123 was rejected"
    scrubbed = _scrub(text, api_key="sk-super-secret-123")
    assert "sk-super-secret-123" not in scrubbed
    assert "***REDACTED***" in scrubbed


def test_raised_error_message_never_contains_base_url_or_api_key() -> None:
    """AC-05."""
    base_url = "https://internal-vllm.example.corp/v1"
    provider = OpenAICompatibleProvider(
        base_url=base_url, api_key="sk-should-never-leak",
        transport=replay_transport("error_server_error.json", status_code=500),
    )
    with pytest.raises(ProviderRequestFailedError) as exc_info:
        provider.complete(ModelRequest(messages=(ModelMessage(role="user", content="hi"),)))
    message = str(exc_info.value)
    assert base_url not in message
    assert "sk-should-never-leak" not in message
    assert exc_info.value.error_class.value in message


# --------------------------------------------------------------------------- #
# Retry — AC-06, AC-07
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("first_step", [
    {"status": 429, "json": {"error": {"code": "rate_limit_exceeded", "message": "slow down"}}},
    {"status": 500, "json": {"error": {"message": "boom"}}},
    _raise_read_timeout,
])
def test_retryable_classes_retry_and_can_succeed(first_step, monkeypatch) -> None:
    """AC-06."""
    monkeypatch.setattr(services_module.time, "sleep", lambda *_: None)
    success_body = load_fixture("simple_completion.json")
    transport, calls = _sequenced_transport(first_step, {"status": 200, "json": success_body})
    provider = OpenAICompatibleProvider(transport=transport)

    gateway = ModelGatewayService()
    response = gateway._complete_with_resilience(
        provider, _unique_provider_name(), ModelRequest(messages=(ModelMessage(role="user", content="hi"),)))

    assert response.content == success_body["choices"][0]["message"]["content"]
    assert len(calls) == 2


@pytest.mark.parametrize("status,fixture,expected_class", [
    (400, "error_context_length_exceeded.json", ProviderErrorClass.CONTEXT_LENGTH_EXCEEDED),
    (400, "error_content_filtered.json", ProviderErrorClass.CONTENT_FILTERED),
    (401, "error_authentication_failed.json", ProviderErrorClass.AUTHENTICATION_FAILED),
    (400, "error_invalid_request.json", ProviderErrorClass.INVALID_REQUEST),
    (418, "error_unrecognizable.json", ProviderErrorClass.UNKNOWN),
])
def test_non_retryable_classes_never_retry(status, fixture, expected_class, monkeypatch) -> None:
    """AC-07 — ``time.sleep`` is monkeypatched to explode if called at all,
    so this test fails loudly (not silently) if a non-retryable class were
    ever retried."""
    def _must_not_sleep(*_args, **_kwargs):
        raise AssertionError("a non-retryable class must never trigger a backoff sleep")

    monkeypatch.setattr(services_module.time, "sleep", _must_not_sleep)
    transport, calls = _sequenced_transport({"status": status, "json": load_fixture(fixture)})
    provider = OpenAICompatibleProvider(transport=transport)

    gateway = ModelGatewayService()
    with pytest.raises(ProviderRequestFailedError) as exc_info:
        gateway._complete_with_resilience(
            provider, _unique_provider_name(), ModelRequest(messages=(ModelMessage(role="user", content="hi"),)))

    assert exc_info.value.error_class == expected_class
    assert len(calls) == 1


# --------------------------------------------------------------------------- #
# Retry — AC-08, AC-09, AC-10
# --------------------------------------------------------------------------- #
def test_backoff_delay_is_exponential_with_jitter() -> None:
    """AC-08 — the "equal jitter" design keeps each attempt's value range
    disjoint from and strictly above the previous attempt's (until the cap
    is reached), so ordering is provable without a fixed random seed;
    sampling the same attempt twice proves the randomized jitter component
    (non-identical values)."""
    samples_0 = [_provider_backoff_delay(0, retry_after_seconds=None) for _ in range(10)]
    samples_1 = [_provider_backoff_delay(1, retry_after_seconds=None) for _ in range(10)]
    samples_2 = [_provider_backoff_delay(2, retry_after_seconds=None) for _ in range(10)]

    assert max(samples_0) < min(samples_1)
    assert max(samples_1) < min(samples_2)
    assert len(set(samples_1)) > 1, "identical delays across calls -- no jitter"


def test_retry_after_header_overrides_computed_backoff(monkeypatch) -> None:
    """AC-09."""
    captured: dict = {}
    monkeypatch.setattr(services_module.time, "sleep", lambda seconds: captured.setdefault("seconds", seconds))

    success_body = load_fixture("simple_completion.json")
    transport, calls = _sequenced_transport(
        {"status": 429, "json": load_fixture("error_rate_limited.json"), "headers": {"retry-after": "17"}},
        {"status": 200, "json": success_body},
    )
    provider = OpenAICompatibleProvider(transport=transport)

    gateway = ModelGatewayService()
    gateway._complete_with_resilience(
        provider, _unique_provider_name(), ModelRequest(messages=(ModelMessage(role="user", content="hi"),)))

    assert captured["seconds"] == 17.0
    assert len(calls) == 2


def test_retry_exhausts_at_configured_maximum_and_surfaces_last_error(monkeypatch) -> None:
    """AC-10."""
    monkeypatch.setattr(services_module.time, "sleep", lambda *_: None)
    monkeypatch.setattr(settings, "MODEL_PROVIDER_MAX_RETRIES", 2)

    transport, calls = _sequenced_transport({"status": 500, "json": load_fixture("error_server_error.json")})
    provider = OpenAICompatibleProvider(transport=transport)

    gateway = ModelGatewayService()
    with pytest.raises(ProviderRequestFailedError) as exc_info:
        gateway._complete_with_resilience(
            provider, _unique_provider_name(), ModelRequest(messages=(ModelMessage(role="user", content="hi"),)))

    assert exc_info.value.error_class == ProviderErrorClass.PROVIDER_UNAVAILABLE
    assert len(calls) == 3  # the original call plus 2 retries


# --------------------------------------------------------------------------- #
# Retry — AC-11, AC-12 (execution-level: real per-attempt persistence)
# --------------------------------------------------------------------------- #
def test_execution_succeeds_after_an_inner_retry_with_correct_token_accounting(
    client: TestClient, db_session: Session, monkeypatch) -> None:
    """AC-11, AC-12 — the inner retry (one transient failure, then success)
    is fully contained within the one ``execution_attempts`` row the
    existing worker already writes: exactly one attempt row, correctly
    accounted, with no second worker claim needed."""
    monkeypatch.setattr(services_module.time, "sleep", lambda *_: None)
    # Defensive: keep this shared-key ("OPENAI_COMPATIBLE") circuit breaker
    # from ever tripping due to unrelated failures recorded by other tests
    # in this or other files that also use this exact provider identifier.
    monkeypatch.setattr(settings, "MODEL_PROVIDER_CIRCUIT_FAILURE_THRESHOLD", 100_000)

    success_body = load_fixture("simple_completion.json")
    transport, calls = _sequenced_transport(
        {"status": 500, "json": load_fixture("error_server_error.json")},
        {"status": 200, "json": success_body},
    )
    monkeypatch.setattr(OpenAICompatibleProvider, "_build_default_transport", lambda self: transport)

    org = _register_org(client)
    setup = _ready_agent(client, org, model_configuration={"provider": "OPENAI_COMPATIBLE", "model": "gpt-3.5-turbo"})
    execution = _run_execution(client, org, setup["agent"]["id"])

    assert execution["status"] == "SUCCEEDED"
    assert len(calls) == 2

    attempts = db_session.execute(
        select(ExecutionAttempt).where(ExecutionAttempt.execution_id == uuid.UUID(execution["id"]))
    ).scalars().all()
    assert len(attempts) == 1, "the inner retry must not create a second execution_attempts row"
    assert attempts[0].status == "SUCCEEDED"
    assert attempts[0].total_tokens == execution["model_usage"]["total_tokens"]
    assert attempts[0].total_tokens > 0


def test_execution_error_code_stores_the_taxonomy_class_on_failure(
    client: TestClient, db_session: Session, monkeypatch) -> None:
    """AC-11 — a non-retryable classification is recorded in the existing
    ``error_code`` column (both on the attempt and the execution) as the
    taxonomy value, not the generic ``MODEL_PROVIDER_REQUEST_FAILED``.

    Phase 5.7a.5 note: a *credential-configured* 401 is used here
    (``MODEL_PROVIDER_API_KEYS`` set to a value the fixture still rejects)
    so this test keeps proving the general "taxonomy class lands in
    error_code" mechanism via ``AUTHENTICATION_FAILED`` specifically. A 401
    with **no** credential configured at all now maps to the more specific
    ``PROVIDER_CREDENTIAL_REQUIRED`` instead (see
    ``test_provider_credentials.py``'s AC-09), which is the correct,
    intended behavior 5.7a.5 added, not a regression of this one."""
    monkeypatch.setattr(settings, "MODEL_PROVIDER_CIRCUIT_FAILURE_THRESHOLD", 100_000)
    monkeypatch.setattr(settings, "MODEL_PROVIDER_API_KEYS", {"OPENAI_COMPATIBLE": "sk-configured-but-wrong"})
    transport, calls = _sequenced_transport({"status": 401, "json": load_fixture("error_authentication_failed.json")})
    monkeypatch.setattr(OpenAICompatibleProvider, "_build_default_transport", lambda self: transport)

    org = _register_org(client)
    setup = _ready_agent(client, org, model_configuration={"provider": "OPENAI_COMPATIBLE", "model": "gpt-3.5-turbo"})
    execution = _run_execution(client, org, setup["agent"]["id"])

    assert execution["status"] == "FAILED"
    assert execution["error_code"] == "AUTHENTICATION_FAILED"
    assert len(calls) == 1  # non-retryable -- no inner retry engaged

    row = db_session.get(AgentExecution, uuid.UUID(execution["id"]))
    assert row.error_code == "AUTHENTICATION_FAILED"
    attempt = db_session.execute(
        select(ExecutionAttempt).where(ExecutionAttempt.execution_id == row.id)
    ).scalars().one()
    assert attempt.error_code == "AUTHENTICATION_FAILED"


# --------------------------------------------------------------------------- #
# Retry — AC-13, AC-14 (the streaming pre/post-first-token boundary)
# --------------------------------------------------------------------------- #
def test_streamed_call_failing_before_first_token_retries_and_can_succeed(monkeypatch) -> None:
    """AC-13."""
    monkeypatch.setattr(services_module.time, "sleep", lambda *_: None)
    calls = {"n": 0}

    def _handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            raise httpx.ConnectError("simulated drop before any token", request=request)
        return httpx.Response(200, content=load_sse_fixture("stream_with_usage.sse"),
                              headers={"content-type": "text/event-stream"}, request=request)

    provider = OpenAICompatibleProvider(transport=httpx.MockTransport(_handler))
    gateway = ModelGatewayService()
    output_payload, usage = gateway._invoke_streaming(
        provider, _unique_provider_name(), {"model": "llama3"},
        ModelRequest(messages=(ModelMessage(role="user", content="hi"),)), {"question": "hi"})

    assert calls["n"] == 2
    assert usage["stream_interrupted"] is False
    assert output_payload["result"] == "Paris is the capital of France."


def test_streamed_call_failing_after_first_token_does_not_retry(monkeypatch) -> None:
    """AC-14 — ``stream_truncated.sse`` emits real content before the
    connection ends without ``[DONE]``; a retry here would silently
    discard content the caller already received, so it must not happen."""
    def _must_not_sleep(*_args, **_kwargs):
        raise AssertionError("a post-first-token interruption must never retry")

    monkeypatch.setattr(services_module.time, "sleep", _must_not_sleep)
    calls = {"n": 0}

    def _handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, content=load_sse_fixture("stream_truncated.sse"),
                              headers={"content-type": "text/event-stream"}, request=request)

    provider = OpenAICompatibleProvider(transport=httpx.MockTransport(_handler))
    gateway = ModelGatewayService()
    output_payload, usage = gateway._invoke_streaming(
        provider, _unique_provider_name(), {"model": "llama3"},
        ModelRequest(messages=(ModelMessage(role="user", content="hi"),)), {"question": "hi"})

    assert calls["n"] == 1
    assert usage["stream_interrupted"] is True
    assert output_payload["result"] == "This response gets cut"


# --------------------------------------------------------------------------- #
# Circuit breaking — AC-15, AC-16, AC-17
# --------------------------------------------------------------------------- #
def test_circuit_opens_after_consecutive_failure_threshold(monkeypatch) -> None:
    """AC-15."""
    monkeypatch.setattr(settings, "MODEL_PROVIDER_CIRCUIT_FAILURE_THRESHOLD", 3)
    provider_name = _unique_provider_name()

    for _ in range(3):
        _circuit_before_call(provider_name)  # still closed on every one of these
        _circuit_record_failure(provider_name)

    with pytest.raises(ProviderRequestFailedError) as exc_info:
        _circuit_before_call(provider_name)
    assert exc_info.value.error_class == ProviderErrorClass.PROVIDER_UNAVAILABLE


def test_open_circuit_fails_fast_without_calling_the_provider(monkeypatch) -> None:
    """AC-16."""
    monkeypatch.setattr(settings, "MODEL_PROVIDER_CIRCUIT_FAILURE_THRESHOLD", 1)
    provider_name = _unique_provider_name()
    _circuit_before_call(provider_name)
    _circuit_record_failure(provider_name)  # opens after exactly 1 failure

    calls = {"n": 0}

    def _handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, json=load_fixture("simple_completion.json"), request=request)

    provider = OpenAICompatibleProvider(transport=httpx.MockTransport(_handler))
    gateway = ModelGatewayService()
    with pytest.raises(ProviderRequestFailedError) as exc_info:
        gateway._complete_with_resilience(
            provider, provider_name, ModelRequest(messages=(ModelMessage(role="user", content="hi"),)))

    assert calls["n"] == 0, "the provider must never have been called while the circuit was open"
    assert exc_info.value.error_class == ProviderErrorClass.PROVIDER_UNAVAILABLE


def test_circuit_half_opens_after_cooldown_and_closes_on_success(monkeypatch) -> None:
    """AC-17 — a controllable fake clock (monkeypatching ``time.monotonic``
    on the same ``time`` module ``services.py`` calls) advances the
    cooldown deterministically, without a real sleep."""
    clock = {"t": 1_000_000.0}
    monkeypatch.setattr(services_module.time, "monotonic", lambda: clock["t"])
    monkeypatch.setattr(settings, "MODEL_PROVIDER_CIRCUIT_FAILURE_THRESHOLD", 1)
    monkeypatch.setattr(settings, "MODEL_PROVIDER_CIRCUIT_COOLDOWN_SECONDS", 10.0)
    provider_name = _unique_provider_name()

    _circuit_before_call(provider_name)
    _circuit_record_failure(provider_name)  # opens at t=1_000_000

    with pytest.raises(ProviderRequestFailedError):
        _circuit_before_call(provider_name)  # still well within the cooldown

    clock["t"] += 11.0  # past the 10s cooldown
    _circuit_before_call(provider_name)  # half-open -- lets exactly this call through
    _circuit_record_success(provider_name)  # closes it

    clock["t"] += 0.001
    _circuit_before_call(provider_name)  # closed -- no raise


# --------------------------------------------------------------------------- #
# Timeouts — AC-18
# --------------------------------------------------------------------------- #
def test_connect_and_read_timeouts_are_independently_configurable_and_both_classify_as_timeout() -> None:
    """AC-18 — supplements the pre-existing ``test_timeouts_are_
    configurable`` (5.7a.2): connect/read are separate, independently
    enforced knobs, and whichever one fires classifies the same way."""
    provider = OpenAICompatibleProvider(connect_timeout=1.5, read_timeout=9.0)
    assert provider._client.timeout.connect == 1.5
    assert provider._client.timeout.read == 9.0

    read_timeout_provider = OpenAICompatibleProvider(transport=httpx.MockTransport(_raise_read_timeout))
    with pytest.raises(ProviderRequestFailedError) as read_exc:
        read_timeout_provider.complete(ModelRequest(messages=(ModelMessage(role="user", content="hi"),)))
    assert read_exc.value.error_class == ProviderErrorClass.TIMEOUT

    def _raise_connect_timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("simulated connect timeout", request=request)

    connect_timeout_provider = OpenAICompatibleProvider(transport=httpx.MockTransport(_raise_connect_timeout))
    with pytest.raises(ProviderRequestFailedError) as connect_exc:
        connect_timeout_provider.complete(ModelRequest(messages=(ModelMessage(role="user", content="hi"),)))
    assert connect_exc.value.error_class == ProviderErrorClass.TIMEOUT


# --------------------------------------------------------------------------- #
# Integrity — AC-19, AC-20, AC-22
# --------------------------------------------------------------------------- #
def test_mock_provider_response_carries_no_error_classification() -> None:
    """AC-19 — ``MockProvider``/``ModelResponse``'s pre-existing
    construction is unaffected by the two new fields (both default to
    ``None``)."""
    response = MockProvider().complete(ModelRequest(messages=(ModelMessage(role="user", content="hi"),)))
    assert response.error_class is None
    assert response.retry_after_seconds is None


def test_successful_call_output_and_usage_contract_unchanged(client: TestClient) -> None:
    """AC-20 — every key existing callers already read is still present,
    unchanged, for a successful (non-retried) call."""
    org = _register_org(client)
    setup = _ready_agent(client, org, model_configuration={"provider": "MOCK", "model": "mock-model"})
    execution = _run_execution(client, org, setup["agent"]["id"], input_payload={"question": "hello"})

    assert execution["status"] == "SUCCEEDED"
    assert execution["output_payload"]["echo"] == {"question": "hello"}
    assert set(execution["model_usage"]) >= {
        "provider", "model", "input_tokens", "output_tokens", "total_tokens",
        "token_accounting_complete", "was_streamed", "stream_interrupted",
        "interruption_reason", "time_to_first_token_ms", "generation_duration_ms", "finish_reason",
    }


def test_retry_and_replay_routes_behave_unchanged(client: TestClient, db_session: Session, monkeypatch) -> None:
    """AC-22 — the pre-existing ``/retry``/``/replay`` routes (§31-§37,
    unrelated to this phase) still work exactly as before: a failed
    execution can be retried, and any execution can be replayed as a fresh
    one, once whatever caused the original failure is no longer present.

    Phase 5.7a.5 note: a credential is configured (wrong on purpose) so
    this failure classifies as ``AUTHENTICATION_FAILED``, not the newer,
    more specific ``PROVIDER_CREDENTIAL_REQUIRED`` — see the equivalent
    note on ``test_execution_error_code_stores_the_taxonomy_class_on_
    failure`` above."""
    monkeypatch.setattr(settings, "MODEL_PROVIDER_CIRCUIT_FAILURE_THRESHOLD", 100_000)
    monkeypatch.setattr(settings, "MODEL_PROVIDER_API_KEYS", {"OPENAI_COMPATIBLE": "sk-configured-but-wrong"})
    failing_transport, _ = _sequenced_transport(
        {"status": 401, "json": load_fixture("error_authentication_failed.json")})
    monkeypatch.setattr(OpenAICompatibleProvider, "_build_default_transport", lambda self: failing_transport)

    org = _register_org(client)
    setup = _ready_agent(client, org, model_configuration={"provider": "OPENAI_COMPATIBLE", "model": "gpt-3.5-turbo"})
    execution = _run_execution(client, org, setup["agent"]["id"])
    assert execution["status"] == "FAILED"
    assert execution["error_code"] == "AUTHENTICATION_FAILED"

    succeeding_transport = replay_transport("simple_completion.json")
    monkeypatch.setattr(OpenAICompatibleProvider, "_build_default_transport", lambda self: succeeding_transport)

    r = client.post(f"{RT}/executions/{execution['id']}/retry", headers=org["headers"])
    assert r.status_code == 200, r.text
    retried = r.json()
    assert retried["status"] == "SUCCEEDED"

    r2 = client.post(f"{RT}/executions/{execution['id']}/replay", headers=org["headers"])
    assert r2.status_code == 200, r2.text
    replayed = r2.json()
    assert replayed["status"] == "SUCCEEDED"
    assert replayed["parent_execution_id"] == execution["id"]


# --------------------------------------------------------------------------- #
# Integrity — AC-27 (no new TODO/FIXME/NotImplementedError/skip/xfail)
# --------------------------------------------------------------------------- #
def test_no_new_todo_or_skip_markers_in_this_phases_files() -> None:
    """AC-27 — checks the non-test implementation files this phase touched.
    (Not this test file itself: its own body necessarily *names* these
    tokens as data, in the ``forbidden`` tuple below, which would make a
    self-check trivially fail on its own literal list.)"""
    from pathlib import Path

    backend_dir = Path(__file__).resolve().parents[2]
    files = [
        backend_dir / "app" / "runtime" / "providers" / "types.py",
        backend_dir / "app" / "runtime" / "providers" / "errors.py",
        backend_dir / "app" / "runtime" / "providers" / "openai_compatible.py",
        backend_dir / "app" / "runtime" / "services.py",
        backend_dir / "app" / "core" / "config.py",
    ]
    forbidden = ("TODO", "FIXME", "NotImplementedError", "pytest.mark.skip", "pytest.mark.xfail")
    for path in files:
        text = path.read_text(encoding="utf-8")
        hits = [token for token in forbidden if token in text]
        assert not hits, f"{path.name} contains forbidden marker(s): {hits}"
