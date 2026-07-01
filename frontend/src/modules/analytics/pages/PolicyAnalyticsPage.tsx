import { Card } from '@/components/ui/card'
import { WidgetCard } from '@/components/dashboard/WidgetCard'
import { Badge } from '@/components/ui/badge'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { useAuth } from '@/hooks/useAuth'
import { AnalyticsLayout, PolicyAnalyticsChart, RefreshIndicator } from '../components'
import { usePolicyAnalytics } from '../hooks'
import { REFRESH } from '../hooks/analyticsKeys'
import { AnalyticsAccessDenied } from './AnalyticsAccessDenied'
import type { PolicyStat } from '../types'
import { humanizeToken } from '../utils/format'
import { canViewAnalytics } from '../utils/permissions'

export function PolicyAnalyticsPage() {
  const { permissions } = useAuth()
  if (!canViewAnalytics(permissions)) {
    return <AnalyticsAccessDenied surface="policy analytics" permission="analytics.view" />
  }
  return <PolicyContent />
}

function PolicyTable({ rows, empty }: { rows: PolicyStat[]; empty: string }) {
  if (rows.length === 0) return <p className="py-8 text-center text-sm text-muted-foreground">{empty}</p>
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Policy</TableHead>
          <TableHead>Decision</TableHead>
          <TableHead className="text-right">Triggers</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.map((p) => (
          <TableRow key={p.policy_id}>
            <TableCell className="font-medium">{p.name}</TableCell>
            <TableCell>
              <Badge variant="outline">{humanizeToken(p.decision)}</Badge>
            </TableCell>
            <TableCell className="text-right tabular-nums">{p.trigger_count}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  )
}

function PolicyContent() {
  const { data, isLoading, isError, isFetching, refetch } = usePolicyAnalytics()

  const stats = [
    { label: 'Total Policies', value: data ? String(data.total_policies) : '—' },
    { label: 'Enabled', value: data ? String(data.enabled_policies) : '—' },
    { label: 'Coverage', value: data ? `${data.coverage_pct}%` : '—' },
    { label: 'Effectiveness', value: data ? `${data.effectiveness_pct}%` : '—' },
    { label: 'False Positive Rate', value: data ? `${data.false_positive_rate}%` : '—' },
  ]

  return (
    <AnalyticsLayout
      title="Policy Analytics"
      description="Which governance policies fire, block, and route to humans — and how effective they are."
      actions={
        <RefreshIndicator refreshing={isFetching} everySeconds={REFRESH.charts / 1000} onRefresh={() => void refetch()} />
      }
    >
      <div className="space-y-6">
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
          {stats.map((s) => (
            <Card key={s.label} className="flex flex-col gap-1 p-4">
              <span className="text-xs font-medium text-muted-foreground">{s.label}</span>
              <span className="text-2xl font-semibold tabular-nums">{s.value}</span>
            </Card>
          ))}
        </div>
        {data ? (
          <p className="text-xs text-muted-foreground">* False positive rate is estimated from trigger effectiveness.</p>
        ) : null}

        <WidgetCard
          title="Most Triggered Policies"
          loading={isLoading}
          error={isError}
          onRetry={() => void refetch()}
        >
          {data ? <PolicyAnalyticsChart policies={data.most_triggered} /> : null}
        </WidgetCard>

        <div className="grid gap-6 lg:grid-cols-2">
          <WidgetCard title="Most Blocking Policies" loading={isLoading} error={isError} onRetry={() => void refetch()}>
            {data ? <PolicyTable rows={data.most_blocking} empty="No blocking policies triggered." /> : null}
          </WidgetCard>
          <WidgetCard title="Most Approval-Routing Policies" loading={isLoading} error={isError} onRetry={() => void refetch()}>
            {data ? <PolicyTable rows={data.most_approval} empty="No approval policies triggered." /> : null}
          </WidgetCard>
        </div>

        <WidgetCard title="Least Used Policies" loading={isLoading} error={isError} onRetry={() => void refetch()}>
          {data ? <PolicyTable rows={data.least_used} empty="No policies yet." /> : null}
        </WidgetCard>
      </div>
    </AnalyticsLayout>
  )
}
