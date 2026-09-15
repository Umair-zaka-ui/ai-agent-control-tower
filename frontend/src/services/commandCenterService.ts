import { apiClient } from './apiClient'

/**
 * Phase 5.8 — the Enterprise Agent Command Center's data layer.
 *
 * **Read + trigger, nothing else.** Every read hits an endpoint Phases 5.1–5.7
 * (or 5.8's two read-model additions) already built and already authorize.
 * Every *trigger* — claim, resolve/suppress a finding, execute containment, set
 * an enforcement mode, revoke a grant — calls the existing operation that owns
 * it, which re-authorizes, enforces tenant isolation and writes its own audit.
 * This file decides nothing and computes no domain state.
 *
 * **The truthful-affordance signal arrives with the data.** `enforcement_mode`,
 * `reaches_agent_execution`, `reaches_boundary_calls` and the exact
 * `display`/`limits` sentences are computed **server-side** by 5.7's own
 * `app.bridge.modes` and shipped on every inventory row and on the per-agent
 * mode read. Nothing in the frontend derives them, which is precisely why the
 * UI cannot form a second opinion about what ACT can do to an agent.
 *
 * **Containment is deliberately not wrapped in a convenience helper that hides
 * its target.** `executeContainment` names the agent and the action, because
 * the server will truthfully refuse it for an agent ACT cannot reach — and the
 * UI must already know not to offer it.
 */

const CC = '/api/v1/command-center'
const RUNTIME = '/api/v1/runtime'
const POSTURE = '/api/v1/posture'
const THREAT = '/api/v1/threat'
const BRIDGE = '/api/v1/bridge'
const GRAPH = '/api/v1/graph'
const DISCOVERY = '/api/v1/discovery'

/** A section the caller may not be able to see. `visible: false` is not zero. */
export interface EstateSection<T> {
  visible: boolean
  permission: string
  data: T | null
}

export interface EstateResponse {
  generated_at: string
  agents: {
    total: number
    by_control_state: Record<string, number>
    by_origin_category: Record<string, number>
    by_enforcement_mode: Record<string, number>
    governed: number
    ungoverned: number
    unowned: number
    critical: number
    dormant: number
    dormant_days: number
  }
  posture: EstateSection<Record<string, unknown>>
  shadow: EstateSection<{ count: number; shadow_rule_ids: string[] }>
  threats: EstateSection<{
    open_findings: number
    open_by_severity: Record<string, number>
    containment_window_hours: number
    containment_by_status: Record<string, number>
    containment_refused: number
  }>
  external: EstateSection<{
    active_grants: number
    window_hours: number
    boundary_calls_by_outcome: Record<string, number>
    boundary_calls_denied: number
  }>
  graph: EstateSection<{
    mcp_servers: number
    mcp_by_trust_status: Record<string, number>
    active_edges: number
  }>
  cost: EstateSection<{
    enabled_budgets: number
    window_hours: number
    boundary_calls_not_measurable: number
    note: string
  }>
}

/** One inventory row, already carrying its truthful-affordance signal. */
export interface InventoryRow {
  id: string
  name: string
  control_state: string
  origin_category: string
  origin_provider: string
  criticality: string | null
  owner_id: string | null
  lifecycle_status: string | null
  last_observed_at: string | null
  enforcement_mode: string
  enforcement_display: string
  enforcement_limits: string
  reaches_boundary_calls: boolean
  reaches_agent_execution: boolean
  shadow: boolean
  shadow_conditions: ShadowCondition[]
  shadow_visible: boolean
}

export interface ShadowCondition {
  rule_id: string
  severity: string
  reason: string
  finding_id: string
}

export interface InventoryResponse {
  total: number
  page: number
  page_size: number
  items: InventoryRow[]
}

export interface EnforcementModeRead {
  enforcement_mode: string
  control_state: string
  display: string
  limits: string
  reaches_boundary_calls: boolean
  reaches_agent_execution: boolean
  evaluates_policy: boolean
  derived_from_control_state: boolean
}

