import { describe, expect, it } from 'vitest'

import { humanizeConditions } from '../utils/conditions'
import { formatDuration, humanizeToken, riskLevel, slaCountdown } from '../utils/format'

describe('approval formatters', () => {
  it('formats review durations', () => {
    expect(formatDuration(null)).toBe('—')
    expect(formatDuration(45)).toBe('45s')
    expect(formatDuration(5 * 60)).toBe('5m')
    expect(formatDuration(2 * 3600 + 5 * 60)).toBe('2h 5m')
    expect(formatDuration(26 * 3600)).toBe('1d 2h')
  })

  it('maps risk scores to levels', () => {
    expect(riskLevel(10)).toBe('Low')
    expect(riskLevel(45)).toBe('Moderate')
    expect(riskLevel(70)).toBe('High')
    expect(riskLevel(95)).toBe('Critical')
  })

  it('humanizes SCREAMING_SNAKE tokens', () => {
    expect(humanizeToken('SUBMIT_CLAIM')).toBe('Submit Claim')
    expect(humanizeToken(null)).toBe('—')
  })

  it('computes an SLA countdown and flags overdue', () => {
    const future = new Date(Date.now() + 60 * 60 * 1000).toISOString()
    const past = new Date(Date.now() - 60 * 60 * 1000).toISOString()
    expect(slaCountdown(null)).toBeNull()
    expect(slaCountdown(future)?.overdue).toBe(false)
    const overdue = slaCountdown(past)
    expect(overdue?.overdue).toBe(true)
    expect(overdue?.label).toContain('Overdue')
  })

  it('humanizes policy conditions like the engine', () => {
    expect(humanizeConditions({ amount_gt: 10000 })).toEqual(['amount > 10000'])
    expect(humanizeConditions({ region_eq: 'US' })).toEqual(['region = US'])
    expect(humanizeConditions(null)).toEqual([])
  })
})
