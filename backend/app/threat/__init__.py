"""Phase 5.6 (M5.6) - Runtime Threat Detection & Containment.

A sibling package (not a child of ``app.runtime`` / ``app.graph`` /
``app.posture``). It gives the milestone its teeth, **truthfully.**

The four sentences that govern every module here:

  * **Threat is a runtime event, distinct from Phase 5.5's standing posture.**
    An agent depending on an unapproved MCP server is posture; the agent
    *actually invoking* a tool that server exposes, right now, is a threat.
    ``app.threat.rules`` correlates M4 runtime signals (behavioral findings,
    governance decisions, tool calls) plus 5.4/5.5 evidence, deterministically,
    over a lookback window.

  * **Containment routes ONLY to existing enforcement authorities.**
    ``app.threat.containment.ContainmentOrchestrator`` implements no
    enforcement of its own (AST-proven) — every action *calls*
    ``KillSwitchService``, ``ToolRegistryService``, ``CapabilityService``,
    ``ConnectorService``, ``GovernancePolicyService``, or
    ``api_key_service.revoke_key``. There is no eighth action and no second
    enforcer.

  * **Truthful containment is structural.** Capability derives from exactly
    one signal, ``agents.control_state`` (``GOVERNED`` = ACT actually
    executes/enforces this agent). For any other state, every
    enforcement-requiring action is refused with a real reason
    (``status='REFUSED'``) — never a fake success.

  * **Kill-switch dominance is absolute.** Nothing in this package sets
    ``lifecycle_status`` back to ``'ACTIVE'`` or ``cancel_requested`` back to
    ``False`` (AST-proven). Automation is subordinate to a human kill, always.

It **reuses**: the 4.5/4.7 finding-lifecycle shape (``app.slo.states``,
mirroring ``app.posture``'s own reuse — ADR-0019, extended by ADR-0020), the
Phase 3.8 automation principal (``app.scheduler.principal``) for automated
containment's actor, and every enforcement authority M1-M4.9 already built.
No new enforcer, no new alert engine, no new scheduler, no new registry.

Modules:
  * ``rules.py``       - the deterministic threat-rule catalog + ``ThreatContext``.
  * ``lifecycle.py``   - ``ThreatFindingService`` (the 4.7 lifecycle, applied
                         to runtime-event findings).
  * ``evaluator.py``   - ``ThreatEvaluator`` — runs the rules, idempotent,
                         3.8-schedulable, fails open; recommends (never
                         executes) containment for HIGH/CRITICAL findings.
  * ``containment.py`` - ``ContainmentOrchestrator`` — the action -> authority
                         router; truthful capability; confirmation-gated;
                         reversible where the authority itself supports it.
  * ``schemas.py`` / ``routes.py`` - the read + finding-lifecycle +
                         containment-execute surface.

No external gateway (5.7), no UI (5.8), no compliance mapping (5.9), no
unbounded autonomous remediation.
"""
