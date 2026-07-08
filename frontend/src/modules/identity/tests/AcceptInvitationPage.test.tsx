import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactNode } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { InvitationPreview } from '@/types'

const navigate = vi.fn()
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom')
  return {
    ...actual,
    useNavigate: () => navigate,
    useParams: () => ({ token: 'inv_test-token' }),
  }
})

const previewInvitation = vi.fn()
const registerFromInvitation = vi.fn()
vi.mock('@/services/registrationService', () => ({
  registrationService: {
    previewInvitation: (t: string) => previewInvitation(t),
    registerFromInvitation: (p: unknown) => registerFromInvitation(p),
    verifyEmail: vi.fn(),
    resendVerification: vi.fn(),
  },
  invitationService: {},
}))

const { AcceptInvitationPage } = await import('../pages/AcceptInvitationPage')

const preview = (o: Partial<InvitationPreview> = {}): InvitationPreview => ({
  email: 'ada@acme.com',
  organization_name: 'Acme',
  role_name: 'ADMIN',
  department_name: 'Engineering',
  invited_by_name: 'Owner',
  expires_at: new Date(Date.now() + 7 * 86_400_000).toISOString(),
  ...o,
})

function wrapper({ children }: { children: ReactNode }) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
}

const STRONG = 'Str0ngP@ssword!'

async function fillValidForm() {
  await userEvent.type(screen.getByLabelText(/first name/i), 'Ada')
  await userEvent.type(screen.getByLabelText(/last name/i), 'Lovelace')
  await userEvent.type(screen.getByLabelText('Password'), STRONG)
  await userEvent.type(screen.getByLabelText(/confirm password/i), STRONG)
}

beforeEach(() => {
  vi.clearAllMocks()
  previewInvitation.mockResolvedValue(preview())
  registerFromInvitation.mockResolvedValue({
    email: 'ada@acme.com',
    status: 'EMAIL_PENDING',
    email_sent: true,
    requires_approval: false,
    message: 'Check your email.',
  })
})

describe('AcceptInvitationPage — what am I accepting? (SRS §17)', () => {
  it('shows organization, role, department, inviter and expiry', async () => {
    render(<AcceptInvitationPage />, { wrapper })
    expect(await screen.findByText('Acme')).toBeInTheDocument()
    expect(screen.getByText(/Role: ADMIN · Engineering/)).toBeInTheDocument()
    expect(screen.getByText(/Invited by Owner/)).toBeInTheDocument()
    expect(screen.getByText(/Expires/)).toBeInTheDocument()
  })

  it('renders the email read-only: it comes from the invitation, not the user (§10)', async () => {
    render(<AcceptInvitationPage />, { wrapper })
    const email = (await screen.findByLabelText('Email')) as HTMLInputElement
    expect(email.value).toBe('ada@acme.com')
    expect(email).toHaveAttribute('readonly')
    expect(email).toBeDisabled()
  })

  it('sends the invitation token, never an email address, on submit', async () => {
    render(<AcceptInvitationPage />, { wrapper })
    await screen.findByText('Acme')
    await fillValidForm()
    await userEvent.click(screen.getByRole('button', { name: /create account/i }))

    await waitFor(() => expect(registerFromInvitation).toHaveBeenCalled())
    const payload = registerFromInvitation.mock.calls[0][0]
    expect(payload.token).toBe('inv_test-token')
    expect(payload).not.toHaveProperty('email')
    expect(payload.first_name).toBe('Ada')
  })
})

describe('AcceptInvitationPage — validation (§11, §17)', () => {
  it('keeps submit disabled until every requirement is met', async () => {
    render(<AcceptInvitationPage />, { wrapper })
    await screen.findByText('Acme')
    const submit = screen.getByRole('button', { name: /create account/i })
    expect(submit).toBeDisabled()

    await userEvent.type(screen.getByLabelText(/first name/i), 'Ada')
    await userEvent.type(screen.getByLabelText(/last name/i), 'Lovelace')
    expect(submit).toBeDisabled() // no password yet

    await userEvent.type(screen.getByLabelText('Password'), STRONG)
    expect(submit).toBeDisabled() // no confirmation yet

    await userEvent.type(screen.getByLabelText(/confirm password/i), STRONG)
    expect(submit).toBeEnabled()
  })

  it('refuses a weak password that clears the length floor', async () => {
    render(<AcceptInvitationPage />, { wrapper })
    await screen.findByText('Acme')
    await userEvent.type(screen.getByLabelText(/first name/i), 'Ada')
    await userEvent.type(screen.getByLabelText(/last name/i), 'Lovelace')
    await userEvent.type(screen.getByLabelText('Password'), 'alllowercase123!')
    await userEvent.type(screen.getByLabelText(/confirm password/i), 'alllowercase123!')
    expect(screen.getByRole('button', { name: /create account/i })).toBeDisabled()
  })

  it('shows a mismatch error on the confirmation field', async () => {
    render(<AcceptInvitationPage />, { wrapper })
    await screen.findByText('Acme')
    await userEvent.type(screen.getByLabelText('Password'), STRONG)
    await userEvent.type(screen.getByLabelText(/confirm password/i), 'Different!Passw0rd')
    expect(screen.getByText(/passwords do not match/i)).toBeInTheDocument()
  })

  it('rejects a password containing the invitee\'s own email local-part', async () => {
    previewInvitation.mockResolvedValue(preview({ email: 'johnsmith@acme.com' }))
    render(<AcceptInvitationPage />, { wrapper })
    await screen.findByText('Acme')
    await userEvent.type(screen.getByLabelText('Password'), 'Johnsmith99!!X')
    const rules = screen.getByTestId('password-rules')
    expect(within(rules).getByText(/does not contain your name or email/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /create account/i })).toBeDisabled()
  })

  it('surfaces a server-side policy rejection instead of insisting the password is fine', async () => {
    // The server is the authority (ADR-0004). The meter can approve what it refuses.
    registerFromInvitation.mockRejectedValue({ status: 422, message: 'Password is too common.' })
    render(<AcceptInvitationPage />, { wrapper })
    await screen.findByText('Acme')
    await fillValidForm()
    await userEvent.click(screen.getByRole('button', { name: /create account/i }))
    expect(await screen.findByRole('alert')).toHaveTextContent(/too common/i)
  })
})

