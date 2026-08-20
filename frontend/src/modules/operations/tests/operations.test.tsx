// Phase 3.10 frontend tests — the Release Operations Center.
//
// Grouped by the build prompt's own §12 acceptance criteria. The sharpest
// tests here are the ones about *honesty*: that a kill switch, a BLOCK verdict
// and INSUFFICIENT_DATA health are shown rather than smoothed over, and that a
// dangerous action cannot fire without an explicit confirmation. Those are the
// two properties that make this UI trustworthy at 3am, and the two that would
// be invisible if only the happy path were tested.
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import type { ReactNode } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const svc = {
  overview: vi.fn(),
  releaseHistory: vi.fn(),
  deploymentDetail: vi.fn(),
  rollouts: vi.fn(),
  rollout: vi.fn(),
  rolloutHealth: vi.fn(),
  advanceRollout: vi.fn(),
  pauseRollout: vi.fn(),
  resumeRollout: vi.fn(),
  abortRollout: vi.fn(),
  requestRolloutRollback: vi.fn(),
  traffic: vi.fn(),
  trafficHistory: vi.fn(),
  setTraffic: vi.fn(),
  preflight: vi.fn(),
  runPreflight: vi.fn(),
  preflightHistory: vi.fn(),
  environments: vi.fn(),
  promotionPaths: vi.fn(),
  promote: vi.fn(),
  rollbackHistory: vi.fn(),
  executeRollback: vi.fn(),
  forceRollback: vi.fn(),
  pauseDeployment: vi.fn(),
  resumeDeployment: vi.fn(),
  fleet: vi.fn(),
  queueDepth: vi.fn(),
  drainWorker: vi.fn(),
  reapFleet: vi.fn(),
  jobs: vi.fn(),
  jobRuns: vi.fn(),
  setJobEnabled: vi.fn(),
}
vi.mock('@/services', () => ({ operationsService: svc, runtimeService: {} }))
vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn(), message: vi.fn() },
  Toaster: () => null,
}))

const permissions: string[] = []
vi.mock('@/hooks/useAuth', () => ({
  useAuth: () => ({
    user: { id: 'u1', organization_id: 'org-1', name: 'Owner', email: 'owner@example.com' },
    permissions,
  }),
}))

const { ReleaseOverviewPage } = await import('../ReleaseOverviewPage')
const { EnvironmentMatrixPage } = await import('../EnvironmentMatrixPage')
const { ReleaseHistoryPage } = await import('../ReleaseHistoryPage')
const { OperationsDeploymentDetailPage } = await import('../OperationsDeploymentDetailPage')
const { RolloutsPage } = await import('../RolloutsPage')
const { CanaryDashboardPage } = await import('../CanaryDashboardPage')
const { TrafficAllocationPage } = await import('../TrafficAllocationPage')
const { HealthGatesPage } = await import('../HealthGatesPage')
const { PromotionWizardPage } = await import('../PromotionWizardPage')
const { RollbackWizardPage } = await import('../RollbackWizardPage')
const { WorkerFleetPage } = await import('../WorkerFleetPage')
const { SchedulerJobsPage } = await import('../SchedulerJobsPage')
const { PermissionProvider } = await import('@/authorization')

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom')
  return { ...actual, useParams: () => ({ id: 'dep-1' }) }
})

/**
 * Choose an option that arrives asynchronously.
 *
 * These selects are populated from a react-query result, so the element exists
 * on first paint while its options do not. Selecting immediately fails with
 * "value not found in options" — a race in the test, not in the page.
 */
async function selectWhenReady(labelText: RegExp, value: string) {
  const select = await screen.findByLabelText(labelText)
  await waitFor(() => {
    expect(within(select as HTMLSelectElement).getByRole('option', { name: (_, el) =>
      (el as HTMLOptionElement).value === value })).toBeTruthy()
  })
  await userEvent.selectOptions(select, value)
  return select
}

function wrap(children: ReactNode) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <PermissionProvider>{children}</PermissionProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

