import { Card } from '@/components/ui/card'
import { WidgetCard } from '@/components/dashboard/WidgetCard'
import { useAuth } from '@/hooks/useAuth'
import { AgentRankingTable, AnalyticsLayout, PerformanceChart, RefreshIndicator } from '../components'
import { usePerformanceAnalytics } from '../hooks'
import { REFRESH } from '../hooks/analyticsKeys'
import { AnalyticsAccessDenied } from './AnalyticsAccessDenied'
import { formatSeconds } from '../utils/format'
import { canViewAnalytics } from '../utils/permissions'

export function PerformanceDashboardPage() {
  const { permissions } = useAuth()
  if (!canViewAnalytics(permissions)) {
    return <AnalyticsAccessDenied surface="performance analytics" permission="analytics.view" />
  }
  return <PerformanceContent />
}

function PerformanceContent() {
  const { data, isLoading, isError, isFetching, refetch } = usePerformanceAnalytics()
  const m = data?.metrics

  const cards = [
    { label: 'Avg Response', value: m ? `${m.avg_response_time_ms}ms` : '—' },
    { label: 'Decision Latency', value: m ? `${m.decision_latency_ms}ms` : '—' },
    { label: 'Policy Eval', value: m ? `${m.policy_eval_time_ms}ms` : '—' },
    { label: 'Execution', value: m ? `${m.execution_time_ms}ms` : '—' },
    { label: 'Approval Delay', value: m ? formatSeconds(m.approval_delay_seconds) : '—' },
    { label: 'Failure Rate', value: m ? `${m.failure_rate}%` : '—' },
    { label: 'Retry Rate', value: m ? `${m.retry_rate}%` : '—' },
  ]

  return (
    <AnalyticsLayout
      title="Performance Dashboard"
      description="AI processing latency, failure rates and per-agent performance ranking."
      actions={
        <RefreshIndicator refreshing={isFetching} everySeconds={REFRESH.charts / 1000} onRefresh={() => void refetch()} />
      }
    >
      <div className="space-y-6">
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-7">
          {cards.map((c) => (
            <Card key={c.label} className="flex flex-col gap-1 p-4">
              <span className="text-xs font-medium text-muted-foreground">{c.label}</span>
              <span className="text-xl font-semibold tabular-nums">{c.value}</span>
            </Card>
          ))}
        </div>
        {m?.estimated ? (
          <p className="text-xs text-muted-foreground">
            * Latency metrics are estimated from activity volume and risk; approval delay and failure rate are measured.
          </p>
        ) : null}

        <div className="grid gap-6 lg:grid-cols-2">
          <WidgetCard title="Processing Time Breakdown" loading={isLoading} error={isError} onRetry={() => void refetch()}>
            {m ? <PerformanceChart metrics={m} /> : null}
          </WidgetCard>
          <WidgetCard title="Failure vs Retry" loading={isLoading} error={isError} onRetry={() => void refetch()}>
            {m ? (
              <div className="space-y-4 py-2">
                <Ratio label="Failure Rate" value={m.failure_rate} tone="bg-destructive" />
                <Ratio label="Retry Rate" value={m.retry_rate} tone="bg-warning" />
                <Ratio label="Success" value={Math.max(0, 100 - m.failure_rate)} tone="bg-success" />
              </div>
            ) : null}
          </WidgetCard>
        </div>

        <WidgetCard
          title="Agent Performance Ranking"
          loading={isLoading}
          error={isError}
          isEmpty={Boolean(data && data.ranking.length === 0)}
          emptyMessage="No agent activity yet."
          onRetry={() => void refetch()}
        >
          {data ? <AgentRankingTable rows={data.ranking} /> : null}
        </WidgetCard>
      </div>
    </AnalyticsLayout>
  )
}

function Ratio({ label, value, tone }: { label: string; value: number; tone: string }) {
  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between text-sm">
        <span>{label}</span>
        <span className="font-medium tabular-nums">{value}%</span>
      </div>
      <div className="h-2 w-full overflow-hidden rounded-full bg-muted">
        <div className={`h-full rounded-full ${tone}`} style={{ width: `${Math.min(100, value)}%` }} />
      </div>
    </div>
  )
}
