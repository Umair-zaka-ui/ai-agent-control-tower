# Provider fixtures

Raw OpenAI-compatible chat-completions response bodies (and, for streaming
scenarios, raw SSE text), used by `test_openai_compatible_provider.py` via
a replay `httpx` transport so no test depends on a live model endpoint
(AC-23/AC-24 in 5.7a.2; AC-25 in 5.7a.3).

## Provenance — read before trusting these as "recorded"

`backend/scripts/record_provider_fixtures.py` is the intended way to
(re)generate these: run it against a real Ollama instance and it writes
each non-streaming scenario as JSON and each streaming scenario as raw SSE
bytes, stripping any auth header first.

**In this environment, no Ollama instance was reachable** (`curl
localhost:11434` timed out — no local install, re-verified in the 5.7a.3
session too), so every file below was **hand-authored to match Ollama's/
OpenAI's documented wire format** rather than literally captured from a
live run. They are not fabricated arbitrarily:

- The six non-streaming files (5.7a.2) match the documented `/v1/chat/
  completions` response shape (top-level `id`/`object`/`created`/`model`/
  `system_fingerprint`/`choices`/`usage`, `choices[0].message`/
  `finish_reason`, `message.tool_calls[].function.{name,arguments}` with
  `arguments` as a JSON-encoded string). `omitted_optional_fields.json`
  specifically encodes a real, documented Ollama behavior: its OpenAI-compat
  layer omits `usage`/`system_fingerprint`/`id`/`object`/`created` in some
  responses.
- The five streaming `.sse` files (5.7a.3) match OpenAI's documented
  chunked-delta format: `data: {"choices":[{"delta": {...},
  "finish_reason": ...}]}\n\n` lines terminated by `data: [DONE]\n\n`, a
  streamed tool call's `function.arguments` arriving as successive string
  fragments keyed by `index`, and `usage` present only in the same event
  that carries `finish_reason` (or absent entirely, matching Ollama).
  `stream_truncated.sse` is the one fixture that *cannot* be recorded from
  a real endpoint on purpose — see the recorder script's own docstring.

**If you have a local Ollama install**, re-run the recorder to replace the
recordable ones with genuinely captured responses — the parsing code makes
no assumption about which is which:

```bash
ollama pull llama3
python -m scripts.record_provider_fixtures --base-url http://localhost:11434/v1 --model llama3
```

## Files

| File | Scenario | Acceptance criterion |
|---|---|---|
| `simple_completion.json` | Plain completion, no tools, `finish_reason: stop` | AC-03 |
| `max_tokens_reached.json` | `finish_reason: length` | AC-08 |
| `single_tool_call.json` | One tool call requested | AC-06 |
| `multiple_tool_calls.json` | Two tool calls requested in one response | AC-07 |
| `omitted_optional_fields.json` | Only `choices[0].message`/`finish_reason` present — no `usage`, `id`, `object`, `created`, `system_fingerprint` | AC-11 |
| `multi_turn_with_tool_message.json` | Final assistant answer after a request whose message history included a `tool`-role message | AC-04 |
| `stream_simple_completion.sse` | Multi-chunk streamed completion, `finish_reason: stop`, no usage | 5.7a.3 AC-01 |
| `stream_with_usage.sse` | Streamed completion whose final chunk carries `usage` | 5.7a.3 AC-02, AC-10 |
| `stream_without_usage.sse` | Streamed completion with no `usage` anywhere — the Ollama case | 5.7a.3 AC-11 |
| `stream_tool_call_fragmented.sse` | Two interleaved tool calls, each fragmented across many chunks | 5.7a.3 AC-03, AC-04 |
| `stream_truncated.sse` | Connection ends mid-stream — no `finish_reason` chunk, no `[DONE]` | 5.7a.3 AC-05 |

None of these contain a credential or `Authorization` header (AC-24) — the
recorder strips them before writing, and none was ever present in the
hand-authored versions either.
