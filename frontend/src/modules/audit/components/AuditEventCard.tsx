import { Bot, Cog, User as UserIcon } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import { Link } from 'react-router-dom'

import { ROUTES } from '@/constants/routes'
import { formatRelativeTime } from '@/utils/format'
import type { AuditActorType, AuditEventListItem } from '../types'
import { humanizeToken } from '../utils/format'
import { EventSeverityBadge } from './EventSeverityBadge'
import { EventTypeBadge } from './EventTypeBadge'

const ACTOR_ICON: Record<AuditActorType, LucideIcon> = {
  USER: UserIcon,
  AGENT: Bot,
  SYSTEM: Cog,
}

/** Compact event card for the dashboard "Recent Events" list (SRS §AuditEventCard). */
export function AuditEventCard({ event }: { event: AuditEventListItem }) {
  const ActorIcon = ACTOR_ICON[event.actor_type] ?? Cog
  return (
    <Link
      to={`${ROUTES.AUDIT}/${event.id}`}
      className="flex items-center justify-between gap-3 rounded-md border border-border px-3 py-2.5 transition-colors hover:bg-muted/50"
    >
      <div className="flex min-w-0 items-center gap-3">
        <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-muted text-muted-foreground">
          <ActorIcon className="h-4 w-4" aria-hidden />
        </span>
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <EventTypeBadge eventType={event.event_type} category={event.category} />
          </div>
          <p className="mt-0.5 truncate text-xs text-muted-foreground">
            {event.actor_name ?? humanizeToken(event.actor_type)}
            {event.resource ? ` · ${event.resource}` : ''} · {formatRelativeTime(event.created_at)}
          </p>
        </div>
      </div>
      <EventSeverityBadge severity={event.severity} />
    </Link>
  )
}