// --------------------------------------------------------------------------- //
// Fixtures
// --------------------------------------------------------------------------- //
const VERSION = {
  id: 'v-2', semantic_version: '2.0.0', status: 'PUBLISHED',
  checksum: 'abc123def456', checksum_algorithm: 'SHA256',
  signature_id: 'sig-1', signed_at: '2026-08-19T10:00:00Z',
  manifest_digest: 'digest-1', signature_state: 'SIGNED' as const,
  rollback_target_id: 'v-1',
}

const HEALTHY_ROW = {
  deployment_id: 'dep-1', agent_id: 'agent-1', agent_name: 'Billing Assistant',
  agent_lifecycle_status: 'ACTIVE', kill_switch_active: false,
  environment_id: 'env-1', environment_name: 'PRODUCTION', is_production: true,
  version: VERSION, deployment_strategy: 'CANARY', status: 'ACTIVE',
  lifecycle_state: 'ACTIVE', revision: 3, state_reason: null, servable: true,
  traffic_weight: 100, health_status: 'HEALTHY',
  release_health: { health_state: 'HEALTHY', is_proving: true, sample_count: 250, metrics: {}, evaluated_at: null },
  gate_verdict: 'PASS' as const, gate_evaluated_at: null, active_rollout: null,
  deployed_at: '2026-08-19T09:00:00Z', updated_at: null,
}

const KILLED_ROW = {
  ...HEALTHY_ROW,
  deployment_id: 'dep-2', agent_id: 'agent-2', agent_name: 'Risk Scorer',
  agent_lifecycle_status: 'SUSPENDED', kill_switch_active: true,
  environment_id: 'env-2', environment_name: 'STAGING', is_production: false,
  gate_verdict: 'BLOCK' as const, servable: false, traffic_weight: null,
  release_health: {
    health_state: 'INSUFFICIENT_DATA', is_proving: false, sample_count: 2, metrics: {}, evaluated_at: null,
  },
}

const OVERVIEW = {
  deployments: [HEALTHY_ROW, KILLED_ROW],
  environments: [
    { id: 'env-1', name: 'PRODUCTION', display_name: 'Production', is_production: true },
    { id: 'env-2', name: 'STAGING', display_name: 'Staging', is_production: false },
  ],
  summary: { total: 2, serving: 1, kill_switched: 1, blocked: 1, rolling_out: 0 },
}

const DETAIL = {
  deployment_id: 'dep-1',
  agent: { id: 'agent-1', name: 'Billing Assistant', lifecycle_status: 'ACTIVE' },
  kill_switch_active: false, version: VERSION,
  rollback_target: { ...VERSION, id: 'v-1', semantic_version: '1.4.2' },
  environment: { id: 'env-1', name: 'PRODUCTION', is_production: true },
  deployment_strategy: 'CANARY', status: 'ACTIVE', lifecycle_state: 'ACTIVE',
  revision: 3, state_reason: null, servable: true, health_status: 'HEALTHY',
  release_health: { health_state: 'HEALTHY', is_proving: true, sample_count: 250, metrics: {}, evaluated_at: null },
  gate: {
    verdict: 'PASS',
    findings: [{ code: 'PREFLIGHT_SIGNATURE_VERIFIED', severity: 'PASS', message: 'Signature verified.' }],
    evaluated_at: '2026-08-19T09:30:00Z',
  },
  allocation: {
    revision: 4,
    weights: [{ agent_version_id: 'v-2', semantic_version: '2.0.0', weight: 100 }],
    updated_at: null,
  },
  rollout: null, approvals: [], initiated_by: 'user-abc',
  deployed_at: '2026-08-19T09:00:00Z', retired_at: null, updated_at: null,
  duration_seconds: null,
  timeline: [{
    id: 'ev-1', kind: 'LIFECYCLE' as const, event_type: 'DEPLOYMENT_SUCCEEDED',
    from_state: 'DEPLOYING', to_state: 'ACTIVE', reason: null, actor_id: 'user-abc',
    occurred_at: '2026-08-19T09:00:00Z',
  }],
}

