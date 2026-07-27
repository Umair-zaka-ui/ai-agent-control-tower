"""Phase 5.7a.2 tests — the OpenAI-compatible provider adapter.

Every test replays a committed fixture (or a small inline wire-format
dict for scenarios not worth a whole fixture file, e.g. AC-09's four
finish-reason values) through an ``httpx.MockTransport`` — no test in this
file, or anywhere in the suite, depends on a live endpoint (AC-23). See
``fixtures/providers/README.md`` for what the fixtures are and where they
came from.

Each test cites the acceptance-criterion ID it proves in its own docstring,
matching ``test_provider_abstraction.py``'s convention.
"""

from __future__ import annotations

import json
import uuid

import httpx
import pytest
from fastapi.testclient import TestClient

from app.identity.errors import ErrorCode
from app.runtime.providers import registry as registry_module
from app.runtime.providers.base import ModelProvider
from app.runtime.providers.errors import CapabilityUnsupportedError, ProviderRequestFailedError
from app.runtime.providers.openai_compatible import OpenAICompatibleProvider
from app.runtime.providers.types import (
    FinishReason,
    ModelMessage,
    ModelRequest,
    ModelToolDefinition,
)
from tests.runtime.conftest import FIXTURES_DIR, load_fixture, replay_transport

PASSWORD = "T3st!Passw0rd#Ok"
RT = "/api/v1/runtime"


def _capturing_transport(fixture_name: str) -> tuple[httpx.MockTransport, list[dict]]:
    """Like ``replay_transport`` but also records every outgoing request
    body, so a test can assert on what the adapter actually sent, not just
    what it returned."""
    body = load_fixture(fixture_name)
    sent: list[dict] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content))
        return httpx.Response(200, json=body, request=request)

    return httpx.MockTransport(_handler), sent


def _inline_transport(body: dict) -> httpx.MockTransport:
    def _handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=body, request=request)

    return httpx.MockTransport(_handler)


# --------------------------------------------------------------------------- #
# AC-01, AC-02 — registration & conformance
# --------------------------------------------------------------------------- #
def test_registered_as_openai_compatible_not_openai() -> None:
    """AC-02 — the identifier names the wire protocol, not a vendor."""
    assert "OPENAI_COMPATIBLE" in registry_module.registered_identifiers()
    assert "OPENAI" not in registry_module.registered_identifiers()
    provider = registry_module.resolve("OPENAI_COMPATIBLE")
    assert isinstance(provider, OpenAICompatibleProvider)
    assert isinstance(provider, ModelProvider)


def test_registry_resolve_forwards_model_and_api_key_to_this_provider() -> None:
    """Supplements AC-02/AC-14 — proves the registry's signature-checked
    ``model``/``api_key`` forwarding (added this sub-phase) actually
    reaches ``OpenAICompatibleProvider``, whose constructor declares both."""
    provider = registry_module.resolve("OPENAI_COMPATIBLE", model="llama3", api_key="sk-registry-test")
    assert provider.model == "llama3"
    assert provider._client.headers["authorization"] == "Bearer sk-registry-test"


# --------------------------------------------------------------------------- #
# AC-03 — simple completion
# --------------------------------------------------------------------------- #
def test_simple_completion_returns_correct_model_response() -> None:
    """AC-03."""
    fixture = load_fixture("simple_completion.json")
    provider = OpenAICompatibleProvider(transport=replay_transport("simple_completion.json"))
    response = provider.complete(ModelRequest(messages=(ModelMessage(role="user", content="Why is the sky blue?"),)))

    assert response.content == fixture["choices"][0]["message"]["content"]
    assert response.finish_reason == FinishReason.STOP
    assert response.tool_calls == ()
    assert response.raw_usage["input_tokens"] == fixture["usage"]["prompt_tokens"]
    assert response.raw_usage["output_tokens"] == fixture["usage"]["completion_tokens"]
    assert response.raw_usage["total_tokens"] == fixture["usage"]["total_tokens"]


