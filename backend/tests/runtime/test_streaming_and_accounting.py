"""Phase 5.7a.3 tests — streaming, token accounting, and cost.

Three groups, matching the build prompt's own acceptance-criteria
groupings: streaming (AC-01..09), accounting (AC-10..14), cost
(AC-15..21). Integrity/suite-level criteria (AC-22..30) are proven by the
full suite run cited in the phase summary, not duplicated here except
where a specific new behavior needs its own assertion.

Every streaming test replays a committed ``.sse`` fixture through
``httpx.MockTransport`` — no test depends on a live endpoint (AC-25). See
``fixtures/providers/README.md``.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.runtime import AgentExecution, ExecutionAttempt, ModelPricing
from app.runtime.providers.mock import MockProvider
from app.runtime.providers.openai_compatible import OpenAICompatibleProvider
from app.runtime.providers.types import FinishReason, ModelMessage, ModelRequest, assemble_response
from app.runtime.services import PricingService
from tests.runtime.conftest import FIXTURES_DIR, load_fixture, load_sse_fixture, replay_sse_transport, replay_transport

PASSWORD = "T3st!Passw0rd#Ok"
RT = "/api/v1/runtime"


# --------------------------------------------------------------------------- #
# HTTP helpers (local copies, matching this directory's established
# convention of not importing fixtures across test modules)
# --------------------------------------------------------------------------- #
def _register_org(client: TestClient) -> dict:
    email = f"stream_{uuid.uuid4().hex[:10]}@example.com"
    assert client.post("/auth/register", json={
        "organization_name": "Streaming Org", "name": "Owner", "email": email, "password": PASSWORD,
    }).status_code == 201
    tokens = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD}).json()
    h = {"Authorization": f"Bearer {tokens['access_token']}"}
    me = client.get("/api/v1/auth/me", headers=h).json()
    return {"headers": h, "user_id": me["user"]["id"], "organization_id": me["user"]["organization_id"]}


def _register_agent(client: TestClient, admin: dict) -> dict:
    r = client.post(f"{RT}/agents", headers=admin["headers"], json={
        "name": f"Streaming Agent {uuid.uuid4().hex[:6]}", "agent_type": "ASSISTANT", "criticality": "MEDIUM",
        "description": "A test agent.", "business_purpose": "Exercise streaming/accounting in tests.",
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
# Streaming — AC-01, AC-02
# --------------------------------------------------------------------------- #
def test_stream_emits_incremental_content_deltas_not_one_block() -> None:
    """AC-01."""
    provider = OpenAICompatibleProvider(transport=replay_sse_transport("stream_simple_completion.sse"))
    chunks = list(provider.stream(ModelRequest(messages=(ModelMessage(role="user", content="hi"),))))

    assert len(chunks) > 1
    non_empty = [c for c in chunks if c.content]
    assert len(non_empty) > 1, "expected more than one chunk to actually carry text"
    assert all(len(c.content) < 20 for c in non_empty), "a chunk's content should be a small delta, not the whole reply"


def test_stream_reassembles_a_complete_model_response() -> None:
    """AC-02."""
    fixture_events = load_sse_fixture("stream_with_usage.sse").decode()
    provider = OpenAICompatibleProvider(transport=replay_sse_transport("stream_with_usage.sse"))
    chunks = list(provider.stream(ModelRequest(messages=(ModelMessage(role="user", content="hi"),))))
    assembled = assemble_response(chunks)

    assert assembled.content == "Paris is the capital of France."
    assert assembled.finish_reason == FinishReason.STOP
    assert assembled.raw_usage == {"input_tokens": 14, "output_tokens": 8, "total_tokens": 22}
    assert "usage" in fixture_events  # sanity: this fixture really does carry usage


# --------------------------------------------------------------------------- #
# Streaming — AC-03, AC-04 (tool call reassembly)
# --------------------------------------------------------------------------- #
def test_stream_tool_call_fragmented_across_chunks_reassembles() -> None:
    """AC-03 — one of the two interleaved calls, checked in isolation."""
    provider = OpenAICompatibleProvider(transport=replay_sse_transport("stream_tool_call_fragmented.sse"))
    chunks = list(provider.stream(ModelRequest(
        messages=(ModelMessage(role="user", content="weather?"),),
        tools=(),
    )))
    assembled = assemble_response(chunks)

    ny_call = next(c for c in assembled.tool_calls if c.id == "call_a1b2c3")
    assert ny_call.name == "get_weather"
    assert ny_call.arguments == {"location": "New York, NY"}


def test_stream_multiple_interleaved_tool_calls_reassemble_by_index() -> None:
    """AC-04 — both calls, in order, neither corrupted by the other's
    interleaved fragments."""
    provider = OpenAICompatibleProvider(transport=replay_sse_transport("stream_tool_call_fragmented.sse"))
    chunks = list(provider.stream(ModelRequest(messages=(ModelMessage(role="user", content="weather?"),))))
    assembled = assemble_response(chunks)

    assert len(assembled.tool_calls) == 2
    assert assembled.tool_calls[0].id == "call_a1b2c3"
    assert assembled.tool_calls[0].arguments == {"location": "New York, NY"}
    assert assembled.tool_calls[1].id == "call_d4e5f6"
    assert assembled.tool_calls[1].arguments == {"location": "Boston, MA"}
    assert assembled.finish_reason == FinishReason.TOOL_CALLS


# --------------------------------------------------------------------------- #
# Streaming — AC-05 (truncation), AC-06 (max duration)
# --------------------------------------------------------------------------- #
def test_truncated_stream_yields_interrupted_final_chunk_at_adapter_level() -> None:
    """AC-05 (adapter level) — no ``[DONE]``, no finish_reason chunk: the
    adapter's own generator must still terminate with something the
    platform can recognize as "interrupted," not hang or raise."""
    provider = OpenAICompatibleProvider(transport=replay_sse_transport("stream_truncated.sse"))
    chunks = list(provider.stream(ModelRequest(messages=(ModelMessage(role="user", content="hi"),))))

    assert chunks[-1].finish_reason == FinishReason.ERROR
    assembled = assemble_response(chunks)
    assert assembled.content == "This response gets cut"
    assert assembled.finish_reason == FinishReason.ERROR


def test_truncated_stream_persists_partial_and_sets_stream_interrupted(client: TestClient, db_session: Session,
                                                                       monkeypatch) -> None:
    """AC-05 (platform level) — a real execution configured to stream,
    replaying the truncated fixture, ends up SUCCEEDED (something usable
    was received) but flagged ``stream_interrupted``."""
    from app.runtime.providers.openai_compatible import OpenAICompatibleProvider as OCP

    monkeypatch.setattr(OCP, "_build_default_transport",
                        lambda self: replay_sse_transport("stream_truncated.sse"))

    org = _register_org(client)
    setup = _ready_agent(client, org, model_configuration={
        "provider": "OPENAI_COMPATIBLE", "model": "llama3", "stream": True,
    })
    execution = _run_execution(client, org, setup["agent"]["id"])

    assert execution["status"] == "SUCCEEDED"
    assert execution["model_usage"]["was_streamed"] is True
    assert execution["model_usage"]["stream_interrupted"] is True

    row = db_session.get(AgentExecution, uuid.UUID(execution["id"]))
    assert row.stream_interrupted is True
    assert row.was_streamed is True
    assert row.output_payload["result"] == "This response gets cut"


def test_max_response_duration_terminates_stream_and_persists_partial(client: TestClient, monkeypatch) -> None:
    """AC-06 — forcing the budget to a guaranteed-already-exceeded value
    (rather than sleeping in the test) makes this deterministic: the
    platform must stop consuming the generator after the very first chunk
    and still persist whatever that one chunk carried."""
    from app.runtime.providers.openai_compatible import OpenAICompatibleProvider as OCP
    from app.core.config import settings

    monkeypatch.setattr(settings, "MODEL_STREAM_MAX_DURATION_SECONDS", -1.0)
    monkeypatch.setattr(OCP, "_build_default_transport",
                        lambda self: replay_sse_transport("stream_simple_completion.sse"))

    org = _register_org(client)
    setup = _ready_agent(client, org, model_configuration={
        "provider": "OPENAI_COMPATIBLE", "model": "llama3", "stream": True,
    })
    execution = _run_execution(client, org, setup["agent"]["id"])

    assert execution["status"] == "SUCCEEDED"
    assert execution["model_usage"]["stream_interrupted"] is True
    assert execution["model_usage"]["finish_reason"] is None
    assert "maximum response duration" in execution["model_usage"]["interruption_reason"]


# --------------------------------------------------------------------------- #
# Streaming — AC-07, AC-08
# --------------------------------------------------------------------------- #
def test_non_streaming_caller_receives_unchanged_tuple_shape(client: TestClient) -> None:
    """AC-07 — a version whose model_configuration has no "stream" key
    behaves exactly as every pre-5.7a.3 test already depends on."""
    org = _register_org(client)
    setup = _ready_agent(client, org, model_configuration={"provider": "MOCK", "model": "mock-model"})
    execution = _run_execution(client, org, setup["agent"]["id"], input_payload={"question": "hello"})

    assert execution["status"] == "SUCCEEDED"
    assert execution["output_payload"]["echo"] == {"question": "hello"}
    assert execution["model_usage"]["provider"] == "MOCK"
    assert execution["model_usage"]["was_streamed"] is False


def test_was_streamed_recorded_correctly_for_both_modes(client: TestClient, db_session: Session) -> None:
    """AC-08. Each agent gets its own org — registering two similarly-
    described agents in one org can trip Phase 5.1's duplicate detection,
    which is an unrelated concern to this test."""
    org_a = _register_org(client)
    non_streamed = _ready_agent(client, org_a, model_configuration={"provider": "MOCK", "model": "mock-model"})
    execution_a = _run_execution(client, org_a, non_streamed["agent"]["id"])
    assert execution_a["model_usage"]["was_streamed"] is False
    row_a = db_session.get(AgentExecution, uuid.UUID(execution_a["id"]))
    assert row_a.was_streamed is False

    org_b = _register_org(client)
    streamed = _ready_agent(client, org_b, model_configuration={
        "provider": "OPENAI_COMPATIBLE", "model": "llama3", "stream": True,
    })
    execution_b = _run_execution(client, org_b, streamed["agent"]["id"])
    assert execution_b["model_usage"]["was_streamed"] is True
    row_b = db_session.get(AgentExecution, uuid.UUID(execution_b["id"]))
    assert row_b.was_streamed is True


# --------------------------------------------------------------------------- #
# Streaming — AC-09 (no SSE vocabulary escapes the adapter)
# --------------------------------------------------------------------------- #
def test_no_sse_wire_vocabulary_outside_the_adapter() -> None:
    """AC-09."""
    import inspect

    import app.runtime.providers.base as base_module
    import app.runtime.providers.registry as registry_module
    import app.runtime.providers.types as types_module
    import app.runtime.services as services_module

    sse_tokens = ("data:", "[DONE]", "text/event-stream", "iter_lines")
    for module in (base_module, registry_module, types_module, services_module):
        source = inspect.getsource(module)
        hits = [token for token in sse_tokens if token in source]
        assert not hits, f"{module.__name__} contains SSE wire-format vocabulary: {hits}"


# --------------------------------------------------------------------------- #
# Accounting — AC-10, AC-11
# --------------------------------------------------------------------------- #
def test_tokens_recorded_from_a_response_carrying_usage(client: TestClient, db_session: Session,
                                                        monkeypatch) -> None:
    """AC-10."""
    from app.runtime.providers.openai_compatible import OpenAICompatibleProvider as OCP

    monkeypatch.setattr(OCP, "_build_default_transport", lambda self: replay_transport("simple_completion.json"))
    fixture = load_fixture("simple_completion.json")

    org = _register_org(client)
    setup = _ready_agent(client, org, model_configuration={"provider": "OPENAI_COMPATIBLE", "model": "gpt-3.5-turbo"})
    execution = _run_execution(client, org, setup["agent"]["id"])

    assert execution["model_usage"]["token_accounting_complete"] is True
    row = db_session.get(AgentExecution, uuid.UUID(execution["id"]))
    assert row.prompt_tokens == fixture["usage"]["prompt_tokens"]
    assert row.completion_tokens == fixture["usage"]["completion_tokens"]
    assert row.total_tokens == fixture["usage"]["total_tokens"]
    assert row.token_accounting_complete is True


def test_omitted_usage_sets_incomplete_and_records_null_not_zero(client: TestClient, db_session: Session,
                                                                 monkeypatch) -> None:
    """AC-11 — never estimate."""
    from app.runtime.providers.openai_compatible import OpenAICompatibleProvider as OCP

    monkeypatch.setattr(OCP, "_build_default_transport",
                        lambda self: replay_transport("omitted_optional_fields.json"))

    org = _register_org(client)
    setup = _ready_agent(client, org, model_configuration={"provider": "OPENAI_COMPATIBLE", "model": "llama3"})
    execution = _run_execution(client, org, setup["agent"]["id"])

    assert execution["model_usage"]["token_accounting_complete"] is False
    row = db_session.get(AgentExecution, uuid.UUID(execution["id"]))
    assert row.token_accounting_complete is False
    assert row.prompt_tokens is None
    assert row.completion_tokens is None
    assert row.total_tokens is None


# --------------------------------------------------------------------------- #
# Accounting — AC-12, AC-13, AC-14
# --------------------------------------------------------------------------- #
def test_tokens_recorded_per_attempt_not_only_per_execution(client: TestClient, db_session: Session) -> None:
    """AC-12."""
    org = _register_org(client)
    setup = _ready_agent(client, org, model_configuration={"provider": "MOCK", "model": "mock-model"})
    execution = _run_execution(client, org, setup["agent"]["id"])

    attempt = db_session.execute(
        select(ExecutionAttempt).where(ExecutionAttempt.execution_id == uuid.UUID(execution["id"]))
    ).scalars().one()
    assert attempt.token_accounting_complete is True
    assert attempt.total_tokens is not None and attempt.total_tokens > 0
    assert attempt.total_tokens == execution["model_usage"]["total_tokens"]


def test_time_to_first_token_recorded_for_a_streamed_call(client: TestClient, monkeypatch) -> None:
    """AC-13."""
    from app.runtime.providers.openai_compatible import OpenAICompatibleProvider as OCP

    monkeypatch.setattr(OCP, "_build_default_transport",
                        lambda self: replay_sse_transport("stream_with_usage.sse"))

    org = _register_org(client)
    setup = _ready_agent(client, org, model_configuration={
        "provider": "OPENAI_COMPATIBLE", "model": "llama3", "stream": True,
    })
    execution = _run_execution(client, org, setup["agent"]["id"])

    ttft = execution["model_usage"]["time_to_first_token_ms"]
    assert isinstance(ttft, int) and ttft >= 0


def test_generation_duration_recorded_for_both_modes(client: TestClient, monkeypatch) -> None:
    """AC-14. Separate orgs — see the note on test_was_streamed_recorded_
    correctly_for_both_modes."""
    org_a = _register_org(client)
    non_streamed = _ready_agent(client, org_a, model_configuration={"provider": "MOCK", "model": "mock-model"})
    execution_a = _run_execution(client, org_a, non_streamed["agent"]["id"])
    assert isinstance(execution_a["model_usage"]["generation_duration_ms"], int)
    assert execution_a["model_usage"]["generation_duration_ms"] >= 0

    from app.runtime.providers.openai_compatible import OpenAICompatibleProvider as OCP
    monkeypatch.setattr(OCP, "_build_default_transport",
                        lambda self: replay_sse_transport("stream_with_usage.sse"))
    org_b = _register_org(client)
    streamed = _ready_agent(client, org_b, model_configuration={
        "provider": "OPENAI_COMPATIBLE", "model": "llama3", "stream": True,
    })
    execution_b = _run_execution(client, org_b, streamed["agent"]["id"])
    assert isinstance(execution_b["model_usage"]["generation_duration_ms"], int)
    assert execution_b["model_usage"]["generation_duration_ms"] >= 0


# --------------------------------------------------------------------------- #
# Cost — AC-15, AC-18, AC-20, AC-21
# --------------------------------------------------------------------------- #
def test_cost_computed_from_real_tokens_and_effective_pricing(client: TestClient, db_session: Session,
                                                               monkeypatch) -> None:
    """AC-15, AC-20, AC-21 — uses the migration-seeded gpt-3.5-turbo price."""
    from app.runtime.providers.openai_compatible import OpenAICompatibleProvider as OCP

    monkeypatch.setattr(OCP, "_build_default_transport", lambda self: replay_transport("simple_completion.json"))
    fixture = load_fixture("simple_completion.json")

    org = _register_org(client)
    setup = _ready_agent(client, org, model_configuration={"provider": "OPENAI_COMPATIBLE", "model": "gpt-3.5-turbo"})
    execution = _run_execution(client, org, setup["agent"]["id"])
    assert execution["status"] == "SUCCEEDED"

    row = db_session.get(AgentExecution, uuid.UUID(execution["id"]))
    expected = (fixture["usage"]["prompt_tokens"] / 1000) * 0.0005 + (fixture["usage"]["completion_tokens"] / 1000) * 0.0015
    assert float(row.cost_amount) == pytest.approx(expected, abs=1e-8)
    assert row.cost_currency == "USD"
    assert row.pricing_version == "2025-01-seed"
    assert row.cost_is_estimated is False
    # AC-20 -- attributable to execution, agent, version, org, model all at once.
    assert row.organization_id == uuid.UUID(org["organization_id"])
    assert row.agent_id == uuid.UUID(setup["agent"]["id"])
    assert row.agent_version_id == uuid.UUID(setup["version"]["id"])
    assert execution["model_usage"]["model"] == "gpt-3.5-turbo"


def test_local_provider_with_no_pricing_costs_zero_not_null(client: TestClient, db_session: Session) -> None:
    """AC-18."""
    org = _register_org(client)
    setup = _ready_agent(client, org, model_configuration={"provider": "MOCK", "model": "mock-model"})
    execution = _run_execution(client, org, setup["agent"]["id"])

    row = db_session.get(AgentExecution, uuid.UUID(execution["id"]))
    assert row.cost_amount == 0
    assert row.cost_amount is not None
    assert row.pricing_version is None
    assert row.cost_is_estimated is False


def test_pricing_service_returns_zero_for_unpriced_provider_directly(db_session: Session) -> None:
    """AC-18, unit level."""
    result = PricingService(db_session).calculate_cost(
        provider="MOCK", model="mock-model", prompt_tokens=100, completion_tokens=50,
        at=datetime.now(timezone.utc),
    )
    assert result.amount == 0.0
    assert result.pricing_version is None


# --------------------------------------------------------------------------- #
# Cost — AC-16, AC-17 (effective dating)
# --------------------------------------------------------------------------- #
def test_pricing_change_inserts_new_row_and_closes_the_prior_one(db_session: Session) -> None:
    """AC-16."""
    provider = f"TEST_PROVIDER_{uuid.uuid4().hex[:8]}"
    model = "test-model"
    service = PricingService(db_session)

    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    t1 = datetime(2026, 6, 1, tzinfo=timezone.utc)
    first = service.set_price(provider=provider, model=model, prompt_cost_per_1k=0.001,
                              completion_cost_per_1k=0.002, pricing_version="v1", effective_from=t0)
    second = service.set_price(provider=provider, model=model, prompt_cost_per_1k=0.003,
                               completion_cost_per_1k=0.004, pricing_version="v2", effective_from=t1)
    db_session.flush()

    rows = db_session.execute(
        select(ModelPricing).where(ModelPricing.provider == provider, ModelPricing.model_name == model)
        .order_by(ModelPricing.effective_from)
    ).scalars().all()
    assert len(rows) == 2
    assert rows[0].id == first.id
    assert rows[0].effective_to == t1  # closed, not deleted or mutated in price
    assert rows[0].prompt_cost_per_1k == pytest.approx(0.001)  # original price untouched
    assert rows[1].id == second.id
    assert rows[1].effective_to is None  # the new one is open-ended ("current")


def test_execution_priced_before_a_change_keeps_its_original_cost(db_session: Session) -> None:
    """AC-17 — historical accuracy: resolving a price *at* a past instant
    must keep returning the price that was actually in effect then, even
    after a newer price has since been added."""
    provider = f"TEST_PROVIDER_{uuid.uuid4().hex[:8]}"
    model = "test-model"
    service = PricingService(db_session)

    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    priced_at = datetime(2026, 3, 1, tzinfo=timezone.utc)  # between t0 and t1
    t1 = datetime(2026, 6, 1, tzinfo=timezone.utc)

    service.set_price(provider=provider, model=model, prompt_cost_per_1k=0.001, completion_cost_per_1k=0.002,
                      pricing_version="v1", effective_from=t0)
    db_session.flush()

    original_cost = service.calculate_cost(provider=provider, model=model, prompt_tokens=1000,
                                           completion_tokens=1000, at=priced_at)
    assert original_cost.pricing_version == "v1"

    # A price change happens *after* the execution was already priced.
    service.set_price(provider=provider, model=model, prompt_cost_per_1k=0.999, completion_cost_per_1k=0.999,
                      pricing_version="v2", effective_from=t1)
    db_session.flush()

    recomputed = service.calculate_cost(provider=provider, model=model, prompt_tokens=1000,
                                        completion_tokens=1000, at=priced_at)
    assert recomputed == original_cost
    assert recomputed.pricing_version == "v1"


# --------------------------------------------------------------------------- #
# Cost — AC-19 (legacy rows marked estimated)
# --------------------------------------------------------------------------- #
def test_legacy_placeholder_cost_rows_are_marked_estimated(client: TestClient, db_session: Session) -> None:
    """AC-19 — exercises the exact UPDATE migration 0028 issued
    (``UPDATE agent_executions SET cost_is_estimated = true WHERE cost <>
    0``) against a row created here, rather than depending on what
    already happens to be in the shared dev database from earlier phases'
    runs. A freshly-created (post-5.7a.3) execution starts out
    ``cost_is_estimated=False``; simulating "this predates the migration"
    by forcing a legacy-shaped state and re-running the same statement
    proves the mechanism, independent of history."""
    from sqlalchemy import text

    org = _register_org(client)
    setup = _ready_agent(client, org, model_configuration={"provider": "MOCK", "model": "mock-model"})
    execution = _run_execution(client, org, setup["agent"]["id"])
    execution_id = uuid.UUID(execution["id"])

    row = db_session.get(AgentExecution, execution_id)
    assert row.cost_is_estimated is False  # newly computed, real

    # Simulate "this row predates 5.7a.3": a legacy placeholder cost with
    # the flag not yet set.
    row.cost = 1.23456
    row.cost_is_estimated = False
    db_session.flush()

    db_session.execute(text("UPDATE agent_executions SET cost_is_estimated = true WHERE id = :id AND cost <> 0"),
                       {"id": str(execution_id)})
    db_session.flush()
    db_session.refresh(row)

    assert row.cost_is_estimated is True
    assert float(row.cost) == pytest.approx(1.23456)  # not recomputed or reset -- only flagged


# --------------------------------------------------------------------------- #
# Integrity — AC-22
# --------------------------------------------------------------------------- #
def test_mock_provider_streaming_behavior_is_unchanged() -> None:
    """AC-22."""
    provider = MockProvider()
    request = ModelRequest(messages=(ModelMessage(role="user", content="hello"),))
    chunks = list(provider.stream(request))
    assert len(chunks) == 1
    assert chunks[0].content == "[mock-model] processed 1 message(s)."
    assert chunks[0].finish_reason == FinishReason.STOP
    assert dict(chunks[0].raw_usage)["total_tokens"] > 0
