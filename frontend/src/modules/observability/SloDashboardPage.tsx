import { useQuery, useQueries } from '@tanstack/react-query'
import { Boxes, Loader2 } from 'lucide-react'

import { EmptyState, PageHeader } from '@/components/common'
import {
  Card, CardContent,
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui'
import { observabilityService } from '@/services'
import { ObservabilityNav } from './components/ObservabilityNav'
import { ErrorBudgetBar, SloStateBadge } from './components/badges'

/**
 * Phase 4.9 view 7 — SLO Dashboard (M4-4.9-FR-007).
 *
 * Target, latest observed value, state and error-budget consumption for every
 * SLO (4.7). A burned budget reads destructive and says "spent"; an
 * `INSUFFICIENT_DATA` evaluation is shown as such, never as met.
 */
export function SloDashboardPage() {
  const slos = useQuery({ queryKey: ['obs-slos'], queryFn: () => observabilityService.slos() })

  const evals = useQueries({
    queries: (slos.data ?? []).map((s) => ({
      queryKey: ['obs-slo-eval', s.id],
      queryFn: () => observabilityService.sloEvaluations(s.id),
      enabled: Boolean(slos.data),
    })),
  })

  const latest = new Map<string, ReturnType<typeof buildLatest>>()
  ;(slos.data ?? []).forEach((s, i) => {
    latest.set(s.id, buildLatest(evals[i]?.data))
  })

  return (
    <div className="mx-auto max-w-7xl space-y-6 p-4 sm:p-6">
      <PageHeader
        icon={Boxes}
        title="SLO Dashboard"
        description="Runtime reliability as objectives — an SLI, a target, a window, an error budget."
      />
      <ObservabilityNav />

      <Card>
        <CardContent className="p-0">
          {slos.isLoading ? (
            <div className="flex justify-center p-10"><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /></div>
          ) : !slos.data || slos.data.length === 0 ? (
            <EmptyState icon={Boxes} title="No SLOs defined" description="Define a service objective and it will appear here with its error budget." />
          ) : (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Name</TableHead>
                    <TableHead>SLI</TableHead>
                    <TableHead>Window</TableHead>
                    <TableHead>Target</TableHead>
                    <TableHead>Observed</TableHead>
                    <TableHead>State</TableHead>
                    <TableHead>Error budget</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {slos.data.map((s) => {
                    const l = latest.get(s.id)
                    return (
                      <TableRow key={s.id}>
                        <TableCell className="font-medium">{s.name}{s.enabled ? '' : ' (disabled)'}</TableCell>
                        <TableCell className="text-xs">{s.sli}</TableCell>
                        <TableCell>{s.window}</TableCell>
                        <TableCell>{s.target}</TableCell>
                        <TableCell>{l?.observed ?? '—'}</TableCell>
                        <TableCell><SloStateBadge value={l?.state} /></TableCell>
                        <TableCell><ErrorBudgetBar consumed={l?.consumed ?? null} /></TableCell>
                      </TableRow>
                    )
                  })}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}

function buildLatest(evaluations: { state: string; observed_value: number | null; budget_consumed: number | null; evaluated_at: string }[] | undefined) {
  if (!evaluations || evaluations.length === 0) return null
  const newest = [...evaluations].sort(
    (a, b) => new Date(b.evaluated_at).getTime() - new Date(a.evaluated_at).getTime(),
  )[0]
  return { state: newest.state, observed: newest.observed_value, consumed: newest.budget_consumed }
}
