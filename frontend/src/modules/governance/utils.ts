import type { BadgeProps } from '@/components/ui/badge'

/** Shared severity/status → badge-variant maps for the governance pages. */
export const SEVERITY_VARIANT: Record<string, BadgeProps['variant']> = {
  LOW: 'secondary',
  MEDIUM: 'warning',
  HIGH: 'destructive',
  CRITICAL: 'destructive',
}

export const FINDING_STATUS_VARIANT: Record<string, BadgeProps['variant']> = {
  OPEN: 'destructive',
  ACKNOWLEDGED: 'warning',
  REMEDIATED: 'success',
  DISMISSED: 'secondary',
}

export const RULE_STATUS_VARIANT: Record<string, BadgeProps['variant']> = {
  DRAFT: 'secondary',
  ACTIVE: 'success',
  DISABLED: 'secondary',
}

export const REMEDIATION_STATUS_VARIANT: Record<string, BadgeProps['variant']> = {
  PENDING: 'warning',
  APPROVED: 'default',
  EXECUTED: 'success',
  FAILED: 'destructive',
  CANCELLED: 'secondary',
}

export const CAMPAIGN_STATUS_VARIANT: Record<string, BadgeProps['variant']> = {
  DRAFT: 'secondary',
  SCHEDULED: 'default',
  ACTIVE: 'warning',
  COMPLETED: 'success',
  ARCHIVED: 'secondary',
}

export const RISK_BAND_VARIANT: Record<string, BadgeProps['variant']> = {
  LOW: 'secondary',
  MEDIUM: 'warning',
  HIGH: 'destructive',
  CRITICAL: 'destructive',
}

export function formatDate(value: string | null | undefined): string {
  if (!value) return '—'
  return new Date(value).toLocaleString()
}

export function labelForFindingType(t: string): string {
  return t.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
}
