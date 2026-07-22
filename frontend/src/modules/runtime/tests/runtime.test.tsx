// Phase 5.0 frontend tests — runtime dashboard, agent registration, running
// an execution, and permission-gated runtime navigation.
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import type { ReactNode } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const svc = {
  dashboard: vi.fn(),
  agents: vi.fn(),
  registerAgent: vi.fn(),
  executions: vi.fn(),
  requestExecution: vi.fn(),
}
vi.mock('@/services', () => ({ runtimeService: svc }))
vi.mock('@/hooks/useAuth', () => ({
  useAuth: () => ({
    user: { id: 'u1', organization_id: 'org-1', name: 'Owner', email: 'owner@example.com' },
    permissions: ['runtime.agent.view', 'runtime.agent.create', 'runtime.deployment.view',
                 'runtime.execution.view', 'runtime.execution.create', 'runtime.approval.review',
                 'runtime.health.view'],
  }),
}))

const { RuntimeDashboardPage } = await import('../RuntimeDashboardPage')
const { AgentsPage } = await import('../AgentsPage')
const { ExecutionsPage } = await import('../ExecutionsPage')
const { RuntimeNav } = await import('../components/RuntimeNav')
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

const DASHBOARD_FIXTURE = {
  registered_agents: 3, active_agents: 2, active_deployments: 1, running_executions: 0,
  queued_executions: 0, failed_executions_24h: 1, pending_approvals: 0, suspended_agents: 0,
  cost_today: 0.0042, success_rate: 87.5, avg_queue_ms: 12, avg_execution_ms: 340,
  execution_trend: [{ date: '2026-07-18', count: 5 }],
  status_distribution: [{ status: 'SUCCEEDED', count: 4 }, { status: 'FAILED', count: 1 }],
}

const AGENT_FIXTURE = {
  id: 'agent-1', organization_id: 'org-1', name: 'Claims Agent', slug: null,
  description: null, agent_type: 'ASSISTANT', status: 'ACTIVE', lifecycle_status: 'ACTIVE',
  criticality: 'MEDIUM', data_classification: 'INTERNAL', default_environment: 'DEVELOPMENT',
  project_id: null, owner_type: null, owner_id: null,
  created_at: '2026-07-18T05:00:00Z', updated_at: '2026-07-18T05:00:00Z', archived_at: null,
}

const EXECUTION_FIXTURE = {
  id: 'exec-1', organization_id: 'org-1', agent_id: 'agent-1', agent_version_id: 'v1',
  deployment_id: 'd1', trigger_type: 'API', triggered_by_identity_id: 'u1',
  parent_execution_id: null, correlation_id: null, idempotency_key: null,
  input_payload: { question: 'hi' }, output_payload: { result: 'ok' }, status: 'SUCCEEDED',
  decision: 'ALLOW', risk_score: 30, priority: 'NORMAL', queued_at: '2026-07-18T05:00:00Z',
  started_at: '2026-07-18T05:00:00Z', completed_at: '2026-07-18T05:00:01Z', duration_ms: 6,
  attempt_count: 1, cancel_requested: false, error_code: null, error_message: null,
  model_usage: { provider: 'MOCK' }, tool_usage: null, cost: 0.0001,
  created_at: '2026-07-18T05:00:00Z', updated_at: '2026-07-18T05:00:01Z',
}

beforeEach(() => {
  vi.clearAllMocks()
  svc.dashboard.mockResolvedValue(DASHBOARD_FIXTURE)
  svc.agents.mockResolvedValue([AGENT_FIXTURE])
  svc.executions.mockResolvedValue([EXECUTION_FIXTURE])
  svc.registerAgent.mockResolvedValue({ ...AGENT_FIXTURE, id: 'agent-2', lifecycle_status: 'DRAFT' })
  svc.requestExecution.mockResolvedValue(EXECUTION_FIXTURE)
})

