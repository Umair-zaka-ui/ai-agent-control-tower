import type { AuditEventListItem, AuditSeverity } from '../types'

/** Title-case a SCREAMING_SNAKE token, e.g. AUTH_LOGIN → Auth Login. */
export function humanizeToken(value: string | null | undefined): string {
  if (!value) return '—'
  return value
    .toLowerCase()
    .split('_')
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(' ')
}

/** Coarse ordering used when client-side sorting/comparing severities. */
export const SEVERITY_ORDER: Record<AuditSeverity, number> = {
  INFO: 0,
  LOW: 1,
  MEDIUM: 2,
  HIGH: 3,
  CRITICAL: 4,
}

/** Short clock label (HH:MM) for the timeline rail. */
export function clockTime(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '—'
  return new Intl.DateTimeFormat('en-US', {
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).format(date)
}

/** Stable searchable text for a row (used by tests / client-side fallbacks). */
export function auditSearchText(item: AuditEventListItem): string {
  return [item.id, item.event_type, item.actor_name, item.resource, item.action]
    .filter(Boolean)
    .join(' ')
    .toLowerCase()
}
