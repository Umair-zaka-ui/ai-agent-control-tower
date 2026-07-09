import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { AlertTriangle, Loader2 } from 'lucide-react'

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { protectionService } from '@/services'

const LEVELS = ['ALL', 'HIGH', 'CRITICAL', 'SEVERE'] as const

const LEVEL_TONE: Record<string, string> = {
  LOW: 'text-muted-foreground',
  MEDIUM: 'text-muted-foreground',
  HIGH: 'text-warning',
  CRITICAL: 'text-destructive',
  SEVERE: 'text-destructive',
}

function signalList(signals: Record<string, unknown>): string {
  return Object.entries(signals)
    .filter(([, v]) => v === true)
    .map(([k]) => k.replace(/_/g, ' '))
    .join(', ')
}

/**
 * Risk events (SRS §26). Scored authentication attempts with the signals that drove
 * the score and the decision taken.
 */
export function RiskEventsPage() {
  const [level, setLevel] = useState<string>('ALL')
  const events = useQuery({
    queryKey: ['risk-events', level],
    queryFn: () => protectionService.riskEvents(level === 'ALL' ? undefined : level),
  })

  return (
    <div className="mx-auto max-w-4xl space-y-4 p-4 sm:p-6">
      <div>
        <h1 className="text-xl font-semibold text-foreground">Risk events</h1>
        <p className="text-sm text-muted-foreground">Scored sign-in attempts and their signals.</p>
      </div>

      <div className="flex gap-2" role="tablist" aria-label="Filter by risk level">
        {LEVELS.map((l) => (
          <button
            key={l}
            role="tab"
            aria-selected={level === l}
            onClick={() => setLevel(l)}
            className={`rounded-md px-3 py-1 text-sm capitalize ${
              level === l ? 'bg-primary text-primary-foreground' : 'bg-muted text-muted-foreground'
            }`}
          >
            {l.toLowerCase()}
          </button>
        ))}
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <AlertTriangle className="h-5 w-5 text-warning" aria-hidden="true" />
            Events
          </CardTitle>
        </CardHeader>
        <CardContent>
          {events.isLoading ? (
            <div className="flex justify-center p-4" role="status" aria-label="Loading">
              <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" aria-hidden="true" />
            </div>
          ) : (events.data ?? []).length === 0 ? (
            <p className="text-sm text-muted-foreground">No risk events.</p>
          ) : (
            <ul className="divide-y divide-border" data-testid="risk-events">
              {(events.data ?? []).map((e) => (
                <li key={e.id} className="flex items-center justify-between gap-3 py-2">
                  <div className="min-w-0">
                    <p className="text-sm font-medium text-foreground">
                      <span className={LEVEL_TONE[e.risk_level] ?? ''}>{e.risk_level}</span>
                      <span className="ml-2 text-muted-foreground">· {e.decision}</span>
                    </p>
                    <p className="truncate text-xs text-muted-foreground">
                      {e.ip_address ?? '—'} · {signalList(e.signals) || 'no anomalies'}
                    </p>
                  </div>
                  <div className="shrink-0 text-right">
                    <p className={`text-sm font-semibold ${LEVEL_TONE[e.risk_level] ?? ''}`}>
                      {e.risk_score}
                    </p>
                    <p className="text-xs text-muted-foreground">
                      {new Date(e.created_at).toLocaleTimeString()}
                    </p>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