beforeEach(() => {
  vi.clearAllMocks()
  permissions.length = 0
  permissions.push(
    'runtime.deployment.view', 'runtime.deployment.deploy', 'runtime.deployment.rollback',
    'runtime.environment.view', 'runtime.worker.view', 'runtime.worker.manage',
    'runtime.scheduler.view', 'runtime.scheduler.manage',
  )
  svc.overview.mockResolvedValue(OVERVIEW)
  svc.deploymentDetail.mockResolvedValue(DETAIL)
  svc.releaseHistory.mockResolvedValue([])
  svc.rollouts.mockResolvedValue([])
  svc.environments.mockResolvedValue(OVERVIEW.environments)
  svc.promotionPaths.mockResolvedValue([])
  svc.rollbackHistory.mockResolvedValue([])
  svc.traffic.mockResolvedValue(null)
  svc.trafficHistory.mockResolvedValue([])
  svc.preflight.mockResolvedValue(null)
  svc.preflightHistory.mockResolvedValue([])
  svc.fleet.mockResolvedValue({ workers: [], capacity_by_cohort: {} })
  svc.queueDepth.mockResolvedValue({
    queued: 0, running: 0, workers: 0, workers_accepting_work: 0,
    capacity: 0, active: 0, available_slots: 0,
  })
  svc.jobs.mockResolvedValue([])
  svc.jobRuns.mockResolvedValue([])
})

// --------------------------------------------------------------------------- //
// AC-01 — all twelve views render from their endpoints
// --------------------------------------------------------------------------- //
describe('AC-01 — the twelve operational views', () => {
  it('renders the deployment overview from the aggregation endpoint', async () => {
    wrap(<ReleaseOverviewPage />)
    expect(await screen.findByText('Billing Assistant')).toBeInTheDocument()
    expect(screen.getByText('Risk Scorer')).toBeInTheDocument()
    expect(svc.overview).toHaveBeenCalled()
  })

  it('renders the environment matrix pivoted by environment', async () => {
    wrap(<EnvironmentMatrixPage />)
    expect(await screen.findByRole('columnheader', { name: /Production/ })).toBeInTheDocument()
    expect(screen.getByRole('rowheader', { name: 'Billing Assistant' })).toBeInTheDocument()
  })

  it('renders release history', async () => {
    svc.releaseHistory.mockResolvedValue([{
      id: 'ev-1', kind: 'LIFECYCLE', event_type: 'DEPLOYMENT_SUCCEEDED',
      from_state: 'DEPLOYING', to_state: 'ACTIVE', reason: 'Shipped.',
      actor_id: 'user-abc', occurred_at: '2026-08-19T09:00:00Z',
      deployment_id: 'dep-1', agent_id: 'agent-1', agent_name: 'Billing Assistant',
      environment_name: 'PRODUCTION',
    }])
    wrap(<ReleaseHistoryPage />)
    expect(await screen.findByText('DEPLOYMENT SUCCEEDED')).toBeInTheDocument()
    expect(screen.getByText('Shipped.')).toBeInTheDocument()
  })

  it('renders the rollout list', async () => {
    svc.rollouts.mockResolvedValue([{
      id: 'ro-1', kind: 'CANARY', state: 'IN_PROGRESS', current_stage_index: 1,
      state_reason: null, agent_id: 'agent-1', agent_name: 'Billing Assistant',
      environment_id: 'env-1', environment_name: 'PRODUCTION',
      candidate_version: '2.0.0', stable_version: '1.4.2', stage_count: 3,
      is_live: true, created_at: null, updated_at: null,
    }])
    wrap(<RolloutsPage />)
    expect(await screen.findByText('Billing Assistant')).toBeInTheDocument()
    expect(screen.getByText('2 / 3')).toBeInTheDocument()
  })

  it('renders the worker fleet from /fleet', async () => {
    svc.fleet.mockResolvedValue({
      workers: [{
        worker_id: 'host-abc123', cohort: '01-primary', status: 'RUNNING',
        concurrency: 4, active_count: 2, hostname: 'host', heartbeat_at: null,
        registered_at: null, stopped_at: null,
      }],
      capacity_by_cohort: { '01-primary': 4 },
    })
    wrap(<WorkerFleetPage />)
    expect(await screen.findByText('host-abc123')).toBeInTheDocument()
    expect(screen.getByText('01-primary: 4 slots')).toBeInTheDocument()
  })

  it('renders scheduler jobs and their run history', async () => {
    svc.jobs.mockResolvedValue([{
      id: 'job-1', organization_id: null, name: 'connector-health-sweep',
      handler_key: 'integration.connector_health_sweep', schedule_kind: 'INTERVAL',
      schedule_spec: { interval_seconds: 300 }, params: {}, enabled: true,
      timeout_seconds: 300, retry_policy: {}, concurrency_policy: 'NO_OVERLAP',
      next_run_at: null, last_claimed_at: null,
    }])
    wrap(<SchedulerJobsPage />)
    expect(await screen.findByText('connector-health-sweep')).toBeInTheDocument()
    expect(screen.getByText('ENABLED')).toBeInTheDocument()
  })
})

