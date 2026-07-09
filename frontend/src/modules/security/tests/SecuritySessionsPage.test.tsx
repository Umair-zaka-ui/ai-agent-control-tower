import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactNode } from 'react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { AuthDevice, AuthSession, OrgUser } from '@/types'

const logout = vi.fn()
const permissions: string[] = []

vi.mock('@/hooks/useAuth', () => ({
  useAuth: () => ({ logout, permissions, user: null, token: 't', isAuthenticated: true }),
}))

const listSessions = vi.fn()
const listDevices = vi.fn()
const revokeSession = vi.fn()
const trustDevice = vi.fn()
const blockDevice = vi.fn()
const logoutAllDevices = vi.fn()
const adminListUsers = vi.fn()
const adminListUserSessions = vi.fn()
const adminListUserDevices = vi.fn()
const adminRevokeSession = vi.fn()
const adminRevokeAll = vi.fn()
const mySecurityEvents = vi.fn()
const adminListSecurityEvents = vi.fn()
const adminListSessionEvents = vi.fn()

vi.mock('@/services/authService', () => ({
  sessionService: {
    listSessions: () => listSessions(),
    listDevices: () => listDevices(),
    revokeSession: (id: string, reason?: string) => revokeSession(id, reason),
    trustDevice: (id: string) => trustDevice(id),
    blockDevice: (id: string) => blockDevice(id),
    logoutAllDevices: () => logoutAllDevices(),
    mySecurityEvents: (n?: number) => mySecurityEvents(n),
  },
  adminSessionService: {
    listUsers: () => adminListUsers(),
    listUserSessions: (id: string) => adminListUserSessions(id),
    listUserDevices: (id: string) => adminListUserDevices(id),
    revokeSession: (id: string, reason?: string) => adminRevokeSession(id, reason),
    revokeAllSessions: (id: string, reason?: string) => adminRevokeAll(id, reason),
    listSecurityEvents: (p: unknown) => adminListSecurityEvents(p),
    listSessionEvents: (id: string) => adminListSessionEvents(id),
  },
}))

vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

// Imported after the mocks so the module graph picks them up.
const { SecuritySessionsPage } = await import('../SecuritySessionsPage')

const session = (o: Partial<AuthSession> = {}): AuthSession =>
  ({
    id: 's1',
    status: 'ACTIVE',
    device_id: 'd1',
    device_name: 'Chrome on Windows 10/11',
    device_type: 'desktop',
    browser: 'Chrome',
    browser_version: '120',
    operating_system: 'Windows 10/11',
    ip_address: '203.0.113.7',
    country: null,
    city: null,
    login_method: 'PASSWORD',
    created_at: new Date().toISOString(),
    last_seen_at: new Date().toISOString(),
    last_activity_at: new Date().toISOString(),
    idle_expires_at: new Date(Date.now() + 1_800_000).toISOString(),
    absolute_expires_at: new Date(Date.now() + 43_200_000).toISOString(),
    revoked_at: null,
    revoked_reason: null,
    security_score: 100,
    is_trusted: false,
    is_current: false,
    security_band: 'HEALTHY',
    ...o,
  }) as AuthSession

const device = (o: Partial<AuthDevice> = {}): AuthDevice =>
  ({
    id: 'd1',
    device_name: 'Chrome on Windows 10/11',
    device_type: 'desktop',
    browser: 'Chrome',
    browser_version: '120',
    operating_system: 'Windows 10/11',
    status: 'UNKNOWN',
    last_ip: '203.0.113.7',
    last_seen_at: new Date().toISOString(),
    created_at: new Date().toISOString(),
    is_current: false,
    ...o,
  }) as AuthDevice

function wrapper({ children }: { children: ReactNode }) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  // The page now links to the change-password / password-dashboard routes, so it
  // needs a router in the tree.
  return (
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>{children}</MemoryRouter>
    </QueryClientProvider>
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  permissions.length = 0
  listSessions.mockResolvedValue([session({ id: 'current', is_current: true }), session({ id: 'other' })])
  listDevices.mockResolvedValue([device()])
  revokeSession.mockResolvedValue(session())
  logoutAllDevices.mockResolvedValue({ revoked_session_ids: ['current', 'other'] })
  adminListUsers.mockResolvedValue([])
  adminListUserSessions.mockResolvedValue([])
  adminListUserDevices.mockResolvedValue([])
  mySecurityEvents.mockResolvedValue([])
  adminListSecurityEvents.mockResolvedValue({ items: [], total: 0, limit: 25, offset: 0 })
  adminListSessionEvents.mockResolvedValue([])
})

const secEvent = (o: Record<string, unknown> = {}) => ({
  id: `e${Math.random()}`,
  event_type: 'SESSION_CREATED',
  actor_type: 'HUMAN',
  actor_id: 'u1',
  target_type: 'HUMAN_USER',
  target_id: 'u1',
  organization_id: 'o1',
  request_id: null,
  correlation_id: null,
  ip_address: null,
  meta: {},
  created_at: new Date().toISOString(),
  ...o,
})

