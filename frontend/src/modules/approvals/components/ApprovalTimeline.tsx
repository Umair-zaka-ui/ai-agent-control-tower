import {
  CheckCircle2,
  Clock,
  FileText,
  MessageSquare,
  ShieldAlert,
  UserPlus,
  XCircle,
} from 'lucide-react'
import type { LucideIcon } from 'lucide-react'

import { EmptyState } from '@/components/common/EmptyState'
import { formatDateTime } from '@/utils/format'
import type { ApprovalTimelineEvent } from '../types'

const EVENTS: Record<string, { label: string; icon: LucideIcon }> = {
  APPROVAL_REQUESTED: { label: 'Approval requested', icon: FileText },
  APPROVAL_ASSIGNED: { label: 'Reviewer assigned', icon: UserPlus },
  APPROVAL_COMMENTED: { label: 'Comment added', icon: MessageSquare },
  APPROVAL_ESCALATED: { label: 'Escalated', icon: ShieldAlert },
  APPROVAL_APPROVED: { label: 'Approved', icon: CheckCircle2 },
  APPROVAL_REJECTED: { label: 'Rejected', icon: XCircle },
}

/** Vertical audit timeline of review actions (SRS §Audit Timeline). */
export function ApprovalTimeline({ events }: { events: ApprovalTimelineEvent[] }) {
  if (events.length === 0) {
    return (
      <EmptyState
        icon={Clock}
        title="No review activity yet"
        description="Lifecycle events for this approval will appear here."
      />
    )
  }

  return (
    <ol className="space-y-4">
      {events.map((event) => {
        const meta = EVENTS[event.event_type] ?? { label: event.event_type, icon: Clock }
        const Icon = meta.icon
        const detail = describe(event)
        return (
          <li key={event.id} className="flex gap-3">
            <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-muted text-muted-foreground">
              <Icon className="h-4 w-4" aria-hidden />
            </span>
            <div className="flex-1 space-y-0.5 border-b border-border pb-3">
              <p className="text-sm font-medium text-foreground">{meta.label}</p>
              <p className="text-xs text-muted-foreground">
                {formatDateTime(event.created_at)}
                {event.actor_name ? ` · ${event.actor_name}` : ''}
              </p>
              {detail ? <p className="text-xs text-muted-foreground">{detail}</p> : null}
            </div>
          </li>
        )
      })}
    </ol>
  )
}

function describe(event: ApprovalTimelineEvent): string | null {
  const meta = event.metadata ?? {}
  if (event.event_type === 'APPROVAL_ESCALATED' && typeof meta.target === 'string') {
    const reason = typeof meta.reason === 'string' ? ` — ${meta.reason}` : ''
    return `To ${String(meta.target).replace(/_/g, ' ').toLowerCase()}${reason}`
  }
  if (typeof meta.review_comment === 'string' && meta.review_comment) {
    return meta.review_comment
  }
  return null
}
