import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { DeleteConfirmModal } from '../components/DeleteConfirmModal'

describe('DeleteConfirmModal', () => {
  it('keeps the delete button disabled until DELETE is typed', async () => {
    const onConfirm = vi.fn()
    render(
      <DeleteConfirmModal
        open
        onOpenChange={vi.fn()}
        policyName="Large Claim Approval"
        onConfirm={onConfirm}
      />,
    )

    const deleteButton = screen.getByRole('button', { name: /delete policy/i })
    expect(deleteButton).toBeDisabled()

    await userEvent.type(screen.getByLabelText(/type delete to confirm/i), 'DELETE')
    expect(deleteButton).toBeEnabled()

    await userEvent.click(deleteButton)
    expect(onConfirm).toHaveBeenCalledTimes(1)
  })
})
