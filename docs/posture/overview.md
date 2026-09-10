# Security Posture & Shadow Findings (Phase 5.5 / M5.5)

Phase 5.5 turns the evidence 5.1–5.4 produced — the canonical asset model,
discovery, the authority graph, the dependency / blast-radius graph — plus
credentials, governance policies and SLOs, into **deterministic, explainable
posture findings**. See
[ADR-0019](../architecture/adr/0019-posture-findings-and-derived-shadow.md)
for the design reasoning.

## Three disciplines

### No opaque score

Every finding is a structured record: `rule_id`, `control_id`, `severity`,
`reason`, `remediation`, `evidence` (rows in 5.1–5.4), `status`,
`first_seen_at` / `last_seen_at`, `governing_policy`. Never a free-text
verdict.

`GET /api/v1/posture/summary` returns a number that is a **fixed weighted
sum** of the open findings by severity:

```
score = Σ (severity_weight × open_finding_count)   over open FINDING findings
severity_weight = {CRITICAL: 10, HIGH: 5, WARNING: 2, INFO: 1}
```

The response carries the formula, the weights, the `ruleset_version` and the
per-rule contributions — so a CISO can recompute it by hand and, diffing two
summaries, see exactly which findings moved it. `INSUFFICIENT_DATA` and
resolved/suppressed findings are excluded by construction. Nothing is stored;
the summary is recomputed from `posture_findings` every call (ADR-0008). No
ML — `test_ac04` walks the AST and forbids the imports.

### Shadow is a derived finding-state, not a boolean

There is **no `shadow` column** anywhere. An agent is shadow **iff** it has
an open finding whose `rule_id` is a shadow-class rule
(`discovered_outside_lifecycle`, `unmanaged_external_agent`,
`unowned_with_production_access`, `production_activity_without_governance`).
`GET /api/v1/posture/shadow-agents` is that query. Each condition names
itself, carries its evidence, is disputable, and clears when its finding
resolves or the condition stops holding.

### Findings are signals — 5.5 does not enforce

A posture finding surfaces risk. It does not stop an execution, deny a tool
or suspend an agent. The 4.3 governance engine + kill switch remain the sole
enforcers (Phase 5.6 wires *threat* findings to them). `app/posture` names no
`KillSwitchService`, no `RuntimeGovernanceEngine`, no execution-status
mutation — `test_ac07`, the containment-by-absence proof 4.4 / 4.5 shipped.

## The engine

`PostureEvaluator` (`app/posture/evaluator.py`) runs the
[deterministic rule catalog](./rules.md) for one agent
(`POST /posture/agents/{id}/evaluate`) or the whole tenant
(`POST /posture/evaluate`, and the `posture.evaluate` scheduler handler — no
new scheduler). It is **idempotent**: a re-run over unchanged evidence opens
nothing new (the DB-enforced dedup key does the work; a still-true condition
bumps `recurrence_count`). Per rule, after it runs, any open finding the rule
did not re-assert is auto-resolved.

**Fails open.** A rule that raises is caught: the sweep produces no finding
for it, fabricates nothing, blocks nothing (`rule_errors` is reported).

## The finding lifecycle (reused from Phase 4.7)

`posture_findings` is a dedicated table (the 4.5 / 4.7 "new table, not a
discriminator" call) that reuses the 4.7 lifecycle **shape** verbatim —
`app.slo.states` is imported, not re-spelled:

- `OPEN → ACKNOWLEDGED → RESOLVED → SUPPRESSED`, and `RESOLVED → OPEN` on
  recurrence.
- One open finding per condition: the partial unique index
  `uq_posture_findings_active` on `(organization_id, dedup_key) WHERE status
  IN ('OPEN','ACKNOWLEDGED')` makes the database decide the race.
- A `RESOLVED` finding **re-opens** on recurrence (`recurrence_count`
  increments). A `SUPPRESSED` one does **not** — that is the point of
  suppressing it. Suppression is permission-gated (`posture.manage`) and
  audited; it is not resolution.

`INSUFFICIENT_DATA` outcomes are recorded as findings with
`outcome = 'INSUFFICIENT_DATA'`, severity `INFO`, and are excluded from the
score — they are the explicit "we could not tell" that stops a missing
signal from reading as compliance.

## API

| Route | Permission | |
| --- | --- | --- |
| `GET /posture/findings` | `posture.view` | filterable (status, severity, rule, subject, outcome, shadow) |
| `GET /posture/findings/{id}` | `posture.view` | |
| `POST /posture/findings/{id}/acknowledge` `/resolve` `/suppress` | `posture.manage` | audited lifecycle transitions |
| `GET /posture/agents/{id}/findings` | `posture.view` | |
| `POST /posture/agents/{id}/evaluate` | `posture.manage` | one agent |
| `POST /posture/evaluate` | `posture.manage` | whole tenant |
| `GET /posture/shadow-agents` | `posture.view` | the derived shadow view |
| `GET /posture/agents/{id}/shadow` | `posture.view` | |
| `GET /posture/summary` | `posture.view` | the deterministic score |
| `GET /posture/rules` | `posture.view` | catalog + effective settings |
| `PUT /posture/rules/{rule_id}` | `posture.manage` | versioned + audited tuning |

Tenant-isolated throughout; graph-traversing rules (`dangerous_dependency`)
inherit the 5.3 / 5.4 per-hop tenant bound; a cross-tenant finding read is
404. No secret ever appears in a finding — a credential finding references
the `agent_api_keys` row, never the hash.
