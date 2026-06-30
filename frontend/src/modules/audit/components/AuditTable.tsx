import { Link } from 'react-router-dom'
import { Bot, Cog, Eye, User as UserIcon } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { ROUTES } from '@/constants/routes'
import { formatDateTime } from '@/utils/format'
import type { AuditActorType, AuditEventListItem } from '../types'
import { humanizeToken } from '../utils/format'
import { EventSeverityBadge } from './EventSeverityBadge'
import { EventStatusBadge } from './EventStatusBadge'
import { EventTypeBadge } from './EventTypeBadge'

const ACTOR_ICON: Record<AuditActorType, LucideIcon> = {
  USER: UserIcon,
  AGENT: Bot,
  SYSTEM: Cog,
}

/** The enriched audit event table (SRS §Audit Table). */
export function AuditTable({ events }: { events: AuditEventListItem[] }) {
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Timestamp</TableHead>
          <TableHead>Event ID</TableHead>
          <TableHead>Actor</TableHead>
          <TableHead>Event Type</TableHead>
          <TableHead>Resource</TableHead>
          <TableHead>Decision</TableHead>
          <TableHead>Severity</TableHead>
          <TableHead>Status</TableHead>
          <TableHead className="text-right">Actions</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {events.map((event) => {
          const ActorIcon = ACTOR_ICON[event.actor_type] ?? Cog
          return (
            <TableRow key={event.id}>
              <TableCell className="whitespace-nowrap text-muted-foreground">
                {formatDateTime(event.created_at)}
              </TableCell>
              <TableCell className="font-mono text-xs">
                <Link to={`${ROUTES.AUDIT}/${event.id}`} className="hover:text-primary hover:underline">
                  {String(event.id).slice(0, 8)}
                </Link>
              </TableCell>
              <TableCell>
                <span className="inline-flex items-center gap-2">
                  <ActorIcon className="h-4 w-4 text-muted-foreground" aria-hidden />
                  <span className="font-medium">{event.actor_name ?? humanizeToken(event.actor_type)}</span>
                </span>
              </TableCell>
              <TableCell>
                <EventTypeBadge eventType={event.event_type} category={event.category} />
              </TableCell>
              <TableCell className="text-muted-foreground">{event.resource ?? '—'}</TableCell>
              <TableCell className="text-muted-foreground">
                {event.decision ? humanizeToken(event.decision) : '—'}
              </TableCell>
              <TableCell>
                <EventSeverityBadge severity={event.severity} />
              </TableCell>
              <TableCell>
                <EventStatusBadge status={event.status} />
              </TableCell>
              <TableCell className="text-right">
                <Button variant="ghost" size="icon" asChild aria-label={`View event ${event.id}`}>
                  <Link to={`${ROUTES.AUDIT}/${event.id}`}>
                    <Eye className="h-4 w-4" />
                  </Link>
                </Button>
              </TableCell>
            </TableRow>
          )
        })}
      </TableBody>
    </Table>
  )
}
