import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'

import { ActivityFeed } from '../components/ActivityFeed'
import { FleetHealthPanel } from '../components/FleetHealthPanel'
import { InsightsPanel } from '../components/InsightsPanel'
import { activityFeedFixture, fleetFixture, insightsFixture } from './fixtures'

describe('FleetHealthPanel', () => {
  it('renders the five health cards with counts', () => {
    render(<FleetHealthPanel data={fleetFixture} />)
    expect(screen.getByText('Healthy')).toBeInTheDocument()
    expect(screen.getByText('8')).toBeInTheDocument()
    expect(screen.getByText('Blocked')).toBeInTheDocument()
    expect(screen.getByText('Suspended')).toBeInTheDocument()
  })
})

describe('InsightsPanel', () => {
  it('renders rule-based insight titles', () => {
    render(<InsightsPanel insights={insightsFixture} />)
    expect(screen.getByText(/Approval volume increased 18%/)).toBeInTheDocument()
    expect(screen.getByText(/risk decreased by 12%/)).toBeInTheDocument()
  })

  it('shows an empty state with no insights', () => {
    render(<InsightsPanel insights={[]} />)
    expect(screen.getByText(/Analytics will appear/)).toBeInTheDocument()
  })
})

describe('ActivityFeed', () => {
  it('renders live actions with decision badges', () => {
    render(<ActivityFeed actions={activityFeedFixture} />)
    expect(screen.getByText('Submit Claim')).toBeInTheDocument()
    expect(screen.getByText('Approval requested')).toBeInTheDocument()
    expect(screen.getByText('Blocked')).toBeInTheDocument()
  })

  it('shows an empty state when there is no activity', () => {
    render(<ActivityFeed actions={[]} />)
    expect(screen.getByText('No recent activity')).toBeInTheDocument()
  })
})
