import { Activity } from 'lucide-react'

import { EmptyState } from '@/components/common/EmptyState'
import { Badge, type BadgeProps } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import type { AgentAction } from '@/types'
import { formatRelativeTime } from '@/utils/format'
import { humanizeToken } from '../utils/format'

const DECISION_VARIANT: Record<string, BadgeProps['variant']> = {
  ALLOW: 'success',
  BLOCK: 'destructive',
  PENDING_APPROVAL: 'warning',
}

const DECISION_LABEL: Record<string, string> = {
  ALLOW: 'Executed',
  BLOCK: 'Blocked',
  PENDING_APPROVAL: 'Approval requested',
}

/** Live agent activity feed (SRS §Real-Time Operations). Refreshes every 10s. */
export function ActivityFeed({ actions, loading }: { actions?: AgentAction[]; loading?: boolean }) {
  if (loading || !actions) {
    return (
      <div className="space-y-2">
        {Array.from({ length: 6 }).map((_, i) => (
          <Skeleton key={i} className="h-12 w-full" />
        ))}
      </div>
    )
  }
  if (actions.length === 0) {
    return (
      <EmptyState
        icon={Activity}
        title="No recent activity"
        description="Live agent activity will stream here as agents act."
      />
    )
  }
  return (
    <ul className="space-y-1">
      {actions.map((a) => (
        <li
          key={a.id}
          className="flex items-center justify-between gap-3 rounded-md px-2 py-2 transition-colors hover:bg-muted/40"
        >
          <div className="flex min-w-0 items-center gap-3">
            <span className="w-12 shrink-0 text-right font-mono text-xs text-muted-foreground">
              {formatRelativeTime(a.created_at)}
            </span>
            <span className="truncate text-sm">
              <span className="font-medium">{humanizeToken(a.action)}</span>
              <span className="text-muted-foreground"> · {a.resource}</span>
            </span>
          </div>
          <Badge variant={DECISION_VARIANT[a.decision] ?? 'secondary'}>
            {DECISION_LABEL[a.decision] ?? a.decision}
          </Badge>
        </li>
      ))}
    </ul>
  )
}