# --------------------------------------------------------------------------- #
# AC-04 — all four roles, both directions
# --------------------------------------------------------------------------- #
def test_all_four_message_roles_translate_in_both_directions() -> None:
    """AC-04 — outgoing: every ``ModelMessage`` role reaches the wire body
    with the right shape (``tool`` carries ``tool_call_id``). Incoming: the
    fixture's assistant reply comes back as ``response.content``."""
    transport, sent = _capturing_transport("multi_turn_with_tool_message.json")
    provider = OpenAICompatibleProvider(transport=transport)

    request = ModelRequest(messages=(
        ModelMessage(role="system", content="You are a helpful weather assistant."),
        ModelMessage(role="user", content="What's the weather in New York right now?"),
        ModelMessage(role="assistant", content="Let me check that for you."),
        ModelMessage(role="tool", content='{"tempF": 58, "conditions": "partly cloudy"}', tool_call_id="call_9f1e2a"),
    ))
    response = provider.complete(request)

    sent_messages = sent[0]["messages"]
    assert [m["role"] for m in sent_messages] == ["system", "user", "assistant", "tool"]
    assert sent_messages[3]["tool_call_id"] == "call_9f1e2a"
    assert sent_messages[3]["content"] == '{"tempF": 58, "conditions": "partly cloudy"}'
    # Only the tool message carries tool_call_id -- it must not leak onto the others.
    assert all("tool_call_id" not in m for m in sent_messages[:3])

    fixture = load_fixture("multi_turn_with_tool_message.json")
    assert response.content == fixture["choices"][0]["message"]["content"]


# --------------------------------------------------------------------------- #
# AC-05 — tool definition translation
# --------------------------------------------------------------------------- #
def test_tool_definitions_translate_to_wire_format() -> None:
    """AC-05."""
    transport, sent = _capturing_transport("single_tool_call.json")
    provider = OpenAICompatibleProvider(transport=transport)

    tool = ModelToolDefinition(
        name="get_weather", description="Look up the current weather for a location.",
        parameters={"type": "object", "properties": {"location": {"type": "string"}}, "required": ["location"]},
    )
    provider.complete(ModelRequest(
        messages=(ModelMessage(role="user", content="What's the weather in New York, NY?"),),
        tools=(tool,),
    ))

    wire_tools = sent[0]["tools"]
    assert wire_tools == [{
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "Look up the current weather for a location.",
            "parameters": {"type": "object", "properties": {"location": {"type": "string"}}, "required": ["location"]},
        },
    }]


# --------------------------------------------------------------------------- #
# AC-06, AC-07 — tool call parsing
# --------------------------------------------------------------------------- #
def test_single_tool_call_parses_into_model_tool_call() -> None:
    """AC-06."""
    provider = OpenAICompatibleProvider(transport=replay_transport("single_tool_call.json"))
    response = provider.complete(ModelRequest(
        messages=(ModelMessage(role="user", content="What's the weather in New York, NY?"),),
        tools=(ModelToolDefinition(name="get_weather", description="d"),),
    ))

    assert len(response.tool_calls) == 1
    call = response.tool_calls[0]
    assert call.id == "call_9f1e2a"
    assert call.name == "get_weather"
    assert call.arguments == {"location": "New York, NY"}
    assert response.finish_reason == FinishReason.TOOL_CALLS
    assert response.content == ""  # wire content was null


def test_multiple_tool_calls_parse_correctly() -> None:
    """AC-07."""
    provider = OpenAICompatibleProvider(transport=replay_transport("multiple_tool_calls.json"))
    response = provider.complete(ModelRequest(
        messages=(ModelMessage(role="user", content="Weather in NYC and Boston?"),),
        tools=(ModelToolDefinition(name="get_weather", description="d"),),
    ))

    assert len(response.tool_calls) == 2
    assert response.tool_calls[0].arguments == {"location": "New York, NY"}
    assert response.tool_calls[1].arguments == {"location": "Boston, MA"}
    assert {c.id for c in response.tool_calls} == {"call_a1b2c3", "call_d4e5f6"}


