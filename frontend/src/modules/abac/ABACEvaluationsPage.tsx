import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Loader2, ScrollText } from 'lucide-react'

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { abacService } from '@/services'
import type { ABACEvaluationRow, ID } from '@/types'
import { DECISION_STYLES } from './lib'

const DECISIONS = ['', 'ALLOW', 'DENY', 'REQUIRE_APPROVAL', 'REQUIRE_MFA',
  'REQUIRE_JUSTIFICATION', 'MASK_FIELDS', 'LIMIT_ACTION', 'NOT_APPLICABLE']

/** Evaluation viewer (§36): decisions, matched policies, explanations, latency. */
export function ABACEvaluationsPage() {
  const [decision, setDecision] = useState('')
  const [openId, setOpenId] = useState<ID | null>(null)
  const evaluations = useQuery({
    queryKey: ['abac-evaluations', decision],
    queryFn: () => abacService.evaluations(decision || undefined),
  })

  return (
    <div className="mx-auto max-w-5xl space-y-4 p-4 sm:p-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold text-foreground">ABAC evaluations</h1>
          <p className="text-sm text-muted-foreground">
            Every policy decision, with its explanation. Sensitive values are redacted.
          </p>
        </div>
        <select value={decision} aria-label="Filter by decision"
          onChange={(e) => setDecision(e.target.value)}
          className="rounded-md border border-border bg-background px-2 py-1.5 text-sm">
          {DECISIONS.map((d) => <option key={d} value={d}>{d || 'All decisions'}</option>)}
        </select>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base"><ScrollText className="h-4 w-4" /> Decisions</CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          {evaluations.isLoading ? (
            <div className="flex justify-center p-6"><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /></div>
          ) : (evaluations.data ?? []).length === 0 ? (
            <p className="p-4 text-sm text-muted-foreground">No evaluations recorded.</p>
          ) : (
            <ul className="divide-y divide-border" data-testid="evaluations-list">
              {(evaluations.data ?? []).map((row: ABACEvaluationRow) => (
                <li key={row.id} className="p-3">
                  <button type="button" className="flex w-full items-center justify-between gap-3 text-left"
                    onClick={() => setOpenId(openId === row.id ? null : row.id)}>
                    <div className="min-w-0">
                      <p className="truncate text-sm text-foreground">{row.action}</p>
                      <p className="text-xs text-muted-foreground">
                        {row.created_at ? new Date(row.created_at).toLocaleString() : ''}
                        {row.evaluation_time_ms != null ? ` · ${row.evaluation_time_ms.toFixed(1)}ms` : ''}
                        {row.request_id ? ` · ${row.request_id}` : ''}
                      </p>
                    </div>
                    <span className={`rounded px-2 py-0.5 text-xs font-medium ${DECISION_STYLES[row.decision] ?? ''}`}>
                      {row.decision}
                    </span>
                  </button>
                  {openId === row.id && (
                    <pre className="mt-2 max-h-72 overflow-auto rounded-md bg-muted p-2 text-xs"
                      data-testid="evaluation-detail">
                      {JSON.stringify({
                        matched_policy_ids: row.matched_policy_ids,
                        obligations: row.obligations,
                        explanation: row.explanation,
                        correlation_id: row.correlation_id,
                      }, null, 2)}
                    </pre>
                  )}
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
