# Telemetry privacy — the scrubber, the baseline, and the one absolute rule

> **Phase 4.1 (ACT-SRS-M4 §7, §14, §4.8).** What this platform captures, what it
> refuses to capture, and how a secret is prevented from reaching storage.
> Implemented in `app/observability/scrubbing.py` and
> `app/observability/capture.py`.

## Three rules, in order of strength

1. **Chain-of-thought is never captured.** No mode enables it. Structural, not a
   policy.
2. **Secrets are scrubbed before persistence.** Not masked at display — removed
   on the write path.
3. **Content is not captured by default.** `METADATA_ONLY` is the baseline;
   Phase 4.8 builds the opt-in.

## Rule 1 — private reasoning is never captured

Chain-of-thought is **not** "content that is off by default". It is a separate
class, `DataClass.NEVER`, and there is no capture mode — present or future —
that admits it.

```python
_ALLOWED = {
    CaptureMode.METADATA_ONLY:     {DataClass.METADATA},
    CaptureMode.CONTENT:           {DataClass.METADATA, DataClass.CONTENT},
    CaptureMode.SENSITIVE_CONTENT: {DataClass.METADATA, DataClass.CONTENT,
                                    DataClass.SENSITIVE_CONTENT},
}
```

`NEVER` and `SECRET` appear in **no** mode's set. That absence *is* the guarantee.
It is a property of the table rather than a special case someone could forget to
carry forward, and the test asserts it over **every member of `CaptureMode`** —
so a mode added by a later phase cannot quietly acquire them:

```python
@pytest.mark.parametrize("mode", list(CaptureMode))
def test_ac11_no_capture_mode_admits_private_reasoning(mode):
    assert is_capturable(DataClass.NEVER, mode) is False
    assert is_capturable(DataClass.SECRET, mode) is False
```

Why structural rather than a toggle: **a policy toggle can be flipped by a future
phase in a hurry. A branch that returns `False` for every mode has to be deleted
on purpose, in a diff someone reviews.**

### Recognized by name, however spelled

Providers expose reasoning under names they choose — Anthropic's `thinking`
blocks, OpenAI's `reasoning` / `reasoning_content`, the generic
`chain_of_thought`. Matching is normalized (case folded, separators stripped), so
`chain-of-thought`, `chain_of_thought` and `ChainOfThought` are one thing.

### Stripped unconditionally, before anything else

`strip_reasoning()` runs **first** and is **mode-independent**. A provider that
starts returning a thinking block inside its usage metadata must not be able to
smuggle reasoning into telemetry just because the surrounding object was
classified as metadata.

Reasoning classification also **beats** content classification — a field called
`reasoning_content` is `NEVER`, not `CONTENT`. Checking content first would get
exactly this backwards.

### Dropped, not redacted

```python
>>> strip_reasoning({"status": "OK", "reasoning": "first I considered..."})
{'status': 'OK'}
```

The field disappears entirely. A `***REDACTED***` marker would still record that
reasoning existed and how many turns had it — which is still a claim about the
model's private state. **Absence records nothing.**

## Rule 2 — secrets are scrubbed before persistence

`app/observability/scrubbing.py` has **no dependencies on this platform**. Not
the models, not the config, not the ORM, not even `app.core`. Standard library
only, asserted over the AST:

```python
def test_ac09_the_scrubber_imports_nothing_from_this_platform():
    ...
    assert not [m for m in imported if m.startswith("app")]
```

That isolation is the same discipline
`app/integration/connectors/storage/scope.py` was built with, and for the same
reason: the one function that decides whether a secret can reach persistent
storage must be readable, reviewable and exhaustively testable **without standing
a telemetry pipeline up around it**.

### The nine secret classes (§14)

| Class | Example keys |
|---|---|
| `authorization_header` | `authorization`, `proxy-authorization` |
| `bearer_token` | `access_token`, `id_token`, `jwt`, `assertion` |
| `api_key` | `api_key`, `x-api-key`, `client_secret`, `subscription_key` |
| `password` | `password`, `passphrase`, `secret` |
| `connector_credential` | `credentials`, `connection_string`, `dsn`, `sas_token` |
| `provider_credential` | `openai_api_key`, `aws_secret_access_key`, `azure_key` |
| `refresh_token` | `refresh_token`, `offline_token` |
| `cookie` | `cookie`, `set-cookie`, `csrf_token` |
| `private_key` | `private_key`, `signing_key`, `tls_key`, `ssh_key` |

Kept as an explicit, named table rather than one flat regex, so the tests can
assert **coverage of the specification** — "every class named in §14 is
scrubbed" — instead of asserting that a particular regex happens to match a
particular string. The test is parametrized over the table, so a class added to
§14 later cannot ship without a test.

### Two ways a secret is found

**By key** — the name says what the value is:

```python
>>> scrub({"authorization": "Bearer abc"})
{'authorization': '***REDACTED***'}
```

**By shape** — the value looks like a credential regardless of what it is called:

```python
>>> scrub({"harmless_looking_field": "sk-proj-abcdefghijklmnopqrstuvwxyz012345"})
{'harmless_looking_field': '***REDACTED***'}
```

Key matching alone is not enough, because a secret carried under an innocuous
name would survive it. Shape matching alone is not enough, because a high-entropy
string is not reliably distinguishable from a legitimate identifier. **Both run,
and either one is sufficient to redact.**

