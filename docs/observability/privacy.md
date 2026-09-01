# Telemetry privacy — the scrubber, the baseline, and the one absolute rule

> **Phase 4.1 (ACT-SRS-M4 §7, §14, §4.8).** What this platform captures, what it
> refuses to capture, and how a secret is prevented from reaching storage.
> Implemented in `app/observability/scrubbing.py` and
> `app/observability/capture.py`.
>
> **Phase 4.8 added the per-scope capture-policy layer, the governed content
> store, the distinct content permission, and per-class retention — see
> "[Phase 4.8 — capture policy, content capture & access governance](#phase-48--capture-policy-content-capture--access-governance)"
> at the end of this document and [retention.md](./retention.md). The three §7 /
> §14 rules below are the structural floor beneath all of it.**

## Three rules, in order of strength

1. **Chain-of-thought is never captured.** No mode enables it. Structural, not a
   policy.
2. **Secrets are scrubbed before persistence.** Not masked at display — removed
   on the write path.
3. **Content is not captured by default.** `METADATA_ONLY` is the baseline;
   Phase 4.8 built the opt-in (capture policy, below).

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

Phase 4.8 built the policy system that lets a tenant opt in deliberately, per
tenant / environment / agent / classification, with the retention and access
controls that decision requires — see below.

### The four data classes

| Class | What | Captured in 4.1 |
|---|---|---|
| `METADATA` | Identifiers, timings, counts, statuses, costs | **Yes** |
| `CONTENT` | Prompts, model output, tool arguments and results | No by default — 4.8 policy may allow, redacted or full |
| `SENSITIVE_CONTENT` | Regulated or personal content | No — strictly narrower than CONTENT |
| `SECRET` | Credentials of any kind | **Never** |
| `NEVER` | Private model reasoning | **Never** |

Representing the distinction now — while only `METADATA` is ever captured — is
what lets 4.8 build a real policy on top without first having to invent the
vocabulary and retrofit it to existing call sites.

### Where the mode is resolved

One function, `current_mode()`, is the **platform baseline** and still always
answers `METADATA_ONLY` — the conservative default that applies when no policy
narrows the scope. Phase 4.8 added the per-scope layer *on top*
(`app.telemetry_privacy.policy.resolve_capture_mode`, below); it resolves against
`telemetry_capture_policies` rows, and it imports the 4.1 primitive (for
`strip_reasoning` and the `NEVER` floor), never the reverse.

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

## Phase 4.8 — capture policy, content capture & access governance

> **Phase 4.8 (ACT-SRS-M4 §3.5, §4.8, §16, §17, §24; Gate F).** The three rules
> above are the floor. This section is the policy system built on it.

### The four capture modes

| Mode | Captures | Notes |
|---|---|---|
| `DISABLED` | nothing | No `trace_content` row, and no new content-bearing telemetry record, is ever created for the scope. |
| `METADATA_ONLY` | metadata only | The 4.1 baseline (above). The **platform default**. |
| `REDACTED_CONTENT` | metadata + content, classification-masked | Sensitive-named fields masked, long text truncated, **before persistence**; secrets scrubbed. |
| `FULL_CONTENT` | metadata + full business content | Secrets **still scrubbed** (Rule 2). "Full content" is full *business* content, never full secrets. |

Rules 1 (no chain-of-thought) and 2 (scrub before persist) hold beneath all four
— `strip_reasoning` then `scrub` run in every content-capturing mode before any
`trace_content` row is written; an AST test pins `strip_reasoning` as the first
call in `redact_for_capture`.

**The exact `DISABLED` boundary.** `DISABLED` means the telemetry plane records
nothing new for the scope. Because 4.1's trace *metadata* is derived (computed on
demand from domain rows, never stored — §13), it cannot be retroactively erased;
but a `DISABLED` scope creates no telemetry-plane record of its own, which is the
strongest boundary a derived plane admits.

### Resolution & precedence

A `telemetry_capture_policies` row applies to the intersection of the scope
columns it sets. The **most specific** matching enabled row wins:

```
classification  >  agent  >  environment  >  tenant  >  platform-default
```

Ties break by most-recently-updated then id, so the effective mode is a pure
function of the stored rows. `GET
/api/v1/runtime/telemetry/effective-mode?environment_id=&agent_id=&classification=`
returns the winning policy, the scope it matched, the reason, and **every
candidate considered**.

