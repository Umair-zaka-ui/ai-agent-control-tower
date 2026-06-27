import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'

import { PolicyBuilder } from '../components/PolicyBuilder'

function renderBuilder(props?: Partial<React.ComponentProps<typeof PolicyBuilder>>) {
  return render(
    <MemoryRouter>
      <PolicyBuilder mode="create" onSubmit={vi.fn()} onCancel={vi.fn()} {...props} />
    </MemoryRouter>,
  )
}

describe('PolicyBuilder', () => {
  it('blocks step 1 with validation errors when required fields are empty', async () => {
    const onSubmit = vi.fn()
    renderBuilder({ onSubmit })

    await userEvent.click(screen.getByRole('button', { name: /next/i }))

    expect(screen.getByText('Policy name is required')).toBeInTheDocument()
    expect(screen.getByText('Description is required')).toBeInTheDocument()
    expect(onSubmit).not.toHaveBeenCalled()
  })

  it('advances past step 1 once name and description are provided', async () => {
    renderBuilder()

    await userEvent.type(screen.getByLabelText(/policy name/i), 'Block PHI export')
    await userEvent.type(screen.getByLabelText(/description/i), 'Stop PHI leaving the org')
    await userEvent.click(screen.getByRole('button', { name: /next/i }))

    expect(screen.queryByText('Policy name is required')).not.toBeInTheDocument()
    expect(screen.getByText(/all agents in the organization/i)).toBeInTheDocument()
  })
})
