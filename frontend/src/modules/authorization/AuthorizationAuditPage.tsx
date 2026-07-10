import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Loader2 } from 'lucide-react'

import { Card, CardContent } from '@/components/ui/card'
import { authorizationService } from '@/services'

const EVENT_TYPES = [
  'ROLE_CREATED',
  'ROLE_UPDATED',
  'ROLE_ARCHIVED',
  'ROLE_DELETED',
  'ROLE_ASSIGNED',
  'ROLE_REMOVED',
  'PERMISSION_CREATED',
  'PERMISSION_ASSIGNED',
  'PERMISSION_REMOVED',
  'ROLE_HIERARCHY_UPDATED',
  'AUTHORIZATION_DECISION',
]

/** Authorization audit trail (Phase 4.3.1 §23) — change events and decisions. */
export function AuthorizationAuditPage() {
  const [eventType, setEventType] = useState('')

  const audit = useQuery({
    queryKey: ['authz-audit', eventType],
    queryFn: () => authorizationService.audit({ eventType: eventType || undefined }),
  })

  return (
    <div className="mx-auto max-w-4xl space-y-4 p-4 sm:p-6">
      <div>
        <h1 className="text-xl font-semibold text-foreground">Authorization audit</h1>
        <p className="text-sm text-muted-foreground">Every role, permission and hierarchy change is recorded.</p>
      </div>

      <select
        value={eventType}
        onChange={(e) => setEventType(e.target.value)}
        className="rounded-md border border-border bg-background px-2 py-1.5 text-sm"
      >
        <option value="">All events</option>
        {EVENT_TYPES.map((t) => (
          <option key={t} value={t}>{t}</option>
        ))}
      </select>

      <Card>
        <CardContent className="p-0">
          {audit.isLoading ? (
            <div className="flex justify-center p-6" role="status" aria-label="Loading">
              <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
            </div>
          ) : (audit.data ?? []).length === 0 ? (
            <p className="p-4 text-sm text-muted-foreground">No audit entries.</p>
          ) : (
            <ul className="divide-y divide-border" data-testid="authz-audit-list">
              {(audit.data ?? []).map((row) => (
                <li key={row.id} className="flex items-start justify-between gap-3 p-3">
                  <div className="min-w-0">
                    <p className="text-sm font-medium text-foreground">
                      {row.event_type}
                      {row.decision ? <span className="ml-2 text-xs text-muted-foreground">{row.decision}</span> : null}
                    </p>
                    <p className="truncate text-xs text-muted-foreground">
                      {row.permission ? `${row.permission} · ` : ''}
                      {row.reason ?? (row.meta ? JSON.stringify(row.meta) : '')}
                    </p>
                  </div>
                  <span className="shrink-0 text-xs text-muted-foreground">
                    {row.created_at ? new Date(row.created_at).toLocaleString() : ''}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
