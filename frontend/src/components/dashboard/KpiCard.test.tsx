import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Bot } from 'lucide-react'

import { KpiCard } from './KpiCard'

describe('KpiCard', () => {
  it('renders the title and value', () => {
    render(<KpiCard title="Total Agents" value={23} icon={Bot} />)
    expect(screen.getByText('Total Agents')).toBeInTheDocument()
    expect(screen.getByText('23')).toBeInTheDocument()
  })

  it('shows a skeleton instead of the value while loading', () => {
    render(<KpiCard title="Total Agents" value={23} icon={Bot} loading />)
    expect(screen.queryByText('23')).not.toBeInTheDocument()
  })

  it('is keyboard-accessible and fires onClick when interactive', async () => {
    const onClick = vi.fn()
    render(<KpiCard title="Pending" value={7} icon={Bot} onClick={onClick} />)
    const card = screen.getByRole('button', { name: /pending/i })
    await userEvent.click(card)
    expect(onClick).toHaveBeenCalledTimes(1)
  })
})
