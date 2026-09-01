# The Enterprise Runtime Governance & Observability Center

> **Phase 4.9 (ACT-SRS-M4 §4.9, §28, §29; Gate M).** The operator-facing control
> plane where all of Milestone 4 becomes visible. The M4 analogue of M3's
> Release Operations Center (3.10), and built to the same rule: **read +
> trigger only, server authoritative, truthful state, dangerous actions
> confirmation-gated.** It adds no domain logic — it assembles and triggers
> what 4.1–4.8 already enforce.

## The nine views

| View | Route | Feeds from | Actions |
|---|---|---|---|
| **Runtime Overview** | `/observability` | `GET /api/v1/runtime/overview` (4.9 read model) + `GET /api/v1/observability/export/health` (4.6, for the exporter tile) | — |
| **Trace Explorer** | `/observability/traces` | `GET /api/v1/observability/traces` (4.2) | — |
| **Trace Detail** | `/observability/traces/:executionId` | `GET /api/v1/observability/executions/{id}/trace` (4.2 metadata) + `GET /api/v1/observability/traces/{trace_id}/content` (4.8, **content**) | — |
| **Cost Center** | `/observability/cost` | `GET /api/v1/cost/summary`, `/api/v1/budgets`, `/api/v1/budgets/{id}/utilization` (4.4) | — |
| **Governance Decisions** | `/observability/governance` | `GET /api/v1/runtime/governance/decisions` (4.9 read model over 4.3) | — |
| **Behavior & Anomalies** | `/observability/behavior` | `GET /api/v1/runtime/behavior/findings` (4.5) | — |
| **SLO Dashboard** | `/observability/slos` | `GET /api/v1/runtime/slos`, `/slos/{id}/evaluations` (4.7) | — |
| **Alert Center** | `/observability/alerts` | `GET /api/v1/runtime/alerts` (4.7) | ack / resolve / **suppress** (guarded) |
| **Telemetry Policy** | `/observability/policy` | `GET /api/v1/runtime/telemetry/capture-policies`, `/retention-policies`, `/effective-mode` (4.8) | create/delete capture policy (guarded on content modes), **run retention** (guarded) |

### The two new read-model endpoints

Every other view is fed by an endpoint 4.1–4.8 already exposes. Two were
genuinely missing:

- **`GET /api/v1/runtime/overview`** (`runtime.telemetry.view`) — the fleet
  composite: execution volume and success rate over 24h (`INSUFFICIENT_DATA`
  below the 20-sample floor, never rendered as 0%), spend today (flagged if any
  row is estimated), open alerts by severity, worker health, SLO breach count,
  recent behavioural anomalies, and the org's effective capture mode. One
  request instead of seven. **Exporter health is deliberately not in this
  composite** — it belongs to the 4.6 OpenTelemetry export plane that
  `app/runtime` never imports (a 4.6 structural test enforces this); the Runtime
  Overview screen fetches it from `GET /api/v1/observability/export/health`
  directly.
- **`GET /api/v1/runtime/governance/decisions`** (`runtime.execution.view`) — a
  tenant-wide, filterable governance-decision list. Phase 4.3 exposed the
  lineage only *per execution*; there was no way to answer "show me every STOP
  this week". `reason` is a platform-templated sentence (a ceiling, a tool
  name, a model name), never a prompt or model output.

Both live in `app/runtime/observability_center.py`, which is **read-only by
construction** — a test walks its AST and fails on any `add` / `commit` /
`delete` / `flush`. Neither computes domain state.

## Per-persona assembly (§29)

The center is not one dashboard. A **persona lens** narrows the visible views to
what a role needs:

| Persona | Views |
|---|---|
| Platform Engineer | Overview, Trace Explorer, Trace Detail, Governance, Behavior, Alerts |
| SRE / Ops | Overview, Trace Explorer, Behavior, SLOs, Alerts |
| Security / CISO | Overview, Trace Explorer, Governance, Behavior, Alerts |
| Governance Officer | Overview, Governance, Telemetry Policy |
| FinOps | Overview, Cost Center |
| Engineering Management | Overview, Cost Center, Behavior, SLOs |
| CIO / CTO | Overview, Cost Center, SLOs |

