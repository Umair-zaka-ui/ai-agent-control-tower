import { apiClient } from './apiClient'

/**
 * Phase 4.9 — the Enterprise Runtime Governance & Observability Center's data
 * layer.
 *
 * **Read + trigger, nothing else.** Every read below hits an endpoint that
 * Phases 4.1–4.8 (or 4.9's two read-model additions) already built and already
 * authorize; every *trigger* (alert ack/resolve/suppress, capture-policy edit,
 * retention run) calls an existing 4.7/4.8 operation that re-authorizes it,
 * enforces tenant isolation, honours idempotency and writes its own audit. This
 * file decides nothing.
 *
 * **Content is special.** `traceContent()` is the ONLY way this center reads
 * trace content, and it goes through 4.8's `GET /observability/traces/{id}/content`
 * — the endpoint that requires the distinct `runtime.trace.content.view`
 * permission and emits `RUNTIME_TRACE_CONTENT_VIEWED` on every call. There is no
 * bypass route. A 403 here means "in-tenant, but you lack the content
 * permission"; a 404 means "no such trace for this tenant".
 */

const RUNTIME = '/api/v1/runtime'
const OBS = '/api/v1/observability'

export interface OverviewResponse {
  generated_at: string
  executions: {
    window_hours: number
    by_status: Record<string, number>
    terminal: number
    succeeded: number
    failed_24h: number
    running_now: number
    queued_now: number
    success_rate: number | null
    success_rate_insufficient_data: boolean
  }
  spend: {
    since: string
    amount: number
    currency: string
    includes_estimated: boolean
    estimated_row_count: number
  }
  alerts: { active: number; by_severity: Record<string, number>; critical: number }
  slos: {
    enabled: number
    latest_by_state: Record<string, number>
    breached: number
    insufficient_data: number
  }
  behavior: {
    window_days: number
    by_state: Record<string, number>
    anomalous: number
    degraded: number
  }
  workers: {
    total: number
    by_status: Record<string, number>
    offline: number
    degraded: number
    note: string | null
  }
  capture: { org_effective_mode: string; source: string; reason: string }
}

export interface ExporterHealthResponse {
  exporter: {
    degraded: boolean
    last_error: string | null
    last_success_at: string | null
    consecutive_failures: number
    spans_exported_total: number
    spans_dropped_total: number
    [key: string]: unknown
  }
  platform_default: Record<string, unknown>
}

export interface TraceSummary {
  trace_id: string
  execution_id: string
  correlated: boolean
  status: string
  agent_id: string | null
  agent_version_id: string | null
  created_at: string | null
  started_at: string | null
  completed_at: string | null
  duration_ms: number | null
  queue_wait_ms: number | null
  error_code: string | null
  cost_amount: number | null
  cost_currency: string | null
  total_tokens: number | null
  loop_iterations: number
  attempt_count: number
  termination_reason: string | null
}

export interface TracePage {
  items: TraceSummary[]
  limit: number
  offset: number
  has_more: boolean
  window_start: string | null
  window_end: string | null
  filters_applied: string[]
}

export interface AssembledSpan {
  span_id: string
  parent_span_id: string | null
  kind: string
  name: string
  source_table: string | null
  source_id: string | null
  started_at: string | null
  ended_at: string | null
  duration_ms: number | null
  status: string | null
  error_code: string | null
  attributes: Record<string, string>
}

export interface AssembledTrace {
  trace_id: string
  execution_id: string
  request_id: string | null
  correlated: boolean
  attributes: Record<string, string>
  spans: AssembledSpan[]
  notes: string[]
}

export interface TraceContentItem {
  id: string
  source_table: string
  source_id: string | null
  sequence: number
  role: string | null
  classification: string | null
  mode_applied: string
  redacted: boolean
  secret_scrubbed: boolean
  body: unknown
  captured_at: string | null
}

export interface TraceContentView {
  execution_id: string
  mode: string
  captured: boolean
  items: TraceContentItem[]
  note?: string
  policy: Record<string, unknown>
}

export interface TraceContentResponse {
  trace_id: string
  executions: number
  traces: TraceContentView[]
}

export interface GovernanceDecision {
  id: string
  execution_id: string
  trace_id: string | null
  agent_id: string | null
  agent_name: string | null
  checkpoint: string
  decision: string
  reason_code: string
  reason: string | null
  obligation: Record<string, unknown> | null
  policy_id: string | null
  budget_id: string | null
  evaluated_at: string | null
}

