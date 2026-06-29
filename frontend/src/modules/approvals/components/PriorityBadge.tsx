import { Badge, type BadgeProps } from '@/components/ui/badge'
import type { ApprovalPriority } from '../types'

const PRIORITY: Record<ApprovalPriority, { label: string; variant: BadgeProps['variant'] }> = {
  LOW: { label: 'Low', variant: 'success' },
  MEDIUM: { label: 'Medium', variant: 'warning' },
  HIGH: { label: 'High', variant: 'outline' },
  CRITICAL: { label: 'Critical', variant: 'destructive' },
}

export function PriorityBadge({ priority }: { priority: ApprovalPriority }) {
  const meta = PRIORITY[priority] ?? { label: priority ?? 'Unknown', variant: 'secondary' as const }
  if (priority === 'HIGH') {
    return (
      <Badge
        variant="outline"
        className="border-transparent bg-orange-500/15 text-orange-600 dark:text-orange-400"
      >
        {meta.label}
      </Badge>
    )
  }
  return <Badge variant={meta.variant}>{meta.label}</Badge>
}
