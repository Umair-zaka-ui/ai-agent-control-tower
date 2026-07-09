import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import type { ReactNode } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const navigate = vi.fn()
let currentToken = 'rst_valid-token'
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom')
  return {
    ...actual,
    useNavigate: () => navigate,
    useParams: () => ({ token: currentToken }),
  }
})

const forgotPassword = vi.fn()
const resetPassword = vi.fn()
const verifyNewEmail = vi.fn()
vi.mock('@/services', () => ({
  recoveryService: {
    forgotPassword: (e: string) => forgotPassword(e),
    resetPassword: (p: unknown) => resetPassword(p),
    verifyNewEmail: (t: string) => verifyNewEmail(t),
  },
}))

const { ForgotPasswordPage } = await import('../pages/ForgotPasswordPage')
const { ResetPasswordPage } = await import('../pages/ResetPasswordPage')
const { VerifyNewEmailPage } = await import('../pages/VerifyNewEmailPage')

const STRONG = 'Zt9$mQ2!vLp7Xw'

function wrapper({ children }: { children: ReactNode }) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  const { MemoryRouter } = require('react-router-dom')
  return (
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>{children}</MemoryRouter>
    </QueryClientProvider>
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  currentToken = 'rst_valid-token'
  forgotPassword.mockResolvedValue({ success: true, message: 'ok' })
  resetPassword.mockResolvedValue({ success: true, message: 'ok' })
  verifyNewEmail.mockResolvedValue({ success: true, message: 'ok' })
})

// --------------------------------------------------------------------------- //
// Forgot password — uniform, non-enumerating
// --------------------------------------------------------------------------- //
describe('ForgotPasswordPage', () => {
  it('shows the same confirmation whether or not the account exists', async () => {
    const user = userEvent.setup()
    render(<ForgotPasswordPage />, { wrapper })
    await user.type(screen.getByLabelText(/email/i), 'someone@example.com')
    await user.click(screen.getByRole('button', { name: /send reset link/i }))
    expect(await screen.findByText(/check your email/i)).toBeInTheDocument()
    expect(screen.getByText(/if an account exists/i)).toBeInTheDocument()
  })

  it('still shows the neutral confirmation when the request errors (no oracle)', async () => {
    const user = userEvent.setup()
    forgotPassword.mockRejectedValue({ status: 500, message: 'boom' })
    render(<ForgotPasswordPage />, { wrapper })
    await user.type(screen.getByLabelText(/email/i), 'someone@example.com')
    await user.click(screen.getByRole('button', { name: /send reset link/i }))
    expect(await screen.findByText(/check your email/i)).toBeInTheDocument()
  })
})

// --------------------------------------------------------------------------- //
// Reset password
// --------------------------------------------------------------------------- //
describe('ResetPasswordPage', () => {
  it('keeps submit disabled until the policy is met and passwords match', async () => {
    const user = userEvent.setup()
    render(<ResetPasswordPage />, { wrapper })
    const submit = screen.getByRole('button', { name: /reset password/i })
    expect(submit).toBeDisabled()
    await user.type(screen.getByLabelText('New password'), STRONG)
    await user.type(screen.getByLabelText(/confirm new password/i), STRONG)
    expect(submit).toBeEnabled()
  })

  it('submits the token from the URL and navigates to success', async () => {
    const user = userEvent.setup()
    render(<ResetPasswordPage />, { wrapper })
    await user.type(screen.getByLabelText('New password'), STRONG)
    await user.type(screen.getByLabelText(/confirm new password/i), STRONG)
    await user.click(screen.getByRole('button', { name: /reset password/i }))
    await waitFor(() =>
      expect(resetPassword).toHaveBeenCalledWith({ token: 'rst_valid-token', new_password: STRONG }),
    )
    expect(navigate).toHaveBeenCalledWith('/recovery-success', { replace: true })
  })

  it('shows a dead-link message and a way to request a new link when the token is expired', async () => {
    const user = userEvent.setup()
    resetPassword.mockRejectedValue({ code: 'RESET_TOKEN_EXPIRED', message: 'x' })
    render(<ResetPasswordPage />, { wrapper })
    await user.type(screen.getByLabelText('New password'), STRONG)
    await user.type(screen.getByLabelText(/confirm new password/i), STRONG)
    await user.click(screen.getByRole('button', { name: /reset password/i }))
    expect(await screen.findByText(/link no longer works/i)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /request a new reset link/i })).toBeInTheDocument()
  })
})

// --------------------------------------------------------------------------- //
// Verify new email
// --------------------------------------------------------------------------- //
describe('VerifyNewEmailPage', () => {
  it('redeems the token automatically and confirms the change', async () => {
    render(<VerifyNewEmailPage />, { wrapper })
    expect(await screen.findByText(/email updated/i)).toBeInTheDocument()
    expect(verifyNewEmail).toHaveBeenCalledWith('rst_valid-token')
  })

  it('treats an already-confirmed change as success, not an error', async () => {
    verifyNewEmail.mockRejectedValue({ code: 'EMAIL_ALREADY_VERIFIED', message: 'x' })
    render(<VerifyNewEmailPage />, { wrapper })
    expect(await screen.findByText(/email updated/i)).toBeInTheDocument()
  })

  it('shows an expired message for a dead confirmation link', async () => {
    verifyNewEmail.mockRejectedValue({ code: 'EMAIL_VERIFICATION_EXPIRED', message: 'x' })
    render(<VerifyNewEmailPage />, { wrapper })
    expect(await screen.findByText(/link expired/i)).toBeInTheDocument()
  })
})
