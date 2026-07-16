// Phase 4.3.7 frontend tests (§25) — dashboard widgets, decision explorer
// filters + detail, access review lifecycle actions, analytics tiles and
// permission-gated portal navigation.
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import type { ReactNode } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const svc = {
  dashboard: vi.fn(),
  analytics: vi.fn(),
  decisions: vi.fn(),
  campaigns: vi.fn(),
  createCampaign: vi.fn(),
  activateCampaign: vi.fn(),
  completeCampaign: vi.fn(),
  archiveCampaign: vi.fn(),
  campaignItems: vi.fn(),
  decideItem: vi.fn(),
  exportCampaign: vi.fn(),
}
vi.mock('@/services', () => ({ adminService: svc }))
vi.mock('@/hooks/useAuth', () => ({
  useAuth: () => ({
    permissions: ['admin.*', 'role.view', 'organization.view', 'resource.view',
                  'authorization.abac.view', 'authorization.abac.simulate', 'audit.view'],
  }),
}))

const { AdminDashboardPage } = await import('../AdminDashboardPage')
const { DecisionExplorerPage } = await import('../DecisionExplorerPage')
const { AccessReviewsPage } = await import('../AccessReviewsPage')
const { SecurityAnalyticsPage } = await import('../SecurityAnalyticsPage')
const { AdminNav } = await import('../components/AdminNav')
const { PermissionProvider } = await import('@/authorization')

function wrap(children: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <PermissionProvider>{children}</PermissionProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  svc.dashboard.mockResolvedValue({
    widgets: {
      total_users: 12, active_roles: 5, active_permissions: 80, active_policies: 3,
      active_sessions: 4, authorization_requests_24h: 240, denied_requests_24h: 9,
      approval_requests_pending: 2, mfa_challenges_total: 1, high_risk_decisions_24h: 0,
      cache_hit_ratio: 0.92, policy_evaluation_latency_ms: 3.4,
    },
    charts: {
      authorization_trend: [{ date: '2026-07-15', total: 100, denied: 4 }],
      top_permissions: [{ permission: 'agent.view', total: 50, denied: 1 }],
      policy_matches: [{ policy: 'PHI guard', matches: 7 }],
      decision_breakdown: [{ decision: 'DENY', total: 4 }],
      approval_queue: [{ status: 'PENDING', total: 2 }],
    },
  })
  svc.analytics.mockResolvedValue({
    denied_requests_24h: 9, denied_requests_7d: 40, high_risk_decisions_24h: 1,
    mfa_challenges_total: 3, approval_requests_total: 10, approval_approval_rate: 0.8,
    authorization_latency_ms_avg: 2.5, authorization_latency_ms_p95: 8.1,
    cache_hit_ratio: 0.91, abac_denies_total: 6, abac_challenges_total: 2,
    policy_errors_total: 0,
    top_denied_permissions: [{ permission: 'policy.create', denied: 5 }],
    denied_trend: [{ date: '2026-07-15', denied: 4 }],
    sharing_trend: [{ date: '2026-07-15', shares: 2 }],
  })
  svc.decisions.mockResolvedValue([{
    id: 'd1', identity_id: 'u1', organization_id: 'o1', permission: 'policy.create',
    resource_type: null, resource_id: null, allowed: false,
    reason: 'Missing required permission', scope: null, source_role: null,
    evaluation_time_ms: 2.2, request_id: 'req-1', created_at: '2026-07-16T10:00:00Z',
  }])
  svc.campaigns.mockResolvedValue([{
    id: 'c1', organization_id: 'o1', name: 'Q3 certification', description: null,
    status: 'ACTIVE', scope: null, reviewer_id: null, due_at: null, created_by: 'u1',
    activated_at: '2026-07-16T09:00:00Z', completed_at: null,
    created_at: '2026-07-16T08:00:00Z', total_items: 2, decided_items: 1,
    revoked_items: 0,
  }])
  svc.campaignItems.mockResolvedValue([{
    id: 'i1', campaign_id: 'c1', subject_id: 'u2', subject_label: 'bob@example.com',
    assignment_id: 'a1', role_id: 'r1', role_name: 'ROLE_AUDITOR',
    scope_label: 'ORGANIZATION', decision: 'PENDING', decided_by: null,
    decided_at: null, comment: null,
  }])
  svc.decideItem.mockResolvedValue({})
})

