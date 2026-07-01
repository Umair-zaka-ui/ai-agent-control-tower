import { describe, expect, it } from 'vitest'

import { formatKpiValue, formatSeconds, isPositiveTrend, riskColor } from '../utils/format'
import { canViewAnalytics, canViewExecutive, canViewOperations } from '../utils/permissions'
import { kpisFixture } from './fixtures'

describe('analytics format utils', () => {
  it('formats KPI values with units', () => {
    expect(formatKpiValue(kpisFixture[2])).toBe('8.5%') // failure_rate
    expect(formatKpiValue(kpisFixture[3])).toBe('240ms') // avg_decision_time
    expect(formatKpiValue(kpisFixture[0])).toBe('12') // total_agents
  })

  it('treats a rising failure rate as a negative trend', () => {
    // failure_rate is up + positive_is_good=false → not positive.
    expect(isPositiveTrend(kpisFixture[2])).toBe(false)
    // actions_today up + positive_is_good=true → positive.
    expect(isPositiveTrend(kpisFixture[1])).toBe(true)
  })

  it('maps risk scores to band colours', () => {
    expect(riskColor(10)).not.toBe(riskColor(95))
  })

  it('formats durations from seconds', () => {
    expect(formatSeconds(45)).toBe('45s')
    expect(formatSeconds(3700)).toBe('1h 1m')
    expect(formatSeconds(null)).toBe('—')
  })
})

describe('analytics permissions', () => {
  it('gates surfaces on the right permission codes', () => {
    expect(canViewAnalytics(['analytics.view'])).toBe(true)
    expect(canViewAnalytics([])).toBe(false)
    expect(canViewExecutive(['analytics.executive'])).toBe(true)
    expect(canViewExecutive(['analytics.view'])).toBe(false)
    expect(canViewOperations(['analytics.operations'])).toBe(true)
    expect(canViewOperations(['analytics.view'])).toBe(false)
  })
})
