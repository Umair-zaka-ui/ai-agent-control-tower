import { describe, expect, it } from 'vitest'

import type { SecurityEvent } from '@/types'
import { eventDetail, eventLabel, eventSeverity, eventVariant } from '../eventLabels'

const event = (o: Partial<SecurityEvent> = {}): SecurityEvent =>
  ({
    id: 'e1',
    event_type: 'SESSION_CREATED',
    actor_type: 'HUMAN',
    actor_id: 'u1',
    target_type: 'HUMAN_USER',
    target_id: 'u1',
    organization_id: 'o1',
    request_id: null,
    correlation_id: null,
    ip_address: null,
    meta: {},
    created_at: new Date().toISOString(),
    ...o,
  }) as SecurityEvent

describe('eventLabel', () => {
  it('renders a human label instead of the raw enum', () => {
    expect(eventLabel('SESSION_LIMIT_EXCEEDED')).toBe('Oldest session signed out (device limit)')
    expect(eventLabel('TOKEN_REUSE_DETECTED')).toBe('Refresh-token reuse detected')
  })

  it('falls back to the raw code for an unknown event rather than hiding it', () => {
    // An event we cannot label is still an event the auditor must see.
    expect(eventLabel('SOME_FUTURE_EVENT')).toBe('SOME_FUTURE_EVENT')
  })
})

describe('eventSeverity', () => {
  it('treats theft and lockout signals as critical', () => {
    expect(eventSeverity('TOKEN_REUSE_DETECTED')).toBe('critical')
    expect(eventSeverity('SESSION_SUSPICIOUS')).toBe('critical')
    expect(eventSeverity('AUTH_LOGIN_LOCKED')).toBe('critical')
    expect(eventVariant('SESSION_SUSPICIOUS')).toBe('destructive')
  })

  it('treats failed logins, revocations and new devices as warnings', () => {
    expect(eventSeverity('AUTH_LOGIN_FAILED')).toBe('warning')
    expect(eventSeverity('SESSION_REVOKED')).toBe('warning')
    expect(eventSeverity('DEVICE_REGISTERED')).toBe('warning')
    expect(eventVariant('SESSION_REVOKED')).toBe('warning')
  })

  it('treats routine lifecycle events as info', () => {
    expect(eventSeverity('SESSION_CREATED')).toBe('info')
    expect(eventSeverity('TOKEN_ROTATED')).toBe('info')
    expect(eventVariant('SESSION_CREATED')).toBe('outline')
  })
})

describe('eventDetail — the forensic payload', () => {
  it('surfaces WHY and BY WHOM for an admin force-logout', () => {
    const detail = eventDetail(
      event({
        event_type: 'SESSION_REVOKED',
        meta: { reason: 'ADMIN_REVOKED', actor_email: 'owner@acme.com', session_id: 's1' },
      }),
    )
    expect(detail).toContain('admin revoked')
    expect(detail).toContain('by owner@acme.com')
  })

  it('surfaces the reason for a timeout', () => {
    expect(eventDetail(event({ event_type: 'SESSION_TIMEOUT', meta: { reason: 'IDLE_TIMEOUT' } }))).toContain(
      'idle timeout',
    )
  })

  it('surfaces the risk band on a suspicious session', () => {
    expect(
      eventDetail(event({ event_type: 'SESSION_SUSPICIOUS', meta: { band: 'HIGH_RISK', signal: 'x' } })),
    ).toContain('risk: high risk')
  })

  it('surfaces signals and IP where present', () => {
    const detail = eventDetail(
      event({ event_type: 'SUSPICIOUS_LOGIN', ip_address: '203.0.113.7', meta: { signals: ['new_device'] } }),
    )
    expect(detail).toContain('new_device')
    expect(detail).toContain('203.0.113.7')
  })

  it('returns null when there is nothing forensic to say', () => {
    expect(eventDetail(event())).toBeNull()
  })
})
