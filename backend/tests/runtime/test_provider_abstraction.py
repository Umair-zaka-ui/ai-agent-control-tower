"""Phase 5.7a.1 tests — model provider abstraction & registry.

Two layers, per the acceptance criteria:

- **Unit/conformance** — the pure abstraction (``ModelProvider``, the
  internal representation types, the registry) exercised directly with no
  database. Most of this file.
- **Integration** — the execution pipeline actually routing through the
  abstraction end to end: real Postgres via ``SessionLocal()``
  (``client``/``db_session`` fixtures from ``conftest.py``), no mocks for
  the database.

Each test cites the acceptance-criterion ID it proves in its own docstring.
"""

from __future__ import annotations

import dataclasses
import inspect
import uuid
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.runtime.providers import registry as registry_module
from app.runtime.providers.base import ModelProvider
from app.runtime.providers.errors import CapabilityUnsupportedError, ProviderUnavailableError
from app.runtime.providers.mock import MockProvider
from app.runtime.providers.types import (
    FinishReason,
    ModelCapabilities,
    ModelMessage,
    ModelRequest,
    ModelResponse,
    ModelToolDefinition,
)

PASSWORD = "T3st!Passw0rd#Ok"
RT = "/api/v1/runtime"

# --------------------------------------------------------------------------- #
# The conformance suite — reusable by every future adapter (ACT-MDL-NFR-100).
# Adding a provider means adding one line here, not copying tests.
# --------------------------------------------------------------------------- #
PROVIDERS_UNDER_TEST = [MockProvider]  # Phase 5.7a.2 appends the real adapter here.


@pytest.mark.parametrize("provider_cls", PROVIDERS_UNDER_TEST)
class TestProviderConformance:
    """AC-03, AC-15 — every entry in ``PROVIDERS_UNDER_TEST`` runs through
    every method below with no per-provider test duplication."""

    def test_is_a_model_provider(self, provider_cls) -> None:
        assert issubclass(provider_cls, ModelProvider)
        assert isinstance(provider_cls(), ModelProvider)

    def test_describe_returns_capabilities(self, provider_cls) -> None:
        capabilities = provider_cls().describe()
        assert isinstance(capabilities, ModelCapabilities)
        assert isinstance(capabilities.max_context_tokens, int) and capabilities.max_context_tokens > 0

    def test_supports_matches_describe(self, provider_cls) -> None:
        provider = provider_cls()
        capabilities = provider.describe()
        assert provider.supports("streaming") == capabilities.supports_streaming
        assert provider.supports("tools") == capabilities.supports_tools
        assert provider.supports("system_prompt") == capabilities.supports_system_prompt

    def test_complete_returns_a_model_response(self, provider_cls) -> None:
        provider = provider_cls()
        request = ModelRequest(messages=(ModelMessage(role="user", content="hello"),))
        response = provider.complete(request)
        assert isinstance(response, ModelResponse)
        assert response.content
        assert isinstance(response.finish_reason, FinishReason)

    def test_stream_yields_at_least_one_model_response(self, provider_cls) -> None:
        provider = provider_cls()
        request = ModelRequest(messages=(ModelMessage(role="user", content="hello"),))
        chunks = list(provider.stream(request))
        assert len(chunks) >= 1
        assert all(isinstance(chunk, ModelResponse) for chunk in chunks)

    def test_capability_enforcement_is_consistent_with_describe(self, provider_cls) -> None:
        """No skip here by design (AC-20 forbids new skips): whichever way
        ``describe()`` answers for 'tools', ``complete()`` must behave
        consistently with it — either it works, or it raises."""
        provider = provider_cls()
        request_with_tools = ModelRequest(
            messages=(ModelMessage(role="user", content="hi"),),
            tools=(ModelToolDefinition(name="lookup", description="looks something up"),),
        )
        if provider.supports("tools"):
            response = provider.complete(request_with_tools)
            assert isinstance(response, ModelResponse)
        else:
            with pytest.raises(CapabilityUnsupportedError):
                provider.complete(request_with_tools)


