/**
 * Phase 5.8 — what the command center is allowed to offer for one agent.
 *
 * **This module contains no knowledge about enforcement modes.** Read it and
 * you will not find `'OBSERVED'`, `'GATEWAY_ENFORCED'`, a mode→label map, or a
 * rule about which mode can be contained. That absence is the design.
 *
 * Phases 5.1–5.7 spent the whole milestone making ACT honest about reach:
 * `control_state` is server-authoritative (5.1), containment is truthfully
 * refused for an agent ACT does not run (5.6), and `NATIVE_ENFORCED` is not
 * even *storable* — it is derived from `control_state == 'GOVERNED'`, so a row
 * cannot claim enforcement ACT lacks (5.7). The command center is the one
 * surface a human acts from, and a button that said "Suspend" on an agent ACT
 * cannot suspend would re-introduce exactly the over-claim that work removed —
 * in the place where it would actually cause harm.
 *
 * So the frontend does not decide. The server sends `reaches_agent_execution`,
 * `reaches_boundary_calls`, and the exact `display`/`limits` sentences, all
 * computed by 5.7's own `app.bridge.modes`. These functions read those fields
 * and nothing else. If ACT's notion of reach ever changes, this file does not
 * need to — and, more importantly, it *cannot* silently disagree.
 *
 * `label` and `limits` are returned verbatim. The UI never composes its own
 * sentence for a mode, because "Governed" is a word the server deliberately
 * never uses for a GATEWAY_ENFORCED agent.
 */

/** Exactly the server-sent fields an affordance may be derived from. */
export interface GovernanceSignal {
  enforcement_mode: string
  enforcement_display: string
  enforcement_limits: string
  reaches_boundary_calls: boolean
  reaches_agent_execution: boolean
}

export interface Affordances {
  /**
   * Whether to offer containment that acts on the agent itself — suspend,
   * terminate. True only where ACT genuinely runs the agent. This is the
   * server's `reaches_agent_execution`, passed through.
   */
  canContainAgent: boolean
  /**
   * Whether ACT can refuse this agent's capability calls at its boundary.
   * Not the same as controlling the agent, and never labelled as if it were.
   */
  canGovernBoundaryCalls: boolean
  /** The server's own sentence for what ACT does. Never composed here. */
  label: string
  /** The server's own sentence for what ACT cannot do. Never omitted. */
  limits: string
  /**
   * Why containment is not offered, in the server's words, so the UI can say
   * *why* rather than just hiding a button. Null when containment is offered.
   */
  containmentUnavailableReason: string | null
}

export function affordancesFor(signal: GovernanceSignal): Affordances {
  const canContainAgent = signal.reaches_agent_execution === true
  return {
    canContainAgent,
    canGovernBoundaryCalls: signal.reaches_boundary_calls === true,
    label: signal.enforcement_display,
    limits: signal.enforcement_limits,
    // An absent affordance with no explanation reads as a missing feature.
    // The honest version says which limit removed it, using the sentence the
    // server already wrote for exactly this purpose.
    containmentUnavailableReason: canContainAgent ? null : signal.enforcement_limits,
  }
}

/**
 * Normalizes the two shapes the same signal arrives in — an inventory row
 * (5.8's aggregation) and the per-agent mode read (5.7's endpoint) — so a
 * caller never hand-copies fields between them and cannot drop one in the
 * process.
 */
export function signalFromModeRead(read: {
  enforcement_mode: string
  display: string
  limits: string
  reaches_boundary_calls: boolean
  reaches_agent_execution: boolean
}): GovernanceSignal {
  return {
    enforcement_mode: read.enforcement_mode,
    enforcement_display: read.display,
    enforcement_limits: read.limits,
    reaches_boundary_calls: read.reaches_boundary_calls,
    reaches_agent_execution: read.reaches_agent_execution,
  }
}
