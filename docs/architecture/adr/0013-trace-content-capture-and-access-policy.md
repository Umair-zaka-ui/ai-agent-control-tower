# ADR-0013 — Trace content is a governed, separately-stored, separately-permissioned data class

- **Status:** Accepted
- **Date:** 2026-09-01
- **Deciders:** Phase 4.8 (Milestone 4 — Runtime Governance & Observability)
- **Supersedes:** —
- **Relates to:** ADR-0008 (telemetry is a derived plane, non-gating), ADR-0011
  (export is fail-open), ADR-0006 (deterministic governance). Completes the
  boundary 4.1 and 4.2 deliberately left open.

## Context

4.1 established a conservative `METADATA_ONLY` baseline, a secret scrubber in the
write path, the `metadata / content / sensitive / secret` data-class
vocabulary, and a structural `NEVER` class for chain-of-thought. 4.2 built the
trace explorer and detail view, **metadata only**, and named
`runtime.trace.content.view` in code without registering it — leaving the
content boundary with a visible owner but no implementation.

4.8 has to make content capture real. The forces:

1. **Content is the sensitive part.** Prompts, tool arguments, tool results,
   model output — PHI, PII, secrets, proprietary data. A platform that captured
   it by default and offered an off switch would be correct until the first
   tenant forgot to flip it.

2. **The domain already persists content.** `execution_messages.content`,
   `agent_executions.input_payload` / `output_payload`, and
   `tool_calls.input_summary` / `output_summary` carry raw content **today** —
   the model-driven tool loop (5.6a.3) needs the transcript to feed results back
   to the model, and the execution-detail page reads the payloads. This content
   is *domain truth*, not telemetry.

3. **"Redact before persistence, not display-time masking" (§14).** The
   protection has to be in the write path. But the domain write path cannot be
   the redaction point without breaking the loop.

4. **Retention deletes telemetry, never domain truth (§24, M4-4.8-FR-032).**
   An execution row's existence and its captured content are different
   lifetimes.

5. **Executing an agent is not permission to read its prompts (§4.8, §16).**
   Metadata view and content view must be different permissions, content being
   strictly stronger, and every content view audited.

## Options considered

### Decision A — where the governed content lives

#### Option A1 — govern the existing domain locations in place

Redact `execution_messages` / the payload columns before they are persisted;
the content endpoint reads them directly with a policy filter.

- Pros: no new table; one copy of the content.
- Cons: the domain rows are *truth the loop and the detail page depend on*.
  Redacting `execution_messages.content` before persistence would feed a masked
  transcript back to the model on the next turn — a behaviour change to
  execution itself. Retention could then only expire content by damaging the
  execution record. §13's "prefer governing existing locations" assumes those
  locations are telemetry; here they are not.

#### Option A2 — a dedicated `trace_content` telemetry store, materialised on first authorised view

The domain rows are untouched. When a content view is authorised and the
resolved mode permits content, the domain values are read, scrubbed + redacted,
and written to `trace_content` — a telemetry-plane table with its own
`classification` / `mode_applied` / `redacted` columns and its own retention.

- Pros: redaction happens before *this* store's persistence, satisfying §14 for
  the telemetry copy, while the domain rows stay authoritative. `trace_content`
  expires on the `trace_content` retention schedule with no effect on the
  execution. This is exactly the "`trace_content` table with a redaction /
  classification column and its own retention" §5 explicitly permits.
- Cons: content is duplicated (once, redacted). Materialisation-on-read means a
  policy loosened *after* an execution ran will, on the next view, materialise
  that older execution's content — retroactive visibility of already-persisted
  domain truth under a newer, permissioned, audited policy.

### Decision B — the permission

#### Option B1 — reuse `runtime.telemetry.view` with a policy gate

- Pros: no new permission.
- Cons: every metadata viewer becomes a content viewer wherever a content mode
  is enabled. Directly contradicts §4.8 / §16.

#### Option B2 — register `runtime.trace.content.view` as a distinct, stronger permission

- Pros: the access-governance property §4.8 is built around. A grant is
  deliberate; not implied by execute or metadata; every use audited.
- Cons: one more permission in the catalog, and a route that has to check two
  permissions (metadata via dependency, content imperatively) to keep the
  404-vs-403 discipline.

### Decision C — enforcement

Never in play. A capture policy that could stop an execution would be an
enforcer, and 4.3 is the only enforcer. `app/telemetry_privacy` references no
kill switch, no governance engine, no execution-state mutation (AST-asserted).

## Decision

**A2, B2, C = a governed, separately-stored, separately-permissioned data class.**

- **`trace_content` is a dedicated telemetry store**, materialised on the first
  authorised content view and never before. The domain rows it derives from are
  untouched and outlive it. Secret scrubbing (§14) and, for `REDACTED_CONTENT`,
  classification field-masking run **before** each `trace_content` row is
  inserted. Chain-of-thought is stripped first, in every mode (§7).

