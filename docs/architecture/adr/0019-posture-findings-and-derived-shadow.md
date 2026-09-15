# ADR-0019 — Security posture is a dedicated finding table on the reused 4.7 lifecycle; shadow is a derived finding-state, never a boolean

- **Status:** Accepted
- **Date:** 2026-09-10
- **Deciders:** Phase 5.5 / M5.5 (Milestone 5 — Universal Agent Control & Security Fabric)
- **Supersedes:** —
- **Relates to:** ADR-0006 (deterministic governance — the no-LLM discipline
  extended to posture scoring), ADR-0008 (derived plane — a posture summary
  is a view over the findings, never a stored copy), ADR-0009 (governance is
  the fail-closed enforcement plane — posture is *not* a second one),
  ADR-0016 (discovery evidence vs canonical truth), ADR-0017 / ADR-0018 (the
  relational control graph + dependency graph — the evidence 5.5 reads).

## Context

Milestone 5.5 turns the evidence 5.1–5.4 produced — the canonical asset
model, discovery, the authority graph, the dependency / blast-radius graph —
plus credentials, governance policies and SLOs, into **visible security
risk**: findings like *no accountable owner*, *stale credential*, *depends on
an unapproved MCP server*, *can reach payroll*, *discovered outside the
approved lifecycle*.

Three temptations were live:

1. **A `shadow = true` boolean on `agents`.** "Is this shadow AI?" reads as a
   yes/no. But a boolean is undisputable and unexplainable — it cannot say
   *why*, and clearing it is a manual toggle rather than a consequence of the
   condition changing.
2. **An opaque / ML posture score.** "This agent is 0.87 risky" is the
   unauditable, unappealable verdict Phase 4.5 was built to replace. A CISO
   cannot act on it or defend it.
3. **Wiring findings to enforcement.** A *no-owner* finding could suspend the
   agent; an *unapproved-MCP* finding could deny the tool. That would fork the
   one-enforcement-path invariant the platform has held since M4.3.

The platform has also proved a finding engine three times (3.5 health → 4.5
behavioral → 4.7 SLO/alert). The fourth question was: reuse the 4.7
`runtime_alerts` table with a `source = 'POSTURE'` discriminator, or a
dedicated table?

## Decision

**Security posture is a deterministic rule engine over local evidence,
producing self-explaining findings in a dedicated `posture_findings` table
that reuses the 4.7 lifecycle shape. Shadow is a query over those findings.
Any score is a deterministic, versioned function of them. `app/posture`
contains no enforcement path.**

1. **A dedicated `posture_findings` table — the same call 4.5/4.7 made.**
   Phase 4.7 kept its evidence in `slo_evaluations` / `behavioral_findings`
   and pointed a shared alert lifecycle at it; Phase 4.5 chose a new table
   over a `signal_type` discriminator on `deployment_health_evaluations`
   because *what each table is about* differs. A `runtime_alerts` row is *a
   significant runtime condition worth an operator's queue* (metric,
   threshold, trace context, `source IN ('SLO','BEHAVIORAL')`). A posture
   finding is *standing risk state about an asset* — a rule id, a control id,
   evidence rows in 5.1–5.4, a remediation. Sharing would mean nullable
   columns on both halves and a discriminator standing in for two tables. So:
   a new table — but the **lifecycle shape is reused verbatim**.
   `app.slo.states` (`AlertStatus`, `ALLOWED_TRANSITIONS`,
   `ACTIVE_ALERT_STATUSES`, `max_severity`) is *imported*, not re-spelled:
   OPEN → ACKNOWLEDGED → RESOLVED → SUPPRESSED, a partial unique index
   (`uq_posture_findings_active` on `(organization_id, dedup_key) WHERE status
   IN ('OPEN','ACKNOWLEDGED')`) so one condition is one open finding,
   reopen-on-recurrence, suppression that is not resolution.

2. **The evaluation shape is Phase 4.5's.** Each rule is a **pure function of
   (asset state + graph evidence + policy)** — same evidence ⇒ same finding,
   reconstructable, no ML (`test_ac04` walks the AST and forbids the imports,
   the same proof 4.5 shipped). `INSUFFICIENT_DATA` is first-class and
   recorded explicitly: a rule that cannot evaluate (e.g.
   *dangerous-dependency* when the agent has no dependency edges) says so —
   it does **not** default to "healthy" (unknown ≠ safe, and absence ≠
   compliance).

