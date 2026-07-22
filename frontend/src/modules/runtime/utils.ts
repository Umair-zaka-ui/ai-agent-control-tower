import type { BadgeProps } from '@/components/ui/badge'
import { formatDateTime } from '@/utils/format'

/** Shared status → badge-variant maps for the runtime pages. */
export const AGENT_LIFECYCLE_VARIANT: Record<string, BadgeProps['variant']> = {
  DRAFT: 'secondary',
  REGISTERED: 'default',
  VALIDATING: 'default',
  VALIDATION_FAILED: 'destructive',
  VALIDATED: 'default',
  PENDING_APPROVAL: 'warning',
  REJECTED: 'destructive',
  APPROVED: 'default',
  ACTIVE: 'success',
  SUSPENDED: 'warning',
  DEPRECATED: 'secondary',
  ARCHIVED: 'secondary',
  RETIRED: 'secondary',
}

export const VERSION_STATUS_VARIANT: Record<string, BadgeProps['variant']> = {
  DRAFT: 'secondary',
  VALIDATING: 'default',
  READY_FOR_REVIEW: 'default',
  APPROVED: 'default',
  PUBLISHED: 'success',
  DEPRECATED: 'secondary',
  REVOKED: 'destructive',
}

export const DEPLOYMENT_STATUS_VARIANT: Record<string, BadgeProps['variant']> = {
  CREATED: 'secondary',
  PENDING_APPROVAL: 'warning',
  SCHEDULED: 'default',
  DEPLOYING: 'default',
  HEALTH_CHECKING: 'default',
  ACTIVE: 'success',
  DEGRADED: 'warning',
  FAILED: 'destructive',
  SUSPENDED: 'warning',
  ROLLING_BACK: 'default',
  RETIRED: 'secondary',
}

export const EXECUTION_STATUS_VARIANT: Record<string, BadgeProps['variant']> = {
  CREATED: 'secondary',
  AUTHORIZING: 'default',
  DENIED: 'destructive',
  PENDING_APPROVAL: 'warning',
  REJECTED: 'destructive',
  QUEUED: 'default',
  SCHEDULED: 'default',
  RUNNING: 'default',
  BLOCKED: 'warning',
  SUCCEEDED: 'success',
  FAILED: 'destructive',
  TIMED_OUT: 'destructive',
  CANCELLED: 'secondary',
  DEAD_LETTERED: 'destructive',
}

export const CRITICALITY_VARIANT: Record<string, BadgeProps['variant']> = {
  LOW: 'secondary',
  MEDIUM: 'default',
  HIGH: 'warning',
  MISSION_CRITICAL: 'destructive',
}

export const formatDate = formatDateTime

export function formatCost(value: number | null | undefined): string {
  if (value === null || value === undefined) return '—'
  return `$${value.toFixed(4)}`
}

export function formatMs(value: number | null | undefined): string {
  if (value === null || value === undefined) return '—'
  return value < 1000 ? `${value}ms` : `${(value / 1000).toFixed(2)}s`
}
