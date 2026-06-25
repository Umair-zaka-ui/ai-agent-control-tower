import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { WidgetCard } from './WidgetCard'

describe('WidgetCard states', () => {
  it('renders children in the happy path', () => {
    render(
      <WidgetCard title="Activity">
        <p>chart goes here</p>
      </WidgetCard>,
    )
    expect(screen.getByText('chart goes here')).toBeInTheDocument()
  })

  it('shows an error message and retry button on error', async () => {
    const onRetry = vi.fn()
    render(
      <WidgetCard title="Activity" error onRetry={onRetry}>
        <p>chart goes here</p>
      </WidgetCard>,
    )
    expect(screen.queryByText('chart goes here')).not.toBeInTheDocument()
    expect(screen.getByText(/unable to load activity/i)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: /retry/i }))
    expect(onRetry).toHaveBeenCalled()
  })

  it('shows the empty message when empty', () => {
    render(
      <WidgetCard title="Activity" isEmpty emptyMessage="nothing here">
        <p>chart goes here</p>
      </WidgetCard>,
    )
    expect(screen.getByText('nothing here')).toBeInTheDocument()
  })
})