// --------------------------------------------------------------------------- //
// AC-02 — deployment detail carries the §22 field set
// --------------------------------------------------------------------------- //
describe('AC-02 — deployment detail', () => {
  it('surfaces the immutable version identity including checksum and signature', async () => {
    wrap(<OperationsDeploymentDetailPage />)
    expect(await screen.findByText('Version identity')).toBeInTheDocument()
    expect(screen.getByText('abc123def456')).toBeInTheDocument()
    expect(screen.getByText('SIGNED')).toBeInTheDocument()
    // The rollback target is part of knowing where this can go back to.
    expect(screen.getByText('1.4.2')).toBeInTheDocument()
  })

  it('renders the traffic allocation, approvals section and event timeline', async () => {
    wrap(<OperationsDeploymentDetailPage />)
    expect(await screen.findByText('Traffic allocation')).toBeInTheDocument()
    expect(screen.getByText('Event timeline')).toBeInTheDocument()
    expect(screen.getByText('DEPLOYMENT SUCCEEDED')).toBeInTheDocument()
  })

  it('calls out an unsigned artifact rather than leaving the field blank', async () => {
    svc.deploymentDetail.mockResolvedValue({
      ...DETAIL,
      version: { ...VERSION, signature_id: null, signed_at: null, signature_state: 'UNSIGNED' },
    })
    wrap(<OperationsDeploymentDetailPage />)
    expect(await screen.findByText('UNSIGNED')).toBeInTheDocument()
  })
})

// --------------------------------------------------------------------------- //
// AC-10 — truthful state (the property that makes this UI trustworthy)
// --------------------------------------------------------------------------- //
describe('AC-10 — the UI never presents an unsafe release as safe', () => {
  it('shows an active kill switch on the overview', async () => {
    wrap(<ReleaseOverviewPage />)
    expect(await screen.findByText('Risk Scorer')).toBeInTheDocument()
    expect(screen.getAllByText('KILL SWITCH').length).toBeGreaterThan(0)
    expect(screen.getByRole('alert')).toHaveTextContent(/kill switch/i)
  })

  it('shows a BLOCK verdict as blocking, never softened', async () => {
    wrap(<ReleaseOverviewPage />)
    expect(await screen.findByText('BLOCK')).toBeInTheDocument()
  })

  it('renders INSUFFICIENT_DATA as a warning, not as a neutral or healthy state', async () => {
    wrap(<ReleaseOverviewPage />)
    // The absence of evidence must be visible as such — Phase 3.5's rule,
    // carried into the UI.
    const badge = await screen.findByText('INSUFFICIENT DATA')
    expect(badge).toBeInTheDocument()
    expect(badge.closest('[title]')?.getAttribute('title')).toMatch(/not evidence of health/i)
  })

  it('marks a non-servable deployment as not serving', async () => {
    wrap(<ReleaseOverviewPage />)
    expect(await screen.findByText('NOT SERVING')).toBeInTheDocument()
  })

  it('shows every blocker on the detail view, not just the worst one', async () => {
    svc.deploymentDetail.mockResolvedValue({
      ...DETAIL,
      kill_switch_active: true,
      gate: { verdict: 'BLOCK', findings: [], evaluated_at: null },
      release_health: {
        health_state: 'INSUFFICIENT_DATA', is_proving: false, sample_count: 1,
        metrics: {}, evaluated_at: null,
      },
    })
    wrap(<OperationsDeploymentDetailPage />)
    const banner = await screen.findByRole('alert')
    expect(banner).toHaveTextContent(/Kill switch active/i)
    expect(banner).toHaveTextContent(/Release gate blocked/i)
    expect(banner).toHaveTextContent(/Health INSUFFICIENT_DATA/i)
  })
})

