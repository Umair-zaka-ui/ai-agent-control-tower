import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Loader2, ScrollText } from 'lucide-react'

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { protectionService } from '@/services'

type Filter = 'all' | 'success' | 'failed'

const RISK_TONE = (score: number | null): string => {
  if (score === null) return 'text-muted-foreground'
  if (score >= 76) return 'text-destructive'
  if (score >= 51) return 'text-warning'
  return 'text-muted-foreground'
}

/**
 * Login attempts (SRS §25). Every authentication attempt — success or failure — with
 * its IP, decision and risk score, filterable by outcome.
 */
export function LoginAttemptsPage() {
  const [filter, setFilter] = useState<Filter>('all')
  const success = filter === 'all' ? undefined : filter === 'success'

  const attempts = useQuery({
    queryKey: ['login-attempts', filter],
    queryFn: () => protectionService.loginAttempts(success),
  })

  return (
    <div className="mx-auto max-w-4xl space-y-4 p-4 sm:p-6">
      <div>
        <h1 className="text-xl font-semibold text-foreground">Login attempts</h1>
        <p className="text-sm text-muted-foreground">Every sign-in attempt in your organization.</p>
      </div>

      <div className="flex gap-2" role="tablist" aria-label="Filter attempts">
        {(['all', 'success', 'failed'] as Filter[]).map((f) => (
          <button
            key={f}
            role="tab"
            aria-selected={filter === f}
            onClick={() => setFilter(f)}
            className={`rounded-md px-3 py-1 text-sm capitalize ${
              filter === f ? 'bg-primary text-primary-foreground' : 'bg-muted text-muted-foreground'
            }`}
          >
            {f}
          </button>
        ))}
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <ScrollText className="h-5 w-5 text-primary" aria-hidden="true" />
            Attempts
          </CardTitle>
        </CardHeader>
        <CardContent className="overflow-x-auto">
          {attempts.isLoading ? (
            <div className="flex justify-center p-4" role="status" aria-label="Loading">
              <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" aria-hidden="true" />
            </div>
          ) : (attempts.data ?? []).length === 0 ? (
            <p className="text-sm text-muted-foreground">No attempts recorded.</p>
          ) : (
            <table className="w-full min-w-[640px] text-sm" data-testid="login-attempts">
              <thead>
                <tr className="border-b border-border text-left text-xs text-muted-foreground">
                  <th className="py-2 pr-3 font-medium">Time</th>
                  <th className="py-2 pr-3 font-medium">Email</th>
                  <th className="py-2 pr-3 font-medium">Result</th>
                  <th className="py-2 pr-3 font-medium">IP</th>
                  <th className="py-2 pr-3 font-medium">Risk</th>
                  <th className="py-2 font-medium">Decision</th>
                </tr>
              </thead>
              <tbody>
                {(attempts.data ?? []).map((a) => (
                  <tr key={a.id} className="border-b border-border/50">
                    <td className="whitespace-nowrap py-2 pr-3 text-xs text-muted-foreground">
                      {new Date(a.created_at).toLocaleString()}
                    </td>
                    <td className="max-w-[180px] truncate py-2 pr-3">{a.email}</td>
                    <td className="py-2 pr-3">
                      <span className={a.success ? 'text-success' : 'text-destructive'}>
                        {a.success ? 'Success' : (a.failure_reason ?? 'Failed')}
                      </span>
                    </td>
                    <td className="py-2 pr-3 text-muted-foreground">{a.ip_address ?? '—'}</td>
                    <td className={`py-2 pr-3 font-medium ${RISK_TONE(a.risk_score)}`}>
                      {a.risk_score ?? '—'}
                    </td>
                    <td className="py-2 text-muted-foreground">{a.decision ?? '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