describe('AdminDashboardPage (§6)', () => {
  it('renders all twelve widgets and the charts', async () => {
    wrap(<AdminDashboardPage />)
    await waitFor(() => expect(screen.getByTestId('dashboard-widgets')).toBeInTheDocument())
    expect(screen.getByText('Total users')).toBeInTheDocument()
    expect(screen.getByText('12')).toBeInTheDocument()
    expect(screen.getByText('Cache hit ratio')).toBeInTheDocument()
    expect(screen.getByText('92%')).toBeInTheDocument()
    expect(screen.getByText('Authorization trend (7d)')).toBeInTheDocument()
    expect(screen.getByText('PHI guard')).toBeInTheDocument()
    expect(screen.getByText('PENDING')).toBeInTheDocument()
  })
})

describe('DecisionExplorerPage (§13)', () => {
  it('lists decisions and expands the explanation', async () => {
    wrap(<DecisionExplorerPage />)
    await waitFor(() => expect(screen.getByTestId('decision-list')).toBeInTheDocument())
    expect(screen.getByText('policy.create')).toBeInTheDocument()
    expect(screen.getByText('DENY')).toBeInTheDocument()
    await userEvent.click(screen.getByText('policy.create'))
    expect(screen.getByTestId('decision-detail')).toHaveTextContent('Missing required permission')
  })

  it('applies filters through the service', async () => {
    wrap(<DecisionExplorerPage />)
    await waitFor(() => expect(svc.decisions).toHaveBeenCalled())
    await userEvent.type(screen.getByLabelText('Permission'), 'agent.view')
    await userEvent.selectOptions(screen.getByLabelText('Decision'), 'false')
    await userEvent.click(screen.getByText('Search'))
    await waitFor(() => expect(svc.decisions).toHaveBeenLastCalledWith(
      { permission: 'agent.view', allowed: false }))
  })
})

describe('AccessReviewsPage (§14)', () => {
  it('lists campaigns with progress and lifecycle actions', async () => {
    wrap(<AccessReviewsPage />)
    await waitFor(() => expect(screen.getByTestId('campaign-list')).toBeInTheDocument())
    expect(screen.getByText('Q3 certification')).toBeInTheDocument()
    expect(screen.getByText('1/2 decided · 0 revoked')).toBeInTheDocument()
    expect(screen.getByText('ACTIVE')).toBeInTheDocument()
    // Complete is disabled while items are pending (1/2 decided).
    expect(screen.getByText('Complete')).toBeDisabled()
  })

  it('expands items and records a certify decision', async () => {
    wrap(<AccessReviewsPage />)
    await waitFor(() => expect(screen.getByText('Q3 certification')).toBeInTheDocument())
    await userEvent.click(screen.getByText('Q3 certification'))
    await waitFor(() => expect(screen.getByTestId('campaign-items')).toBeInTheDocument())
    expect(screen.getByText('bob@example.com')).toBeInTheDocument()
    await userEvent.click(screen.getByText('Certify'))
    await waitFor(() => expect(svc.decideItem).toHaveBeenCalledWith('c1', 'i1', 'CERTIFIED'))
  })

  it('creates a campaign', async () => {
    svc.createCampaign.mockResolvedValue({})
    wrap(<AccessReviewsPage />)
    await userEvent.type(screen.getByLabelText('Campaign name'), 'Q4 review')
    await userEvent.click(screen.getByText('Create'))
    await waitFor(() => expect(svc.createCampaign).toHaveBeenCalledWith({ name: 'Q4 review' }))
  })
})

describe('SecurityAnalyticsPage (§17)', () => {
  it('renders the metric tiles and trends', async () => {
    wrap(<SecurityAnalyticsPage />)
    await waitFor(() => expect(screen.getByTestId('analytics-tiles')).toBeInTheDocument())
    expect(screen.getByText('Denied (24h)')).toBeInTheDocument()
    expect(screen.getByText('Approval rate')).toBeInTheDocument()
    expect(screen.getByText('80%')).toBeInTheDocument()
    expect(screen.getByText('Top denied permissions')).toBeInTheDocument()
  })
})

describe('AdminNav (§5, §21)', () => {
  it('shows every section the viewer is permitted to see', () => {
    wrap(<AdminNav />)
    for (const label of ['Dashboard', 'Roles', 'Organization', 'Resources',
                         'ABAC policies', 'Simulator', 'Decisions', 'Access reviews',
                         'Audit', 'Analytics']) {
      expect(screen.getByText(label)).toBeInTheDocument()
    }
  })
})
