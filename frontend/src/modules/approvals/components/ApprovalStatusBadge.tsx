import { Badge, type BadgeProps } from '@/components/ui/badge'
import type { ApprovalStatus } from '../types'

const STATUS: Record<ApprovalStatus, { label: string; variant: BadgeProps['variant'] }> = {
  PENDING: { label: 'Pending', variant: 'warning' },
  APPROVED: { label: 'Approved', variant: 'success' },
  REJECTED: { label: 'Rejected', variant: 'destructive' },
  // Purple for escalated — uses an explicit class since the palette has no
  // dedicated "purple" variant.
  ESCALATED: { label: 'Escalated', variant: 'outline' },
  EXPIRED: { label: 'Expired', variant: 'secondary' },
}

export function ApprovalStatusBadge({ status }: { status: ApprovalStatus }) {
  const meta = STATUS[status] ?? { label: status ?? 'Unknown', variant: 'secondary' as const }
  if (status === 'ESCALATED') {
    return (
      <Badge
        variant="outline"
        className="border-transparent bg-purple-500/15 text-purple-600 dark:text-purple-400"
      >
        {meta.label}
      </Badge>
    )
  }
  return <Badge variant={meta.variant}>{meta.label}</Badge>
}
