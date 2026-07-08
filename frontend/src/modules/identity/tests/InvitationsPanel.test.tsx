import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactNode } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { Invitation } from '@/types'

const permissions: string[] = []
vi.mock('@/hooks/useAuth', () => ({
  useAuth: () => ({ permissions, logout: vi.fn(), isAuthenticated: true, user: null, token: 't' }),
}))

const list = vi.fn()
const create = vi.fn()
const resend = vi.fn()
const cancel = vi.fn()
const emailDeliveryStatus = vi.fn()
vi.mock('@/services/registrationService', () => ({
  invitationService: {
    list: (s?: string) => list(s),
    create: (p: unknown) => create(p),
    resend: (id: string) => resend(id),
    cancel: (id: string) => cancel(id),
    emailDeliveryStatus: () => emailDeliveryStatus(),
  },
  registrationService: {},
}))

const toastSuccess = vi.fn()
const toastError = vi.fn()
vi.mock('sonner', () => ({ toast: { success: toastSuccess, error: toastError } }))

const { InvitationsPanel } = await import('../components/InvitationsPanel')

const invitation = (o: Partial<Invitation> = {}): Invitation =>
  ({
    id: 'i1',
    organization_id: 'o1',
    email: 'ada@acme.com',
    role_id: null,
    department_id: null,
    team_id: null,
    invited_by: 'u1',
    status: 'PENDING',
    expires_at: new Date(Date.now() + 7 * 86_400_000).toISOString(),
    accepted_at: null,
    cancelled_at: null,
    resent_count: 0,
    last_sent_at: null,
    created_at: new Date().toISOString(),
    is_expired: false,
    ...o,
  }) as Invitation

function wrapper({ children }: { children: ReactNode }) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
}

beforeEach(() => {
  vi.clearAllMocks()
  permissions.length = 0
  list.mockResolvedValue([])
  create.mockResolvedValue(invitation())
  resend.mockResolvedValue(invitation({ resent_count: 1 }))
  cancel.mockResolvedValue(invitation({ status: 'CANCELLED' }))
  emailDeliveryStatus.mockResolvedValue({ enabled: true, outbox_path: null })
})

describe('InvitationsPanel — permission gating (§15)', () => {
  it('renders nothing without invitation.view', async () => {
    render(<InvitationsPanel />, { wrapper })
    expect(screen.queryByTestId('invitations-panel')).not.toBeInTheDocument()
    expect(list).not.toHaveBeenCalled()
  })

  it('shows the list but no controls with view-only permission', async () => {
    permissions.push('invitation.view')
    list.mockResolvedValue([invitation()])
    render(<InvitationsPanel />, { wrapper })

    expect(await screen.findByText('ada@acme.com')).toBeInTheDocument()
    expect(screen.queryByLabelText(/invite by email/i)).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /resend/i })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /^cancel$/i })).not.toBeInTheDocument()
  })
})

describe('InvitationsPanel — manage (§15)', () => {
  beforeEach(() => permissions.push('invitation.view', 'invitation.manage'))

  it('creates an invitation and clears the field', async () => {
    render(<InvitationsPanel />, { wrapper })
    const field = await screen.findByLabelText(/invite by email/i)
    await userEvent.type(field, 'new@acme.com')
    await userEvent.click(screen.getByRole('button', { name: /send invitation/i }))

    await waitFor(() => expect(create).toHaveBeenCalledWith({ email: 'new@acme.com' }))
    await waitFor(() => expect(field).toHaveValue(''))
    expect(toastSuccess).toHaveBeenCalled()
  })

  it('reports an existing user clearly instead of a generic failure', async () => {
    create.mockRejectedValue({ status: 409, message: 'exists' })
    render(<InvitationsPanel />, { wrapper })
    await userEvent.type(await screen.findByLabelText(/invite by email/i), 'owner@acme.com')
    await userEvent.click(screen.getByRole('button', { name: /send invitation/i }))
    await waitFor(() =>
      expect(toastError).toHaveBeenCalledWith('That email already belongs to a user.'),
    )
  })

  it('warns that resending kills the previous link', async () => {
    list.mockResolvedValue([invitation()])
    render(<InvitationsPanel />, { wrapper })
    await userEvent.click(await screen.findByRole('button', { name: /resend/i }))
    await waitFor(() => expect(resend).toHaveBeenCalledWith('i1'))
    expect(toastSuccess).toHaveBeenCalledWith(
      'New link sent. The previous link no longer works.',
    )
  })

  it('cancels an invitation', async () => {
    list.mockResolvedValue([invitation()])
    render(<InvitationsPanel />, { wrapper })
    await userEvent.click(await screen.findByRole('button', { name: /^cancel$/i }))
    await waitFor(() => expect(cancel).toHaveBeenCalledWith('i1'))
  })

  it('offers no actions on a terminal invitation', async () => {
    list.mockResolvedValue([
      invitation({ id: 'i2', status: 'ACCEPTED' }),
      invitation({ id: 'i3', status: 'EXPIRED' }),
    ])
    render(<InvitationsPanel />, { wrapper })
    await screen.findByText('ACCEPTED')
    expect(screen.queryByRole('button', { name: /resend/i })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /^cancel$/i })).not.toBeInTheDocument()
  })

  it('never renders a token, not even a prefix', async () => {
    list.mockResolvedValue([invitation()])
    const { container } = render(<InvitationsPanel />, { wrapper })
    await screen.findByText('ada@acme.com')
    expect(container.textContent).not.toMatch(/inv_/)
  })

  it('shows the resend count and expiry', async () => {
    list.mockResolvedValue([invitation({ resent_count: 2 })])
    render(<InvitationsPanel />, { wrapper })
    // The panel renders before its query resolves; wait for content, not the container.
    await screen.findByText('ada@acme.com')
    const panel = screen.getByTestId('invitations-panel')
    expect(within(panel).getByText(/resent ×2/)).toBeInTheDocument()
    expect(within(panel).getByText(/expires in \d+ days/)).toBeInTheDocument()
  })

  it('renders an empty state rather than nothing', async () => {
    render(<InvitationsPanel />, { wrapper })
    expect(await screen.findByText(/no invitations yet/i)).toBeInTheDocument()
  })
})


describe('InvitationsPanel — email delivery warning', () => {
  beforeEach(() => permissions.push('invitation.view', 'invitation.manage'))

  it('warns loudly when no email is actually sent', async () => {
    // The bug this guards: an invitation shows "PENDING · expires in 7 days" while the
    // link was written to a file. The invitee waits for ever.
    emailDeliveryStatus.mockResolvedValue({
      enabled: false,
      outbox_path: 'var/dev-outbox.log',
    })
    render(<InvitationsPanel />, { wrapper })

    const warning = await screen.findByTestId('email-delivery-warning')
    expect(warning).toHaveTextContent(/no invitations are sent/i)
    expect(warning).toHaveTextContent('var/dev-outbox.log')
    expect(warning).toHaveTextContent(/NOTIFICATIONS_ENABLED=true/)
    expect(warning).toHaveAttribute('role', 'alert')
  })

  it('stays quiet when mail is really being sent', async () => {
    render(<InvitationsPanel />, { wrapper })
    await screen.findByLabelText(/invite by email/i)
    expect(screen.queryByTestId('email-delivery-warning')).not.toBeInTheDocument()
  })

  it('does not query delivery status without invitation.view', async () => {
    permissions.length = 0
    render(<InvitationsPanel />, { wrapper })
    expect(emailDeliveryStatus).not.toHaveBeenCalled()
  })
})