3. **Shadow is a derived finding-state.** There is **no `shadow` column**
   anywhere (`test_ac05` asserts it structurally). An agent is shadow **iff**
   it has an open finding whose `rule_id` is in
   `app.posture.rules.SHADOW_RULE_IDS` (`discovered_outside_lifecycle`,
   `unmanaged_external_agent`, `unowned_with_production_access`,
   `production_activity_without_governance`). `GET /posture/shadow-agents` is
   that query; each condition names itself, carries its evidence, is
   disputable, and clears when its finding resolves or the condition stops
   holding on the next evaluation.

4. **No opaque score.** `PostureSummaryService` returns a number that is a
   fixed weighted sum of the open findings by severity —
   `score = Σ (severity_weight × open_finding_count)` — and the response
   carries the formula, the weights, the ruleset version and the per-rule
   contributions. Two summaries diffed show *exactly* which findings moved
   the number. Nothing is stored: the summary is recomputed from
   `posture_findings` every call (ADR-0008). A threshold change goes through
   `posture_rule_settings` with a monotonic `revision` and an audit event, so
   it is versioned and explainable.

5. **Findings are signals — 5.5 does not enforce.** `app/posture` names no
   `KillSwitchService`, no `RuntimeGovernanceEngine`, no execution-status
   mutation (`test_ac07`, the containment-by-absence proof 4.4 / 4.5 shipped).
   The 4.3 engine + kill switch remain the sole enforcers; Phase 5.6 wires
   *threat* findings to them.

6. **Idempotent, 3.8-schedulable, fails open.** `PostureEvaluator` is a
   registered `posture.evaluate` scheduler handler — no new scheduler. A rule
   that raises is caught: the sweep produces no finding for it, fabricates
   nothing, blocks nothing.

## Consequences

### Positive
- Every "this agent is high-risk" comes with the rules it broke, the evidence
  rows behind them, and the remediation — actionable and defensible.
- Shadow AI is a disputable, self-clearing finding-state, not a flag someone
  forgets to unset.
- The posture score is reconstructable by hand; a CISO can answer "why did it
  move" from the diff of two summaries.
- The finding lifecycle is the one the platform has run three times — one
  set of transition semantics, one dedup primitive, one audit shape.
- The one-enforcement-path invariant holds: posture is a fourth *derived*
  plane, not a second enforcement plane.

### Negative / accepted cost
- `posture_findings` is a new table. Justified by the 4.5/4.7 precedent — a
  discriminator on `runtime_alerts` would carry nullable columns for two
  unrelated shapes.
- `posture_rule_settings` is a second new table. It is the versioned
  tenant-override layer the score-reconstructability requirement needs; the
  rules themselves stay code (`app.posture.rules`, `POSTURE_RULESET_VERSION`).
- Some SRS-named rules are **not** delivered because the evidence does not
  support them: "excessive privilege" as an RBAC concept (an agent holds no
  role assignments) and "excessive delegated authority" (5.3 delegation edges
  are human↔human). The privilege-scope concern is covered instead by
  `excessive_tool_scope` and `unapproved_tool`; the gap is recorded in
  `docs/posture/rules.md` rather than fabricated.

### Residual risk
- A rule's threshold is operator-tunable. A mis-tuned threshold could hide a
  real finding; the audit trail (`POSTURE_RULE_SETTING_CHANGED`, prev → new,
  revision) and the summary's `governing_policy` block are the backstop.
- `INSUFFICIENT_DATA` depends on a rule correctly recognising its own missing
  evidence. Each such branch is unit-tested; a rule that silently assumed
  evidence would be a bug, not a design gap.

## Revisit when

- **Phase 5.6 adds runtime threat detection + containment** — confirm a
  threat is a runtime *event* (distinct from standing posture), and that 5.6
  is the layer that wires findings to the 4.3 engine / kill switch. `app/posture`
  must still have no enforcement path.
- ~~**Phase 5.9 maps posture to compliance frameworks**~~ — **Settled by
  [ADR-0022](0022-assurance-evidence-not-verdict.md) (2026-09-16).** `control_id`
  was exactly what the mapping needed: 5.9's assurance controls read a rule's
  `control_id` and its open findings, and 5.5 still only *produces* findings.
  One thing this line did not anticipate: absence of findings cannot be read as
  a pass, because it is indistinguishable from "posture never ran". 5.9
  therefore checks the `POSTURE_EVALUATED` audit event before reading findings
  at all, and reports INSUFFICIENT_EVIDENCE when no evaluation is on record.
- **A posture score needs trend history** — add a snapshot table as its own
  ADR (still deterministic and reconstructable; the live summary stays the
  source of truth).
- **The rule set needs per-rule scheduling / partial evaluation** — today
  `posture.evaluate` sweeps the whole tenant; revisit if that gets expensive
  at scale (it is bounded per agent by the dependency-graph traversal, which
  ADR-0018 benchmarked).