describe('SecuritySessionsPage — self-service (SRS §19, §24)', () => {
  it('lists active sessions and known devices', async () => {
    render(<SecuritySessionsPage />, { wrapper })
    expect(await screen.findByText(/active sessions/i)).toBeInTheDocument()
    await waitFor(() => expect(screen.getByTestId('current-session-badge')).toBeInTheDocument())
    expect(screen.getAllByText(/chrome on windows/i).length).toBeGreaterThan(0)
  })

  it('confirms before revoking another device, then calls the API', async () => {
    render(<SecuritySessionsPage />, { wrapper })
    const revokeButtons = await screen.findAllByRole('button', { name: /^revoke$/i })
    await userEvent.click(revokeButtons[0])

    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).getByText(/revoke this session\?/i)).toBeInTheDocument()
    expect(revokeSession).not.toHaveBeenCalled() // nothing happens until confirmed

    await userEvent.click(within(dialog).getByRole('button', { name: /revoke session/i }))
    await waitFor(() => expect(revokeSession).toHaveBeenCalledWith('other', undefined))
    expect(logout).not.toHaveBeenCalled()
  })

  it('cancelling the confirmation revokes nothing', async () => {
    render(<SecuritySessionsPage />, { wrapper })
    const revokeButtons = await screen.findAllByRole('button', { name: /^revoke$/i })
    await userEvent.click(revokeButtons[0])
    const dialog = await screen.findByRole('dialog')
    await userEvent.click(within(dialog).getByRole('button', { name: /cancel/i }))
    expect(revokeSession).not.toHaveBeenCalled()
  })

  it('warns that signing out the current session returns you to sign-in, and clears auth', async () => {
    render(<SecuritySessionsPage />, { wrapper })
    const signOut = await screen.findByRole('button', { name: /^sign out$/i })
    await userEvent.click(signOut)

    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).getByText(/you are using this session right now/i)).toBeInTheDocument()
    await userEvent.click(within(dialog).getByRole('button', { name: /^sign out$/i }))

    await waitFor(() => expect(revokeSession).toHaveBeenCalledWith('current', undefined))
    await waitFor(() => expect(logout).toHaveBeenCalled())
  })

  it('signs out of every device and clears local auth state', async () => {
    render(<SecuritySessionsPage />, { wrapper })
    await userEvent.click(await screen.findByRole('button', { name: /sign out everywhere/i }))
    const dialog = await screen.findByRole('dialog')
    await userEvent.click(within(dialog).getByRole('button', { name: /sign out everywhere/i }))

    await waitFor(() => expect(logoutAllDevices).toHaveBeenCalled())
    await waitFor(() => expect(logout).toHaveBeenCalled())
  })

  it('warns when a session is flagged high risk', async () => {
    listSessions.mockResolvedValue([session({ id: 'x', security_band: 'HIGH_RISK', security_score: 20 })])
    render(<SecuritySessionsPage />, { wrapper })
    expect(await screen.findByText(/flagged high risk/i)).toBeInTheDocument()
  })

  it('blocking a device asks first and warns that its sessions end', async () => {
    render(<SecuritySessionsPage />, { wrapper })
    await userEvent.click(await screen.findByRole('button', { name: /block/i }))
    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).getByText(/any session on that device ends now/i)).toBeInTheDocument()
    expect(blockDevice).not.toHaveBeenCalled()
  })
})

describe('SecuritySessionsPage — admin panel (SRS §17, §32)', () => {
  it('is hidden from users without session.view', async () => {
    render(<SecuritySessionsPage />, { wrapper })
    await screen.findByText(/active sessions/i)
    expect(screen.queryByText(/team sessions/i)).not.toBeInTheDocument()
    expect(adminListUsers).not.toHaveBeenCalled()
  })

  it('lets an admin pick a member and force-logout one of their sessions', async () => {
    permissions.push('session.view', 'session.revoke')
    adminListUsers.mockResolvedValue([
      { id: 'u1', email: 'dev@acme.com', display_name: 'Dev', organization_id: 'o1', role: 'VIEWER', is_active: true, status: 'ACTIVE' } as OrgUser,
    ])
    adminListUserSessions.mockResolvedValue([session({ id: 'ms1' })])
    adminRevokeSession.mockResolvedValue(session({ id: 'ms1', revoked_reason: 'ADMIN_REVOKED' }))

    render(<SecuritySessionsPage />, { wrapper })
    expect(await screen.findByText(/team sessions/i)).toBeInTheDocument()

    // Wait for the member list to load before selecting: the <select> starts with
    // only its placeholder option.
    await screen.findByRole('option', { name: /Dev/ })
    await userEvent.selectOptions(screen.getByLabelText(/member/i), 'u1')
    await waitFor(() => expect(adminListUserSessions).toHaveBeenCalledWith('u1'))

    const panel = await screen.findByTestId('admin-sessions-panel')
    await waitFor(() =>
      expect(within(panel).getAllByRole('button', { name: /^revoke$/i })).not.toHaveLength(0),
    )
    await userEvent.click(within(panel).getAllByRole('button', { name: /^revoke$/i })[0])

    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).getByText(/their account stays active/i)).toBeInTheDocument()
    await userEvent.click(within(dialog).getByRole('button', { name: /revoke session/i }))
    await waitFor(() => expect(adminRevokeSession).toHaveBeenCalledWith('ms1', undefined))
  })

  it('hides revoke controls from an admin who can view but not revoke', async () => {
    permissions.push('session.view')
    adminListUsers.mockResolvedValue([
      { id: 'u1', email: 'dev@acme.com', display_name: 'Dev', organization_id: 'o1', role: 'VIEWER', is_active: true, status: 'ACTIVE' } as OrgUser,
    ])
    adminListUserSessions.mockResolvedValue([session({ id: 'ms1' })])

    render(<SecuritySessionsPage />, { wrapper })
    await screen.findByRole('option', { name: /Dev/ })
    await userEvent.selectOptions(screen.getByLabelText(/member/i), 'u1')
    await waitFor(() => expect(adminListUserSessions).toHaveBeenCalled())

    expect(screen.queryByRole('button', { name: /sign out of all devices/i })).not.toBeInTheDocument()
  })
})