**The lens never grants access.** Each view also carries the permission its data
needs; a link the user cannot use is hidden as courtesy, and the server
re-authorizes every endpoint regardless (§3.3). The selected persona is a
per-browser convenience stored in `localStorage`, defaulting to "All views".

## Content governance — inherited from 4.8, in full

The Trace Detail **content pane** is the one place this center renders content,
and it honours 4.8 completely:

1. **Distinct permission.** Content is shown only to holders of
   `runtime.trace.content.view`. A metadata-only operator sees the timeline and
   a truthful gated message — *"Content view requires an additional permission …
   separate from and stronger than the metadata view"* — never the content, and
   never a misleading error. The client does not even issue the request in that
   case, so nothing is audited for an access that did not happen.
2. **One route, audited.** When an authorised operator clicks **View content**,
   the pane calls `GET /api/v1/observability/traces/{trace_id}/content` — 4.8's
   endpoint, which emits `RUNTIME_TRACE_CONTENT_VIEWED` on every call. There is
   no other route to content in `observabilityService`; a test asserts exactly
   one `apiClient` call ends in `/content` and it is that endpoint. Content is
   never fetched on page load — only on explicit request.
3. **Capture mode is truthful.**
   - `METADATA_ONLY` → *"no execution content was captured. This is the policy
     working, not an error."*
   - `DISABLED` → *"Telemetry is DISABLED for this scope — no content, and no
     telemetry event, was recorded."*
   - `REDACTED_CONTENT` → the masked items, each flagged `redacted`.
   - `FULL_CONTENT` → the scrubbed items, flagged `secret scrubbed` where a
     secret was removed.
4. **404 vs 403 honoured.** A `404` from the endpoint renders *"this trace was
   not found for your organization"* (cross-tenant is indistinguishable from
   missing, by design). A `403` / `TRACE_CONTENT_ACCESS_DENIED` renders *"the
   server declined … your account does not hold `runtime.trace.content.view`"* —
   a distinct state, not a generic failure.

## Read + trigger, and truthful state

- **Every action is an existing 4.x operation.** Alert ack/resolve/suppress hit
  4.7's `POST /alerts/{id}/…`; capture-policy edits and the retention run hit
  4.8's endpoints. The server authorizes, enforces tenant isolation, honours
  `Idempotency-Key`, and writes its own audit
  (`RUNTIME_ALERT_*`, `RUNTIME_TELEMETRY_POLICY_CHANGED`,
  `RUNTIME_TELEMETRY_RETENTION_RUN`).
- **Dangerous actions are confirmation-gated** (§22, reusing 3.10's
  `ConfirmActionDialog` / `useGuardedAction`):
  - **Suppress an alert** — requires a reason (it lands in the audit); a
    suppressed alert does not re-open on recurrence.
  - **Raise capture to `REDACTED_CONTENT` / `FULL_CONTENT`** — type-to-confirm,
    with warnings that it starts persisting prompts and makes content readable
    to the content-permission holders. Setting `METADATA_ONLY` / `DISABLED` is a
    plain action.
  - **Run the retention sweep** — a deliberate confirm; it permanently deletes
    expired telemetry (never domain truth).
- **Truthful state.** A burned error budget reads *"budget spent"* in
  destructive red; `INSUFFICIENT_DATA` (SLO or behavioural) is shown as its own
  warning state, never as "met" or "normal"; a degraded exporter raises a banner
  on the Overview; a `DISABLED` capture mode is shown as such. Nothing computes
  state — every value arrives decided by the server.
- **Concurrency conflicts surface, not silently retry.** The shared
  `useGuardedAction` recognises the server's conflict codes and shows *"someone
  else changed this while you were looking at it"*, then refreshes — it never
  re-submits a stale intent.

## What this is NOT

- **Not new logic.** No runtime-governance, cost, telemetry, privacy, SLO or
  alert *decision* is made here. `app/runtime/observability_center.py` writes
  nothing; the frontend triggers only existing operations.
- **Not a content bypass.** The center adds no content route. Content flows
  exclusively through 4.8's audited endpoint.
- **Not a new authorization model.** The UI reflects permissions for UX; the
  server is the authority.
- **Not notification delivery.** The Alert Center shows the signal; nothing
  pages anyone (4.7's line, unchanged).
- **Not hardening / the milestone proof.** That is 4.10.
