import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import type { ReactNode } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { AccountLock, BlockedIp, LoginAttempt, ProtectionRule, ProtectionSummary } from '@/types'

const svc = {
  summary: vi.fn(),
  loginAttempts: vi.fn(),
  riskEvents: vi.fn(),
  accountLocks: vi.fn(),
  unlockLock: vi.fn(),
  blockedIps: vi.fn(),
  blockIp: vi.fn(),
  unblockIp: vi.fn(),
  rules: vi.fn(),
  createRule: vi.fn(),
  updateRule: vi.fn(),
  deleteRule: vi.fn(),
}
vi.mock('@/services', () => ({ protectionService: svc }))

const { SecurityDashboardPage } = await import('../SecurityDashboardPage')
const { AccountLocksPage } = await import('../AccountLocksPage')
const { BlockedIpsPage } = await import('../BlockedIpsPage')
const { IdentityProtectionRulesPage } = await import('../IdentityProtectionRulesPage')

function wrapper({ children }: { children: ReactNode }) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return (
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>{children}</MemoryRouter>
    </QueryClientProvider>
  )
}

const summary: ProtectionSummary = {
  failed_logins_today: 12,
  locked_accounts: 2,
  high_risk_attempts: 3,
  blocked_ips: 1,
  active_rules: 4,
  risk_events_recent: 9,
}

const lock = (o: Partial<AccountLock> = {}): AccountLock => ({
  id: 'lock1',
  user_id: 'u1',
  organization_id: 'o1',
  reason: 'FAILED_LOGIN_THRESHOLD',
  status: 'ACTIVE',
  locked_at: new Date().toISOString(),
  expires_at: new Date(Date.now() + 900_000).toISOString(),
  unlocked_at: null,
  unlocked_by: null,
  meta: {},
  created_at: new Date().toISOString(),
  user_email: 'locked@acme.com',
  risk_score: 5,
  ...o,
})

beforeEach(() => {
  vi.clearAllMocks()
  svc.summary.mockResolvedValue(summary)
  svc.accountLocks.mockResolvedValue([lock()])
  svc.unlockLock.mockResolvedValue(lock({ status: 'MANUALLY_UNLOCKED' }))
  svc.blockedIps.mockResolvedValue([])
  svc.blockIp.mockResolvedValue({ id: 'b1' } as BlockedIp)
  svc.rules.mockResolvedValue([])
  svc.createRule.mockResolvedValue({ id: 'r1' } as ProtectionRule)
})

describe('SecurityDashboardPage', () => {
  it('renders the protection widgets', async () => {
    render(<SecurityDashboardPage />, { wrapper })
    expect(await screen.findByText('Failed logins (24h)')).toBeInTheDocument()
    expect(screen.getByText('12')).toBeInTheDocument()
    expect(screen.getByText('Locked accounts')).toBeInTheDocument()
  })
})

describe('AccountLocksPage', () => {
  it('lists locked accounts and unlocks one with a reason', async () => {
    const user = userEvent.setup()
    render(<AccountLocksPage />, { wrapper })
    expect(await screen.findByText('locked@acme.com')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: /unlock/i }))
    // The unlock button in the modal is disabled until a reason is entered.
    const confirm = screen.getByRole('button', { name: /unlock account/i })
    expect(confirm).toBeDisabled()
    await user.type(screen.getByLabelText(/reason/i), 'verified by phone')
    expect(confirm).toBeEnabled()
    await user.click(confirm)
    await waitFor(() =>
      expect(svc.unlockLock).toHaveBeenCalledWith('lock1', 'verified by phone'),
    )
  })
})

describe('BlockedIpsPage', () => {
  it('blocks an IP', async () => {
    const user = userEvent.setup()
    render(<BlockedIpsPage />, { wrapper })
    await screen.findByText(/no ips are blocked/i)
    await user.type(screen.getByLabelText(/ip address/i), '203.0.113.9')
    await user.click(screen.getByRole('button', { name: /^block$/i }))
    await waitFor(() =>
      expect(svc.blockIp).toHaveBeenCalledWith(
        expect.objectContaining({ ip_address: '203.0.113.9' }),
      ),
    )
  })
})

describe('IdentityProtectionRulesPage', () => {
  it('creates a rule with JSON conditions', async () => {
    const user = userEvent.setup()
    render(<IdentityProtectionRulesPage />, { wrapper })
    await screen.findByText(/no rules yet/i)
    await user.type(screen.getByLabelText(/^name$/i), 'Block severe')
    await user.click(screen.getByRole('button', { name: /create rule/i }))
    await waitFor(() =>
      expect(svc.createRule).toHaveBeenCalledWith(
        expect.objectContaining({ name: 'Block severe', decision: 'CHALLENGE' }),
      ),
    )
  })

  it('disables create when the conditions JSON is invalid', async () => {
    const user = userEvent.setup()
    render(<IdentityProtectionRulesPage />, { wrapper })
    await screen.findByText(/no rules yet/i)
    await user.type(screen.getByLabelText(/^name$/i), 'Bad rule')
    const editor = screen.getByLabelText(/conditions/i)
    await user.clear(editor)
    await user.type(editor, '{{ not json')
    expect(screen.getByRole('button', { name: /create rule/i })).toBeDisabled()
  })
})