Recognized shapes include authorization header values (`Bearer`/`Basic`/`Digest`
/`Negotiate`/`HMAC`), bare JWTs, vendor-prefixed keys (`sk-`, `ghp_`, `xoxb-`,
`AKIA…`, `AIza…`), PEM private-key blocks, and URLs carrying inline credentials
(`postgresql://user:pass@host/db`).

### Not over-eager

An unrestrained matcher would cost the telemetry plane ordinary operational
facts. `password_changed_at` is a timestamp, `has_password` is a boolean,
`credential_id` is a foreign key, `prompt_tokens` is a count. All survive:

```python
>>> scrub({"password_changed_at": "2026-01-01", "password": "hunter2"})
{'password_changed_at': '2026-01-01', 'password': '***REDACTED***'}
```

### Other properties worth knowing

- **The input is never mutated.** A caller must be able to scrub a payload for
  telemetry without altering the domain object it came from.
- **A value with no secret passes through identically.** Scrubbing must be
  transparent to ordinary values, or the telemetry plane becomes useless.
- **Deep structures are truncated, not recursed.** Past `MAX_DEPTH` the subtree
  is replaced with the marker. A pathological structure must not turn a
  best-effort telemetry write into a stack overflow that takes the execution
  down with it.
- **`REDACTED` is deliberately not empty and not `None`.** A reader must be able
  to tell "there was a secret here and it was removed" from "there was nothing
  here", or an audit of the telemetry plane cannot distinguish a working
  scrubber from an absent one.

### Scrub is not mask

`mask_hint()` in `app/runtime/providers/credential_crypto.py` keeps the last four
characters so a human can recognize a key they configured. That is a different
job with a different threat model — the operator is looking at their own
credential on purpose. **Telemetry has no such need, so it keeps nothing.**

### Before persistence, not at display

§14 is about the write path. A value that reached the database unscrubbed is
already leaked, and masking it in a UI afterwards changes nothing. The test
asserts the value **in the database**:

```python
emit_event(db, ..., payload={"authorization": "Bearer super-secret-token"})
stored = db.execute(select(RuntimeEvent)...).scalar_one()
assert "super-secret-token" not in str(stored.payload)
```

Structurally, filtering happens at **construction** of a `RuntimeEventRecord`,
not at persistence — so there is no way to hold a record whose payload has not
been through the filter, and a future caller cannot construct one and reach
storage by another route.

## Rule 3 — METADATA_ONLY is the baseline

Telemetry records *that* a model was called, by whom, for how long, at what cost,
with what outcome. It does **not** record the prompt, the tool arguments, the
tool result, or the model's output.

```python
>>> filter_for_capture({
...     "status": "SUCCEEDED", "duration_ms": 12,
...     "prompt": "the confidential business question",
...     "output_payload": {"answer": "..."},
... })
{'status': 'SUCCEEDED', 'duration_ms': 12}
```

This is a deliberate choice about what a conservative default costs. A platform
that captured content by default and offered a switch to turn it off would be
correct exactly until the first tenant forgot to flip it. A platform that
captures nothing by default is less immediately useful and **cannot leak what it
never held**.

Phase 4.8 builds the policy system that lets a tenant opt in deliberately, per
environment, with the retention and access controls that decision requires.

### The four data classes

| Class | What | Captured in 4.1 |
|---|---|---|
| `METADATA` | Identifiers, timings, counts, statuses, costs | **Yes** |
| `CONTENT` | Prompts, model output, tool arguments and results | No — 4.8 may allow |
| `SENSITIVE_CONTENT` | Regulated or personal content | No — strictly narrower than CONTENT |
| `SECRET` | Credentials of any kind | **Never** |
| `NEVER` | Private model reasoning | **Never** |

Representing the distinction now — while only `METADATA` is ever captured — is
what lets 4.8 build a real policy on top without first having to invent the
vocabulary and retrofit it to existing call sites.

### Where the mode is resolved

One function, `current_mode()`, which always answers `METADATA_ONLY` in 4.1. It
is deliberately a *function* rather than a constant so that 4.8 can make it
consult `Environment.policy` without every caller changing.

No settings key was added for it. A switch with nothing behind it would create a
way to *believe* content capture is configured while no code path honours it —
which is worse than not having the switch.

## The pipeline, and why the order is not interchangeable

`filter_for_capture()` runs three steps:

1. **Strip reasoning** — unconditional, mode-independent (§7).
2. **Drop non-capturable classes** — under the baseline this removes every
   content field, so prompts and tool payloads never reach step 3 at all.
3. **Scrub** — the surviving metadata still goes through the scrubber.

Step 3 is **not redundant** with step 2. Step 2 asks *"is this the kind of thing
we capture?"*; step 3 asks *"does this specific value contain a secret?"*. A
field can pass the first and fail the second — an error message quoting a
connection string, a debug blob carrying a header — and that is exactly the case
that leaks if only one of them runs.

## End-to-end assurance

A real execution is run with a distinctive marker in its input payload, and the
marker is asserted to appear **nowhere** in `runtime_events`:

```python
marker = f"CONFIDENTIAL-{uuid.uuid4().hex[:10]}"
client.post(f"{RT}/executions", json={..., "input_payload": {"question": marker}})
for event in events_for(execution):
    assert marker not in str(event.payload)
```

## See also

- [architecture.md](./architecture.md) — the three-plane model, non-gating
  telemetry, trace assembly
- [semantic-conventions.md](./semantic-conventions.md) — the attribute
  vocabulary and bounded cardinality
