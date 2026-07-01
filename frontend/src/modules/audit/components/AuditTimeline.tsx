import { Clock } from 'lucide-react'
import { Link } from 'react-router-dom'

import { EmptyState } from '@/components/common/EmptyState'
import { ROUTES } from '@/constants/routes'
import { formatDate } from '@/utils/format'
import type { AuditTimelineItem } from '../types'
import { clockTime } from '../utils/format'
import { EventSeverityBadge } from './EventSeverityBadge'

interface AuditTimelineProps {
  items: AuditTimelineItem[]
  loading?: boolean
}

/** Vertical activity rail of the most recent events (SRS §Event Timeline). */
export function AuditTimeline({ items, loading }: AuditTimelineProps) {
  if (loading) {
    return (
      <ol className="space-y-4" aria-busy>
        {Array.from({ length: 5 }).map((_, i) => (
          <li key={i} className="flex gap-3">
            <div className="h-8 w-12 shrink-0 animate-pulse rounded bg-muted" />
            <div className="h-8 flex-1 animate-pulse rounded bg-muted" />
          </li>
        ))}
      </ol>
    )
  }

  if (items.length === 0) {
    return (
      <EmptyState
        icon={Clock}
        title="No recent activity"
        description="Audit events will appear here as users and AI agents operate."
      />
    )
  }

  return (
    <ol className="relative space-y-1">
      {items.map((item) => (
        <li key={item.id}>
          <Link
            to={`${ROUTES.AUDIT}/${item.id}`}
            className="group flex items-start gap-3 rounded-md px-2 py-2 transition-colors hover:bg-muted/50"
          >
            <span
              className="w-12 shrink-0 pt-0.5 text-right font-mono text-xs text-muted-foreground"
              title={formatDate(item.created_at)}
            >
              {clockTime(item.created_at)}
            </span>
            <span className="mt-1.5 h-2 w-2 shrink-0 rounded-full bg-primary/60 group-hover:bg-primary" aria-hidden />
            <span className="flex-1 text-sm text-foreground">{item.label}</span>
            <EventSeverityBadge severity={item.severity} />
          </Link>
        </li>
      ))}
    </ol>
  )
}