describe('RuntimeDashboardPage (§70)', () => {
  it('renders KPI tiles and trend/status charts from the live snapshot', async () => {
    wrap(<RuntimeDashboardPage />)
    await waitFor(() => expect(svc.dashboard).toHaveBeenCalled())
    expect(await screen.findByText('Registered agents')).toBeInTheDocument()
    expect(screen.getByText('3')).toBeInTheDocument()
    expect(screen.getByText('Success rate (24h)')).toBeInTheDocument()
    expect(screen.getByText('87.5%')).toBeInTheDocument()
    expect(screen.getByText('Cost today')).toBeInTheDocument()
    expect(screen.getByText('$0.00')).toBeInTheDocument()
  })
})

describe('AgentsPage (§16)', () => {
  it('lists agents with their lifecycle status', async () => {
    wrap(<AgentsPage />)
    expect(await screen.findByText('Claims Agent')).toBeInTheDocument()
    expect(screen.getByText('ACTIVE')).toBeInTheDocument()
  })

  it('links "Register agent" to the registration wizard', async () => {
    wrap(<AgentsPage />)
    await waitFor(() => expect(svc.agents).toHaveBeenCalled())
    const link = screen.getByText('Register agent').closest('a')
    expect(link).toHaveAttribute('href', '/runtime/agents/new')
  })

  it('re-queries with a saved view when one is selected', async () => {
    wrap(<AgentsPage />)
    await waitFor(() => expect(svc.agents).toHaveBeenCalled())
    await userEvent.selectOptions(screen.getByLabelText('Saved view'), 'ACTIVE')
    await waitFor(() => expect(svc.agents).toHaveBeenCalledWith(expect.objectContaining({ view: 'ACTIVE' })))
  })
})

describe('ExecutionsPage (§26)', () => {
  it('lists executions with status, cost and duration', async () => {
    wrap(<ExecutionsPage />)
    const table = await screen.findByRole('table')
    expect(await within(table).findByText('Claims Agent')).toBeInTheDocument()
    expect(within(table).getByText('SUCCEEDED')).toBeInTheDocument()
  })

  it('runs the selected agent with the given input payload', async () => {
    wrap(<ExecutionsPage />)
    await screen.findByRole('option', { name: 'Claims Agent' })
    await userEvent.selectOptions(screen.getByLabelText('Agent'), 'agent-1')
    const payloadBox = screen.getByLabelText('Input payload (JSON)')
    await userEvent.clear(payloadBox)
    await userEvent.type(payloadBox, '{{"question": "hi"}}')
    await userEvent.click(screen.getByText('Run'))
    await waitFor(() => expect(svc.requestExecution).toHaveBeenCalledWith(
      expect.objectContaining({ agent_id: 'agent-1' }),
    ))
  })

  it('disables Run until an agent is selected', () => {
    wrap(<ExecutionsPage />)
    expect(screen.getByText('Run')).toBeDisabled()
  })
})

describe('RuntimeNav (§69)', () => {
  it('shows every section the viewer is permitted to see', () => {
    wrap(<RuntimeNav />)
    for (const label of ['Dashboard', 'Agents', 'Deployments', 'Executions', 'Approvals', 'Operations']) {
      expect(screen.getByText(label)).toBeInTheDocument()
    }
  })

  it('hides sections the viewer lacks permission for', async () => {
    vi.doMock('@/hooks/useAuth', () => ({
      useAuth: () => ({ user: { organization_id: 'org-1' }, permissions: ['runtime.agent.view'] }),
    }))
    vi.resetModules()
    const { RuntimeNav: ScopedNav } = await import('../components/RuntimeNav')
    const { PermissionProvider: ScopedProvider } = await import('@/authorization')
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(
      <QueryClientProvider client={qc}>
        <MemoryRouter>
          <ScopedProvider><ScopedNav /></ScopedProvider>
        </MemoryRouter>
      </QueryClientProvider>,
    )
    expect(screen.getByText('Dashboard')).toBeInTheDocument()
    expect(screen.getByText('Agents')).toBeInTheDocument()
    expect(screen.queryByText('Approvals')).not.toBeInTheDocument()
    expect(screen.queryByText('Operations')).not.toBeInTheDocument()
  })
})
