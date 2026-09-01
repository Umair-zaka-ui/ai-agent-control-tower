/**
 * Phase 4.9 — the Enterprise Runtime Governance & Observability Center.
 *
 * Nine operator views over the Milestone 4 engines (4.1–4.8). **Read + trigger
 * only:** every read hits an endpoint 4.1–4.8 (or 4.9's two read-model
 * additions) already built and already authorize; every trigger (alert
 * lifecycle, capture-policy edit, retention run) calls an existing 4.7/4.8
 * operation that re-authorizes it, honours tenant isolation and writes its own
 * audit. Nothing here decides a governance, cost or privacy question.
 *
 * **Content is governed by 4.8.** The Trace Detail content pane is the only
 * place content is rendered, and it is served exclusively by
 * `GET /observability/traces/{trace_id}/content` — the endpoint with the
 * distinct `runtime.trace.content.view` permission and the
 * `RUNTIME_TRACE_CONTENT_VIEWED` audit. There is no bypass route.
 */
export { RuntimeOverviewPage } from './RuntimeOverviewPage'
export { TraceExplorerPage } from './TraceExplorerPage'
export { TraceDetailPage } from './TraceDetailPage'
export { CostCenterPage } from './CostCenterPage'
export { GovernanceDecisionsPage } from './GovernanceDecisionsPage'
export { BehaviorAnomaliesPage } from './BehaviorAnomaliesPage'
export { SloDashboardPage } from './SloDashboardPage'
export { AlertCenterPage } from './AlertCenterPage'
export { TelemetryPolicyPage } from './TelemetryPolicyPage'
export { ObservabilityNav } from './components/ObservabilityNav'
export { PERSONAS, OBS_VIEWS, viewsForPersona } from './personas'
export type { PersonaId } from './personas'