export const commandCenterService = {
  // ---- 5.8 read-model aggregation (the only two new endpoints) ----
  estate: () => apiClient.get<EstateResponse>(`${CC}/estate`).then((r) => r.data),
  inventory: (params: Record<string, unknown> = {}) =>
    apiClient.get<InventoryResponse>(`${CC}/agents`, { params }).then((r) => r.data),

  // ---- 5.1 inventory + control state ----
  agent: (id: string) => apiClient.get<Record<string, unknown>>(`${RUNTIME}/agents/${id}`).then((r) => r.data),
  controlState: (id: string) =>
    apiClient.get<Record<string, unknown>>(`${RUNTIME}/agents/${id}/control-state`)
      .then((r) => r.data),
  /** Guarded. Server re-authorizes, validates the transition and audits. */
  claim: (id: string, body: Record<string, unknown>) =>
    apiClient.post(`${RUNTIME}/agents/${id}/claim`, body),
  transitionControlState: (id: string, body: Record<string, unknown>) =>
    apiClient.post(`${RUNTIME}/agents/${id}/control-state`, body),

  // ---- 5.2 discovery ----
  discoverySources: () => apiClient.get<unknown[]>(`${DISCOVERY}/sources`).then((r) => r.data),
  discoveryFindings: (params: Record<string, unknown> = {}) =>
    apiClient.get<unknown[]>(`${DISCOVERY}/findings`, { params }).then((r) => r.data),

  // ---- 5.3 / 5.4 graph ----
  edges: (params: Record<string, unknown> = {}) =>
    apiClient.get<unknown[]>(`${GRAPH}/edges`, { params }).then((r) => r.data),
  dependencies: (agentId: string) =>
    apiClient.get<Record<string, unknown>>(`${GRAPH}/agents/${agentId}/dependencies`)
      .then((r) => r.data),
  unapprovedMcp: () => apiClient.get<Record<string, unknown>>(`${GRAPH}/blast-radius/unapproved-mcp`)
    .then((r) => r.data),
  mcpServers: () => apiClient.get<unknown[]>(`${GRAPH}/mcp-servers`).then((r) => r.data),

  // ---- 5.5 posture + shadow ----
  postureSummary: () => apiClient.get<Record<string, unknown>>(`${POSTURE}/summary`).then((r) => r.data),
  postureFindings: (params: Record<string, unknown> = {}) =>
    apiClient.get<PostureFinding[]>(`${POSTURE}/findings`, { params }).then((r) => r.data),
  agentShadow: (agentId: string) =>
    apiClient.get<{ agent_id: string; shadow: boolean; conditions: ShadowCondition[] }>(
      `${POSTURE}/agents/${agentId}/shadow`).then((r) => r.data),
  shadowAgents: () =>
    apiClient.get<{ shadow_rule_ids: string[]; count: number; agents: ShadowAgent[] }>(
      `${POSTURE}/shadow-agents`).then((r) => r.data),
  resolvePostureFinding: (id: string) => apiClient.post(`${POSTURE}/findings/${id}/resolve`, {}),
  suppressPostureFinding: (id: string, body: Record<string, unknown>) =>
    apiClient.post(`${POSTURE}/findings/${id}/suppress`, body),

  // ---- 5.6 threats + containment ----
  threatFindings: (params: Record<string, unknown> = {}) =>
    apiClient.get<ThreatFinding[]>(`${THREAT}/findings`, { params }).then((r) => r.data),
  containmentActions: (params: Record<string, unknown> = {}) =>
    apiClient.get<ContainmentAction[]>(`${THREAT}/containment`, { params }).then((r) => r.data),
  resolveThreatFinding: (id: string) => apiClient.post(`${THREAT}/findings/${id}/resolve`, {}),
  /**
   * Guarded, and only ever offered where the server says ACT can reach the
   * agent. If it were called anyway, 5.6 would truthfully refuse it and record
   * a REFUSED row — the UI must match that truth, not discover it.
   */
  executeContainment: (agentId: string, body: Record<string, unknown>) =>
    apiClient.post(`${THREAT}/agents/${agentId}/containment`, body),

  // ---- 5.7 external governance ----
  enforcementMode: (agentId: string) =>
    apiClient.get<EnforcementModeRead>(`${BRIDGE}/agents/${agentId}/enforcement-mode`).then((r) => r.data),
  setEnforcementMode: (agentId: string, body: Record<string, unknown>) =>
    apiClient.put(`${BRIDGE}/agents/${agentId}/enforcement-mode`, body),
  modes: () => apiClient.get<ModeCatalogEntry[]>(`${BRIDGE}/modes`).then((r) => r.data),
  grants: (agentId: string) => apiClient.get<Grant[]>(`${BRIDGE}/agents/${agentId}/grants`).then((r) => r.data),
  revokeGrant: (grantId: string, body: Record<string, unknown>) =>
    apiClient.post(`${BRIDGE}/grants/${grantId}/revoke`, body),
  gatewayCalls: (params: Record<string, unknown> = {}) =>
    apiClient.get<GatewayCall[]>(`${BRIDGE}/calls`, { params }).then((r) => r.data),
}

export interface ShadowAgent {
  agent: { id: string; name: string | null; control_state: string | null }
  conditions: ShadowCondition[]
}

export interface PostureFinding {
  id: string
  rule_id: string
  severity: string
  status: string
  outcome: string
  reason: string
  remediation: string | null
  subject_id: string
  subject_type: string
}

export interface ThreatFinding {
  id: string
  rule_id: string
  severity: string
  status: string
  outcome: string
  reason: string
  agent_id: string | null
}

export interface ContainmentAction {
  id: string
  action_type: string
  authority: string
  status: string
  agent_id: string
  control_state_at_time: string | null
  refusal_reason: string | null
}

export interface ModeCatalogEntry {
  mode: string
  display: string
  limits: string
  reaches_boundary_calls: boolean
  reaches_agent_execution: boolean
  assignable: boolean
}

export interface Grant {
  id: string
  label: string
  key_id: string
  revoked_at: string | null
  scope: { capability: string; target_ref: string | null }[]
}

export interface GatewayCall {
  id: string
  agent_id: string
  capability_key: string
  outcome: string
  enforcement_mode_at_time: string
  denial_reason: string | null
  cost_outcome: string
  policy_outcome: string
  dispatch_status: string
}
