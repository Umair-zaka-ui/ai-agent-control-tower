import { AgentInventoryPage } from './AgentInventoryPage'

/**
 * Phase 5.8 — Ownership.
 *
 * The inventory narrowed to agents with no accountable owner. A separate view
 * rather than a filter chip because "who answers for this agent" is the
 * question a governance officer opens the tool to ask, and Phase 5.5 already
 * treats unowned-with-production-access as a shadow-class condition in its own
 * right — the two views are looking at the same fact from different jobs.
 */
export function OwnershipPage() {
  return <AgentInventoryPage title="Ownership" unownedOnly />
}
