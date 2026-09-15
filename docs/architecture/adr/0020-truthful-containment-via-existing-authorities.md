# ADR-0020 — Containment orchestrates the existing enforcement authorities; capability is truthfully derived from control_state, never assumed

- **Status:** Accepted
- **Date:** 2026-09-14
- **Deciders:** Phase 5.6 / M5.6 (Milestone 5 — Universal Agent Control & Security Fabric)
- **Supersedes:** —
- **Relates to:** ADR-0009 (runtime governance is a fail-closed plane,
  evaluated on one enforcement path — this ADR extends that path to
  containment, never forks it), ADR-0015 (control_state — the truthful-
  containment signal), ADR-0019 (posture findings + the reused 4.7 lifecycle
  — this ADR's ``threat_findings`` makes the identical choice for a runtime
  event instead of a standing state).

## Context

5.5 made risk *visible*: posture findings, signals only, no enforcement.
Milestone 5.6 gives the milestone its **teeth** — deterministic runtime
**threat detection** over M4's runtime signals (behavioral findings,
governance decisions, tool calls) plus 5.4/5.5 evidence, and **containment**
that can actually stop something.

This is the highest-risk phase in the milestone because it touches the
enforcement path M4.3 built and M4.4/M4.5 proved has exactly one instance.
Two temptations were live:

1. **A second enforcer.** "Containment" sounds like it needs its own
   suspend/deny/terminate logic — a natural but wrong instinct, since the
   platform already has exactly one execution-stopping engine
   (`RuntimeGovernanceEngine`) and exactly one suspend authority
   (`KillSwitchService`), each already proven (AST + behavioral tests) to be
   the *only* thing that can do what it does.
2. **A claimed capability the platform doesn't have.** ACT can *observe* an
   externally-discovered agent (Phase 5.1/5.2) long before it can *enforce*
   anything against it. A containment UI or API that offers "suspend this
   agent" identically for a `GOVERNED` agent and a `DISCOVERED` one would be
   lying about the second case — and a security product that fakes control
   is worse than one that admits a gap.

## Decision

**Containment is orchestration, not enforcement.** `app.threat.containment
.ContainmentOrchestrator` maps one of seven containment actions to exactly
one existing enforcement authority, invokes it through its real interface,
and records the outcome. It implements no enforcement of its own.

1. **The action → authority map is exhaustive and fixed.**

   | Action | Authority | Real call |
   | --- | --- | --- |
   | `TERMINATE_EXECUTION` | `KILL_SWITCH` | `KillSwitchService`, scope `EXECUTION` |
   | `SUSPEND_AGENT` | `KILL_SWITCH` | `KillSwitchService`, scope `AGENT` |
   | `DENY_TOOL` | `TOOL_LIFECYCLE` | `ToolRegistryService.revoke` |
   | `REVOKE_CAPABILITY` | `CAPABILITY_LIFECYCLE` | `CapabilityService.revoke` |
   | `ISOLATE_CREDENTIAL` | `CREDENTIAL_LIFECYCLE` | `api_key_service.revoke_key` |
   | `DISABLE_INTEGRATION` | `CONNECTOR_LIFECYCLE` | `ConnectorService.disable` |
   | `REQUIRE_APPROVAL` | `GOVERNANCE_POLICY` | `GovernancePolicyService.create` (a real, mandatory, agent-scoped `requires_approval` policy — the same constraint the 4.3 engine's own checkpoints read) |

   There is no eighth action. An action this platform cannot map to an
   existing authority is not offered — it is not built as a new enforcer.

2. **Capability is truthfully derived from exactly one signal:
   `agents.control_state`.** `GOVERNED` means ACT is the system actually
   executing/enforcing this agent; anything else (`DISCOVERED`/`CLAIMED`/
   `REGISTERED`) means it is not. For a non-`GOVERNED` agent, every
   enforcement-requiring action is refused — `status='REFUSED'`, a real
   `refusal_reason`, `authority_ref` and `result` both empty. There is no
   code path that fabricates a success. This is the single gate
   (`ContainmentOrchestrator.truthful_capability`); nothing else in the
   package may call an authority without going through it.

3. **Kill-switch dominance is structural, not procedural.** `SUSPEND_AGENT`
   and `TERMINATE_EXECUTION` are marked `reversible=False` by construction —
   this module contains no branch that sets `lifecycle_status` back to
   `'ACTIVE'` or `cancel_requested` back to `False` (the same AST property
   `app.runtime.governance` proves for itself, extended here by
   `test_ac06_no_reactivation_or_kill_clearing_in_threat_package`). Automated
   detection (`ThreatEvaluator`) never calls a containment authority at
   all — it only ever creates a `RECOMMENDED` row. A human kill, once fired,
   cannot be undone by anything this package does, ever.

4. **A dedicated `threat_findings` table**, not a `posture_findings`
   discriminator — the same call ADR-0019 made, for the same reason: a
   threat is a *runtime event* ("this happened just now"), posture is a
   *standing state* ("this is how things stand"). An agent depending on an
   unapproved MCP server is posture; the agent *actually invoking* a tool
   that server exposes is a threat — `unapproved_mcp_tool_invoked` is
   exactly that rule. The lifecycle *shape* is reused verbatim
   (`app.slo.states`, mirroring `app.posture.lifecycle`).

5. **`containment_actions` records; it does not enforce.** Every `EXECUTED`
   row's `authority_ref` names the real row a real authority produced (an
   `agent_tools`/`agent_capabilities` id, a `connector_instances` id, a
   `runtime_governance_policies` id, or `{"table": "agents"/"agent_executions"}`
   for a kill-switch action). There is no status value this table invents
   that represents enforcement happening inside the table itself.

