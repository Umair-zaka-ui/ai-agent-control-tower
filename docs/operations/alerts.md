# The alert lifecycle

> **Phase 4.7 (ACT-SRS-M4 §4.7, §18; Gate K).** An SLO breach or a *significant*
> behavioral finding (4.5) becomes a first-class, durable, auditable alert with
> a real lifecycle — **OPEN → ACKNOWLEDGED → RESOLVED → SUPPRESSED** —
> deduplicated so one ongoing condition is one alert. It stays a signal:
> nothing delivers it anywhere.

## One lifecycle, two evidence sources (the model decision)

**`runtime_alerts` is a distinct table that *references* its evidence — it is
not a shared `runtime_findings` table, and it does not re-home 4.5's
`behavioral_findings`.**

```
behavioral_findings   slo_evaluations       <- evidence, each in its own table,
        \                   /                  each a first-class record already
         \                 /
          runtime_alerts  (source, source_id -> the evidence row)
          the lifecycle layer: status, severity, dedup, timestamps, audit
```

Why not a shared table: `behavioral_findings` (4.5) is already a first-class,
self-explaining record with its own dedup key and its own consumers; an SLO
evaluation is a different shape with a different dedup key. Merging them would
mean re-homing a shipped table and carrying a discriminator column that is null
on half the rows. Referencing is cheaper and keeps each evidence type honest
about what it is. The 4.5 model docstring already anticipated this: *"consumed
by an operator (and, in Phase 4.7, by an alert lifecycle)."*

## Not every finding is an alert; not every alert is an incident (§18)

Escalation is **explicit and threshold-defined**, never automatic:

| Evidence | Becomes an alert when |
|---|---|
| SLO evaluation | `state == BREACHED` |
| Behavioral finding | `state == ANOMALOUS` — **a `DEGRADED` finding stays a finding** |

A `DEGRADED` behavioral finding is a real signal an operator can look at in the
4.5 findings view; it is not loud enough to be an alert. The significance
threshold is a named constant (`app.slo.alerts._SIGNIFICANT_FINDING_STATE`), not
a scattered `if`.

An alert is also not automatically an "incident" — there is no incident concept
in this phase. Keep the model minimal: a first-class finding/alert with a
lifecycle, not incident + alert + rule engines too early.

## The lifecycle

```
            ┌──────────────── recurrence ────────────────┐
            ▼                                             │
   (raised) OPEN ──ack──▶ ACKNOWLEDGED ──resolve──▶ RESOLVED ──┘
     │  │                      │
     │  └──────suppress────────┴──▶ SUPPRESSED   (does NOT re-open on recurrence)
     └─────────resolve──────────────▶ RESOLVED
```

| Transition | How |
|---|---|
| → OPEN | `POST /slos/evaluate` on a breach / significant finding; or a RESOLVED alert re-opening on recurrence |
| → ACKNOWLEDGED | `POST /api/v1/runtime/alerts/{id}/acknowledge` (`runtime.alert.manage`) |
| → RESOLVED | `POST .../resolve`; or **automatically** when a later evaluation reports the objective `MET` |
| → SUPPRESSED | `POST .../suppress` — the operator has decided this condition is known/expected |

Every transition is **audited** (`RUNTIME_ALERT_CREATED` / `_ACKNOWLEDGED` /
`_RESOLVED` / `_SUPPRESSED`) with the actor, or with no actor and `meta.auto`
when a later evaluation cleared it. An illegal transition (resolving an
already-resolved alert, acknowledging a suppressed one) is
`ALERT_TRANSITION_INVALID` (409). An identical transition converges silently —
two operators acknowledging the same alert both succeed.

## Dedup — one ongoing condition is one active alert (M4-4.7-FR-013)

`dedup_key` is condition-specific:

| Source | `dedup_key` |
|---|---|
| SLO breach | `slo:<slo_id>` |
| Behavioral anomaly | `behavioral:<agent_id>:<signal_type>` |

`uq_runtime_alerts_active_dedup` is a **partial unique index** over
`(organization_id, dedup_key) WHERE status IN ('OPEN','ACKNOWLEDGED')` — the
**database** decides the race, not application timing, the same primitive Phase
3.7 used for `uq_rollback_events_dedup`. Re-evaluating an active condition bumps
`recurrence_count` and `last_seen_at` and may *raise* (never lower) severity. A
`RESOLVED` alert **re-opens** on recurrence (same row, `recurrence_count`
increments). A `SUPPRESSED` alert does **not** re-open — that is the point of
suppressing it.

Proven under a real race: eight threads on eight Postgres connections running
`POST /slos/evaluate` concurrently against one breach produce **one** evaluation
row and **one** alert.

## The §18 fields

`runtime_alerts` carries: `source`, `source_id`, `severity`
(INFO/WARNING/HIGH/CRITICAL), `status`, `slo_id`, `agent_id`,
`agent_version_id`, `environment_id`, `execution_id`, `trace_id`, `metric`,
`threshold_value`, `observed_value`, `baseline_value`, `title`, `summary`,
`dedup_key`, `context`, `recurrence_count`, and the lifecycle timestamps
(`opened_at`, `last_seen_at`, `acknowledged_at/_by`, `resolved_at/_by`,
`suppressed_at`, `updated_at`).

`summary` is a **platform-authored templated sentence** — never a prompt, a tool
argument, or a model output (§10). `GET /api/v1/runtime/alerts` filters by
`status` / `severity` / `source` / `agent_id` / `slo_id` / `opened_after`.

## Severity

Deterministic, from the evidence:

| Source | Severity |
|---|---|
| SLO breach | `budget_consumed ≥ 3.0` → CRITICAL; `≥ 1.5` → HIGH; else WARNING |
| Behavioral anomaly | HIGH (it is already the significant tier) |

## What this is NOT

- **No notification delivery.** No Slack, email, PagerDuty, webhook, or SMTP
  anywhere in the alert path — asserted by an AST walk of `app/slo` that fails
  on any delivery client (`requests`, `httpx`, `smtplib`, `slack`, …) and on any
  method named `send` / `notify` / `deliver` / `page`. The alert **record is the
  product**; a future integration reads it.
- **No enforcement.** An alert never stops or alters an execution.
- **Durable.** An open alert stays open across a restart (see `RECOVERY.md`).
