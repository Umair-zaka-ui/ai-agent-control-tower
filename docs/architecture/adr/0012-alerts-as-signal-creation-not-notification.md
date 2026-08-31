# ADR-0012 — An alert is a durable signal; creation is not notification

- **Status:** Accepted
- **Date:** 2026-08-31
- **Deciders:** Phase 4.7 (Milestone 4 — Runtime Governance & Observability)
- **Supersedes:** —
- **Relates to:** ADR-0006 (deterministic governance), ADR-0008 (telemetry is
  derived and non-gating), ADR-0011 (export is fail-open)

## Context

Phase 4.7 adds two things: SLOs (an SLI, a target, a window, an error budget)
and a first-class alert lifecycle. Both are straightforward to build wrong, and
the wrong versions are the ones everyone expects.

The forces:

1. **"Alerts" means "paging" to most people.** The word carries an expectation
   of Slack messages, emails, PagerDuty escalation, on-call rotations. A
   reviewer seeing an `alerts` table will ask where the webhook is.

2. **Delivery is a whole product.** A notification system needs delivery
   guarantees, retry with backoff, deduplication windows, rate limits, quiet
   hours, escalation policies, per-recipient routing, and an audit of what was
   sent to whom. Each of those is a subsystem. Bolting the first one on ("just
   a webhook while we're here") commits the platform to all of them, because
   the moment one notification is missed, the missing retry logic is a bug.

3. **4.5 already built findings.** `behavioral_findings` is a shipped,
   first-class, self-explaining table with its own dedup key and its own
   consumers. An alert lifecycle that introduced a second "finding" concept
   would have two overlapping records for the same event, and a stage where
   they disagree.

4. **The SRS is explicit.** §4.7: *"build the signal, not the notification
   platform … alert creation and external notification are separate
   concepts."* §18: *"not every finding is an alert, and not every alert is an
   incident … build the minimum coherent model."*

5. **Everything reliability-adjacent on this platform is a signal, not an
   enforcer.** Telemetry is non-gating (ADR-0008). Behavioral findings are
   signals; 4.3 enforces (Milestone 4 ruling #11). Budgets supply a constraint;
   4.3 stops (ruling #9). An SLO breach must fit that pattern or it breaks it.

## Options considered

### Decision A — the finding/alert model

#### Option A1 — one shared `runtime_findings` table with a `source` discriminator

Re-home `behavioral_findings` into a generic table; SLO evaluations and
behavioral signals become rows in it; the lifecycle columns live there too.

- Pros: one table, one query for "everything wrong right now".
- Cons: re-homing a shipped table (4.5) for a phase that is supposed to
  *consume* it. A discriminator column that is null on half the rows
  (`rollout_plan_id` on SLO rows, `signal_type` on SLO rows, `sli` on
  behavioral rows). Every existing `behavioral_findings` consumer has to learn
  the new shape. The lifecycle mixed into the evidence means a re-evaluation
  that produces the same finding has to decide whether to touch the lifecycle
  columns.

#### Option A2 — a distinct `runtime_alerts` table that references its evidence

Evidence stays where it is (`behavioral_findings`, `slo_evaluations`). An alert
is a separate row with `source` + `source_id` pointing at the evidence, plus
the lifecycle (status, severity, dedup, timestamps).

- Pros: 4.5's table is untouched and keeps working. Each evidence type stays
  honest about its own shape. The lifecycle is one concept in one place. An
  alert can outlive a cascade of either evidence table because `context` JSONB
  carries a self-contained copy of the explanation. One lifecycle, two evidence
  sources — which is exactly what §18 asks for.
- Cons: "what is wrong right now" is two queries (findings + alerts) or a join.
  A soft pointer (`source_id` is not an FK) instead of referential integrity.

### Decision B — delivery

#### Option B1 — ship a minimal notifier (one webhook, or reuse the email service)

- Pros: an operator gets pinged today.
- Cons: force (2). The platform now owes delivery semantics it did not build.
  The §4.7 line is crossed on day one, and un-crossing it later means
  deprecating a feature people came to rely on.

#### Option B2 — build only the record; deliver nothing

- Pros: the alert record is a stable contract a future integration (4.9's
  operator center, a Slack app, a PagerDuty bridge) reads without this phase
  having guessed its delivery needs. The restraint is enforceable: a test walks
  the AST of `app/slo` and fails on any delivery client.
- Cons: nobody is paged by this phase. An operator has to poll
  `GET /api/v1/runtime/alerts` or wait for 4.9's UI.

### Decision C — enforcement

Never seriously in play: an SLO breach that stopped executions would be an
enforcer, and 4.3 is the only enforcer (ruling #3). `app/slo` imports no
governance engine and no kill switch, asserted over the AST.

## Decision

**A2, B2, C = signal-only.**

- **`runtime_alerts` is a distinct lifecycle table** that references
  `behavioral_findings` / `slo_evaluations` by `(source, source_id)`. One
  lifecycle, two evidence sources. 4.5's table is unchanged.

- **No delivery mechanism is built.** `app/slo` imports no `requests`, `httpx`,
  `smtplib`, `slack`, `pagerduty`, `boto3`, `app.email`, or notification
  service, and defines no method named `send` / `notify` / `deliver` / `page`.
  Two AST tests enforce it. The alert record is the product; 4.9 and future
  integrations consume it.

- **A breach / alert is a signal, never enforcement.** No execution-state
  mutation, no kill switch, no governance call anywhere in `app/slo`.
  Emitting is non-gating: `app/runtime` and `app/workers` import nothing from
  `app.slo` (there is no code path from an execution to an alert).

- **Escalation is explicit and threshold-defined (§18).** An SLO evaluation
  becomes an alert only when `BREACHED`; a behavioral finding only when its
  state is `ANOMALOUS` (a named constant), never merely `DEGRADED`. A
  `DEGRADED` finding stays a finding. There is no "incident" concept — the model
  is a first-class finding/alert with a lifecycle, and nothing more.

- **SLO evaluation reuses the 3.5 / 4.5 shape** (ADR-0006's deterministic line):
  veto → sufficiency → objective → budget, `INSUFFICIENT_DATA` first-class, an
  explanation an operator can recompute by hand. No model, no scoring. The
  shared state values (`INSUFFICIENT_DATA`, `UNKNOWN`) are spelled exactly as
  3.5 and 4.5 spell them, asserted against the live modules.

- **One ongoing condition is one active alert**, enforced by a partial unique
  index (`WHERE status IN ('OPEN','ACKNOWLEDGED')`), the same primitive 3.7
  used. A RESOLVED alert re-opens on recurrence; a SUPPRESSED one does not.

## Consequences

### Positive

- The §4.7 line holds and is *enforceable* — a future "just a webhook" PR fails
  a test, not a code review.
- 4.5's `behavioral_findings` keeps working untouched; the alert lifecycle is a
  thin layer over it.
- The alert record is a clean contract for 4.9 and any notification integration
  to build on, with none of this phase's assumptions baked into a delivery path.
- A breach cannot corrupt or halt runtime truth — same guarantee ADR-0008 gave
  telemetry and ADR-0011 gave export.
- The dedup race is decided by the database, so it is correct under concurrent
  evaluation and not just in a single-threaded test.

### Negative / accepted cost

- **Nobody is paged by this phase.** An operator polls `GET .../alerts` or waits
  for 4.9. That is the deliberate trade — the alternative is owning delivery
  semantics now.
- **"Everything wrong right now" is not one query.** Findings and alerts are two
  tables; a consumer joins or queries both.
- **`source_id` is a soft pointer, not an FK.** An alert can reference a
  `behavioral_findings` row that a later cascade removes; the `context` JSONB
  copy is the mitigation, and it means the explanation is duplicated once (at
  raise time) on purpose.
- **Auto-resolve is a small piece of cleverness.** When a later evaluation
  reports `MET`, the system resolves the alert with no actor. If an operator
  disagrees (the objective is met but the underlying cause is not understood),
  they have to re-open by letting it recur or accept the auto-resolution. This
  is bounded — auto-resolve only touches `OPEN`/`ACKNOWLEDGED` alerts, never
  `SUPPRESSED`.

### Residual risk

- The signal-only boundary erodes the same way ADR-0011's does: not by someone
  adding a notifier on purpose, but by a "quick" `import requests` in the alert
  path to hit one internal endpoint. The AST tests are the guard and must not
  be `# noqa`'d.
- `_SIGNIFICANT_FINDING_STATE = "ANOMALOUS"` is the entire escalation policy for
  behavioral findings. If a future phase wants per-signal or per-tenant
  significance thresholds, that is a real feature with its own config surface —
  it should not be hacked in by widening the constant to a set.
- Auto-resolve depends on the evaluate op actually running. If the 3.8 scheduler
  never adopts it, alerts raised by a one-off manual evaluation will not
  auto-resolve and will accumulate as stale `OPEN` rows. 4.9's UI should surface
  "last evaluated" prominently so a stale queue is visible.

## Revisit when

- **A notification integration is actually built** (a Slack app, a PagerDuty
  bridge, 4.9's in-app notifications). That phase consumes `runtime_alerts` and
  owns delivery; this ADR should be referenced, not reopened, unless the record
  shape proves insufficient.
- **Per-signal or per-tenant significance thresholds are needed.** The single
  `ANOMALOUS` constant becomes a config surface — a new feature, a new ADR.
- **An "incident" concept is genuinely needed** (correlating several alerts into
  one operator-facing event, a post-mortem record). §18 explicitly deferred it;
  a phase that adds it should show why the flat alert model stopped being
  enough.
- **3.8's scheduler adopts the evaluate op.** Confirm the idempotency
  (`uq_slo_evaluations_window` + the partial dedup index) holds under the
  scheduler's overlap/retry behavior, and that auto-resolve does not thrash an
  alert that is flapping around its target.
