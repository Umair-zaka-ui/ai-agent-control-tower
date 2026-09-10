"""Phase 5.5 (M5.5) - Security Posture & Shadow Findings.

A sibling package (not a child of ``app.runtime`` / ``app.graph``). It turns
the evidence 5.1-5.4 produced -- the canonical asset model, discovery, the
authority graph, the dependency / blast-radius graph -- plus credentials,
governance policies and SLOs, into **deterministic, explainable posture
findings**.

The three sentences that govern every module here:

  * **No opaque score.** Every finding is a structured record -- rule /
    control, evidence rows, affected asset, severity, reason, first/last-seen,
    remediation, status, governing policy. Any aggregate
    (``app.posture.summary``) is a **deterministic, versioned** function of
    the open findings: a CISO can see exactly which findings drove the number
    and why it moved. No ML (AST-asserted, the Phase 4.5 proof).

  * **Shadow is a derived finding-state, not a boolean.** An agent is
    "shadow" *because* specific shadow-class rules fired -- ``app.posture.shadow``
    is a query over ``posture_findings.rule_id``, never a column on ``agents``.
    Each shadow classification names its condition and is disputable.

  * **Findings are signals -- 5.5 does not enforce.** The 4.3 governance
    engine + kill switch remain the sole enforcers (5.6 wires threat findings
    to those authorities). ``app/posture`` contains no enforcement vocabulary
    -- AST-proven, the containment-by-absence Phases 4.4 / 4.5 shipped.

It **reuses** the finding engine the platform already proved three times
(3.5 health -> 4.5 behavioral -> 4.7 SLO/alert): the 4.5 deterministic
evaluation shape (veto -> sufficiency -> rule; ``INSUFFICIENT_DATA``
first-class) and the 4.7 finding lifecycle (OPEN/ACKNOWLEDGED/RESOLVED/
SUPPRESSED, DB-enforced dedup, reopen-on-recurrence -- ``app.slo.states`` is
imported, not re-spelled). It is a **new table** (``posture_findings``) for
the same reason 4.5/4.7 chose new tables -- what the table is *about* differs
(ADR-0019).

Modules:
  * ``rules.py``     - the deterministic rule catalog + ``PostureContext``
                       (one batch of evidence per agent) + the pure rule
                       functions.
  * ``evaluator.py`` - ``PostureEvaluator`` -- runs the enabled rules for an
                       agent (or a whole tenant), idempotent, 3.8-schedulable.
  * ``lifecycle.py`` - ``PostureFindingService`` -- the create-or-reopen
                       primitive + operator transitions (mirrors
                       ``app.slo.alerts.AlertService``).
  * ``settings.py``  - ``PostureRuleSettingService`` -- per-tenant enable /
                       disable / param override, versioned + audited.
  * ``summary.py``   - ``PostureSummaryService`` -- the deterministic,
                       reconstructable posture score + breakdown.
  * ``shadow.py``    - the "shadow agents" query.
  * ``schemas.py`` / ``routes.py`` - the read + finding-lifecycle surface.

No runtime threat detection (5.6), no containment / enforcement (5.6), no
external gateway (5.7), no UI (5.8), no compliance mapping (5.9).
"""
