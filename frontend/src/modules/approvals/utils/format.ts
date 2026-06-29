import type { ISODateString } from '@/types'
import type { ApprovalListItem } from '../types'

/** Human-readable review duration from seconds, e.g. "2h 5m" or "—". */
export function formatDuration(seconds: number | null | undefined): string {
  if (seconds == null || Number.isNaN(seconds)) return '—'
  if (seconds < 60) return `${Math.round(seconds)}s`
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `${minutes}m`
  const hours = Math.floor(minutes / 60)
  const remMinutes = minutes % 60
  if (hours < 24) return remMinutes ? `${hours}h ${remMinutes}m` : `${hours}h`
  const days = Math.floor(hours / 24)
  const remHours = hours % 24
  return remHours ? `${days}d ${remHours}h` : `${days}d`
}

export interface SlaState {
  label: string
  /** True when the deadline has already passed. */
  overdue: boolean
  /** True when under two hours remain. */
  urgent: boolean
}

/** Compute an SLA countdown relative to now from an ISO deadline. */
export function slaCountdown(due: ISODateString | null | undefined): SlaState | null {
  if (!due) return null
  const target = new Date(due).getTime()
  if (Number.isNaN(target)) return null
  const diffSeconds = Math.round((target - Date.now()) / 1000)
  if (diffSeconds <= 0) {
    return { label: `Overdue by ${formatDuration(-diffSeconds)}`, overdue: true, urgent: true }
  }
  return {
    label: `${formatDuration(diffSeconds)} left`,
    overdue: false,
    urgent: diffSeconds < 2 * 60 * 60,
  }
}

/** Map a 0–100 risk score to a coarse level label. */
export function riskLevel(score: number): 'Low' | 'Moderate' | 'High' | 'Critical' {
  if (score >= 81) return 'Critical'
  if (score >= 61) return 'High'
  if (score >= 31) return 'Moderate'
  return 'Low'
}

/** Title-case a SCREAMING_SNAKE token for display, e.g. SUBMIT_CLAIM → Submit Claim. */
export function humanizeToken(value: string | null | undefined): string {
  if (!value) return '—'
  return value
    .toLowerCase()
    .split('_')
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(' ')
}

/** Stable searchable text for a queue row (used by client-side fallbacks). */
export function approvalSearchText(item: ApprovalListItem): string {
  return [item.id, item.agent_name, item.resource, item.action, item.reviewer_name]
    .filter(Boolean)
    .join(' ')
    .toLowerCase()
}
