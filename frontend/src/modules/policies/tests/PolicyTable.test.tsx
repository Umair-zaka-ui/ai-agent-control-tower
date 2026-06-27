import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'

import { PolicyTable } from '../components/PolicyTable'
import { policyFixture } from './fixtures'

function renderTable(props?: Partial<React.ComponentProps<typeof PolicyTable>>) {
  return render(
    <MemoryRouter>
      <PolicyTable
        policies={[policyFixture]}
        canManage
        canTest
        onToggle={vi.fn()}
        onDuplicate={vi.fn()}
        onDelete={vi.fn()}
        {...props}
      />
    </MemoryRouter>,
  )
}

describe('PolicyTable', () => {
  it('renders policy rows with decision, severity and status', () => {
    renderTable()
    expect(screen.getByText('Large Claim Approval')).toBeInTheDocument()
    expect(screen.getByText('CLAIM')).toBeInTheDocument()
    expect(screen.getByText('Pending Approval')).toBeInTheDocument()
    expect(screen.getByText('High')).toBeInTheDocument()
    expect(screen.getByText('Enabled')).toBeInTheDocument()
  })

  it('shows manage actions (Edit/Delete) for managers', async () => {
    renderTable({ canManage: true })
    await userEvent.click(screen.getByRole('button', { name: /actions for/i }))
    expect(screen.getByText('Edit')).toBeInTheDocument()
    expect(screen.getByText('Delete')).toBeInTheDocument()
  })

  it('hides manage actions for non-managers (role-based UI)', async () => {
    renderTable({ canManage: false, canTest: false })
    await userEvent.click(screen.getByRole('button', { name: /actions for/i }))
    expect(screen.queryByText('Edit')).not.toBeInTheDocument()
    expect(screen.queryByText('Delete')).not.toBeInTheDocument()
    expect(screen.getByText('View')).toBeInTheDocument()
  })
})