def test_conformance_suite_adds_a_provider_in_one_line() -> None:
    """AC-15 — a structural guarantee, not just a claim: exactly one list,
    no per-provider test functions to copy/paste."""
    assert PROVIDERS_UNDER_TEST == [MockProvider]
    assert all(issubclass(cls, ModelProvider) for cls in PROVIDERS_UNDER_TEST)


# --------------------------------------------------------------------------- #
# ABC mechanics (AC-01, AC-02)
# --------------------------------------------------------------------------- #
def test_model_provider_is_abstract() -> None:
    """AC-01."""
    with pytest.raises(TypeError):
        ModelProvider()  # type: ignore[abstract]


def test_subclass_omitting_a_required_method_fails_to_instantiate() -> None:
    """AC-02."""
    class MissingStream(ModelProvider):
        def complete(self, request):
            return ModelResponse(content="x")

        def describe(self):
            return ModelCapabilities(supports_streaming=False, supports_tools=False,
                                     supports_system_prompt=False, max_context_tokens=1)
        # stream() intentionally omitted.

    with pytest.raises(TypeError):
        MissingStream()  # type: ignore[abstract]


# --------------------------------------------------------------------------- #
# Registry (AC-05, AC-06)
# --------------------------------------------------------------------------- #
def test_registry_resolves_a_registered_identifier() -> None:
    """AC-05."""
    provider = registry_module.resolve("MOCK")
    assert isinstance(provider, MockProvider)
    assert "MOCK" in registry_module.registered_identifiers()


def test_registry_rejects_an_unregistered_identifier() -> None:
    """AC-06 — matches the pre-abstraction fail-closed behavior exactly:
    same error code, same "unavailable" semantics."""
    with pytest.raises(ProviderUnavailableError) as exc_info:
        registry_module.resolve("DEFINITELY_NOT_REGISTERED")
    assert exc_info.value.code == "MODEL_PROVIDER_UNAVAILABLE"


# --------------------------------------------------------------------------- #
# Capability enforcement (AC-08, AC-09)
# --------------------------------------------------------------------------- #
def test_unsupported_capability_raises_specific_error() -> None:
    """AC-08."""
    provider = MockProvider()
    request = ModelRequest(
        messages=(ModelMessage(role="user", content="hi"),),
        tools=(ModelToolDefinition(name="x", description="y"),),
    )
    with pytest.raises(CapabilityUnsupportedError) as exc_info:
        provider.complete(request)
    assert exc_info.value.code == "MODEL_CAPABILITY_UNSUPPORTED"


def test_mock_provider_describe_is_accurate() -> None:
    """AC-09."""
    capabilities = MockProvider().describe()
    assert capabilities.supports_streaming is True
    assert capabilities.supports_tools is False
    assert capabilities.supports_system_prompt is True
    assert capabilities.max_context_tokens > 0


# --------------------------------------------------------------------------- #
# Internal representation (AC-11, AC-12, AC-13, AC-14)
# --------------------------------------------------------------------------- #
_PROVIDER_VOCABULARY = (
    "openai", "anthropic", "claude", "gpt-", "azure", "bedrock", "gemini", "cohere", "mistral",
    "chatml", "chat_completion", "completions_api",
)


def test_types_module_names_no_provider() -> None:
    """AC-11 — inspects actual field/class names via the AST, not the
    module's prose (the module docstring legitimately *names* OpenAI/
    Anthropic as examples of what must never leak in as a field — that's
    documentation of the rule, not a violation of it)."""
    import ast

    import app.runtime.providers.types as types_module

    tree = ast.parse(inspect.getsource(types_module))
    identifiers: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            identifiers.append(node.name)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            identifiers.append(node.target.id)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            identifiers.append(node.name)

    lowered = [identifier.lower() for identifier in identifiers]
    hits = [word for word in _PROVIDER_VOCABULARY for identifier in lowered if word.rstrip("-_") in identifier]
    assert not hits, f"types.py names a specific provider in a class/field/function name: {hits} (in {identifiers})"


def test_model_request_is_immutable() -> None:
    """AC-12."""
    request = ModelRequest(messages=(ModelMessage(role="user", content="hi"),),
                           sampling_parameters={"temperature": 0.5})
    with pytest.raises(dataclasses.FrozenInstanceError):
        request.messages = ()
    with pytest.raises(TypeError):
        request.sampling_parameters["temperature"] = 999  # MappingProxyType -- nested, not just top-level