# --------------------------------------------------------------------------- #
# AC-08, AC-09, AC-10 — finish reason mapping
# --------------------------------------------------------------------------- #
def test_max_tokens_reached_maps_to_length() -> None:
    """AC-08."""
    provider = OpenAICompatibleProvider(transport=replay_transport("max_tokens_reached.json"))
    response = provider.complete(ModelRequest(messages=(ModelMessage(role="user", content="explain in detail"),),
                                              max_tokens=16))
    assert response.finish_reason == FinishReason.LENGTH


@pytest.mark.parametrize("raw,expected", [
    ("stop", FinishReason.STOP),
    ("length", FinishReason.LENGTH),
    ("tool_calls", FinishReason.TOOL_CALLS),
    ("content_filter", FinishReason.CONTENT_FILTER),
])
def test_each_known_finish_reason_maps_correctly(raw: str, expected: FinishReason) -> None:
    """AC-09."""
    body = {"choices": [{"message": {"content": "x"}, "finish_reason": raw}]}
    provider = OpenAICompatibleProvider(transport=_inline_transport(body))
    response = provider.complete(ModelRequest(messages=(ModelMessage(role="user", content="hi"),)))
    assert response.finish_reason == expected


def test_unrecognized_finish_reason_raises_rather_than_defaulting() -> None:
    """AC-10."""
    body = {"choices": [{"message": {"content": "x"}, "finish_reason": "some_bogus_value_nobody_mapped"}]}
    provider = OpenAICompatibleProvider(transport=_inline_transport(body))
    with pytest.raises(ValueError):
        provider.complete(ModelRequest(messages=(ModelMessage(role="user", content="hi"),)))


# --------------------------------------------------------------------------- #
# AC-11 — tolerating omitted optional fields
# --------------------------------------------------------------------------- #
def test_response_omitting_optional_fields_parses_without_error() -> None:
    """AC-11 — no id/object/created/system_fingerprint/usage at all.

    Phase 5.7a.3 note (``ACT-MDL-FR-046``): ``raw_usage`` is asserted
    empty, not zero-filled. A provider that omits ``usage`` entirely must
    report "unavailable," not "zero tokens used" — those mean different
    things, and ``ModelGatewayService`` relies on ``bool(raw_usage)`` to
    tell them apart (``token_accounting_complete``). Zero-filling here
    would have been exactly the kind of estimate-that-looks-real FR-046
    exists to forbid."""
    fixture = load_fixture("omitted_optional_fields.json")
    provider = OpenAICompatibleProvider(transport=replay_transport("omitted_optional_fields.json"))
    response = provider.complete(ModelRequest(messages=(ModelMessage(role="user", content="hi"),)))

    assert response.content == fixture["choices"][0]["message"]["content"]
    assert response.finish_reason == FinishReason.STOP
    assert response.tool_calls == ()
    assert response.raw_usage == {}


# --------------------------------------------------------------------------- #
# AC-12 — sampling parameter filtering
# --------------------------------------------------------------------------- #
def test_supported_sampling_parameters_forwarded_unsupported_dropped(caplog) -> None:
    """AC-12."""
    transport, sent = _capturing_transport("simple_completion.json")
    provider = OpenAICompatibleProvider(transport=transport)

    with caplog.at_level("DEBUG", logger="app.runtime.providers.openai_compatible"):
        provider.complete(ModelRequest(
            messages=(ModelMessage(role="user", content="hi"),),
            sampling_parameters={"temperature": 0.7, "top_p": 0.9, "top_k": 40, "repeat_penalty": 1.1},
        ))

    body = sent[0]
    assert body["temperature"] == 0.7
    assert body["top_p"] == 0.9
    assert "top_k" not in body
    assert "repeat_penalty" not in body
    assert any("top_k" in record.message and "repeat_penalty" in record.message for record in caplog.records)