6. **Every dangerous action is confirmation-gated.** All seven actions reach
   an enforcement authority, so all seven require an explicit `confirm=true`
   before invocation — a call without it returns `PENDING_CONFIRMATION`,
   nothing invoked. Automated detection never sets `confirm`; only an
   operator (or a future, narrowly-scoped automation this phase does not
   build) can push past that gate.

7. **Automated invocation reuses the existing automation principal**
   (`app.scheduler.principal`, Phase 3.8) — the same non-human, unusable-
   login, per-organization `User` row every scheduled job already acts
   under. No new "system identity."

8. **`containment.execute` is a distinct, stronger permission** — never
   implied by `threat.view`/`threat.manage`. It is the one permission on this
   platform that can reach the kill switch, revoke a grant, isolate a
   credential, or disable an integration.

## Consequences

### Positive
- The one-enforcement-path invariant (ADR-0009, proven at M4.3/4.4/4.5)
  extends to containment instead of forking: there is still exactly one
  thing that stops an execution and exactly one thing that suspends an
  agent.
- A containment claim is always true. There is no code path where ACT says
  "contained" about an agent it never had authority over.
- Reversibility is honest: only `DENY_TOOL`/`REVOKE_CAPABILITY`/
  `DISABLE_INTEGRATION`/`REQUIRE_APPROVAL` can be reverted, and only through
  the same authority's own reverse operation (discovered mid-build:
  `DISABLE_INTEGRATION`'s reverse is genuinely two lifecycle transitions,
  `disabled → configured → active` — there is no direct `disabled → active`
  edge — so the revert path calls `update_configuration` then `activate`,
  matching the real state machine rather than assuming a shortcut).
- Detection and containment are cleanly separated: a threat finding is
  always produced; a containment action is only ever recommended by
  automation, never executed by it — bounding autonomous remediation by
  construction, not by policy.

### Negative / accepted cost
- Two new tables (`threat_findings`, `containment_actions`). Justified by
  the same 4.5/4.7/ADR-0019 reasoning: what each row is *about* differs from
  every existing finding/alert/decision table.
- The truthful-containment gate is coarse (`GOVERNED` vs. not) because
  Phase 5.7's enforcement-mode vocabulary does not exist yet. This is
  explicit and named as the seam 5.7 will refine, not hidden behind a
  richer-looking capability model this phase cannot actually back.
  **Update (2026-09-15, ADR-0021):** 5.7 shipped that vocabulary and the gate
  stayed coarse *on purpose*. `GATEWAY_ENFORCED` means ACT can refuse an
  external agent's calls through ACT's boundary, not that ACT can suspend or
  terminate it — so admitting it here would have made `SUSPEND_AGENT` claim a
  success ACT cannot deliver. The coarse gate turned out to be the correct one,
  not a placeholder.
- Two threat rules the SRS names — "prompt/indirect-injection" and
  "cross-agent/delegation abuse" — are not delivered: neither has a
  deterministic signal in the current schema (no reason-code taxonomy for
  content-based denials; no timestamped "used after revocation" evidence for
  delegation abuse). Recorded, not fabricated.

### Residual risk
- `ThreatEvaluator`'s recommendation logic (HIGH/CRITICAL → `RECOMMENDED`
  `SUSPEND_AGENT`) is itself a judgment call about which action to suggest.
  It is only ever a suggestion — an operator (or 5.7's narrower automation)
  still has to confirm — but a miscalibrated rule could recommend
  unnecessarily often. The audit trail and the rule-firing test coverage are
  the backstop.
- `containment.execute` granted broadly would let an operator suspend agents
  or revoke grants freely within their tenant. This is intentional (it
  mirrors `runtime.kill_switch.execute`'s existing scope) but worth naming:
  the permission is powerful by design, not by oversight.

## Revisit when

- ~~**Phase 5.7 builds the external gateway and makes enforcement modes
  real**~~ — **Settled by
  [ADR-0021](0021-truthful-external-enforcement-modes.md) (2026-09-15),
  opposite to the way this line expected.** The coarse
  `control_state == GOVERNED` gate was *not* replaced: `GATEWAY_ENFORCED`
  reaches only calls routed through ACT's boundary, so widening the gate would
  have let a containment action claim a reach ACT lacks. 5.7's own boundary
  enforcement (revoking a grant) lives in `ExternalGrantService.revoke`, and no
  eighth containment action was added — this ADR's action set is still
  exhaustively seven.
- **A containment action is proposed that acts at 5.7's boundary** — e.g.
  routing `REVOKE_CAPABILITY` to `ExternalGrantService.revoke` for a
  `GATEWAY_ENFORCED` agent. That is a legitimate eighth action, but it must
  carry its own truthful-refusal reason naming the boundary as its limit, and
  must not be mistaken for the ability to stop the agent.
- **A narrowly-scoped automated execution path is proposed** — it must stay
  bounded (a fixed, reviewed action set, never "whatever the rule decides"),
  must never bypass confirmation for a genuinely dangerous action, and must
  inherit kill-switch dominance unchanged.
- **An eighth containment action is proposed** — it must map to an existing
  authority or this ADR's central decision is void; if no existing authority
  can perform it, that is a signal to stop and design the authority itself
  (elsewhere, deliberately), not to add it here as a shortcut.