**Conservative default (M4-4.8-FR-002).** With no matching row: a production
environment, or one whose `Environment.policy` declares a sensitive
classification (`CONFIDENTIAL` / `RESTRICTED` / `PII` / `PHI` / `REGULATED`),
resolves to `METADATA_ONLY` (`source: "conservative-default"`); every other scope
also resolves to `METADATA_ONLY` (`source: "platform-default"`). A resolution
**never** yields `FULL_CONTENT` without an explicit policy row, and a malformed
stored mode coerces toward `METADATA_ONLY`. A misconfiguration fails toward
*less* capture.

### The governed content store

Content is **materialised on the first authorised content view and never
before** — there is no background capture job. `TraceContentService.materialize`
reads the domain locations (`agent_executions.input_payload` / `output_payload`,
the `execution_messages` transcript, `tool_calls.input_summary` /
`output_summary`) and, **for each value, before the `trace_content` row is
inserted**, runs `strip_reasoning` → `scrub` → (for `REDACTED_CONTENT`)
classification masking. The insert is idempotent (`uq_trace_content_source`).

**Why a dedicated store and not redaction-in-place.** `execution_messages` and
the payload columns are *domain truth* — the tool loop feeds them back to the
model, the execution-detail page reads them. Redacting them in place would
corrupt execution state and would violate "retention deletes telemetry, never
domain truth" (§24, M4-4.8-FR-032). The `trace_content` copy has its own
redaction, classification and retention lifetime; the domain rows are untouched
and outlive it. See
[ADR-0013](../architecture/adr/0013-trace-content-capture-and-access-policy.md).

### Access governance — the central property

Reading trace **content** requires `runtime.trace.content.view` — a **distinct**
permission, **strictly stronger** than `runtime.telemetry.view`:

- **not** in the read-only permission bundle — a grant is deliberate;
- **not** implied by executing an agent, nor by holding the metadata view;
- **every** successful content view is audited (`RUNTIME_TRACE_CONTENT_VIEWED`,
  actor + resource ids, **never the payload**).

> An SRE can see that a tool failed 34% of the time (metadata) without being able
> to read the PHI in that tool's arguments (content) — unless separately,
> auditably authorised.

**404 vs 403.** `GET /api/v1/observability/traces/{trace_id}/content`:

| Situation | Response |
|---|---|
| Trace absent *for this tenant* (missing, or another tenant's) | `TRACE_NOT_FOUND` — **404** |
| Trace present for the tenant; caller lacks `runtime.trace.content.view` | `TRACE_CONTENT_ACCESS_DENIED` — **403** |
| Caller lacks even the metadata view | `PERMISSION_DENIED` — 403 (route dependency) |

The trace is resolved **before** the content permission is checked, so the two
cases stay distinct — without ever letting one tenant confirm another's trace
exists (§34).

### Management

| Method | Path | Permission |
|---|---|---|
| `GET` / `POST` | `/api/v1/runtime/telemetry/capture-policies` | `runtime.telemetry_policy.view` / `.manage` |
| `GET` / `PATCH` / `DELETE` | `/api/v1/runtime/telemetry/capture-policies/{id}` | view / manage |
| `GET` | `/api/v1/runtime/telemetry/effective-mode` | view |
| `GET` | `/api/v1/observability/traces/{trace_id}/content` | **`runtime.trace.content.view`** |

Every capture-policy write is audited (`RUNTIME_TELEMETRY_POLICY_CHANGED`).
`classification` is a closed vocabulary — an unknown value is `422`, not a
silently-ignored policy — and a policy row never holds a secret.

### Not enforcement

A capture policy never stops or alters an execution (§9). `app/telemetry_privacy`
references no kill switch, no governance engine, no execution-state mutation
(AST-asserted).

## See also

- [architecture.md](./architecture.md) — the three-plane model, non-gating
  telemetry, trace assembly
- [retention.md](./retention.md) — per-class retention and the safe expiration
  sweep (Phase 4.8)
- [semantic-conventions.md](./semantic-conventions.md) — the attribute
  vocabulary and bounded cardinality
- [ADR-0013](../architecture/adr/0013-trace-content-capture-and-access-policy.md)
  — trace content as a governed, separately-stored, separately-permissioned data
  class
