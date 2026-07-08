import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import type { SecurityEvent } from '@/types'
import { eventDetail, eventLabel, eventVariant } from '../eventLabels'
import { timeAgo } from '../utils'

interface SecurityEventListProps {
  events: SecurityEvent[]
  loading?: boolean
  error?: boolean
  emptyMessage?: string
  /** Timelines read forwards; streams read newest-first. */
  order?: 'oldest-first' | 'newest-first'
  'data-testid'?: string
}

/**
 * The security-event stream, rendered (SRS §26; DoD §32 "…and audit").
 *
 * Every row shows *what*, *when*, and — critically — *why* and *by whom*, pulled
 * from the event's forensic `meta`. An audit row that says only "session revoked"
 * answers none of the questions an incident review asks.
 */
export function SecurityEventList({
  events,
  loading,
  error,
  emptyMessage = 'No security activity recorded.',
  order = 'newest-first',
  'data-testid': testId,
}: SecurityEventListProps) {
  if (loading) {
    return (
      <div className="space-y-2" data-testid={testId}>
        {[0, 1, 2].map((i) => (
          <Skeleton key={i} className="h-12 w-full rounded-md" />
        ))}
      </div>
    )
  }

  if (error) {
    return <p className="text-sm text-destructive">Could not load security activity.</p>
  }

  if (!events.length) {
    return <p className="text-sm text-muted-foreground">{emptyMessage}</p>
  }

  const rows = order === 'oldest-first' ? events : [...events]

  return (
    <ol className="space-y-2" data-testid={testId}>
      {rows.map((event) => {
        const detail = eventDetail(event)
        return (
          <li
            key={event.id}
            className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-border bg-card px-3 py-2"
          >
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <Badge variant={eventVariant(event.event_type)}>{eventLabel(event.event_type)}</Badge>
                <span className="text-xs text-muted-foreground">{timeAgo(event.created_at)}</span>
              </div>
              {detail && (
                <p className="mt-0.5 truncate text-sm text-muted-foreground" title={detail}>
                  {detail}
                </p>
              )}
            </div>
            <time
              className="shrink-0 text-xs text-muted-foreground"
              dateTime={event.created_at}
              title={new Date(event.created_at).toLocaleString()}
            >
              {new Date(event.created_at).toLocaleString()}
            </time>
          </li>
        )
      })}
    </ol>
  )
}
