import { WidgetCard } from '@/components/dashboard/WidgetCard'
import { Badge } from '@/components/ui/badge'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { useAuth } from '@/hooks/useAuth'
import {
  AnalyticsLayout,
  RefreshIndicator,
  RiskDistributionChart,
  RiskHeatmap,
  RiskTrendChart,
} from '../components'
import { useRiskAnalytics } from '../hooks'
import { REFRESH } from '../hooks/analyticsKeys'
import { AnalyticsAccessDenied } from './AnalyticsAccessDenied'
import type { RiskGroup } from '../types'
import { humanizeToken, riskColor } from '../utils/format'
import { canViewAnalytics } from '../utils/permissions'

export function RiskAnalyticsPage() {
  const { permissions } = useAuth()
  if (!canViewAnalytics(permissions)) {
    return <AnalyticsAccessDenied surface="risk analytics" permission="analytics.view" />
  }
  return <RiskContent />
}

function GroupList({ groups }: { groups: RiskGroup[] }) {
  if (groups.length === 0) {
    return <p className="py-8 text-center text-sm text-muted-foreground">No data yet.</p>
  }
  return (
    <ul className="space-y-2">
      {groups.map((g) => (
        <li key={g.label} className="flex items-center justify-between gap-3">
          <span className="w-32 shrink-0 truncate text-sm">{g.label}</span>
          <div className="h-2 flex-1 overflow-hidden rounded-full bg-muted">
            <div
              className="h-full rounded-full"
              style={{ width: `${g.avg_risk}%`, backgroundColor: riskColor(g.avg_risk) }}
            />
          </div>
          <span className="w-16 text-right text-sm font-medium tabular-nums">{g.avg_risk}</span>
        </li>
      ))}
    </ul>
  )
}

function RiskContent() {
  const { data, isLoading, isError, isFetching, refetch } = useRiskAnalytics()

  return (
    <AnalyticsLayout
      title="Risk Analytics"
      description="Organizational AI risk distribution, trend, and concentration across the fleet."
      actions={
        <RefreshIndicator refreshing={isFetching} everySeconds={REFRESH.charts / 1000} onRefresh={() => void refetch()} />
      }
    >
      <div className="space-y-6">
        <div className="grid gap-6 lg:grid-cols-2">
          <WidgetCard title="Risk Distribution" loading={isLoading} error={isError} onRetry={() => void refetch()}>
            {data ? <RiskDistributionChart bands={data.distribution} /> : null}
          </WidgetCard>
          <WidgetCard
            title="Risk Trend (30 days)"
            loading={isLoading}
            error={isError}
            isEmpty={Boolean(data && data.trend.every((p) => p.risk_score === 0))}
            emptyMessage="No risk data yet."
            onRetry={() => void refetch()}
          >
            {data ? <RiskTrendChart data={data.trend} /> : null}
          </WidgetCard>
        </div>

        <WidgetCard title="Risk Heatmap (agent type × band)" loading={isLoading} error={isError} onRetry={() => void refetch()}>
          {data ? <RiskHeatmap rows={data.heatmap} /> : null}
        </WidgetCard>

        <div className="grid gap-6 lg:grid-cols-2">
          <WidgetCard title="Risk by Department" loading={isLoading} error={isError} onRetry={() => void refetch()}>
            {data ? <GroupList groups={data.by_department} /> : null}
          </WidgetCard>
          <WidgetCard title="Risk by Agent Type" loading={isLoading} error={isError} onRetry={() => void refetch()}>
            {data ? <GroupList groups={data.by_agent_type} /> : null}
          </WidgetCard>
        </div>

        <WidgetCard
          title="Highest-Risk Agents"
          loading={isLoading}
          error={isError}
          isEmpty={Boolean(data && data.high_risk_agents.length === 0)}
          emptyMessage="No agent activity yet."
          onRetry={() => void refetch()}
        >
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Agent</TableHead>
                <TableHead>Type</TableHead>
                <TableHead className="text-right">Avg Risk</TableHead>
                <TableHead className="text-right">Actions</TableHead>
                <TableHead>Health</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {(data?.high_risk_agents ?? []).map((a) => (
                <TableRow key={a.agent_id}>
                  <TableCell className="font-medium">{a.name ?? '—'}</TableCell>
                  <TableCell className="text-muted-foreground">{humanizeToken(a.agent_type)}</TableCell>
                  <TableCell className="text-right">
                    <Badge style={{ backgroundColor: `${riskColor(a.avg_risk)}26`, color: riskColor(a.avg_risk) }} className="border-transparent">
                      {a.avg_risk}
                    </Badge>
                  </TableCell>
                  <TableCell className="text-right tabular-nums">{a.action_count}</TableCell>
                  <TableCell className="text-muted-foreground">{humanizeToken(a.health)}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </WidgetCard>
      </div>
    </AnalyticsLayout>
  )
}
