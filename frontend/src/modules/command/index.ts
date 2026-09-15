/**
 * Phase 5.8 — the Enterprise Agent Command Center.
 *
 * The operator surface over everything Phases 5.1–5.7 built: inventory,
 * discovery, ownership, the authority graph, dependencies and blast radius,
 * posture and shadow, threats and containment, external governance.
 *
 * Three rules govern every file in this module:
 *
 *   * **It reads and triggers; it never decides.** Each action dispatches to
 *     the 5.1–5.7 endpoint that already owns it and already authorizes,
 *     isolates by tenant, and audits. No domain or enforcement logic lives in
 *     React.
 *
 *   * **Affordances come from the server.** Whether to offer containment is
 *     `reaches_agent_execution`, computed by 5.7's `app.bridge.modes` and sent
 *     with the data. The labels are the server's own `display`/`limits`
 *     sentences, verbatim — which is why a GATEWAY_ENFORCED agent is never
 *     called "governed" here. See `affordances.ts`.
 *
 *   * **It reuses 3.10/4.9 rather than restating them.**
 *     `ConfirmActionDialog` and `useGuardedAction` are imported from
 *     `@/modules/operations`; the persona vocabulary from
 *     `@/modules/observability`. There is no second design system and no
 *     second confirmation pattern.
 */

export { EstateOverviewPage } from './EstateOverviewPage'
export { AgentInventoryPage } from './AgentInventoryPage'
export { OwnershipPage } from './OwnershipPage'
export { AgentDrilldownPage } from './AgentDrilldownPage'
export { ShadowAgentsPage } from './ShadowAgentsPage'
export { PostureFindingsPage } from './PostureFindingsPage'
export { ThreatsPage } from './ThreatsPage'
export { ExternalPlatformsPage } from './ExternalPlatformsPage'
export { ControlGraphPage } from './ControlGraphPage'
export { IdentityDelegationPage } from './IdentityDelegationPage'
export { ToolsMcpPage } from './ToolsMcpPage'
export { GovernanceCoveragePage } from './GovernanceCoveragePage'
export { CostExposurePage } from './CostExposurePage'
export { AssurancePage } from './AssurancePage'

export { COMMAND_VIEWS, PERSONAS, viewsForPersona } from './personas'
export type { PersonaId, CommandView } from './personas'
export { affordancesFor, signalFromModeRead } from './affordances'
export type { Affordances, GovernanceSignal } from './affordances'
export { CommandCenterNav, GovernanceBadge, ShadowReasons, SectionGate } from './components'