describe('SecuritySessionsPage — audit stream (SRS §26, DoD §32)', () => {
  it('shows the user their own recent security activity', async () => {
    mySecurityEvents.mockResolvedValue([
      secEvent({ event_type: 'DEVICE_REGISTERED', meta: { device_name: 'Safari on iOS' } }),
      secEvent({ event_type: 'SESSION_CREATED' }),
    ])
    render(<SecuritySessionsPage />, { wrapper })

    // The loading skeleton shares the testid, so wait for content, not the container.
    expect(await screen.findByText('New device')).toBeInTheDocument()
    const list = screen.getByTestId('my-security-events')
    expect(within(list).getByText('Session started')).toBeInTheDocument()
    expect(within(list).getByText(/Safari on iOS/)).toBeInTheDocument()
  })

  it('renders an empty state rather than nothing when there is no activity', async () => {
    render(<SecuritySessionsPage />, { wrapper })
    expect(await screen.findByText(/no security activity recorded yet/i)).toBeInTheDocument()
    expect(screen.queryByTestId('my-security-events')).not.toBeInTheDocument()
  })

  it('never requests the admin stream for a user without session.view', async () => {
    render(<SecuritySessionsPage />, { wrapper })
    await screen.findByText(/recent security activity/i)
    expect(adminListSecurityEvents).not.toHaveBeenCalled()
    expect(adminListSessionEvents).not.toHaveBeenCalled()
  })

  it("answers 'who revoked this session, when, and why?' in the session timeline", async () => {
    permissions.push('session.view', 'session.revoke')
    adminListUsers.mockResolvedValue([
      { id: 'u1', email: 'dev@acme.com', display_name: 'Dev', organization_id: 'o1', role: 'VIEWER', is_active: true, status: 'ACTIVE' } as OrgUser,
    ])
    adminListUserSessions.mockResolvedValue([session({ id: 'ms1' })])
    adminListSessionEvents.mockResolvedValue([
      secEvent({ event_type: 'SESSION_CREATED' }),
      secEvent({
        event_type: 'SESSION_REVOKED',
        meta: { reason: 'ADMIN_REVOKED', actor_email: 'owner@acme.com', session_id: 'ms1' },
      }),
    ])

    render(<SecuritySessionsPage />, { wrapper })
    await screen.findByRole('option', { name: /Dev/ })
    await userEvent.selectOptions(screen.getByLabelText(/member/i), 'u1')

    const panel = await screen.findByTestId('admin-sessions-panel')
    await waitFor(() => expect(within(panel).getByRole('button', { name: /^history$/i })).toBeInTheDocument())
    await userEvent.click(within(panel).getByRole('button', { name: /^history$/i }))

    await waitFor(() => expect(adminListSessionEvents).toHaveBeenCalledWith('ms1'))
    expect(await screen.findByText('Session revoked')).toBeInTheDocument()
    const timeline = screen.getByTestId('session-timeline')
    expect(within(timeline).getByText(/admin revoked/)).toBeInTheDocument()      // why
    expect(within(timeline).getByText(/by owner@acme.com/)).toBeInTheDocument()  // by whom
  })

  it("shows a member's recent security activity to an admin", async () => {
    permissions.push('session.view')
    adminListUsers.mockResolvedValue([
      { id: 'u1', email: 'dev@acme.com', display_name: 'Dev', organization_id: 'o1', role: 'VIEWER', is_active: true, status: 'ACTIVE' } as OrgUser,
    ])
    adminListSecurityEvents.mockResolvedValue({
      items: [secEvent({ event_type: 'TOKEN_REUSE_DETECTED' })],
      total: 1,
      limit: 25,
      offset: 0,
    })

    render(<SecuritySessionsPage />, { wrapper })
    await screen.findByRole('option', { name: /Dev/ })
    await userEvent.selectOptions(screen.getByLabelText(/member/i), 'u1')

    await waitFor(() =>
      expect(adminListSecurityEvents).toHaveBeenCalledWith({ actorId: 'u1', limit: 25 }),
    )
    expect(await screen.findByText('Refresh-token reuse detected')).toBeInTheDocument()
  })
})