- **Four capture modes** — `METADATA_ONLY` / `REDACTED_CONTENT` / `FULL_CONTENT`
  / `DISABLED` — resolved per tenant / environment / agent / classification with
  precedence `classification > agent > environment > tenant >
  platform-default`. A production or sensitively-classified scope with no
  explicit policy resolves to `METADATA_ONLY`; a malformed stored mode coerces
  toward `METADATA_ONLY`. Never `FULL_CONTENT` without an explicit policy.

- **`runtime.trace.content.view` is registered, distinct, and strictly
  stronger** than `runtime.telemetry.view`: not in the read-only bundle, not
  implied by execute or metadata. The content route resolves the trace first
  (404 if absent for the tenant), then checks the content permission
  imperatively (403 `TRACE_CONTENT_ACCESS_DENIED` if missing). Every successful
  view emits `RUNTIME_TRACE_CONTENT_VIEWED` — actor + resource ids, never the
  payload.

- **Retention is per class** (`trace_content` / `trace_metadata` /
  `metrics_aggregate` / `alert_history` deletable; `governance_decision` /
  `financial_record` retain-only with a one-year floor). The sweep is
  idempotent, batched, bounded, and 3.8-schedulable — the 4.5 / 4.7 / 3.5
  interim pattern. **No scheduler built.**

- **Non-gating.** No capture or retention operation stops or alters an
  execution.

## Consequences

### Positive

- The domain content path (the tool loop, execution detail) is completely
  untouched — 4.8 adds a governed *view* of it, not a rewrite of it.
- `trace_content` can be purged on a 30-day schedule while the execution and its
  transcript persist for as long as the domain keeps them.
- The content boundary 4.1 and 4.2 named is now real and enforceable: a metadata
  viewer cannot read content, and a test proves it by granting only
  `runtime.telemetry.view` and asserting 403.
- Redaction is provably before persistence for the telemetry copy — an AST test
  pins `strip_reasoning` as the first call in the pipeline, and behavioural
  tests confirm a planted secret never lands in `trace_content` in any mode.
- The conservative default means a misconfiguration under-captures; it cannot
  silently start persisting prompts.

### Negative / accepted cost

- **Content is stored twice** where a content mode is enabled — once as domain
  truth, once redacted as telemetry. The redacted copy is the smaller and
  shorter-lived one, but it is a real duplication.
- **Materialise-on-read is retroactive.** Enabling `FULL_CONTENT` today makes
  yesterday's executions' content viewable on the next authorised view. This is
  bounded by the permission (deliberate, audited) and by retention (older domain
  content is what a tightened policy protects — via purge, not via refusing the
  view), but an operator expecting "policy applies only forward" will be
  surprised. Documented in `privacy.md`.
- **The content route checks two permissions.** The metadata view via the route
  dependency, the content view imperatively after trace resolution. This is the
  price of the 404-vs-403 discipline; folding it into one dependency would make
  a cross-tenant trace id return 403 instead of 404 for a content viewer.
- **`DISABLED` cannot un-derive 4.1's metadata.** Because trace metadata is
  computed on demand from domain rows, a `DISABLED` scope still has a derivable
  metadata trace; the boundary it enforces is "no new telemetry-plane record",
  which is stated rather than hidden.

### Residual risk

- The "scrub before persist" guarantee for `trace_content` depends on
  `redact_for_capture` being the only writer. A future code path that inserts
  into `trace_content` directly, bypassing it, would breach §14 silently. The
  AST test on the pipeline order is a partial guard; a stronger guard would be a
  DB trigger, which was judged disproportionate.
- `_REDACT_FIELDS` in `redaction.py` is a name-based denylist. A sensitive
  payload under an unrecognised field name survives `REDACTED_CONTENT` masking
  (the secret scrubber still runs on it). Widening the list is cheap; the
  alternative — masking everything and un-masking a safelist — was judged to
  make `REDACTED_CONTENT` useless for debugging.
- The conservative-default decision reads `Environment.is_production` and
  `Environment.policy` classification hints. An environment mis-flagged as
  non-production defeats the production default — but that misconfiguration
  already has wider consequences than telemetry.

## Revisit when

- **A capture hook at execution finalisation is wanted** (materialise content at
  completion rather than on first view). That removes the retroactive-visibility
  surprise but adds a write to the hot finalisation path — measure it against
  §9 first, and bind the captured mode to the execution rather than re-resolving
  current policy.
- **Classification inputs get richer.** Today classification comes from the
  environment policy. If agents or versions gain first-class data-classification
  labels, the resolver's precedence and the conservative-default trigger should
  consume them.
- **A Telemetry Policy admin UI is built (4.9).** Confirm the effective-mode
  explanation is enough to render "why is this scope METADATA_ONLY" without a
  second API.
- **Retention needs to expire domain content** (a true right-to-erasure
  requirement reaching `execution_messages`). That is a domain-truth deletion
  with its own consistency and audit implications — a new phase and a new ADR,
  not an extension of this sweep.
