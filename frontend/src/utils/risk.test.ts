import { describe, expect, it } from 'vitest'

import { getRiskColorClass, getRiskLevel } from './risk'

describe('risk helpers', () => {
  it('buckets scores into levels by backend thresholds', () => {
    expect(getRiskLevel(10)).toBe('low')
    expect(getRiskLevel(40)).toBe('low')
    expect(getRiskLevel(41)).toBe('medium')
    expect(getRiskLevel(80)).toBe('medium')
    expect(getRiskLevel(81)).toBe('high')
  })

  it('maps levels to semantic colour classes', () => {
    expect(getRiskColorClass(10)).toBe('text-success')
    expect(getRiskColorClass(50)).toBe('text-warning')
    expect(getRiskColorClass(90)).toBe('text-destructive')
  })
})
