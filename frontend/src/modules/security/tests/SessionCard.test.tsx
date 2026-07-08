import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import type { AuthDevice, AuthSession } from '@/types'
import { DeviceCard } from '../components/DeviceCard'
import { SessionCard } from '../components/SessionCard'

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
    last_seen_at: new Date().toISOString(),
    last_activity_at: new Date().toISOString(),
    idle_expires_at: new Date(Date.now() + 30 * 60_000).toISOString(),
    absolute_expires_at: new Date(Date.now() + 12 * 3_600_000).toISOString(),
    revoked_at: null,
    revoked_reason: null,
    security_score: 100,
    is_trusted: false,
    is_current: false,
    security_band: 'HEALTHY',
    ...overrides,
  }) as AuthSession

const device = (overrides: Partial<AuthDevice> = {}): AuthDevice =>
  ({
    id: 'd1',
    device_name: 'Safari on iOS',
    device_type: 'mobile',
    browser: 'Safari',
    browser_version: '17',
    operating_system: 'iOS',
    status: 'UNKNOWN',
    last_ip: '198.51.100.4',
    last_seen_at: new Date().toISOString(),
    created_at: new Date().toISOString(),
    is_current: false,
    ...overrides,
  }) as AuthDevice

describe('SessionCard (SRS §18, §19)', () => {
  it('marks the current device and labels its action "Sign out"', () => {
    render(<SessionCard session={session({ is_current: true })} onRevoke={vi.fn()} />)
    expect(screen.getByTestId('current-session-badge')).toHaveTextContent(/current device/i)
    expect(screen.getByRole('button', { name: /sign out/i })).toBeInTheDocument()
  })

  it('labels another device\'s action "Revoke"', () => {
    render(<SessionCard session={session()} onRevoke={vi.fn()} />)
    expect(screen.getByRole('button', { name: /revoke/i })).toBeInTheDocument()
    expect(screen.queryByTestId('current-session-badge')).not.toBeInTheDocument()
  })

  it('surfaces the security band and score', () => {
    render(<SessionCard session={session({ security_band: 'HIGH_RISK', security_score: 20 })} onRevoke={vi.fn()} />)
    expect(screen.getByText(/high risk · 20/i)).toBeInTheDocument()
  })

  it('shows when the session will idle out', () => {
    render(<SessionCard session={session()} onRevoke={vi.fn()} />)
    expect(screen.getByText(/signs out in .* if idle/i)).toBeInTheDocument()
  })

  it('hands the session back to the caller on revoke', async () => {
    const onRevoke = vi.fn()
    const s = session()
    render(<SessionCard session={s} onRevoke={onRevoke} />)
    await userEvent.click(screen.getByRole('button', { name: /revoke/i }))
    expect(onRevoke).toHaveBeenCalledWith(s)
  })

  it('disables the action while another mutation is in flight', () => {
    render(<SessionCard session={session()} onRevoke={vi.fn()} pending />)
    expect(screen.getByRole('button', { name: /revoke/i })).toBeDisabled()
  })
})

describe('DeviceCard (SRS §14)', () => {
  it('offers Trust for an unknown device', async () => {
    const onTrust = vi.fn()
    render(<DeviceCard device={device()} onTrust={onTrust} onBlock={vi.fn()} />)
    await userEvent.click(screen.getByRole('button', { name: /trust/i }))
    expect(onTrust).toHaveBeenCalled()
  })

  it('hides Trust once the device is trusted', () => {
    render(<DeviceCard device={device({ status: 'TRUSTED' })} onTrust={vi.fn()} onBlock={vi.fn()} />)
    expect(screen.queryByRole('button', { name: /trust/i })).not.toBeInTheDocument()
    expect(screen.getByText('TRUSTED')).toBeInTheDocument()
  })

  it('offers no actions on a blocked device', () => {
    render(<DeviceCard device={device({ status: 'BLOCKED' })} onTrust={vi.fn()} onBlock={vi.fn()} />)
    expect(screen.queryByRole('button', { name: /trust/i })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /block/i })).not.toBeInTheDocument()
  })

  it('refuses to block the device you are using', () => {
    // Blocking your own device signs you out and locks you out of signing back in.
    render(<DeviceCard device={device({ is_current: true })} onTrust={vi.fn()} onBlock={vi.fn()} />)
    expect(screen.getByRole('button', { name: /block/i })).toBeDisabled()
    expect(screen.getByText(/this device/i)).toBeInTheDocument()
  })
})