export interface GovernanceDecisionPage {
  items: GovernanceDecision[]
  limit: number
  offset: number
  has_more: boolean
  vocabulary: { decisions: string[]; checkpoints: string[] }
}

export interface BehavioralFinding {
  id: string
  organization_id: string
  agent_id: string
  agent_version_id: string | null
  environment_id: string | null
  signal_type: string
  metric: string | null
  state: string
  window_start: string
  window_end: string
  observed_value: number | null
  threshold_value: number | null
  baseline_value: number | null
  reason: string | null
  explanation: Record<string, unknown>
  attribution: Record<string, unknown>
  evaluated_at: string
}

export interface Slo {
  id: string
  organization_id: string
  name: string
  sli: string
  scope_type: string
  scope_id: string | null
  target: number
  window: string
  error_budget: number
  enabled: boolean
}

export interface SloEvaluation {
  id: string
  slo_id: string
  window_start: string
  window_end: string
  sample_count: number
  observed_value: number | null
  state: string
  budget_consumed: number | null
  budget_remaining: number | null
  explanation: Record<string, unknown>
  evaluated_at: string
}

export interface RuntimeAlert {
  id: string
  organization_id: string
  source: string
  source_id: string | null
  slo_id: string | null
  severity: string
  status: string
  agent_id: string | null
  agent_version_id: string | null
  environment_id: string | null
  execution_id: string | null
  trace_id: string | null
  metric: string | null
  threshold_value: number | null
  observed_value: number | null
  baseline_value: number | null
  title: string
  summary: string
  dedup_key: string
  context: Record<string, unknown>
  recurrence_count: number
  opened_at: string
  last_seen_at: string
  acknowledged_at: string | null
  acknowledged_by: string | null
  resolved_at: string | null
  resolved_by: string | null
  suppressed_at: string | null
  updated_at: string
}

export interface CapturePolicy {
  id: string
  organization_id: string | null
  environment_id: string | null
  agent_id: string | null
  classification: string | null
  mode: string
  enabled: boolean
  created_by: string | null
  created_at: string
  updated_at: string
}

export interface EffectiveMode {
  mode: string
  source: string
  policy_id: string | null
  matched_scope: Record<string, unknown>
  reason: string
  considered: Record<string, unknown>[]
  precedence: string
}

export interface RetentionClass {
  telemetry_class: string
  retention_days: number
  enabled: boolean
  source: string
  floor_days: number
  retain_only: boolean
}

export interface CostBucket {
  key: string
  label: string | null
  actual_amount: number
  estimated_amount: number
  execution_count: number
  total_tokens: number
  currency: string
}

export interface CostSummary {
  window_start: string
  window_end: string
  actual_amount: number
  estimated_amount: number
  execution_count: number
  total_tokens: number
  unpriced_execution_count: number
  currency: string
  dimension: string | null
  buckets: CostBucket[]
}

export interface SpendAnomaly {
  period: string
  amount: number
  baseline: number
  ratio: number
  threshold_ratio: number
  reason: string
}

export interface Budget {
  id: string
  organization_id: string
  name: string
  description: string | null
  scope_type: string
  scope_id: string | null
  scope_value: string | null
  mode: string
  period: string
  limit_amount: number
  currency: string
  threshold_percent: number
  enabled: boolean
}

export interface BudgetUtilization {
  budget_id: string
  mode: string
  period: string
  period_key: string
  limit_amount: number
  reserved: number
  spent: number
  committed: number
  remaining: number
  utilization_percent: number
  threshold_percent: number
  over_threshold: boolean
  currency: string
}

