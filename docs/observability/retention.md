# Telemetry retention & expiration

> **Phase 4.8 (ACT-SRS-M4 §24, §4.8; Gate F).** Every telemetry class expires on
> its own schedule. Detailed content payloads are kept briefly; financial and
> governance/audit evidence outlives them. Expiration removes **telemetry** — it
> never touches domain truth.

## The six classes

| Class | What expires | Deletes? | Default | Floor |
|---|---|---|---|---|
| `trace_content` | `trace_content` rows (the governed content copy) | yes | 30 d | 1 d |
| `trace_metadata` | `runtime_events` rows (the derived telemetry stream) | yes | 90 d | 7 d |
| `metrics_aggregate` | `slo_evaluations` rows (stored windowed aggregates) | yes | 90 d | 7 d |
| `alert_history` | `runtime_alerts` in `RESOLVED` / `SUPPRESSED` | yes | 365 d | 30 d |
| `governance_decision` | `runtime_governance_decisions` | **no — retain-only** | 2555 d | 365 d |
| `financial_record` | cost / budget ledgers | **no — retain-only** | 2555 d | 365 d |

**Retain-only classes are configurable but never deleted.** A tenant may
*document* a minimum for `governance_decision` / `financial_record` (with a
one-year floor), but the sweep treats them as retain-only — financial and
governance evidence outlives every detailed payload (§24, M4-4.8-FR-031). The
sweep's deletable targets are all **telemetry** tables; it never names an
`agent_executions`, `authorization_audit`, or other domain-truth row in a
`delete()`.

## Two lifetimes: telemetry vs domain truth

An execution row's *existence* and its *captured content* are different facts
with different lifetimes (M4-4.8-FR-032):

```
agent_executions          <- domain truth. Never expired by this phase.
  execution_messages      <- domain truth (the tool loop feeds it back). Never expired here.
  trace_content           <- telemetry copy. Expires on the trace_content schedule.
runtime_events            <- derived telemetry. Expires on the trace_metadata schedule.
```

A `trace_content` purge removes the governed content copy while the
`agent_executions` row and its `execution_messages` transcript remain — proven
directly by `test_ac08_expired_content_is_purged_execution_row_survives`.

## The sweep

`POST /api/v1/runtime/telemetry/retention/run` (`runtime.telemetry_policy.manage`,
`Idempotency-Key`-aware) runs one expiration cycle for the tenant.

- **Bounded.** Each class is swept in batches of 1,000 rows, committed between
  batches (no lock held across a large purge), capped at 50 batches per class
  per run. A run that hits the cap reports `truncated: true`; the next run
  continues where it stopped.
- **Idempotent.** A re-run after everything expired deletes nothing
  (`total_deleted: 0`). This is what makes the op safe for **Phase 3.8's
  scheduler** to drive on a timer — the same interim pattern 4.5, 4.7, 3.7 and
  3.5 built. **No scheduler is built here.**
- **Non-gating and best-effort.** One class failing to sweep rolls back and does
  not block the others; nothing here can affect an execution (§9).
- **Audited when it deletes.** A run that removed rows emits
  `RUNTIME_TELEMETRY_RETENTION_RUN` with the per-class counts. An empty run is
  not audited — it is a telemetry-plane fact, not an administrative change.

## Configuration

| Method | Path | Permission |
|---|---|---|
| `GET` | `/api/v1/runtime/telemetry/retention-policies` | `runtime.telemetry_policy.view` |
| `POST` | `/api/v1/runtime/telemetry/retention-policies` | `runtime.telemetry_policy.manage` |
| `POST` | `/api/v1/runtime/telemetry/retention/run` | `runtime.telemetry_policy.manage` |

`GET` returns the **effective** retention for every class — the tenant's row if
set, otherwise the platform default — with each class's floor and whether it is
retain-only. `POST` upserts one class; a value below the floor is
`RETENTION_POLICY_INVALID` (422).

## Restart behaviour

Capture and retention policies are durable rows. A restart does not reset a
policy or resurrect purged content — see [`../../RECOVERY.md`](../../RECOVERY.md).
