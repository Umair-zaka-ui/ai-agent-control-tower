import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactNode } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const changePassword = vi.fn()
vi.mock('@/services', () => ({
  credentialService: {
    changePassword: (p: unknown) => changePassword(p),
  },
}))

const { ChangePasswordForm } = await import('../components/ChangePasswordForm')

const STRONG = 'Zt9$mQ2!vLp7Xw'

function wrapper({ children }: { children: ReactNode }) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
}

beforeEach(() => {
  vi.clearAllMocks()
  changePassword.mockResolvedValue({ message: 'ok' })
})

describe('ChangePasswordForm', () => {
  it('keeps submit disabled until the policy is met and passwords match', async () => {
    const user = userEvent.setup()
    render(<ChangePasswordForm onSuccess={vi.fn()} />, { wrapper })

    const submit = screen.getByRole('button', { name: /change password/i })
    expect(submit).toBeDisabled()

    await user.type(screen.getByLabelText(/current password/i), 'old-Password!1')
    await user.type(screen.getByLabelText('New password'), 'weak')
    expect(submit).toBeDisabled()

    await user.clear(screen.getByLabelText('New password'))
    await user.type(screen.getByLabelText('New password'), STRONG)
    await user.type(screen.getByLabelText(/confirm new password/i), STRONG)
    expect(submit).toBeEnabled()
  })

  it('submits and calls onSuccess', async () => {
    const user = userEvent.setup()
    const onSuccess = vi.fn()
    render(<ChangePasswordForm onSuccess={onSuccess} />, { wrapper })

    await user.type(screen.getByLabelText(/current password/i), 'old-Password!1')
    await user.type(screen.getByLabelText('New password'), STRONG)
    await user.type(screen.getByLabelText(/confirm new password/i), STRONG)
    await user.click(screen.getByRole('button', { name: /change password/i }))

    await waitFor(() => expect(onSuccess).toHaveBeenCalled())
    expect(changePassword).toHaveBeenCalledWith({
      current_password: 'old-Password!1',
      new_password: STRONG,
    })
  })

  it('renders a wrong-current-password error from the server', async () => {
    const user = userEvent.setup()
    changePassword.mockRejectedValue({ code: 'INVALID_CURRENT_PASSWORD', message: 'x' })
    render(<ChangePasswordForm onSuccess={vi.fn()} />, { wrapper })

    await user.type(screen.getByLabelText(/current password/i), 'wrong-Password!1')
    await user.type(screen.getByLabelText('New password'), STRONG)
    await user.type(screen.getByLabelText(/confirm new password/i), STRONG)
    await user.click(screen.getByRole('button', { name: /change password/i }))

    expect(await screen.findByRole('alert')).toHaveTextContent(/current password is incorrect/i)
  })

  it('refuses a new password equal to the current one', async () => {
    const user = userEvent.setup()
    render(<ChangePasswordForm onSuccess={vi.fn()} />, { wrapper })

    await user.type(screen.getByLabelText(/current password/i), STRONG)
    await user.type(screen.getByLabelText('New password'), STRONG)
    await user.type(screen.getByLabelText(/confirm new password/i), STRONG)

    expect(screen.getByText(/must differ from the current one/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /change password/i })).toBeDisabled()
  })
})