// --------------------------------------------------------------------------- //
// AC-09 — dangerous actions require explicit confirmation
// --------------------------------------------------------------------------- //
describe('AC-09 — dangerous actions are confirmation-gated', () => {
  it('does not roll back on the first click — it opens a confirmation', async () => {
    const user = userEvent.setup()
    wrap(<OperationsDeploymentDetailPage />)
    await user.click(await screen.findByRole('button', { name: /Roll back/i }))

    expect(await screen.findByRole('dialog')).toBeInTheDocument()
    // The crucial assertion: nothing has been dispatched yet.
    expect(svc.executeRollback).not.toHaveBeenCalled()
  })

  it('keeps the confirm button disabled until the environment name is typed', async () => {
    const user = userEvent.setup()
    wrap(<OperationsDeploymentDetailPage />)
    await user.click(await screen.findByRole('button', { name: /Roll back/i }))

    const dialog = await screen.findByRole('dialog')
    const confirm = within(dialog).getByRole('button', { name: /Roll back now/i })
    expect(confirm).toBeDisabled()

    await user.type(within(dialog).getByLabelText(/Reason/i), 'Error rate spiked.')
    expect(confirm).toBeDisabled()  // reason alone is not enough

    await user.type(within(dialog).getByLabelText(/Type PRODUCTION to confirm/i), 'PRODUCTION')
    expect(confirm).toBeEnabled()

    await user.click(confirm)
    await waitFor(() => expect(svc.executeRollback).toHaveBeenCalledWith('dep-1', 'Error rate spiked.'))
  })

  it('cancelling dispatches nothing', async () => {
    const user = userEvent.setup()
    wrap(<OperationsDeploymentDetailPage />)
    await user.click(await screen.findByRole('button', { name: /Roll back/i }))
    const dialog = await screen.findByRole('dialog')
    await user.click(within(dialog).getByRole('button', { name: /Cancel/i }))
    expect(svc.executeRollback).not.toHaveBeenCalled()
  })

  it('gates draining a worker behind a confirmation', async () => {
    const user = userEvent.setup()
    svc.fleet.mockResolvedValue({
      workers: [{
        worker_id: 'host-abc123', cohort: 'default', status: 'RUNNING',
        concurrency: 4, active_count: 2, hostname: 'host', heartbeat_at: null,
        registered_at: null, stopped_at: null,
      }],
      capacity_by_cohort: { default: 4 },
    })
    wrap(<WorkerFleetPage />)
    await user.click(await screen.findByRole('button', { name: /^Drain$/i }))

    const dialog = await screen.findByRole('dialog')
    expect(dialog).toHaveTextContent(/finishes what it is already running/i)
    expect(svc.drainWorker).not.toHaveBeenCalled()

    await user.click(within(dialog).getByRole('button', { name: /Drain worker/i }))
    await waitFor(() => expect(svc.drainWorker).toHaveBeenCalledWith('host-abc123'))
  })

  it('requires typing ABORT before aborting a rollout', async () => {
    const user = userEvent.setup()
    svc.rollout.mockResolvedValue({
      id: 'ro-1', kind: 'CANARY', agent_id: 'agent-1', environment_id: 'env-1',
      candidate_version_id: 'v-2', stable_version_id: 'v-1', state: 'IN_PROGRESS',
      current_stage_index: 0, state_reason: null, revision: 2,
      stages: [{
        stage_index: 0, target_weight: 25, min_duration_seconds: 0, min_samples: 10,
        health_requirement: 'HEALTHY', advance_mode: 'MANUAL', entered_at: null,
      }],
    })
    svc.rolloutHealth.mockResolvedValue(null)
    wrap(<CanaryDashboardPage />)

    await user.click(await screen.findByRole('button', { name: /^Abort$/i }))
    const dialog = await screen.findByRole('dialog')
    const confirm = within(dialog).getByRole('button', { name: /Abort rollout/i })
    expect(confirm).toBeDisabled()
    expect(svc.abortRollout).not.toHaveBeenCalled()
  })
})

