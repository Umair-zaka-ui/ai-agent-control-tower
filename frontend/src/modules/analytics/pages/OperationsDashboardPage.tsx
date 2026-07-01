import { Card } from '@/components/ui/card'
import { WidgetCard } from '@/components/dashboard/WidgetCard'
import { useAuth } from '@/hooks/useAuth'
import {
  ActivityFeed,
  AnalyticsLayout,
  FleetHealthPanel,
  HumanReviewChart,
  RefreshIndicator,
} from '../components'
import { useActivityFeed, useFleetHealth, useHumanReviewAnalytics } from '../hooks'
import { REFRESH } from '../hooks/analyticsKeys'
import { AnalyticsAccessDenied } from './AnalyticsAccessDenied'
import { formatSeconds } from '../utils/format'
import { canViewOperations } from '../utils/permissions'

export function OperationsDashboardPage() {
  const { permissions } = useAuth()
  if (!canViewOperations(permissions)) {
    return <AnalyticsAccessDenied surface="operations dashboard" permission="analytics.operations" />
  }
  return <OperationsContent />
}

function OperationsContent() {
  const feed = useActivityFeed(15)
  const fleet = useFleetHealth()
  const review = useHumanReviewAnalytics()

  const r = review.data
  const stats = [
    { label: 'Pending Queue', value: r ? String(r.pending_queue) : '—' },
    { label: 'Avg Approval Time', value: r ? formatSeconds(r.avg_approval_time_seconds) : '—' },
    { label: 'Approval Ratio', value: r ? `${r.approval_ratio}%` : '—' },
    { label: 'Escalation Rate', value: r ? `${r.escalation_rate}%` : '—' },
  ]

  return (
    <AnalyticsLayout
      title="Operations Dashboard"
      description="Live AI operations monitoring — activity, fleet health, queue and reviewer workload."
      actions={
        <RefreshIndicator
          refreshing={feed.isFetching}
          everySeconds={REFRESH.feed / 1000}
          onRefresh={() => void feed.refetch()}
        />
      }
    >
      <div className="space-y-6">
        <section className="space-y-3">
          <h2 className="text-sm font-semibold text-muted-foreground">AI Fleet Health</h2>
          <FleetHealthPanel data={fleet.data} loading={fleet.isLoading} />
        </section>

        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          {stats.map((s) => (
            <Card key={s.label} className="flex flex-col gap-1 p-4">
              <span className="text-xs font-medium text-muted-foreground">{s.label}</span>
              <span className="text-2xl font-semibold tabular-nums">{s.value}</span>
            </Card>
          ))}
        </div>

        <div className="grid gap-6 lg:grid-cols-2">
          <WidgetCard
            title="Live Agent Activity"
            loading={feed.isLoading}
            error={feed.isError}
            onRetry={() => void feed.refetch()}
          >
            <ActivityFeed actions={feed.data} loading={feed.isLoading} />
          </WidgetCard>

          <WidgetCard
            title="Reviewer Workload"
            loading={review.isLoading}
            error={review.isError}
            onRetry={() => void review.refetch()}
          >
            {review.data ? <HumanReviewChart data={review.data} /> : null}
          </WidgetCard>
        </div>
      </div>
    </AnalyticsLayout>
  )
}
