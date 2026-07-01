import { Badge, type BadgeProps } from '@/components/ui/badge'

/** Derived human status → badge variant (mirrors audit_view._status_of). */
const STATUS_VARIANT: Record<string, BadgeProps['variant']> = {
  Allowed: 'success',
  Approved: 'success',
  Blocked: 'destructive',
  Rejected: 'destructive',
  Failed: 'destructive',
  Alert: 'destructive',
  Pending: 'warning',
  Escalated: 'warning',
  Revoked: 'secondary',
  Deleted: 'secondary',
  Recorded: 'outline',
}

export function EventStatusBadge({ status }: { status: string }) {
  const variant = STATUS_VARIANT[status] ?? 'outline'
  return <Badge variant={variant}>{status}</Badge>
}