# --------------------------------------------------------------------------- #
# AC-13 — max_tokens / stop reach the request
# --------------------------------------------------------------------------- #
def test_max_tokens_and_stop_reach_the_provider_request() -> None:
    """AC-13."""
    transport, sent = _capturing_transport("simple_completion.json")
    provider = OpenAICompatibleProvider(transport=transport)

    provider.complete(ModelRequest(
        messages=(ModelMessage(role="user", content="hi"),),
        max_tokens=256, stop_sequences=("###", "END"),
    ))

    assert sent[0]["max_tokens"] == 256
    assert sent[0]["stop"] == ["###", "END"]


# --------------------------------------------------------------------------- #
# AC-14 — configuration-only across base URLs
# --------------------------------------------------------------------------- #
def test_adapter_works_against_two_base_urls_with_no_code_change() -> None:
    """AC-14 — same class, two different ``base_url``/fixture combinations,
    no per-endpoint subclass or branch anywhere in the adapter."""
    ollama_style = OpenAICompatibleProvider(
        base_url="http://localhost:11434/v1",
        transport=replay_transport("simple_completion.json"),
    )
    minimal_style = OpenAICompatibleProvider(
        base_url="https://vllm.internal.example/v1",
        transport=replay_transport("omitted_optional_fields.json"),
    )

    request = ModelRequest(messages=(ModelMessage(role="user", content="hi"),))
    r1 = ollama_style.complete(request)
    r2 = minimal_style.complete(request)

    assert r1.content and r2.content
    assert type(ollama_style) is type(minimal_style)
    assert ollama_style.base_url != minimal_style.base_url


def test_api_key_configuration_reaches_the_provider_as_a_bearer_header() -> None:
    """Supplements AC-14 — ``registry.resolve()``'s ``api_key`` forwarding
    (added alongside ``model``, for the same reason: 5.7a.1 had nothing
    that needed either). Not every OpenAI-compatible endpoint requires a
    key (Ollama doesn't), but ones that do read it as a plain configured
    value (``settings.MODEL_PROVIDER_API_KEYS``) -- no credential storage
    or resolution, that's Phase 5.7a.5."""
    provider = OpenAICompatibleProvider(api_key="sk-test-configured-value")
    assert provider._client.headers["authorization"] == "Bearer sk-test-configured-value"


# --------------------------------------------------------------------------- #
# AC-15, AC-16, AC-17 — capability enforcement & declaration
# --------------------------------------------------------------------------- #
def test_validate_capabilities_called_inside_complete(monkeypatch) -> None:
    """AC-15."""
    provider = OpenAICompatibleProvider(transport=replay_transport("simple_completion.json"))
    calls = []
    monkeypatch.setattr(provider, "validate_capabilities", lambda request: calls.append(request))

    request = ModelRequest(messages=(ModelMessage(role="user", content="hi"),))
    provider.complete(request)

    assert calls == [request]


def test_requesting_tools_on_a_no_tools_deployment_raises_capability_error() -> None:
    """AC-16 — not every model behind an OpenAI-compatible endpoint
    supports function calling; a deployment configured accordingly must
    fail closed, not silently send tools the server will ignore or reject."""
    provider = OpenAICompatibleProvider(supports_tools=False, transport=replay_transport("simple_completion.json"))
    request = ModelRequest(
        messages=(ModelMessage(role="user", content="hi"),),
        tools=(ModelToolDefinition(name="lookup", description="looks something up"),),
    )
    with pytest.raises(CapabilityUnsupportedError) as exc_info:
        provider.complete(request)
    assert exc_info.value.code == ErrorCode.MODEL_CAPABILITY_UNSUPPORTED


