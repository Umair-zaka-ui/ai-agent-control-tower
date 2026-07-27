"""Phase 5.7a.2 SRS §6 — provider fixture recorder.

Makes real calls against a configured OpenAI-compatible endpoint (Ollama,
vLLM, LM Studio, ...) and writes each scenario's raw response body to
``backend/tests/runtime/fixtures/providers/`` as wire-format JSON — not a
parsed ``ModelResponse``, so the adapter's own parsing code is exercised
against genuine provider output when the fixture is replayed in tests.

Run manually. Never invoked from CI, a test, or any application code path
— ``OpenAICompatibleProvider`` itself has no awareness this script exists.

Usage::

    ollama pull llama3
    python -m scripts.record_provider_fixtures --base-url http://localhost:11434/v1 --model llama3

Each of the six scenarios below is recorded to its own named file,
overwriting whatever is already there. Any ``Authorization`` header is
stripped before writing — a fixture must never contain a credential
(AC-24).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import httpx

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "tests" / "runtime" / "fixtures" / "providers"

_WEATHER_TOOL = {
    "type": "function",
    "function": {
        "name": "get_weather",
        "description": "Look up the current weather for a location.",
        "parameters": {
            "type": "object",
            "properties": {"location": {"type": "string"}},
            "required": ["location"],
        },
    },
}

_SCENARIOS: dict[str, dict] = {
    "simple_completion.json": {
        "messages": [{"role": "user", "content": "Why does the sky look blue?"}],
    },
    "max_tokens_reached.json": {
        "messages": [{"role": "user", "content": "Explain Rayleigh scattering in detail."}],
        "max_tokens": 16,
    },
    "single_tool_call.json": {
        "messages": [{"role": "user", "content": "What's the weather in New York, NY?"}],
        "tools": [_WEATHER_TOOL],
    },
    "multiple_tool_calls.json": {
        "messages": [{"role": "user", "content": "What's the weather in New York, NY and Boston, MA?"}],
        "tools": [_WEATHER_TOOL],
    },
    "omitted_optional_fields.json": {
        "messages": [{"role": "user", "content": "In one sentence: does Ollama always send every OpenAI field?"}],
    },
    "multi_turn_with_tool_message.json": {
        "messages": [
            {"role": "system", "content": "You are a helpful weather assistant."},
            {"role": "user", "content": "What's the weather in New York right now?"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [{
                    "id": "call_9f1e2a", "type": "function",
                    "function": {"name": "get_weather", "arguments": '{"location": "New York, NY"}'},
                }],
            },
            {"role": "tool", "tool_call_id": "call_9f1e2a", "content": '{"tempF": 58, "conditions": "partly cloudy"}'},
        ],
    },
}


def _record_one(client: httpx.Client, model: str, filename: str, scenario: dict) -> None:
    body = {"model": model, **scenario}
    response = client.post("/chat/completions", json=body, timeout=60.0)
    response.raise_for_status()
    data = response.json()
    (FIXTURES_DIR / filename).write_text(json.dumps(data, indent=2) + "\n")
    print(f"wrote {filename}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True, help="e.g. http://localhost:11434/v1")
    parser.add_argument("--model", required=True, help="e.g. llama3")
    args = parser.parse_args()

    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)
    with httpx.Client(base_url=args.base_url) as client:
        for filename, scenario in _SCENARIOS.items():
            _record_one(client, args.model, filename, scenario)
    return 0


if __name__ == "__main__":
    sys.exit(main())
