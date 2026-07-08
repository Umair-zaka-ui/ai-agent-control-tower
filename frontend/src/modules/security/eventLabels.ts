import type { SecurityEvent } from '@/types'

/**
 * Human-readable labels for the security-event stream (SRS §26).
 *
 * An audit reader should not have to know that `SESSION_LIMIT_EXCEEDED` means
 * "signed out because they hit the device limit". Unknown types degrade to the
 * raw code rather than being hidden — an event we cannot label is still an event
 * the reader must see.
 */
const LABELS: Record<string, string> = {
  AUTH_LOGIN_SUCCESS: 'Signed in',
  AUTH_LOGIN_FAILED: 'Failed sign-in',
  AUTH_LOGIN_LOCKED: 'Account locked',
  AUTH_LOGOUT: 'Signed out',
  SESSION_CREATED: 'Session started',
  SESSION_UPDATED: 'Session resumed from idle',
  SESSION_REVOKED: 'Session revoked',
  SESSION_EXPIRED: 'Session expired',
  SESSION_TIMEOUT: 'Session timed out',
  SESSION_SUSPICIOUS: 'Session flagged suspicious',
  SESSION_LIMIT_EXCEEDED: 'Oldest session signed out (device limit)',
  DEVICE_REGISTERED: 'New device',
  DEVICE_TRUSTED: 'Device trusted',
  DEVICE_BLOCKED: 'Device blocked',
  TOKEN_ROTATED: 'Token rotated',
  TOKEN_REFRESHED: 'Token refreshed',
  TOKEN_REUSE_DETECTED: 'Refresh-token reuse detected',
  REFRESH_TOKEN_REUSED: 'Refresh-token reuse detected',
  SUSPICIOUS_LOGIN: 'Unusual sign-in',
  MFA_CHALLENGE_ISSUED: 'MFA challenge issued',
  MFA_SUCCEEDED: 'MFA passed',
  MFA_FAILED: 'MFA failed',
  IDENTITY_LIFECYCLE_CHANGED: 'Account status changed',
}

/** Events that mean something went wrong, or someone is under attack. */
const CRITICAL = new Set([
  'TOKEN_REUSE_DETECTED',
  'REFRESH_TOKEN_REUSED',
  'SESSION_SUSPICIOUS',
  'DEVICE_BLOCKED',
  'AUTH_LOGIN_LOCKED',
  'MFA_FAILED',
])

const WARNING = new Set([
  'AUTH_LOGIN_FAILED',
  'SUSPICIOUS_LOGIN',
  'SESSION_REVOKED',
  'SESSION_LIMIT_EXCEEDED',
  'DEVICE_REGISTERED',
])

export function eventLabel(eventType: string): string {
  return LABELS[eventType] ?? eventType
}

export function eventSeverity(eventType: string): 'critical' | 'warning' | 'info' {
  if (CRITICAL.has(eventType)) return 'critical'
  if (WARNING.has(eventType)) return 'warning'
  return 'info'
}

export function eventVariant(eventType: string): 'destructive' | 'warning' | 'outline' {
  const severity = eventSeverity(eventType)
  if (severity === 'critical') return 'destructive'
  if (severity === 'warning') return 'warning'
  return 'outline'
}

/**
 * One-line "why" drawn from the forensic payload. This is the whole point of the
 * audit stream: an event without its reason and its actor answers nothing.
 */
export function eventDetail(event: SecurityEvent): string | null {
  const meta = event.meta ?? {}
  const parts: string[] = []

  const reason = meta.reason
  if (typeof reason === 'string') parts.push(reason.replace(/_/g, ' ').toLowerCase())

  const actorEmail = meta.actor_email
  if (typeof actorEmail === 'string') parts.push(`by ${actorEmail}`)

  const band = meta.band
  if (typeof band === 'string') parts.push(`risk: ${band.replace('_', ' ').toLowerCase()}`)

  const deviceName = meta.device_name
  if (typeof deviceName === 'string') parts.push(deviceName)

  const signals = meta.signals
  if (Array.isArray(signals) && signals.length) parts.push(signals.join(', '))

  if (event.ip_address) parts.push(event.ip_address)

  return parts.length ? parts.join(' · ') : null
}
