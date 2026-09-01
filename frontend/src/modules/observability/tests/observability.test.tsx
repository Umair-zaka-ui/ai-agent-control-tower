// Phase 4.9 frontend tests — the Enterprise Runtime Governance & Observability
// Center.
//
// The sharpest tests are the content-governance set: that the Trace Detail
// content pane renders content ONLY to a holder of runtime.trace.content.view,
// that it goes exclusively through 4.8's audited endpoint (no bypass), that a
// METADATA_ONLY / DISABLED capture reads as "no content captured" rather than an
// error, and that 404 (cross-tenant) and 403 (no content permission) are
// distinct honest states. After that: truthful state (burned budget, degraded
// exporter, INSUFFICIENT_DATA), per-persona assembly, and confirmation-gated
// dangerous actions.
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import type { ReactNode } from 'react'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const MODULE_DIR = resolve(process.cwd(), 'src/modules/observability')
const SERVICE_FILE = resolve(process.cwd(), 'src/services/observabilityService.ts')

const obs = {
  overview: vi.fn(),
  exporterHealth: vi.fn(),
  traces: vi.fn(),
  executionTrace: vi.fn(),
  traceContent: vi.fn(),
  governanceDecisions: vi.fn(),
  findings: vi.fn(),
  slos: vi.fn(),
  sloEvaluations: vi.fn(),
  alerts: vi.fn(),
  acknowledgeAlert: vi.fn(),
  resolveAlert: vi.fn(),
  suppressAlert: vi.fn(),
  capturePolicies: vi.fn(),
  effectiveMode: vi.fn(),
  createCapturePolicy: vi.fn(),
  updateCapturePolicy: vi.fn(),
  deleteCapturePolicy: vi.fn(),
  retentionPolicies: vi.fn(),
  setRetentionPolicy: vi.fn(),
  runRetention: vi.fn(),
  costSummary: vi.fn(),
  costAnomalies: vi.fn(),
  budgets: vi.fn(),
  budgetUtilization: vi.fn(),
}
vi.mock('@/services', () => ({ observabilityService: obs, operationsService: {}, runtimeService: {} }))
vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn(), message: vi.fn() },
  Toaster: () => null,
}))

let permissions: string[] = []
vi.mock('@/hooks/useAuth', () => ({
  useAuth: () => ({
    user: { id: 'u1', organization_id: 'org-1', name: 'Owner', email: 'o@x.com' },
    permissions,
  }),
}))

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom')
  return { ...actual, useParams: () => ({ executionId: 'exec-1' }) }
})

const { RuntimeOverviewPage } = await import('../RuntimeOverviewPage')
const { TraceExplorerPage } = await import('../TraceExplorerPage')
const { TraceDetailPage } = await import('../TraceDetailPage')
const { CostCenterPage } = await import('../CostCenterPage')
const { GovernanceDecisionsPage } = await import('../GovernanceDecisionsPage')
const { BehaviorAnomaliesPage } = await import('../BehaviorAnomaliesPage')
const { SloDashboardPage } = await import('../SloDashboardPage')
const { AlertCenterPage } = await import('../AlertCenterPage')
const { TelemetryPolicyPage } = await import('../TelemetryPolicyPage')
const { viewsForPersona, OBS_VIEWS } = await import('../personas')
const { PermissionProvider } = await import('@/authorization')