// --------------------------------------------------------------------------- //
// AC-11 — unauthorized actions are not offered as succeed-able
// --------------------------------------------------------------------------- //
describe('AC-11 — the UI reflects permissions (the server still enforces)', () => {
  it('hides the rollback control from a user without the permission', async () => {
    permissions.length = 0
    permissions.push('runtime.deployment.view')
    wrap(<OperationsDeploymentDetailPage />)
    await screen.findByText('Version identity')
    expect(screen.queryByRole('button', { name: /Roll back/i })).not.toBeInTheDocument()
  })

  it('hides worker drain controls without runtime.worker.manage', async () => {
    permissions.length = 0
    permissions.push('runtime.worker.view')
    svc.fleet.mockResolvedValue({
      workers: [{
        worker_id: 'host-abc123', cohort: 'default', status: 'RUNNING',
        concurrency: 1, active_count: 0, hostname: null, heartbeat_at: null,
        registered_at: null, stopped_at: null,
      }],
      capacity_by_cohort: { default: 1 },
    })
    wrap(<WorkerFleetPage />)
    expect(await screen.findByText('host-abc123')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /^Drain$/i })).not.toBeInTheDocument()
  })

  it('hides scheduler enable/disable without runtime.scheduler.manage', async () => {
    permissions.length = 0
    permissions.push('runtime.scheduler.view')
    svc.jobs.mockResolvedValue([{
      id: 'job-1', organization_id: 'org-1', name: 'nightly-sweep',
      handler_key: 'platform.expired_state_cleanup', schedule_kind: 'INTERVAL',
      schedule_spec: {}, params: {}, enabled: true, timeout_seconds: 300,
      retry_policy: {}, concurrency_policy: 'NO_OVERLAP',
      next_run_at: null, last_claimed_at: null,
    }])
    wrap(<SchedulerJobsPage />)
    expect(await screen.findByText('nightly-sweep')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Disable/i })).not.toBeInTheDocument()
  })
})

// --------------------------------------------------------------------------- //
// AC-12 — concurrency conflicts surface gracefully
// --------------------------------------------------------------------------- //
describe('AC-12 — a conflict is explained, not retried', () => {
  it('surfaces ROLLOUT_CONFLICT without re-dispatching the stale intent', async () => {
    const { toast } = await import('sonner')
    const user = userEvent.setup()
    svc.executeRollback.mockRejectedValue({
      status: 409, code: 'ROLLOUT_CONFLICT', message: 'This rollout was modified by another request.',
    })
    wrap(<OperationsDeploymentDetailPage />)

    await user.click(await screen.findByRole('button', { name: /Roll back/i }))
    const dialog = await screen.findByRole('dialog')
    await user.type(within(dialog).getByLabelText(/Reason/i), 'Rolling back.')
    await user.type(within(dialog).getByLabelText(/Type PRODUCTION to confirm/i), 'PRODUCTION')
    await user.click(within(dialog).getByRole('button', { name: /Roll back now/i }))

    await waitFor(() => expect(toast.error).toHaveBeenCalled())
    expect(vi.mocked(toast.error).mock.calls[0][0]).toMatch(/someone else changed this/i)
    // Exactly one attempt — a stale intent must never be auto-retried.
    expect(svc.executeRollback).toHaveBeenCalledTimes(1)
  })

  it('passes a safety refusal through verbatim so the operator sees which rule fired', async () => {
    const { toast } = await import('sonner')
    const user = userEvent.setup()
    svc.executeRollback.mockRejectedValue({
      status: 423, code: 'ROLLBACK_TARGET_UNAVAILABLE',
      message: 'No designated rollback target; refusing rather than rolling back to a guess.',
    })
    wrap(<OperationsDeploymentDetailPage />)

    await user.click(await screen.findByRole('button', { name: /Roll back/i }))
    const dialog = await screen.findByRole('dialog')
    await user.type(within(dialog).getByLabelText(/Reason/i), 'Trying.')
    await user.type(within(dialog).getByLabelText(/Type PRODUCTION to confirm/i), 'PRODUCTION')
    await user.click(within(dialog).getByRole('button', { name: /Roll back now/i }))

    await waitFor(() => expect(toast.error).toHaveBeenCalledWith(
      'No designated rollback target; refusing rather than rolling back to a guess.'))
  })
})

