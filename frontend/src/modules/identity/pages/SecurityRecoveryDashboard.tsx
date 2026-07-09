import { useQuery } from '@tanstack/react-query'
import { Loader2, ShieldQuestion } from 'lucide-react'

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { adminRecoveryService } from '@/services'
import type { RecoveryEvent } from '@/types'

const LABEL: Record<string, string> = {
  PASSWORD_RESET_REQUESTED: 'Reset requested',
  PASSWORD_RESET_COMPLETED: 'Reset completed',
  PASSWORD_RESET_FAILED: 'Reset failed',
  EMAIL_CHANGE_REQUESTED: 'Email change requested',
  EMAIL_CHANGED: 'Email changed',
  EMAIL_CHANGE_VERIFIED: 'Email change confirmed',
  RECOVERY_REQUEST_EXPIRED: 'Request expired',
  RECOVERY_REQUEST_REVOKED: 'Request superseded',
  EMAIL_VERIFICATION_SENT: 'Verification sent',
  EMAIL_VERIFIED: 'Email verified',
}

const TONE: Record<string, string> = {
  PASSWORD_RESET_FAILED: 'text-destructive',
  PASSWORD_RESET_COMPLETED: 'text-success',
  EMAIL_CHANGE_VERIFIED: 'text-success',
  EMAIL_VERIFIED: 'text-success',
}

function targetOf(event: RecoveryEvent): string {
  const meta = event.metadata ?? {}
  return (meta.target_email as string) || (meta.reason as string) || '—'
}

/**
 * Security → Recovery events (SRS §18). A read-only stream of every recovery action
 * in the organization — reset requests, completions, failures, email changes and
 * expiries — for a security administrator to audit. Sourced from the single
 * security-event stream; requires `recovery.view`.
 */
export function SecurityRecoveryDashboard() {
  const events = useQuery({
    queryKey: ['recovery-events'],
    queryFn: () => adminRecoveryService.events(),
  })

  return (
    <div className="mx-auto max-w-3xl space-y-4 p-4 sm:p-6">
      <div>
        <h1 className="text-xl font-semibold text-foreground">Recovery events</h1>
        <p className="text-sm text-muted-foreground">
          Password resets, email changes and verification activity across your organization.
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <ShieldQuestion className="h-5 w-5 text-primary" aria-hidden="true" />
            Recent activity
          </CardTitle>
        </CardHeader>
        <CardContent>
          {events.isLoading ? (
            <div className="flex justify-center p-6" role="status" aria-label="Loading">
              <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" aria-hidden="true" />
            </div>
          ) : events.isError ? (
            <p className="text-sm text-destructive" role="alert">
              Could not load recovery events.
            </p>
          ) : (events.data ?? []).length === 0 ? (
            <p className="text-sm text-muted-foreground">No recovery activity yet.</p>
          ) : (
            <ul className="divide-y divide-border" data-testid="recovery-events">
              {(events.data ?? []).map((event) => (
                <li key={event.id} className="flex items-center justify-between gap-3 py-2">
                  <div className="min-w-0">
                    <p className={`text-sm font-medium ${TONE[event.event_type] ?? 'text-foreground'}`}>
                      {LABEL[event.event_type] ?? event.event_type}
                    </p>
                    <p className="truncate text-xs text-muted-foreground">{targetOf(event)}</p>
                  </div>
                  <time className="whitespace-nowrap text-xs text-muted-foreground">
                    {new Date(event.created_at).toLocaleString()}
                  </time>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
