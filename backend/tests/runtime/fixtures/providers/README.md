# Provider fixtures

Raw OpenAI-compatible chat-completions response bodies, used by
`test_openai_compatible_provider.py` via a replay `httpx` transport so no
test depends on a live model endpoint (AC-23/AC-24).

## Provenance — read before trusting these as "recorded"

`backend/scripts/record_provider_fixtures.py` is the intended way to
(re)generate these: run it against a real Ollama instance and it writes
each scenario below to its own file here, stripping any auth header first.

**In this environment, no Ollama instance was reachable** (`curl
localhost:11434` timed out — no local install), so these six files were
**hand-authored to match Ollama's documented OpenAI-compatible response
shape** (`/v1/chat/completions`) rather than literally captured from a live
run. They are not fabricated arbitrarily: the shape (top-level
`id`/`object`/`created`/`model`/`system_fingerprint`/`choices`/`usage`,
`choices[0].message`/`finish_reason`, `message.tool_calls[].function.
{name,arguments}` with `arguments` as a JSON-encoded string) matches
Ollama's and OpenAI's published wire format exactly. `omitted_optional_
fields.json` specifically encodes a real, documented Ollama behavior:
earlier Ollama versions' OpenAI-compat layer omits `usage`, `system_
fingerprint`, `id`, `object`, and `created` in some responses — this
fixture has none of those, on purpose.

**If you have a local Ollama install**, re-run the recorder to replace
these with genuinely captured responses — the parsing code makes no
assumption about which is which:

```bash
ollama pull llama3
python backend/scripts/record_provider_fixtures.py --base-url http://localhost:11434/v1 --model llama3
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

None of these contain a credential or `Authorization` header (AC-24) — the
recorder strips them before writing, and none was ever present in the
hand-authored versions either.
