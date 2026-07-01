import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { ExportDialog } from '../components/ExportDialog'

describe('ExportDialog', () => {
  it('exports as CSV by default and reports the matching count', async () => {
    const onConfirm = vi.fn()
    render(
      <ExportDialog open onOpenChange={vi.fn()} count={42} onConfirm={onConfirm} />,
    )
    expect(screen.getByText(/42 events matching/i)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: /^export$/i }))
    expect(onConfirm).toHaveBeenCalledWith('csv')
  })

  it('lets the user pick JSON', async () => {
    const onConfirm = vi.fn()
    render(<ExportDialog open onOpenChange={vi.fn()} onConfirm={onConfirm} />)
    await userEvent.click(screen.getByRole('button', { name: /JSON/i }))
    await userEvent.click(screen.getByRole('button', { name: /^export$/i }))
    expect(onConfirm).toHaveBeenCalledWith('json')
  })

  it('keeps the PDF option disabled (placeholder)', () => {
    render(<ExportDialog open onOpenChange={vi.fn()} onConfirm={vi.fn()} />)
    expect(screen.getByRole('button', { name: /PDF/i })).toBeDisabled()
  })
})
