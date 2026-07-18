import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { BarChart3, Loader2, RefreshCw } from 'lucide-react'
import { toast } from 'sonner'

import { EmptyState, PageHeader } from '@/components/common'
import {
  Badge, Button, Card, CardContent, CardHeader, CardTitle,
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui'
import { ROUTES } from '@/constants/routes'
import { governanceService } from '@/services'
import { GovernanceNav } from './components/GovernanceNav'
import { formatDate, labelForFindingType, RISK_BAND_VARIANT } from './utils'

/** §26 — governance analytics: review completion trend, findings by
 * severity/type, privileged access growth and risk score distribution. */
export function GovernanceAnalyticsPage() {
  const qc = useQueryClient()
  const analytics = useQuery({
    queryKey: ['gov-analytics'],
    queryFn: () => governanceService.analytics(),
  })
  const riskScores = useQuery({
    queryKey: ['gov-risk-scores'],
    queryFn: () => governanceService.riskScores(),
  })

  const recalculate = useMutation({
    mutationFn: () => governanceService.recalculateRiskScores(),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['gov-risk-scores'] })
      void qc.invalidateQueries({ queryKey: ['gov-analytics'] })
      toast.success('Risk scores recalculated')
    },
    onError: (e: unknown) => toast.error((e as { message?: string }).message ?? 'Recalculation failed'),
  })

  return (
    <div className="mx-auto max-w-5xl space-y-6 p-4 sm:p-6">
      <PageHeader
        icon={BarChart3}
        title="Governance analytics"
        description="Review completion, findings breakdown, privileged access growth and risk distribution."
        backTo={ROUTES.GOVERNANCE_DASHBOARD}
        backLabel="Governance overview"
      />
      <GovernanceNav />

      {analytics.isLoading ? (
        <div className="flex justify-center p-12"><Loader2 className="h-6 w-6 animate-spin text-muted-foreground" /></div>
      ) : analytics.data ? (
        <div className="grid gap-4 sm:grid-cols-2">
          <Card>
            <CardHeader><CardTitle className="text-base">Review completion trend</CardTitle></CardHeader>
            <CardContent className="space-y-1">
              {analytics.data.review_completion_trend.length === 0 ? (
                <p className="text-sm text-muted-foreground">No completions in the last 30 days.</p>
              ) : analytics.data.review_completion_trend.map((d) => (
                <div key={d.date} className="flex items-center justify-between text-sm">
                  <span className="text-muted-foreground">{d.date}</span>
                  <span className="font-medium text-foreground">{d.completed}</span>
                </div>
              ))}
            </CardContent>
          </Card>

          <Card>
            <CardHeader><CardTitle className="text-base">Findings by severity</CardTitle></CardHeader>
            <CardContent className="flex flex-wrap gap-2">
              {analytics.data.findings_by_severity.length === 0 ? (
                <p className="text-sm text-muted-foreground">No open findings.</p>
              ) : analytics.data.findings_by_severity.map((s) => (
                <Badge key={s.severity} variant="outline" className="px-3 py-1">
                  {s.severity}: {s.total}
                </Badge>
              ))}
            </CardContent>
          </Card>

          <Card>
            <CardHeader><CardTitle className="text-base">Findings by type</CardTitle></CardHeader>
            <CardContent className="flex flex-wrap gap-2">
              {analytics.data.findings_by_type.length === 0 ? (
                <p className="text-sm text-muted-foreground">No findings recorded.</p>
              ) : analytics.data.findings_by_type.map((t) => (
                <Badge key={t.finding_type} variant="outline" className="px-3 py-1">
                  {labelForFindingType(t.finding_type)}: {t.total}
                </Badge>
              ))}
            </CardContent>
          </Card>

          <Card>
            <CardHeader><CardTitle className="text-base">Privileged access growth</CardTitle></CardHeader>
            <CardContent className="space-y-1">
              {analytics.data.privileged_access_growth.length === 0 ? (
                <p className="text-sm text-muted-foreground">No privileged grants in the last 30 days.</p>
              ) : analytics.data.privileged_access_growth.map((m) => (
                <div key={m.month} className="flex items-center justify-between text-sm">
                  <span className="text-muted-foreground">{m.month}</span>
                  <span className="font-medium text-foreground">{m.total}</span>
                </div>
              ))}
            </CardContent>
          </Card>
        </div>
      ) : null}

      <Card>
        <CardHeader className="flex-row items-center justify-between space-y-0">
          <CardTitle className="text-base">Governance risk scores</CardTitle>
          <Button size="sm" variant="outline" disabled={recalculate.isPending}
                  onClick={() => recalculate.mutate()}>
            {recalculate.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
            Recalculate
          </Button>
        </CardHeader>
        <CardContent className="p-0">
          {riskScores.isLoading ? (
            <div className="flex justify-center p-10"><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /></div>
          ) : (riskScores.data ?? []).length === 0 ? (
            <EmptyState icon={BarChart3} title="No risk scores computed yet"
                        description="Click Recalculate to score every active identity in the organization." />
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Identity</TableHead>
                  <TableHead>Computed</TableHead>
                  <TableHead>Band</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {(riskScores.data ?? []).map((r) => (
                  <TableRow key={r.id}>
                    <TableCell className="font-medium">{r.identity_label}</TableCell>
                    <TableCell className="whitespace-nowrap text-muted-foreground">{formatDate(r.computed_at)}</TableCell>
                    <TableCell>
                      <Badge variant={RISK_BAND_VARIANT[r.band] ?? 'secondary'}>{r.band} ({r.score})</Badge>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
