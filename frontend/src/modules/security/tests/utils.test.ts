import { describe, expect, it, vi } from 'vitest'

import type { AuthDevice, AuthSession } from '@/types'
import {
  bandLabel,
  bandVariant,
  describeClient,
  describeLocation,
  deviceStatusVariant,
  expiresIn,
  timeAgo,
} from '../utils'

const session = (overrides: Partial<AuthSession> = {}): AuthSession =>
  ({
    id: 's1',
    status: 'ACTIVE',
    device_id: 'd1',
    device_name: 'Chrome on Windows 10/11',
    device_type: 'desktop',
    browser: 'Chrome',
    browser_version: '120',
    operating_system: 'Windows 10/11',
    ip_address: '203.0.113.7',
    country: null,
    city: null,
    login_method: 'PASSWORD',
    created_at: new Date().toISOString(),
    last_seen_at: null,
    last_activity_at: null,
    idle_expires_at: new Date().toISOString(),
    absolute_expires_at: new Date().toISOString(),
    revoked_at: null,
    revoked_reason: null,
    security_score: 100,
    is_trusted: false,
    is_current: false,
    security_band: 'HEALTHY',
    ...overrides,
  }) as AuthSession

describe('security band mapping (SRS §15)', () => {
  it('maps each band to its badge variant and label', () => {
    expect(bandVariant('HEALTHY')).toBe('success')
    expect(bandVariant('WARNING')).toBe('warning')
    expect(bandVariant('HIGH_RISK')).toBe('destructive')
    expect(bandLabel('HIGH_RISK')).toBe('High risk')
  })

  it('degrades to healthy when the server sends no band', () => {
    expect(bandVariant(null)).toBe('success')
    expect(bandLabel(null)).toBe('Healthy')
  })
})

describe('device status mapping (SRS §14)', () => {
  it('marks blocked devices destructive and trusted ones success', () => {
    expect(deviceStatusVariant('TRUSTED')).toBe('success')
    expect(deviceStatusVariant('BLOCKED')).toBe('destructive')
    expect(deviceStatusVariant('UNKNOWN')).toBe('outline')
  })
})

describe('describeClient', () => {
  it('prefers the server-rendered device name', () => {
    expect(describeClient(session())).toBe('Chrome on Windows 10/11')
  })

  it('falls back to browser + OS when the name is missing', () => {
    expect(describeClient(session({ device_name: null }))).toBe('Chrome on Windows 10/11')
  })

  it('degrades gracefully for an unparsed client', () => {
    const bare = session({ device_name: null, browser: null, operating_system: null })
    expect(describeClient(bare)).toBe('Unknown browser')
  })

  it('works for devices as well as sessions', () => {
    const device = { device_name: 'Safari on iOS', browser: 'Safari' } as AuthDevice
    expect(describeClient(device)).toBe('Safari on iOS')
  })
})

describe('describeLocation', () => {
  it('shows city, country and IP when geo headers are present', () => {
    const s = session({ city: 'Lisbon', country: 'PT' })
    expect(describeLocation(s)).toBe('Lisbon, PT · 203.0.113.7')
  })

  it('falls back to the IP when no reverse proxy supplies geo', () => {
    expect(describeLocation(session())).toBe('203.0.113.7')
  })

  it('says unknown when there is nothing at all', () => {
    expect(describeLocation(session({ ip_address: null }))).toBe('Unknown location')
  })
})

describe('timeAgo', () => {
  it('handles the never case', () => {
    expect(timeAgo(null)).toBe('never')
  })

  it('renders coarse relative times', () => {
    const now = new Date('2026-07-08T12:00:00Z')
    vi.useFakeTimers()
    vi.setSystemTime(now)
    expect(timeAgo(new Date('2026-07-08T11:59:30Z').toISOString())).toBe('just now')
    expect(timeAgo(new Date('2026-07-08T11:45:00Z').toISOString())).toBe('15m ago')
    expect(timeAgo(new Date('2026-07-08T09:00:00Z').toISOString())).toBe('3h ago')
    expect(timeAgo(new Date('2026-07-07T12:00:00Z').toISOString())).toBe('yesterday')
    expect(timeAgo(new Date('2026-07-05T12:00:00Z').toISOString())).toBe('3d ago')
    vi.useRealTimers()
  })
})

describe('expiresIn (idle countdown, SRS §12)', () => {
  it('reports a past deadline as expired rather than a negative time', () => {
    expect(expiresIn(new Date(Date.now() - 60_000).toISOString())).toBe('expired')
  })

  it('never rounds a live session down to 0m', () => {
    expect(expiresIn(new Date(Date.now() + 20_000).toISOString())).toBe('1m')
  })

  it('renders minutes, hours and days', () => {
    expect(expiresIn(new Date(Date.now() + 25 * 60_000).toISOString())).toBe('25m')
    expect(expiresIn(new Date(Date.now() + 3 * 3_600_000).toISOString())).toBe('3h')
    expect(expiresIn(new Date(Date.now() + 7 * 86_400_000).toISOString())).toBe('7d')
  })
})
