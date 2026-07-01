import { describe, expect, it } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'

import { AuditTable } from '../components/AuditTable'
import { auditLoginRowFixture, auditRowFixture } from './fixtures'

function renderTable(events = [auditRowFixture]) {
  return render(
    <MemoryRouter>
      <AuditTable events={events} />
    </MemoryRouter>,
  )
}

describe('AuditTable', () => {
  it('renders the event row with actor, type, resource, severity and status', () => {
    renderTable()
    expect(screen.getByText('BillingAgent')).toBeInTheDocument()
    expect(screen.getByText('Agent Action Decision')).toBeInTheDocument()
    expect(screen.getByText('CLAIM')).toBeInTheDocument()
    expect(screen.getByText('High')).toBeInTheDocument()
    expect(screen.getByText('Blocked')).toBeInTheDocument()
  })

  it('links the event id and the row action to the detail route', () => {
    renderTable()
    const links = screen.getAllByRole('link', { name: /11111111|view event/i })
    expect(links.length).toBeGreaterThan(0)
    expect(links[0]).toHaveAttribute('href', `/audit/${auditRowFixture.id}`)
  })

  it('renders a dash for events without a resource or decision', () => {
    renderTable([auditLoginRowFixture])
    const row = screen.getByText('Jane Reviewer').closest('tr') as HTMLElement
    expect(within(row).getAllByText('—').length).toBeGreaterThanOrEqual(2)
    expect(within(row).getByText('Auth Login')).toBeInTheDocument()
  })
})