def test_model_response_is_immutable() -> None:
    """AC-12."""
    response = ModelResponse(content="hi", raw_usage={"total_tokens": 5})
    with pytest.raises(dataclasses.FrozenInstanceError):
        response.content = "changed"
    with pytest.raises(TypeError):
        response.raw_usage["total_tokens"] = 999


def test_unrepresentable_message_role_raises_rather_than_coercing() -> None:
    """AC-13 — a construct the internal types cannot express (here: a
    message role outside the four defined ones) raises immediately at
    construction, rather than being silently accepted and misinterpreted
    downstream."""
    with pytest.raises(ValueError):
        ModelMessage(role="function", content="x")


def test_finish_reason_covers_all_five_values() -> None:
    """AC-14."""
    assert {reason.value for reason in FinishReason} == {
        "STOP", "LENGTH", "TOOL_CALLS", "CONTENT_FILTER", "ERROR",
    }


def test_unmapped_finish_reason_raises_rather_than_defaulting() -> None:
    """AC-14."""
    with pytest.raises(ValueError):
        FinishReason("some_provider_specific_value_nobody_mapped")


# --------------------------------------------------------------------------- #
# Integration — real Postgres via SessionLocal(), no mocks (AC-04, AC-07,
# AC-10, AC-16)
# --------------------------------------------------------------------------- #
def _register_org(client: TestClient, org: str = "Provider Abstraction Org") -> dict:
    email = f"prov_{uuid.uuid4().hex[:10]}@example.com"
    assert client.post("/auth/register", json={
        "organization_name": org, "name": "Owner", "email": email, "password": PASSWORD,
    }).status_code == 201
    tokens = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD}).json()
    h = {"Authorization": f"Bearer {tokens['access_token']}"}
    me = client.get("/api/v1/auth/me", headers=h).json()
    return {"headers": h, "user_id": me["user"]["id"], "organization_id": me["user"]["organization_id"]}


def _invite_member(client: TestClient, admin: dict, *, role: str = "VIEWER") -> dict:
    email = f"provm_{uuid.uuid4().hex[:10]}@example.com"
    r = client.post("/api/v1/identity/users", headers=admin["headers"], json={
        "email": email, "display_name": "Member", "password": PASSWORD, "role": role,
        "organization_id": admin["organization_id"],
    })
    assert r.status_code in (200, 201), r.text
    tokens = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD}).json()
    h = {"Authorization": f"Bearer {tokens['access_token']}"}
    return {"headers": h}


