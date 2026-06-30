import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'

import { AuditTimeline } from '../components/AuditTimeline'
import { auditTimelineFixture } from './fixtures'

function renderTimeline(items = auditTimelineFixture) {
  return render(
    <MemoryRouter>
      <AuditTimeline items={items} />
    </MemoryRouter>,
  )
}

describe('AuditTimeline', () => {
  it('renders each activity label linked to its event', () => {
    renderTimeline()
    const link = screen.getByRole('link', { name: /BillingAgent Submit Claim/i })
    expect(link).toHaveAttribute('href', `/audit/${auditTimelineFixture[0].id}`)
  })

  it('shows an empty state when there are no items', () => {
    renderTimeline([])
    expect(screen.getByText('No recent activity')).toBeInTheDocument()
  })
})