describe('AcceptInvitationPage — dead links (§18)', () => {
  it.each([
    'INVITATION_EXPIRED',
    'INVITATION_ALREADY_USED',
    'INVITATION_CANCELLED',
    'INVITATION_NOT_FOUND',
  ])('routes %s to the expired page with the reason', async (code) => {
    previewInvitation.mockRejectedValue({ code, status: 410 })
    render(<AcceptInvitationPage />, { wrapper })
    await waitFor(() =>
      expect(navigate).toHaveBeenCalledWith('/invitation-expired', {
        replace: true,
        state: { code },
      }),
    )
  })

  it('routes to the expired page for an error built by the REAL toApiError', async () => {
    // The earlier cases mock `{ code }` directly. This one runs the actual backend
    // envelope through the actual normaliser, because a page that only works against a
    // hand-written mock is a page that does not work.
    const { toApiError } = await import('@/services/apiClient')
    const realError = toApiError({
      response: {
        status: 410,
        data: {
          success: false,
          error: { code: 'INVITATION_EXPIRED', message: 'This invitation has expired.' },
          request_id: null,
        },
      },
      message: 'Request failed with status code 410',
    } as never)

    previewInvitation.mockRejectedValue(realError)
    render(<AcceptInvitationPage />, { wrapper })
    await waitFor(() =>
      expect(navigate).toHaveBeenCalledWith('/invitation-expired', {
        replace: true,
        state: { code: 'INVITATION_EXPIRED' },
      }),
    )
  })

  it('offers a retry on an unexpected failure rather than a dead end', async () => {
    previewInvitation.mockRejectedValue({ status: 500, message: 'boom' })
    render(<AcceptInvitationPage />, { wrapper })
    expect(await screen.findByRole('button', { name: /try again/i })).toBeInTheDocument()
    expect(navigate).not.toHaveBeenCalled()
  })
})

describe('AcceptInvitationPage — accessibility (§17, §21)', () => {
  it('associates every field with a label', async () => {
    render(<AcceptInvitationPage />, { wrapper })
    await screen.findByText('Acme')
    expect(screen.getByLabelText('Email')).toBeInTheDocument()
    expect(screen.getByLabelText(/first name/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/last name/i)).toBeInTheDocument()
    expect(screen.getByLabelText('Password')).toBeInTheDocument()
    expect(screen.getByLabelText(/confirm password/i)).toBeInTheDocument()
  })

  it('marks invalid fields with aria-invalid and links their error text', async () => {
    render(<AcceptInvitationPage />, { wrapper })
    await screen.findByText('Acme')
    await userEvent.type(screen.getByLabelText('Password'), STRONG)
    const confirm = screen.getByLabelText(/confirm password/i)
    await userEvent.type(confirm, 'nope')
    expect(confirm).toHaveAttribute('aria-invalid', 'true')
    expect(confirm).toHaveAttribute('aria-describedby', 'confirmPassword-error')
    expect(document.getElementById('confirmPassword-error')).toBeInTheDocument()
  })

  it('exposes the strength meter as a labelled progressbar', async () => {
    render(<AcceptInvitationPage />, { wrapper })
    await screen.findByText('Acme')
    await userEvent.type(screen.getByLabelText('Password'), STRONG)
    const meter = screen.getByRole('progressbar', { name: /password strength/i })
    expect(meter).toHaveAttribute('aria-valuenow', '3')
    expect(meter).toHaveAttribute('aria-valuemax', '4')
  })

  it('announces the strength politely rather than stealing focus', async () => {
    render(<AcceptInvitationPage />, { wrapper })
    await screen.findByText('Acme')
    await userEvent.type(screen.getByLabelText('Password'), STRONG)
    const status = screen.getAllByRole('status').find((el) => el.textContent === 'Good')
    expect(status).toBeDefined()
    expect(status).toHaveAttribute('aria-live', 'polite')
  })

  it('announces server errors as an alert', async () => {
    registerFromInvitation.mockRejectedValue({ status: 422, message: 'Password is too common.' })
    render(<AcceptInvitationPage />, { wrapper })
    await screen.findByText('Acme')
    await fillValidForm()
    await userEvent.click(screen.getByRole('button', { name: /create account/i }))
    expect(await screen.findByRole('alert')).toBeInTheDocument()
  })
})
