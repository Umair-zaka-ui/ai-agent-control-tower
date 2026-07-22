import { describe, expect, it } from 'vitest'

import {
  AGENT_LIFECYCLE_VARIANT,
  CRITICALITY_VARIANT,
  DEPLOYMENT_STATUS_VARIANT,
  EXECUTION_STATUS_VARIANT,
  formatCost,
  formatDate,
  formatMs,
  VERSION_STATUS_VARIANT,
} from '../utils'

describe('runtime formatters', () => {
  it('formats cost with four decimal places', () => {
    expect(formatCost(0.000123)).toBe('$0.0001')
    expect(formatCost(0)).toBe('$0.0000')
    expect(formatCost(null)).toBe('—')
    expect(formatCost(undefined)).toBe('—')
  })

  it('formats sub-second durations in ms and longer ones in seconds', () => {
    expect(formatMs(42)).toBe('42ms')
    expect(formatMs(999)).toBe('999ms')
    expect(formatMs(1500)).toBe('1.50s')
    expect(formatMs(null)).toBe('—')
  })

  it('formats a null/undefined date as an em dash', () => {
    expect(formatDate(null)).toBe('—')
    expect(formatDate(undefined)).toBe('—')
  })

  it('formats a real ISO date without throwing', () => {
    expect(formatDate('2026-07-18T05:59:56.602040+05:00')).not.toBe('—')
  })
})

describe('runtime status → badge-variant maps', () => {
  it('covers every status this build actually produces', () => {
    for (const status of ['DRAFT', 'ACTIVE', 'SUSPENDED', 'RETIRED']) {
      expect(AGENT_LIFECYCLE_VARIANT[status]).toBeDefined()
    }
    for (const status of ['DRAFT', 'PUBLISHED', 'REVOKED']) {
      expect(VERSION_STATUS_VARIANT[status]).toBeDefined()
    }
    for (const status of ['CREATED', 'ACTIVE', 'FAILED', 'RETIRED']) {
      expect(DEPLOYMENT_STATUS_VARIANT[status]).toBeDefined()
    }
    for (const status of ['SUCCEEDED', 'FAILED', 'TIMED_OUT', 'DEAD_LETTERED', 'BLOCKED']) {
      expect(EXECUTION_STATUS_VARIANT[status]).toBeDefined()
    }
    for (const level of ['LOW', 'MEDIUM', 'HIGH', 'MISSION_CRITICAL']) {
      expect(CRITICALITY_VARIANT[level]).toBeDefined()
    }
  })

  it('marks success/failure states with the matching semantic variant', () => {
    expect(EXECUTION_STATUS_VARIANT.SUCCEEDED).toBe('success')
    expect(EXECUTION_STATUS_VARIANT.FAILED).toBe('destructive')
    expect(EXECUTION_STATUS_VARIANT.DEAD_LETTERED).toBe('destructive')
    expect(AGENT_LIFECYCLE_VARIANT.ACTIVE).toBe('success')
    expect(CRITICALITY_VARIANT.MISSION_CRITICAL).toBe('destructive')
  })
})
