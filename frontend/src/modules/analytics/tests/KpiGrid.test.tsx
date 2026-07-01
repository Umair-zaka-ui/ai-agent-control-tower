import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'

import { KpiGrid } from '../components/KpiGrid'
import { kpisFixture } from './fixtures'

function renderGrid(props?: Partial<React.ComponentProps<typeof KpiGrid>>) {
  return render(
    <MemoryRouter>
      <KpiGrid kpis={kpisFixture} {...props} />
    </MemoryRouter>,
  )
}

describe('KpiGrid', () => {
  it('renders every KPI label', () => {
    renderGrid()
    expect(screen.getByText('Total AI Agents')).toBeInTheDocument()
    expect(screen.getByText('AI Actions Today')).toBeInTheDocument()
    expect(screen.getByText('AI Failure Rate')).toBeInTheDocument()
  })

  it('marks estimated KPIs with an asterisk', () => {
    renderGrid()
    expect(screen.getByText('Avg Decision Time *')).toBeInTheDocument()
  })

  it('shows period-over-period change for trending KPIs', () => {
    renderGrid()
    expect(screen.getAllByText(/% vs prev/).length).toBeGreaterThanOrEqual(2)
  })

  it('renders a skeleton while loading', () => {
    const { container } = render(
      <MemoryRouter>
        <KpiGrid loading />
      </MemoryRouter>,
    )
    expect(container.querySelectorAll('.animate-pulse').length).toBeGreaterThan(0)
  })

  it('filters to a subset when "only" is provided', () => {
    renderGrid({ only: ['total_agents'] })
    expect(screen.getByText('Total AI Agents')).toBeInTheDocument()
    expect(screen.queryByText('AI Failure Rate')).not.toBeInTheDocument()
  })
})
