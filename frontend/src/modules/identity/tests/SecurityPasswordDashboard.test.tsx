import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactNode } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { PasswordDashboard } from '@/types'

const dashboard = vi.fn()
const resetPassword = vi.fn()
vi.mock('@/services', () => ({
  adminCredentialService: {
    dashboard: () => dashboard(),
    resetPassword: (id: string) => resetPassword(id),
  },
}))

const { SecurityPasswordDashboard } = await import('../pages/SecurityPasswordDashboard')

function wrapper({ children }: { children: ReactNode }) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
}

const data: PasswordDashboard = {
  expired: [
    {
      user_id: 'u-exp',
      name: 'Expired Ed',
      email: 'ed@acme.com',
      expires_at: new Date(Date.now() - 86_400_000).toISOString(),
      days_until_expiry: 0,
      is_expired: true,
      must_change: false,
    },
  ],
  expiring_soon: [],
  temporary: [
    {
      user_id: 'u-tmp',
      name: 'Temp Tina',
      email: 'tina@acme.com',
      expires_at: null,
      days_until_expiry: null,
      is_expired: false,
      must_change: true,
    },
  ],
  must_change: [],
  total_users: 5,
}

beforeEach(() => {
  vi.clearAllMocks()
  dashboard.mockResolvedValue(data)
  resetPassword.mockResolvedValue({
    user_id: 'u-exp',
    temporary_password: 'Temp0rary!Pass99',
    expires_at: new Date().toISOString(),
    must_change_password: true,
    message: 'issued',
  })
})

describe('SecurityPasswordDashboard', () => {
  it('lists expired and temporary users', async () => {
    render(<SecurityPasswordDashboard />, { wrapper })
    expect(await screen.findByText('Expired Ed')).toBeInTheDocument()
    expect(screen.getByText('Temp Tina')).toBeInTheDocument()
    expect(screen.getByText(/5 members/i)).toBeInTheDocument()
  })

  it('reveals the temporary password exactly once after a reset', async () => {
    const user = userEvent.setup()
    render(<SecurityPasswordDashboard />, { wrapper })
    await screen.findByText('Expired Ed')

    // No temp password shown before a reset.
    expect(screen.queryByTestId('temp-password')).not.toBeInTheDocument()

    await user.click(screen.getAllByRole('button', { name: /reset/i })[0])

    const panel = await screen.findByTestId('temp-password')
    expect(panel).toHaveTextContent('Temp0rary!Pass99')
    expect(resetPassword).toHaveBeenCalledWith('u-exp')
  })
})