export const observabilityService = {
  // --- Runtime Overview (4.9) ------------------------------------------------
  overview: () => apiClient.get<OverviewResponse>(`${RUNTIME}/overview`).then((r) => r.data),
  // Exporter health comes from 4.6's own endpoint — app/runtime never reads the
  // telemetry-export plane, so the overview composite deliberately omits it.
  exporterHealth: () =>
    apiClient.get<ExporterHealthResponse>(`${OBS}/export/health`).then((r) => r.data),

  // --- Trace Explorer / Detail (4.2) --------------------------------------- //
  traces: (params: Record<string, string | number | boolean | undefined>) =>
    apiClient.get<TracePage>(`${OBS}/traces`, { params }).then((r) => r.data),
  executionTrace: (executionId: string) =>
    apiClient.get<AssembledTrace>(`${OBS}/executions/${executionId}/trace`).then((r) => r.data),

  // --- Trace CONTENT — 4.8's governed, audited endpoint. No bypass. -------- //
  traceContent: (traceId: string) =>
    apiClient.get<TraceContentResponse>(`${OBS}/traces/${traceId}/content`).then((r) => r.data),

  // --- Governance Decisions (4.9 read model over 4.3) --------------------- //
  governanceDecisions: (params: Record<string, string | number | undefined>) =>
    apiClient.get<GovernanceDecisionPage>(`${RUNTIME}/governance/decisions`, { params })
      .then((r) => r.data),

  // --- Behavior & Anomalies (4.5) ---------------------------------------- //
  findings: (params: Record<string, string | number | undefined>) =>
    apiClient.get<BehavioralFinding[]>(`${RUNTIME}/behavior/findings`, { params }).then((r) => r.data),

  // --- SLOs (4.7) ------------------------------------------------------- //
  slos: () => apiClient.get<Slo[]>(`${RUNTIME}/slos`).then((r) => r.data),
  sloEvaluations: (sloId: string) =>
    apiClient.get<SloEvaluation[]>(`${RUNTIME}/slos/${sloId}/evaluations`).then((r) => r.data),

  // --- Alerts (4.7) — reads + guarded lifecycle triggers ---------------- //
  alerts: (params: Record<string, string | number | undefined>) =>
    apiClient.get<RuntimeAlert[]>(`${RUNTIME}/alerts`, { params }).then((r) => r.data),
  acknowledgeAlert: (id: string, note?: string) =>
    apiClient.post<RuntimeAlert>(`${RUNTIME}/alerts/${id}/acknowledge`, { note }).then((r) => r.data),
  resolveAlert: (id: string, note?: string) =>
    apiClient.post<RuntimeAlert>(`${RUNTIME}/alerts/${id}/resolve`, { note }).then((r) => r.data),
  suppressAlert: (id: string, note?: string) =>
    apiClient.post<RuntimeAlert>(`${RUNTIME}/alerts/${id}/suppress`, { note }).then((r) => r.data),

  // --- Telemetry Policy admin (4.8) ------------------------------------ //
  capturePolicies: () =>
    apiClient.get<CapturePolicy[]>(`${RUNTIME}/telemetry/capture-policies`).then((r) => r.data),
  effectiveMode: (params: Record<string, string | undefined>) =>
    apiClient.get<EffectiveMode>(`${RUNTIME}/telemetry/effective-mode`, { params }).then((r) => r.data),
  createCapturePolicy: (payload: {
    mode: string; environment_id?: string; agent_id?: string; classification?: string; enabled?: boolean
  }) =>
    apiClient.post<CapturePolicy>(`${RUNTIME}/telemetry/capture-policies`, payload).then((r) => r.data),
  updateCapturePolicy: (id: string, payload: Record<string, unknown>) =>
    apiClient.patch<CapturePolicy>(`${RUNTIME}/telemetry/capture-policies/${id}`, payload).then((r) => r.data),
  deleteCapturePolicy: (id: string) =>
    apiClient.delete(`${RUNTIME}/telemetry/capture-policies/${id}`).then((r) => r.data),
  retentionPolicies: () =>
    apiClient.get<Record<string, RetentionClass>>(`${RUNTIME}/telemetry/retention-policies`).then((r) => r.data),
  setRetentionPolicy: (payload: { telemetry_class: string; retention_days: number; enabled?: boolean }) =>
    apiClient.post(`${RUNTIME}/telemetry/retention-policies`, payload).then((r) => r.data),
  runRetention: () => apiClient.post(`${RUNTIME}/telemetry/retention/run`, {}).then((r) => r.data),

  // --- Cost Center (4.4) --------------------------------------------- //
  costSummary: (params: Record<string, string | undefined>) =>
    apiClient.get<CostSummary>('/api/v1/cost/summary', { params }).then((r) => r.data),
  costAnomalies: (params: Record<string, string | undefined>) =>
    apiClient.get<SpendAnomaly[]>('/api/v1/cost/anomalies', { params }).then((r) => r.data),
  budgets: () => apiClient.get<Budget[]>('/api/v1/budgets').then((r) => r.data),
  budgetUtilization: (id: string) =>
    apiClient.get<BudgetUtilization>(`/api/v1/budgets/${id}/utilization`).then((r) => r.data),
}