function wrap(children: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <PermissionProvider>{children}</PermissionProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

const ALL = [
  'runtime.telemetry.view', 'runtime.cost.view', 'runtime.execution.view',
  'runtime.telemetry_policy.view', 'runtime.telemetry_policy.manage',
  'runtime.alert.manage', 'runtime.trace.content.view',
]

beforeEach(() => {
  vi.clearAllMocks()
  permissions = [...ALL]
  obs.overview.mockResolvedValue(OVERVIEW)
  obs.exporterHealth.mockResolvedValue({
    exporter: { degraded: true, last_error: 'connection refused', last_success_at: null, consecutive_failures: 3, spans_exported_total: 100, spans_dropped_total: 5 },
    platform_default: {},
  })
  obs.traces.mockResolvedValue(TRACE_PAGE)
  obs.executionTrace.mockResolvedValue(ASSEMBLED)
  obs.governanceDecisions.mockResolvedValue(GOV_PAGE)
  obs.findings.mockResolvedValue(FINDINGS)
  obs.slos.mockResolvedValue(SLOS)
  obs.sloEvaluations.mockResolvedValue(SLO_EVALS)
  obs.alerts.mockResolvedValue(ALERTS)
  obs.capturePolicies.mockResolvedValue([])
  obs.effectiveMode.mockResolvedValue(EFFECTIVE)
  obs.retentionPolicies.mockResolvedValue(RETENTION)
  obs.costSummary.mockResolvedValue(COST)
  obs.budgets.mockResolvedValue(BUDGETS)
  obs.budgetUtilization.mockResolvedValue(BUDGET_UTIL)
  obs.acknowledgeAlert.mockResolvedValue({})
  obs.resolveAlert.mockResolvedValue({})
  obs.suppressAlert.mockResolvedValue({})
  obs.createCapturePolicy.mockResolvedValue({})
  obs.deleteCapturePolicy.mockResolvedValue({})
  obs.runRetention.mockResolvedValue({ total_deleted: 3 })
})

// --------------------------------------------------------------------------- //
// Fixtures
// --------------------------------------------------------------------------- //
const OVERVIEW = {
  generated_at: '2026-09-01T00:00:00Z',
  executions: {
    window_hours: 24, by_status: { SUCCEEDED: 90, FAILED: 10 }, terminal: 100,
    succeeded: 90, failed_24h: 10, running_now: 2, queued_now: 1,
    success_rate: 0.9, success_rate_insufficient_data: false,
  },
  spend: { since: '2026-09-01T00:00:00Z', amount: 12.34, currency: 'USD', includes_estimated: true, estimated_row_count: 4 },
  alerts: { active: 3, by_severity: { CRITICAL: 1, WARNING: 2 }, critical: 1 },
  slos: { enabled: 5, latest_by_state: { MET: 3, BREACHED: 1, INSUFFICIENT_DATA: 1 }, breached: 1, insufficient_data: 1 },
  behavior: { window_days: 7, by_state: { ANOMALOUS: 2 }, anomalous: 2, degraded: 1 },
  workers: { total: 0, by_status: {}, offline: 0, degraded: 0, note: 'inline synchronous worker' },
  capture: { org_effective_mode: 'METADATA_ONLY', source: 'platform-default', reason: 'content capture is opt-in everywhere' },
}

const TRACE_PAGE = {
  items: [{
    trace_id: 'exec-1', execution_id: 'exec-1', correlated: false, status: 'FAILED',
    agent_id: 'a1', agent_version_id: 'v1', created_at: null, started_at: '2026-09-01T00:00:00Z',
    completed_at: null, duration_ms: 120, queue_wait_ms: 5, error_code: 'TIMEOUT',
    cost_amount: 0.01, cost_currency: 'USD', total_tokens: 100, loop_iterations: 1,
    attempt_count: 1, termination_reason: 'WALL_CLOCK',
  }],
  limit: 50, offset: 0, has_more: false, window_start: null, window_end: null, filters_applied: [],
}

const ASSEMBLED = {
  trace_id: 'trace-1', execution_id: 'exec-1', request_id: null, correlated: false,
  attributes: {}, notes: [],
  spans: [{
    span_id: 's1', parent_span_id: null, kind: 'EXECUTION', name: 'execution FAILED',
    source_table: 'agent_executions', source_id: 'exec-1', started_at: '2026-09-01T00:00:00Z',
    ended_at: null, duration_ms: 120, status: 'FAILED', error_code: 'TIMEOUT', attributes: {},
  }],
}

const contentView = (over: Record<string, unknown> = {}) => ({
  trace_id: 'trace-1', executions: 1,
  traces: [{
    execution_id: 'exec-1', mode: 'FULL_CONTENT', captured: true, policy: {},
    items: [{
      id: 'c1', source_table: 'execution_messages', source_id: 'm1', sequence: 0,
      role: 'user', classification: null, mode_applied: 'FULL_CONTENT', redacted: false,
      secret_scrubbed: true, body: { value: { role: 'user', content: 'hello' } }, captured_at: null,
    }],
    ...over,
  }],
})

const GOV_PAGE = {
  items: [{
    id: 'd1', execution_id: 'exec-1', trace_id: 'trace-1', agent_id: 'a1', agent_name: 'Billing',
    checkpoint: 'BEFORE_TOOL_EXECUTION', decision: 'STOP', reason_code: 'COST_CEILING_EXCEEDED',
    reason: 'Cost ceiling of $5.00 exceeded.', obligation: null, policy_id: null, budget_id: 'b1',
    evaluated_at: '2026-09-01T00:00:00Z',
  }],
  limit: 100, offset: 0, has_more: false,
  vocabulary: { decisions: ['ALLOW', 'CHALLENGE', 'DENY', 'STOP'], checkpoints: ['BEFORE_TOOL_EXECUTION'] },
}

const FINDINGS = [{
  id: 'f1', organization_id: 'org-1', agent_id: 'a1', agent_version_id: null, environment_id: null,
  signal_type: 'error_rate_shift', metric: 'error_rate', state: 'INSUFFICIENT_DATA',
  window_start: '2026-08-25T00:00:00Z', window_end: '2026-09-01T00:00:00Z',
  observed_value: null, threshold_value: null, baseline_value: null,
  reason: 'Only 4 executions in the window; at least 20 are required.', explanation: {}, attribution: {},
  evaluated_at: '2026-09-01T00:00:00Z',
}]

const SLOS = [{
  id: 'slo-1', organization_id: 'org-1', name: 'prod success rate', sli: 'success_rate',
  scope_type: 'ORGANIZATION', scope_id: null, target: 0.99, window: '24h', error_budget: 0.01, enabled: true,
}]
const SLO_EVALS = [{
  id: 'e1', slo_id: 'slo-1', window_start: '2026-08-31T00:00:00Z', window_end: '2026-09-01T00:00:00Z',
  sample_count: 200, observed_value: 0.95, state: 'BREACHED', budget_consumed: 5.0, budget_remaining: 0,
  explanation: {}, evaluated_at: '2026-09-01T00:00:00Z',
}]

const ALERTS = [{
  id: 'al-1', organization_id: 'org-1', source: 'SLO', source_id: 'e1', slo_id: 'slo-1',
  severity: 'CRITICAL', status: 'OPEN', agent_id: null, agent_version_id: null, environment_id: null,
  execution_id: null, trace_id: null, metric: 'success_rate', threshold_value: 0.99, observed_value: 0.95,
  baseline_value: null, title: 'SLO breached: prod success rate', summary: 'observed 0.95 below target 0.99',
  dedup_key: 'slo:slo-1', context: {}, recurrence_count: 1, opened_at: '2026-09-01T00:00:00Z',
  last_seen_at: '2026-09-01T00:00:00Z', acknowledged_at: null, acknowledged_by: null,
  resolved_at: null, resolved_by: null, suppressed_at: null, updated_at: '2026-09-01T00:00:00Z',
}]

const EFFECTIVE = {
  mode: 'METADATA_ONLY', source: 'platform-default', policy_id: null, matched_scope: {},
  reason: 'no policy matched; platform default', considered: [],
  precedence: 'classification > agent > environment > tenant > platform-default',
}
const RETENTION = {
  trace_content: { telemetry_class: 'trace_content', retention_days: 30, enabled: true, source: 'platform-default', floor_days: 1, retain_only: false },
  financial_record: { telemetry_class: 'financial_record', retention_days: 2555, enabled: true, source: 'platform-default', floor_days: 365, retain_only: true },
}
const COST = {
  window_start: '2026-08-01T00:00:00Z', window_end: '2026-09-01T00:00:00Z',
  actual_amount: 100.5, estimated_amount: 12.25, execution_count: 42, total_tokens: 9999,
  unpriced_execution_count: 3, currency: 'USD', dimension: 'agent',
  buckets: [{ key: 'a1', label: 'Billing', actual_amount: 80, estimated_amount: 12.25, execution_count: 30, total_tokens: 5000, currency: 'USD' }],
}
const BUDGETS = [{
  id: 'b1', organization_id: 'org-1', name: 'Prod monthly', description: null, scope_type: 'ORGANIZATION',
  scope_id: null, scope_value: null, mode: 'HARD_LIMIT', period: 'MONTHLY', limit_amount: 500,
  currency: 'USD', threshold_percent: 80, enabled: true,
}]
const BUDGET_UTIL = {
  budget_id: 'b1', mode: 'HARD_LIMIT', period: 'MONTHLY', period_key: '2026-09', limit_amount: 500,
  reserved: 10, spent: 450, committed: 460, remaining: 40, utilization_percent: 92, threshold_percent: 80,
  over_threshold: true, currency: 'USD',
}

// =========================================================================== //
// AC-01 — all nine views render
// =========================================================================== //
describe('AC-01 — the nine views', () => {
  it('Runtime Overview renders from GET /runtime/overview', async () => {
    wrap(<RuntimeOverviewPage />)
    expect(await screen.findByRole('heading', { name: 'Runtime Overview' })).toBeTruthy()
    await waitFor(() => expect(obs.overview).toHaveBeenCalled())
  })
  it('Trace Explorer renders from GET /observability/traces', async () => {
    wrap(<TraceExplorerPage />)
    await waitFor(() => expect(obs.traces).toHaveBeenCalled())
    expect(await screen.findByText(/exec-1/)).toBeTruthy()
  })
  it('Cost Center renders from GET /cost/summary', async () => {
    wrap(<CostCenterPage />)
    await waitFor(() => expect(obs.costSummary).toHaveBeenCalled())
  })
  it('Governance Decisions renders from the read model', async () => {
    wrap(<GovernanceDecisionsPage />)
    await waitFor(() => expect(obs.governanceDecisions).toHaveBeenCalled())
    expect(await screen.findByText('STOP')).toBeTruthy()
  })
  it('Behavior renders from GET /behavior/findings', async () => {
    wrap(<BehaviorAnomaliesPage />)
    await waitFor(() => expect(obs.findings).toHaveBeenCalled())
  })
  it('SLO Dashboard renders from GET /slos', async () => {
    wrap(<SloDashboardPage />)
    await waitFor(() => expect(obs.slos).toHaveBeenCalled())
    expect(await screen.findByText('prod success rate')).toBeTruthy()
  })
  it('Alert Center renders from GET /alerts', async () => {
    wrap(<AlertCenterPage />)
    await waitFor(() => expect(obs.alerts).toHaveBeenCalled())
  })
  it('Telemetry Policy renders from the 4.8 endpoints', async () => {
    wrap(<TelemetryPolicyPage />)
    await waitFor(() => expect(obs.capturePolicies).toHaveBeenCalled())
    await waitFor(() => expect(obs.retentionPolicies).toHaveBeenCalled())
  })
})

// =========================================================================== //
// AC-02 — per-persona assembly
// =========================================================================== //
describe('AC-02 — per persona, not one dashboard', () => {
  it('a persona sees a subset of the views, and no persona sees them all except via "all"', () => {
    const finops = viewsForPersona('finops').map((v) => v.key)
    const sre = viewsForPersona('sre').map((v) => v.key)
    expect(finops).toContain('cost')
    expect(finops).not.toContain('policy')
    expect(sre).toContain('alerts')
    expect(sre).not.toContain('cost')
    expect(viewsForPersona('all')).toHaveLength(OBS_VIEWS.length)
  })
  it('the nav hides a view the persona lens excludes', async () => {
    wrap(<RuntimeOverviewPage />)
    const select = await screen.findByLabelText('Persona')
    await userEvent.selectOptions(select, 'finops')
    await waitFor(() => expect(screen.queryByRole('link', { name: /Telemetry Policy/ })).toBeNull())
    expect(screen.getByRole('link', { name: /Cost Center/ })).toBeTruthy()
  })
})

// =========================================================================== //
// AC-03 — Runtime Overview shows real state
// =========================================================================== //
describe('AC-03 / AC-13 — Runtime Overview truthful state', () => {
  it('shows failures, critical alerts, breached SLOs, anomalies and a degraded exporter', async () => {
    wrap(<RuntimeOverviewPage />)
    expect(await screen.findByText('Failed (24h)')).toBeTruthy()
    expect(screen.getByText('Active alerts')).toBeTruthy()
    expect(screen.getByText(/1 critical/)).toBeTruthy()
    expect(screen.getByText(/exporter is degraded/i)).toBeTruthy()
  })
  it('renders an insufficient-data success rate as such, never 0%', async () => {
    obs.overview.mockResolvedValue({
      ...OVERVIEW,
      executions: { ...OVERVIEW.executions, success_rate: null, success_rate_insufficient_data: true },
    })
    wrap(<RuntimeOverviewPage />)
    expect(await screen.findByText('insufficient data')).toBeTruthy()
    expect(screen.queryByText('0%')).toBeNull()
  })
  it('exporter health comes from 4.6\'s own endpoint, not the runtime overview composite', async () => {
    wrap(<RuntimeOverviewPage />)
    await waitFor(() => expect(obs.exporterHealth).toHaveBeenCalled())
    expect(await screen.findByText(/exporter is degraded/i)).toBeTruthy()
  })
})

// =========================================================================== //
// AC-05 / AC-06 / AC-07 — the content-governance set
// =========================================================================== //
describe('content governance (§4.3)', () => {
  it('AC-05 — a metadata-only user never sees the content pane, only a gated message', async () => {
    permissions = ['runtime.telemetry.view'] // no runtime.trace.content.view
    wrap(<TraceDetailPage />)
    expect(await screen.findByText(/Content view requires an additional permission/i)).toBeTruthy()
    // no "View content" button, and the content endpoint is never called
    expect(screen.queryByRole('button', { name: /View content/i })).toBeNull()
    await waitFor(() => expect(obs.executionTrace).toHaveBeenCalled())
    expect(obs.traceContent).not.toHaveBeenCalled()
  })

  it('AC-06 — content is fetched only through the 4.8 endpoint, on explicit request', async () => {
    obs.traceContent.mockResolvedValue(contentView())
    wrap(<TraceDetailPage />)
    const btn = await screen.findByRole('button', { name: /View content/i })
    expect(obs.traceContent).not.toHaveBeenCalled() // not on load
    await userEvent.click(btn)
    await waitFor(() => expect(obs.traceContent).toHaveBeenCalledWith('trace-1'))
    expect(await screen.findByText(/secret scrubbed/i)).toBeTruthy()
  })

  it('AC-07 — METADATA_ONLY capture reads as "no content captured", not an error', async () => {
    obs.traceContent.mockResolvedValue(contentView({ mode: 'METADATA_ONLY', captured: false, items: [], note: undefined }))
    wrap(<TraceDetailPage />)
    await userEvent.click(await screen.findByRole('button', { name: /View content/i }))
    const msg = await screen.findByText(/no execution content was captured/i)
    expect(msg).toBeTruthy()
    // it is framed as the policy working, not a fault
    expect(msg.textContent).toMatch(/policy working, not an error/i)
  })

  it('AC-07 — DISABLED capture reads truthfully', async () => {
    obs.traceContent.mockResolvedValue(contentView({ mode: 'DISABLED', captured: false, items: [], note: undefined }))
    wrap(<TraceDetailPage />)
    await userEvent.click(await screen.findByRole('button', { name: /View content/i }))
    expect(await screen.findByText(/Telemetry is DISABLED for this scope/i)).toBeTruthy()
  })

  it('AC-07/AC-11 — a 403 from the content endpoint is a distinct gated state, not a generic failure', async () => {
    obs.traceContent.mockRejectedValue({ status: 403, code: 'TRACE_CONTENT_ACCESS_DENIED', message: 'denied' })
    wrap(<TraceDetailPage />)
    await userEvent.click(await screen.findByRole('button', { name: /View content/i }))
    expect(await screen.findByText(/does not hold/i)).toBeTruthy()
  })

  it('AC-11 — a 404 is "trace not found", distinct from the 403', async () => {
    obs.traceContent.mockRejectedValue({ status: 404, code: 'TRACE_NOT_FOUND', message: 'not found' })
    wrap(<TraceDetailPage />)
    await userEvent.click(await screen.findByRole('button', { name: /View content/i }))
    expect(await screen.findByText(/was not found for your organization/i)).toBeTruthy()
  })
})

// =========================================================================== //
// AC-08 / AC-09
// =========================================================================== //
describe('AC-08 / AC-09 — cost, governance, behavior', () => {
  it('Cost Center keeps actual and estimated separate and counts unpriced', async () => {
    wrap(<CostCenterPage />)
    expect(await screen.findByText('$100.50')).toBeTruthy()   // actual
    expect(screen.getByText('$12.25')).toBeTruthy()           // estimated
    expect(screen.getByText('Unpriced executions')).toBeTruthy()
  })
  it('Governance Decisions shows checkpoint, decision and templated reason', async () => {
    wrap(<GovernanceDecisionsPage />)
    await waitFor(() => expect(obs.governanceDecisions).toHaveBeenCalled())
    expect(await screen.findByText('COST_CEILING_EXCEEDED')).toBeTruthy()
    expect(screen.getByText('Cost ceiling of $5.00 exceeded.')).toBeTruthy()
    expect(screen.getAllByText('STOP').length).toBeGreaterThan(0)
  })
  it('Behavior shows INSUFFICIENT_DATA as its own state', async () => {
    wrap(<BehaviorAnomaliesPage />)
    await waitFor(() => expect(obs.findings).toHaveBeenCalled())
    expect(await screen.findByText(/only 4 executions/i)).toBeTruthy()
  })
})

// =========================================================================== //
// AC-10 — SLO + alert actions
// =========================================================================== //
describe('AC-10 / AC-12 — SLO dashboard and guarded alert actions', () => {
  it('SLO Dashboard shows a burned budget as "spent"', async () => {
    wrap(<SloDashboardPage />)
    expect(await screen.findByText(/budget spent/i)).toBeTruthy()
    expect(screen.getByText('BREACHED')).toBeTruthy()
  })
  it('acknowledge dispatches straight to the 4.7 endpoint', async () => {
    wrap(<AlertCenterPage />)
    await userEvent.click(await screen.findByRole('button', { name: /Acknowledge/ }))
    await waitFor(() => expect(obs.acknowledgeAlert).toHaveBeenCalledWith('al-1'))
  })
  it('suppress is confirmation-gated with a required reason', async () => {
    wrap(<AlertCenterPage />)
    await userEvent.click(await screen.findByRole('button', { name: /Suppress/ }))
    // dialog appears; the confirm button is disabled until a reason is typed
    const confirm = await screen.findByRole('button', { name: /Suppress alert/ })
    expect(confirm).toBeDisabled()
    expect(obs.suppressAlert).not.toHaveBeenCalled()
    await userEvent.type(screen.getByLabelText(/Why is this condition expected/i), 'known load test')
    expect(screen.getByRole('button', { name: /Suppress alert/ })).not.toBeDisabled()
  })
  it('a manage-less user is not offered the lifecycle actions', async () => {
    permissions = ['runtime.telemetry.view']
    wrap(<AlertCenterPage />)
    expect(await screen.findByText('view only')).toBeTruthy()
    expect(screen.queryByRole('button', { name: /Acknowledge/ })).toBeNull()
    expect(screen.queryByRole('button', { name: /^Suppress$/ })).toBeNull()
  })
})

// =========================================================================== //
// AC-11 (policy) — dangerous telemetry actions
// =========================================================================== //
describe('AC-11 / AC-12 — Telemetry Policy dangerous actions', () => {
  it('raising capture to FULL_CONTENT is type-to-confirm and does not fire until confirmed', async () => {
    wrap(<TelemetryPolicyPage />)
    await screen.findByText('Capture policies')
    await userEvent.selectOptions(screen.getByLabelText('New capture mode'), 'FULL_CONTENT')
    await userEvent.click(screen.getByRole('button', { name: 'Add policy' }))
    expect(await screen.findByText(/persists prompts, tool arguments/i)).toBeTruthy()
    const confirm = screen.getByRole('button', { name: /Enable FULL CONTENT/ })
    expect(confirm).toBeDisabled()
    expect(obs.createCapturePolicy).not.toHaveBeenCalled()
    await userEvent.type(screen.getByLabelText(/Type .* to confirm/i), 'FULL_CONTENT')
    await userEvent.click(screen.getByRole('button', { name: /Enable FULL CONTENT/ }))
    await waitFor(() => expect(obs.createCapturePolicy).toHaveBeenCalledWith({ mode: 'FULL_CONTENT' }))
  })
  it('METADATA_ONLY (not more capture) is a plain action, no confirmation', async () => {
    wrap(<TelemetryPolicyPage />)
    await screen.findByText('Capture policies')
    await userEvent.click(screen.getByRole('button', { name: 'Add policy' })) // default METADATA_ONLY
    await waitFor(() => expect(obs.createCapturePolicy).toHaveBeenCalledWith({ mode: 'METADATA_ONLY' }))
  })
  it('running retention is confirmation-gated', async () => {
    wrap(<TelemetryPolicyPage />)
    await userEvent.click(await screen.findByRole('button', { name: /Run retention sweep/ }))
    expect(await screen.findByText(/permanently deletes telemetry/i)).toBeTruthy()
    expect(obs.runRetention).not.toHaveBeenCalled()
  })
  it('a manage-less user sees policy state but no write controls', async () => {
    permissions = ['runtime.telemetry_policy.view']
    wrap(<TelemetryPolicyPage />)
    await screen.findByText('Capture policies')
    expect(screen.queryByRole('button', { name: 'Add policy' })).toBeNull()
    expect(screen.queryByRole('button', { name: /Run retention sweep/ })).toBeNull()
  })
})

// =========================================================================== //
// AC-15 / AC-17
// =========================================================================== //
describe('AC-15 / AC-17 — hygiene', () => {
  it('the service exposes exactly one content route, and it is the 4.8 audited endpoint', () => {
    const src = readFileSync(SERVICE_FILE, 'utf-8')
    // exactly one apiClient call whose path ends in /content
    const apiContentCalls = src.match(/apiClient\.\w+<[^>]*>\(`[^`]*\/content`/g) ?? []
    expect(apiContentCalls).toHaveLength(1)
    expect(apiContentCalls[0]).toContain('/traces/${traceId}/content')
  })
  it('no TODO / FIXME / skip markers in the module', () => {
    const base = MODULE_DIR
    for (const f of [
      'RuntimeOverviewPage.tsx', 'TraceExplorerPage.tsx', 'TraceDetailPage.tsx',
      'CostCenterPage.tsx', 'GovernanceDecisionsPage.tsx', 'BehaviorAnomaliesPage.tsx',
      'SloDashboardPage.tsx', 'AlertCenterPage.tsx', 'TelemetryPolicyPage.tsx',
      'personas.ts', 'components/ObservabilityNav.tsx', 'components/badges.tsx',
    ]) {
      const src = readFileSync(`${base}/${f}`, 'utf-8')
      expect(src).not.toMatch(/TODO|FIXME|NotImplemented|\.skip\(|\.only\(|xit\(/)
    }
  })
})
