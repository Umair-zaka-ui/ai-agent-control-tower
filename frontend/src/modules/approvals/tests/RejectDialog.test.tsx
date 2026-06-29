import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { RejectDialog } from '../components/RejectDialog'
import { REJECT_REASON_MIN } from '../utils/constants'

describe('RejectDialog', () => {
  it('requires a reason of at least the minimum length before confirming', async () => {
    const onConfirm = vi.fn()
    render(<RejectDialog open onOpenChange={vi.fn()} onConfirm={onConfirm} />)

    const confirm = screen.getByRole('button', { name: /confirm rejection/i })
    expect(confirm).toBeDisabled()

    // Too short.
    await userEvent.type(screen.getByLabelText(/rejection reason/i), 'too short')
    expect(confirm).toBeDisabled()

    // Long enough.
    await userEvent.clear(screen.getByLabelText(/rejection reason/i))
    await userEvent.type(screen.getByLabelText(/rejection reason/i), 'x'.repeat(REJECT_REASON_MIN))
    expect(confirm).toBeEnabled()

    await userEvent.click(confirm)
    expect(onConfirm).toHaveBeenCalledOnce()
  })
})
