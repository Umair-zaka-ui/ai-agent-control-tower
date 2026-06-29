import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'

import { ApprovalTable } from '../components/ApprovalTable'
import { approvalRowFixture } from './fixtures'

function renderTable(props?: Partial<React.ComponentProps<typeof ApprovalTable>>) {
  return render(
    <MemoryRouter>
      <ApprovalTable approvals={[approvalRowFixture]} canReview {...props} />
    </MemoryRouter>,
  )
}

describe('ApprovalTable', () => {
  it('renders queue rows with agent, action, risk, priority and status', () => {
    renderTable()
    expect(screen.getByText('BillingAgent')).toBeInTheDocument()
    expect(screen.getByText('Submit Claim')).toBeInTheDocument()
    expect(screen.getByText('CLAIM')).toBeInTheDocument()
    expect(screen.getByText('92')).toBeInTheDocument()
    expect(screen.getByText('Critical')).toBeInTheDocument()
    expect(screen.getByText('Pending')).toBeInTheDocument()
  })

  it('shows reviewer actions (Approve/Reject) for reviewers', async () => {
    const onApprove = vi.fn()
    const onReject = vi.fn()
    renderTable({ onApprove, onReject })
    await userEvent.click(screen.getByRole('button', { name: /actions for/i }))
    expect(screen.getByText('Approve')).toBeInTheDocument()
    expect(screen.getByText('Reject')).toBeInTheDocument()

    await userEvent.click(screen.getByText('Approve'))
    expect(onApprove).toHaveBeenCalledWith(approvalRowFixture)
  })

  it('hides review actions for non-reviewers (role-based UI)', async () => {
    renderTable({ canReview: false })
    await userEvent.click(screen.getByRole('button', { name: /actions for/i }))
    expect(screen.queryByText('Approve')).not.toBeInTheDocument()
    expect(screen.queryByText('Open workbench')).not.toBeInTheDocument()
    expect(screen.getByText('View details')).toBeInTheDocument()
  })

  it('supports row selection when selectable', async () => {
    const onToggleSelect = vi.fn()
    renderTable({
      selectable: true,
      selected: new Set(),
      onToggleSelect,
      onToggleSelectAll: vi.fn(),
    })
    await userEvent.click(screen.getByRole('checkbox', { name: /select approval/i }))
    expect(onToggleSelect).toHaveBeenCalledWith(approvalRowFixture.id)
  })
})
