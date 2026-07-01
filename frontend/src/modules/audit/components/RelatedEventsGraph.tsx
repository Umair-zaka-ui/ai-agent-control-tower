import { ArrowDown, GitBranch } from 'lucide-react'
import { Link } from 'react-router-dom'

import { EmptyState } from '@/components/common/EmptyState'
import { ROUTES } from '@/constants/routes'
import type { ID } from '@/types'
import { formatDateTime } from '@/utils/format'
import { cn } from '@/utils/cn'
import type { AuditRelatedEvent } from '../types'
import { humanizeToken } from '../utils/format'
import { EventSeverityBadge } from './EventSeverityBadge'

interface RelatedEventsGraphProps {
  events: AuditRelatedEvent[]
  /** The currently-viewed event, highlighted in the flow. */
  currentId: ID
}

/**
 * Vertical flow of events sharing this event's correlation id — the logical
 * request → policy → approval → execution chain (SRS §Related Events graph).
 */
export function RelatedEventsGraph({ events, currentId }: RelatedEventsGraphProps) {
  if (events.length === 0) {
    return (
      <EmptyState
        icon={GitBranch}
        title="No related events"
        description="This event has no other events sharing its correlation id."
      />
    )
  }

  return (
    <ol className="space-y-0">
      {events.map((event, index) => {
        const isCurrent = String(event.id) === String(currentId)
        return (
          <li key={event.id}>
            <Link
              to={`${ROUTES.AUDIT}/${event.id}`}
              aria-current={isCurrent ? 'true' : undefined}
              className={cn(
                'flex items-center justify-between gap-3 rounded-md border px-3 py-2 transition-colors',
                isCurrent
                  ? 'border-primary bg-primary/5'
                  : 'border-border hover:bg-muted/50',
              )}
            >
              <div className="min-w-0">
                <p className="truncate text-sm font-medium">{humanizeToken(event.event_type)}</p>
                <p className="text-xs text-muted-foreground">
                  {formatDateTime(event.created_at)}
                  {event.actor_name ? ` · ${event.actor_name}` : ''}
                </p>
              </div>
              <EventSeverityBadge severity={event.severity} />
            </Link>
            {index < events.length - 1 && (
              <div className="flex justify-center py-1 text-muted-foreground" aria-hidden>
                <ArrowDown className="h-4 w-4" />
              </div>
            )}
          </li>
        )
      })}
    </ol>
  )
}