def _register_agent(client: TestClient, admin: dict) -> dict:
    r = client.post(f"{RT}/agents", headers=admin["headers"], json={
        "name": f"Provider Agent {uuid.uuid4().hex[:6]}", "agent_type": "ASSISTANT", "criticality": "MEDIUM",
        "description": "A test agent.", "business_purpose": "Exercise the provider abstraction in tests.",
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
    body = None
    for step in ("validate", "approve", "publish"):
        r = client.post(f"{RT}/agents/{agent_id}/versions/{version['id']}/{step}", headers=admin["headers"],
                        json=body)
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


def test_every_existing_mock_execution_behavior_is_unchanged(client: TestClient) -> None:
    """AC-04 — the specific shape ``ExecutionWorkerService``/existing tests
    depend on: exact echo, ``provider == 'MOCK'``, a positive token count."""
    org = _register_org(client)
    setup = _ready_agent(client, org, model_configuration={"provider": "MOCK", "model": "mock-model"})

    r = client.post(f"{RT}/executions", headers=org["headers"], json={
        "agent_id": setup["agent"]["id"], "input_payload": {"question": "hello"},
    })
    assert r.status_code == 201, r.text
    execution = r.json()
    assert execution["status"] == "SUCCEEDED"
    assert execution["output_payload"]["echo"] == {"question": "hello"}
    assert execution["model_usage"]["provider"] == "MOCK"
    assert execution["model_usage"]["total_tokens"] > 0
    assert execution["cost"] > 0


def test_provider_selection_reads_frozen_version_config_not_mutable_state(client: TestClient,
                                                                          db_session: Session) -> None:
    """AC-07 — mutating the agent/deployment after publish must not affect
    which provider (or model name) an execution resolves; only the
    version's own frozen ``model_configuration`` does."""
    from app.models.agent import Agent
    from app.models.runtime import AgentDeployment

    org = _register_org(client)
    setup = _ready_agent(client, org, model_configuration={"provider": "MOCK", "model": "frozen-model-name"})

    agent_row = db_session.get(Agent, uuid.UUID(setup["agent"]["id"]))
    agent_row.criticality = "MISSION_CRITICAL"
    deployment_row = db_session.get(AgentDeployment, uuid.UUID(setup["deployment"]["id"]))
    deployment_row.configuration = {"mutated": True, "provider": "SOMETHING_ELSE"}
    db_session.commit()

    r = client.post(f"{RT}/executions", headers=org["headers"], json={
        "agent_id": setup["agent"]["id"], "input_payload": {"a": 1},
    })
    assert r.status_code == 201, r.text
    execution = r.json()
    assert execution["status"] == "SUCCEEDED"
    assert execution["model_usage"]["provider"] == "MOCK"
    assert execution["model_usage"]["model"] == "frozen-model-name"


class _RecordingProvider(ModelProvider):
    """A throwaway provider used only by test_base_url_configuration_reaches_provider
    to prove settings-driven base URLs actually reach a provider's constructor."""

    last_base_url: str | None = None

    def __init__(self, *, base_url: str | None = None) -> None:
        type(self).last_base_url = base_url

    def complete(self, request: ModelRequest) -> ModelResponse:
        return ModelResponse(content="ok", raw_usage={"input_tokens": 1, "output_tokens": 1, "total_tokens": 2})

    def stream(self, request: ModelRequest) -> Iterator[ModelResponse]:
        yield self.complete(request)

    def describe(self) -> ModelCapabilities:
        return ModelCapabilities(supports_streaming=True, supports_tools=False,
                                 supports_system_prompt=True, max_context_tokens=100)


def test_base_url_configuration_reaches_the_provider(client: TestClient, monkeypatch) -> None:
    """AC-10."""
    from app.core.config import settings

    identifier = f"RECORDING-{uuid.uuid4().hex[:8]}"
    registry_module.register(identifier, _RecordingProvider)
    # ModelGatewayService.invoke() upper-cases the configured provider name
    # before looking up both the registry and the base-URL map (matching
    # AgentVersion.model_configuration's existing "MOCK" convention) --
    # store the base URL under that same upper-cased key.
    monkeypatch.setitem(settings.MODEL_PROVIDER_BASE_URLS, identifier.upper(), "https://example.test/v1")
    _RecordingProvider.last_base_url = "UNSET"

    org = _register_org(client)
    setup = _ready_agent(client, org, model_configuration={"provider": identifier, "model": "x"})

    r = client.post(f"{RT}/executions", headers=org["headers"], json={
        "agent_id": setup["agent"]["id"], "input_payload": {"a": 1},
    })
    assert r.status_code == 201, r.text
    assert _RecordingProvider.last_base_url == "https://example.test/v1"


def test_authorization_gateway_runs_before_provider_resolution(client: TestClient, monkeypatch) -> None:
    """AC-16 — an unauthorized request must never reach the registry at
    all; proven by a call-counting spy on ``resolve()``."""
    calls: list[str] = []
    original_resolve = registry_module.resolve

    def _spy(identifier: str, *, base_url: str | None = None):
        calls.append(identifier)
        return original_resolve(identifier, base_url=base_url)

    monkeypatch.setattr(registry_module, "resolve", _spy)

    org = _register_org(client)
    setup = _ready_agent(client, org, model_configuration={"provider": "MOCK", "model": "mock-model"})
    viewer = _invite_member(client, org, role="VIEWER")

    r = client.post(f"{RT}/executions", headers=viewer["headers"], json={
        "agent_id": setup["agent"]["id"], "input_payload": {"a": 1},
    })
    assert r.status_code == 403, r.text
    assert calls == [], "the registry was consulted despite authorization denying the request first"