def test_describe_returns_accurate_capabilities() -> None:
    """AC-17."""
    default_provider = OpenAICompatibleProvider()
    capabilities = default_provider.describe()
    assert capabilities.supports_streaming is True
    assert capabilities.supports_tools is True
    assert capabilities.supports_system_prompt is True
    assert capabilities.max_context_tokens > 0

    restricted = OpenAICompatibleProvider(supports_tools=False, max_context_tokens=4096)
    assert restricted.describe().supports_tools is False
    assert restricted.describe().max_context_tokens == 4096


# --------------------------------------------------------------------------- #
# AC-18 — no provider wire-format vocabulary escapes this module
# --------------------------------------------------------------------------- #
def test_no_openai_wire_vocabulary_outside_this_module() -> None:
    """AC-18 — supplements the existing (still-passing)
    ``test_types_module_names_no_provider``: this checks the *other*
    shared files (``base.py``, ``registry.py``, ``types.py``) directly for
    literal OpenAI *wire-format* tokens. Deliberately excludes words the
    provider-neutral types legitimately reuse on their own terms
    (``finish_reason``, ``tool_calls`` are ``ModelResponse``'s own field
    names, chosen independently of OpenAI's identical spelling) — this
    checks for tokens that are unambiguously OpenAI's own wire shape:
    the ``choices`` wrapper, its ``prompt_tokens``/``completion_tokens``
    usage field names (ours are ``input_tokens``/``output_tokens``), its
    endpoint path, and its ``system_fingerprint`` metadata field."""
    import inspect

    import app.runtime.providers.base as base_module
    import app.runtime.providers.registry as registry_mod
    import app.runtime.providers.types as types_module

    wire_tokens = ("choices", "prompt_tokens", "completion_tokens", "chat/completions", "system_fingerprint")
    for module in (base_module, registry_mod, types_module):
        source = inspect.getsource(module).lower()
        hits = [token for token in wire_tokens if token in source]
        assert not hits, f"{module.__name__} contains OpenAI wire-format vocabulary: {hits}"


# --------------------------------------------------------------------------- #
# AC-20 — ModelGatewayService.invoke() executes through the new adapter
# --------------------------------------------------------------------------- #
def _register_org(client: TestClient) -> dict:
    email = f"oaic_{uuid.uuid4().hex[:10]}@example.com"
    assert client.post("/auth/register", json={
        "organization_name": "OpenAI-Compatible Org", "name": "Owner", "email": email, "password": PASSWORD,
    }).status_code == 201
    tokens = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD}).json()
    h = {"Authorization": f"Bearer {tokens['access_token']}"}
    me = client.get("/api/v1/auth/me", headers=h).json()
    return {"headers": h, "user_id": me["user"]["id"], "organization_id": me["user"]["organization_id"]}


