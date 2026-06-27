import {
  FilePlus2,
  FlaskConical,
  Pencil,
  Power,
  PowerOff,
  ScrollText,
  Trash2,
} from 'lucide-react'
import type { LucideIcon } from 'lucide-react'

import { EmptyState } from '@/components/common/EmptyState'
import type { AuditLog } from '@/types'
import { formatDateTime } from '@/utils/format'

const EVENTS: Record<string, { label: string; icon: LucideIcon }> = {
  POLICY_CREATED: { label: 'Policy created', icon: FilePlus2 },
  POLICY_UPDATED: { label: 'Policy updated', icon: Pencil },
  POLICY_ENABLED: { label: 'Policy enabled', icon: Power },
  POLICY_DISABLED: { label: 'Policy disabled', icon: PowerOff },
  POLICY_TESTED: { label: 'Policy tested', icon: FlaskConical },
  POLICY_DELETED: { label: 'Policy deleted', icon: Trash2 },
}

/** Vertical timeline of policy audit events (SRS §Audit Tab). */
export function PolicyAuditTimeline({ events }: { events: AuditLog[] }) {
  if (events.length === 0) {
    return (
      <EmptyState
        icon={ScrollText}
        title="No audit events yet"
        description="Lifecycle changes to this policy will appear here."
      />
    )
  }

  return (
    <ol className="space-y-4">
      {events.map((event) => {
        const meta = EVENTS[event.event_type] ?? { label: event.event_type, icon: ScrollText }
        const Icon = meta.icon
        return (
          <li key={event.id} className="flex gap-3">
            <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-muted text-muted-foreground">
              <Icon className="h-4 w-4" />
            </span>
            <div className="flex-1 space-y-0.5 border-b border-border pb-3">
              <p className="text-sm font-medium text-foreground">{meta.label}</p>
              <p className="text-xs text-muted-foreground">{formatDateTime(event.created_at)}</p>
              {Object.keys(event.metadata ?? {}).length > 0 && (
                <p className="text-xs text-muted-foreground">
                  {Object.entries(event.metadata)
                    .map(([k, v]) => `${k.replace(/_/g, ' ')}: ${Array.isArray(v) ? v.join(', ') : String(v)}`)
                    .join(' · ')}
                </p>
              )}
            </div>
          </li>
        )
      })}
    </ol>
  )
}
