import type { AuthDevice, AuthSession, SecurityBand } from '@/types'

/** Map the server's security band to a badge variant (SRS §15). */
export function bandVariant(band: SecurityBand | null): 'success' | 'warning' | 'destructive' {
  switch (band) {
    case 'HIGH_RISK':
      return 'destructive'
    case 'WARNING':
      return 'warning'
    default:
      return 'success'
  }
}

export function bandLabel(band: SecurityBand | null): string {
  switch (band) {
    case 'HIGH_RISK':
      return 'High risk'
    case 'WARNING':
      return 'Warning'
    default:
      return 'Healthy'
  }
}

export function deviceStatusVariant(
  status: AuthDevice['status'],
): 'success' | 'destructive' | 'outline' {
  if (status === 'TRUSTED') return 'success'
  if (status === 'BLOCKED') return 'destructive'
  return 'outline'
}

/** "Chrome on Windows 10/11" → falls back gracefully for unparsed clients. */
export function describeClient(item: AuthSession | AuthDevice): string {
  if (item.device_name) return item.device_name
  const browser = item.browser ?? 'Unknown browser'
  const os = item.operating_system
  return os ? `${browser} on ${os}` : browser
}

export function describeLocation(session: AuthSession): string {
  const parts = [session.city, session.country].filter(Boolean)
  if (parts.length) return `${parts.join(', ')} · ${session.ip_address ?? 'unknown IP'}`
  return session.ip_address ?? 'Unknown location'
}

/** Compact relative time. Avoids a date library for one call site. */
export function timeAgo(iso: string | null): string {
  if (!iso) return 'never'
  const seconds = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000)
  if (seconds < 60) return 'just now'
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours}h ago`
  const days = Math.floor(hours / 24)
  return days === 1 ? 'yesterday' : `${days}d ago`
}

/** How long until this session dies of inactivity (SRS §12). */
export function expiresIn(iso: string): string {
  const seconds = (new Date(iso).getTime() - Date.now()) / 1000
  if (seconds <= 0) return 'expired'
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `${Math.max(1, minutes)}m`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours}h`
  return `${Math.floor(hours / 24)}d`
}