// --------------------------------------------------------------------------- //
// AC-04 / AC-05 / AC-06 — traffic, gates, wizards
// --------------------------------------------------------------------------- //
describe('AC-04..06 — traffic, gates and the wizards', () => {
  it('shows allocation weights and revision history', async () => {
    svc.traffic.mockResolvedValue({
      revision: 4, weights: [{ agent_version_id: 'v-2', weight: 100 }], is_current: true,
    })
    svc.trafficHistory.mockResolvedValue([
      { id: 'a-1', revision: 4, weights: [{ agent_version_id: 'v-2', weight: 100 }], reason: 'Cutover.', created_at: null, is_current: true },
    ])
    wrap(<TrafficAllocationPage />)

    await selectWhenReady(/Agent and environment/i, 'agent-1:env-1')
    expect(await screen.findByText('Cutover.')).toBeInTheDocument()
    expect(screen.getByText(/revision 4/i)).toBeInTheDocument()
  })

  it('shows gate findings with their remediation', async () => {
    svc.preflight.mockResolvedValue({
      deployment_id: 'dep-1', verdict: 'BLOCK', evaluated_at: null,
      findings: [{
        code: 'PREFLIGHT_KILL_SWITCH_ACTIVE', severity: 'BLOCK',
        message: 'A kill switch is active.', remediation: 'Clear the kill switch on the agent.',
      }],
    })
    wrap(<HealthGatesPage />)
    await selectWhenReady(/Select a deployment/i, 'dep-1')

    expect(await screen.findByText('PREFLIGHT_KILL_SWITCH_ACTIVE')).toBeInTheDocument()
    expect(screen.getByText(/Clear the kill switch on the agent/i)).toBeInTheDocument()
    expect(screen.getByText('Blocking')).toBeInTheDocument()
  })

  it('promotes only along a configured path, with production type-to-confirm', async () => {
    const user = userEvent.setup()
    svc.promotionPaths.mockResolvedValue([
      { id: 'p-1', from_environment_id: 'env-2', to_environment_id: 'env-1', requires_approval: false },
    ])
    wrap(<PromotionWizardPage />)

    await selectWhenReady(/Deployment to promote/i, 'dep-2')
    await selectWhenReady(/Target environment/i, 'env-1')
    await user.click(screen.getByRole('button', { name: /Promote…/i }))

    const dialog = await screen.findByRole('dialog')
    // Promoting a kill-switched, gate-blocked deployment must show both facts.
    expect(dialog).toHaveTextContent(/Kill switch active/i)
    expect(dialog).toHaveTextContent(/Release gate blocked/i)
    expect(within(dialog).getByRole('button', { name: /^Promote$/i })).toBeDisabled()
    expect(svc.promote).not.toHaveBeenCalled()
  })

  it('shows the rollback target rather than offering a version picker', async () => {
    wrap(<RollbackWizardPage />)
    await selectWhenReady(/Deployment to roll back/i, 'dep-1')
    expect(await screen.findByText('1.4.2')).toBeInTheDocument()
    // No arbitrary target chooser — Phase 3.7 fails closed rather than guessing.
    expect(screen.queryByLabelText(/target version/i)).not.toBeInTheDocument()
  })

  it('explains that a rollback with no designated target will be refused', async () => {
    svc.deploymentDetail.mockResolvedValue({ ...DETAIL, rollback_target: null })
    wrap(<RollbackWizardPage />)
    await selectWhenReady(/Deployment to roll back/i, 'dep-1')

    expect(await screen.findByText('No designated target')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /^Roll back$/i })).toBeDisabled()
  })
})

// --------------------------------------------------------------------------- //
// AC-13 — no secrets reach the rendered page
// --------------------------------------------------------------------------- //
describe('AC-13 — nothing secret is rendered', () => {
  it('renders no secret-shaped content on the detail view', async () => {
    const { container } = wrap(<OperationsDeploymentDetailPage />)
    await screen.findByText('Version identity')
    const text = container.textContent?.toLowerCase() ?? ''
    for (const marker of ['password', 'api_key', 'client_secret', 'private_key', 'bearer ']) {
      expect(text).not.toContain(marker)
    }
  })
})