def _register_agent(client: TestClient, admin: dict) -> dict:
    r = client.post(f"{RT}/agents", headers=admin["headers"], json={
        "name": f"OAIC Agent {uuid.uuid4().hex[:6]}", "agent_type": "ASSISTANT", "criticality": "MEDIUM",
        "description": "A test agent.", "business_purpose": "Exercise the OpenAI-compatible adapter in tests.",
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


def test_model_gateway_service_executes_through_the_new_adapter(client: TestClient) -> None:
    """AC-20 — an execution configured for ``OPENAI_COMPATIBLE`` actually
    resolves and runs through ``OpenAICompatibleProvider``, end to end
    through the full governance stack (registered, versioned, signed,
    authorized, audited), replaying ``simple_completion.json`` via the
    autouse default-transport fixture (no real endpoint involved)."""
    org = _register_org(client)
    agent = _register_agent(client, org)
    _activate_agent(client, org, agent["id"])
    version = _publish_version(client, org, agent["id"],
                               model_configuration={"provider": "OPENAI_COMPATIBLE", "model": "llama3"})
    deployment = _deploy(client, org, agent["id"], version["id"])
    assert deployment["status"] == "ACTIVE"

    r = client.post(f"{RT}/executions", headers=org["headers"], json={
        "agent_id": agent["id"], "input_payload": {"question": "why is the sky blue"},
    })
    assert r.status_code == 201, r.text
    execution = r.json()
    assert execution["status"] == "SUCCEEDED"
    assert execution["model_usage"]["provider"] == "OPENAI_COMPATIBLE"
    assert execution["model_usage"]["model"] == "llama3"
    assert execution["model_usage"]["total_tokens"] > 0
    fixture = load_fixture("simple_completion.json")
    assert execution["output_payload"]["result"] == fixture["choices"][0]["message"]["content"]


# --------------------------------------------------------------------------- #
# AC-24 — no credential in any fixture
# --------------------------------------------------------------------------- #
def test_no_fixture_contains_a_credential() -> None:
    """AC-24."""
    for path in FIXTURES_DIR.glob("*.json"):
        text = path.read_text().lower()
        assert "authorization" not in text and "bearer " not in text and "api_key" not in text, (
            f"{path.name} appears to contain a credential-shaped token"
        )


# --------------------------------------------------------------------------- #
# AC-25 — timeouts configurable and enforced
# --------------------------------------------------------------------------- #
def test_timeouts_are_configurable() -> None:
    """AC-25 (configurability half; enforcement is exercised below)."""
    provider = OpenAICompatibleProvider(connect_timeout=1.5, read_timeout=9.0)
    assert provider._client.timeout.connect == 1.5
    assert provider._client.timeout.read == 9.0


def test_a_provider_side_timeout_raises_provider_request_failed() -> None:
    """AC-25 (enforcement half) — a hanging/failing provider call must not
    propagate a raw ``httpx`` exception; it becomes the one coarse
    provider-layer error (classification is 5.7a.4's job)."""

    def _handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("simulated timeout", request=request)

    provider = OpenAICompatibleProvider(transport=httpx.MockTransport(_handler))
    with pytest.raises(ProviderRequestFailedError) as exc_info:
        provider.complete(ModelRequest(messages=(ModelMessage(role="user", content="hi"),)))
    assert exc_info.value.code == ErrorCode.MODEL_PROVIDER_REQUEST_FAILED


def test_a_non_2xx_response_raises_provider_request_failed() -> None:
    """AC-25 — same coarse handling for an HTTP error status."""

    def _handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "server exploded"}, request=request)

    provider = OpenAICompatibleProvider(transport=httpx.MockTransport(_handler))
    with pytest.raises(ProviderRequestFailedError):
        provider.complete(ModelRequest(messages=(ModelMessage(role="user", content="hi"),)))


# --------------------------------------------------------------------------- #
# AC-26 — live_provider marker registered and excluded by default
# --------------------------------------------------------------------------- #
def test_live_provider_marker_is_registered_and_excluded_by_default() -> None:
    """AC-26."""
    from pathlib import Path

    ini_path = Path(__file__).resolve().parents[2] / "pytest.ini"
    assert ini_path.exists(), "backend/pytest.ini must exist to register the live_provider marker"
    text = ini_path.read_text()
    assert "live_provider" in text
    assert 'not live_provider' in text


@pytest.mark.live_provider
def test_live_ollama_completion() -> None:
    """A genuinely live check against a real local Ollama instance --
    excluded by default (see pytest.ini); run explicitly with:

        pytest backend/tests/runtime/test_openai_compatible_provider.py -m live_provider

    Requires ``ollama serve`` running locally with a pulled model (default
    assumes ``llama3`` at the default Ollama port)."""
    provider = OpenAICompatibleProvider(base_url="http://localhost:11434/v1", model="llama3")
    response = provider.complete(ModelRequest(messages=(ModelMessage(role="user", content="Say 'ok' and nothing else."),)))
    assert response.content
