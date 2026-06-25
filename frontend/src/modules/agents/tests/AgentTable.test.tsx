import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'

import { AgentTable } from '../components/AgentTable'
import type { Agent } from '../types'

const agent: Agent = {
  id: 'a1b2c3d4-0000-0000-0000-000000000000',
  organization_id: 'org',
  name: 'BillingBot',
  description: null,
  agent_type: 'billing',
  status: 'ACTIVE',
  owner: 'ops@example.com',
  department: 'Finance',
  version: '1.0.0',
  capabilities: ['read'],
  default_risk_score: 10,
  max_allowed_risk: 80,
  human_approval_required: false,
  auto_suspend_threshold: null,
  risk_level: 'LOW',
  health: 'HEALTHY',
  created_at: '2026-06-20T10:00:00Z',
  updated_at: '2026-06-25T10:00:00Z',
}

function renderTable(props?: Partial<React.ComponentProps<typeof AgentTable>>) {
  return render(
    <MemoryRouter>
      <AgentTable
        agents={[agent]}
        sortBy="created_at"
        sortDir="desc"
        onSort={vi.fn()}
        onStatusChange={vi.fn()}
        onDelete={vi.fn()}
        {...props}
      />
    </MemoryRouter>,
  )
}

describe('AgentTable', () => {
  it('renders agent rows with status and health', () => {
    renderTable()
    expect(screen.getByText('BillingBot')).toBeInTheDocument()
    expect(screen.getByText('billing')).toBeInTheDocument()
    expect(screen.getByText('Active')).toBeInTheDocument()
    expect(screen.getByText('Healthy')).toBeInTheDocument()
  })

  it('calls onSort when a sortable header is clicked', async () => {
    const onSort = vi.fn()
    renderTable({ onSort })
    await userEvent.click(screen.getByRole('button', { name: /sort by name/i }))
    expect(onSort).toHaveBeenCalledWith('name')
  })
})
