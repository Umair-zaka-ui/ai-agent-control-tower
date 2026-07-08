import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactNode } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const navigate = vi.fn()
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom')
  return {
    ...actual,
    useNavigate: () => navigate,
    useParams: () => ({ token: 'vrf_test-token' }),
    Link: ({ children, to }: { children: ReactNode; to: string }) => <a href={to}>{children}</a>,
  }
})

const verifyEmail = vi.fn()
const resendVerification = vi.fn()
vi.mock('@/services/registrationService', () => ({
  registrationService: {
    verifyEmail: (t: string) => verifyEmail(t),
    resendVerification: (e: string) => resendVerification(e),
    previewInvitation: vi.fn(),
    registerFromInvitation: vi.fn(),
  },
  invitationService: {},
}))

const { VerifyEmailPage } = await import('../pages/VerifyEmailPage')

function wrapper({ children }: { children: ReactNode }) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
}

beforeEach(() => {
  vi.clearAllMocks()
  resendVerification.mockResolvedValue({ message: 'ok' })
})

describe('VerifyEmailPage (§12, §16)', () => {
  it('redeems the token automatically — the user already clicked the link', async () => {
    verifyEmail.mockResolvedValue({
      email: 'ada@acme.com',
      status: 'ACTIVE',
      email_sent: true,
      requires_approval: false,
      message: 'Your email is confirmed. You can now sign in.',
    })
    render(<VerifyEmailPage />, { wrapper })
    await waitFor(() => expect(verifyEmail).toHaveBeenCalledWith('vrf_test-token'))
    expect(await screen.findByText(/email confirmed/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /go to sign in/i })).toBeInTheDocument()
  })

  it('redeems the single-use token exactly once, even under StrictMode double-effects', async () => {
    verifyEmail.mockResolvedValue({
      email: 'ada@acme.com', status: 'ACTIVE', email_sent: true,
      requires_approval: false, message: 'ok',
    })
    const { rerender } = render(<VerifyEmailPage />, { wrapper })
    rerender(<VerifyEmailPage />)
    await waitFor(() => expect(verifyEmail).toHaveBeenCalledTimes(1))
  })

  it('tells a self-registered user that approval is still required', async () => {
    verifyEmail.mockResolvedValue({
      email: 'ada@acme.com',
      status: 'EMAIL_VERIFIED',
      email_sent: true,
      requires_approval: true,
      message: 'Awaiting approval.',
    })
    render(<VerifyEmailPage />, { wrapper })
    expect(await screen.findByText(/administrator must approve/i)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /go to sign in/i })).not.toBeInTheDocument()
  })

  it('treats an already-verified address as success, not failure', async () => {
    verifyEmail.mockRejectedValue({ code: 'EMAIL_ALREADY_VERIFIED', status: 409 })
    render(<VerifyEmailPage />, { wrapper })
    expect(await screen.findByText(/already confirmed/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /go to sign in/i })).toBeInTheDocument()
  })

  it('offers a resend on an expired link, and says how long links last', async () => {
    verifyEmail.mockRejectedValue({ code: 'VERIFICATION_TOKEN_EXPIRED', status: 410 })
    render(<VerifyEmailPage />, { wrapper })
    expect(await screen.findByText(/this link has expired/i)).toBeInTheDocument()
    expect(screen.getByText(/24 hours/)).toBeInTheDocument()

    await userEvent.type(screen.getByLabelText(/your email/i), 'ada@acme.com')
    await userEvent.click(screen.getByRole('button', { name: /send a new link/i }))
    await waitFor(() => expect(resendVerification).toHaveBeenCalledWith('ada@acme.com'))
  })

  it('gives the same non-committal acknowledgement after a resend (§14)', async () => {
    verifyEmail.mockRejectedValue({ code: 'INVALID_VERIFICATION_TOKEN', status: 400 })
    render(<VerifyEmailPage />, { wrapper })
    await screen.findByText(/this link is not valid/i)
    await userEvent.type(screen.getByLabelText(/your email/i), 'nobody@example.com')
    await userEvent.click(screen.getByRole('button', { name: /send a new link/i }))

    // Must not say "we sent you an email" — that would confirm the account exists.
    expect(await screen.findByText(/if that address needs verification/i)).toBeInTheDocument()
  })

  it('announces failures as an alert for screen readers', async () => {
    verifyEmail.mockRejectedValue({ code: 'INVALID_VERIFICATION_TOKEN', status: 400 })
    render(<VerifyEmailPage />, { wrapper })
    expect(await screen.findByRole('alert')).toBeInTheDocument()
  })
})
