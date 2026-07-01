import { WidgetCard } from '@/components/dashboard/WidgetCard'
import { useAuth } from '@/hooks/useAuth'
import { AgentRankingTable, AnalyticsLayout, FleetHealthPanel, RefreshIndicator } from '../components'
import { useFleetHealth, usePerformanceAnalytics } from '../hooks'
import { REFRESH } from '../hooks/analyticsKeys'
import { AnalyticsAccessDenied } from './AnalyticsAccessDenied'
import { canViewAnalytics } from '../utils/permissions'

export function AgentsAnalyticsPage() {
  const { permissions } = useAuth()
  if (!canViewAnalytics(permissions)) {
    return <AnalyticsAccessDenied surface="agent analytics" permission="analytics.view" />
  }
  return <AgentsContent />
}

function AgentsContent() {
  const fleet = useFleetHealth()
  const perf = usePerformanceAnalytics()

  return (
    <AnalyticsLayout
      title="Agent Analytics"
      description="Fleet composition and per-agent throughput, success and risk."
      actions={
        <RefreshIndicator
          refreshing={fleet.isFetching || perf.isFetching}
          everySeconds={REFRESH.charts / 1000}
          onRefresh={() => {
            void fleet.refetch()
            void perf.refetch()
          }}
        />
      }
    >
      <div className="space-y-6">
        <section className="space-y-3">
          <h2 className="text-sm font-semibold text-muted-foreground">AI Fleet Health</h2>
          <FleetHealthPanel data={fleet.data} loading={fleet.isLoading} />
        </section>

        <WidgetCard
          title="Agent Performance Ranking"
          loading={perf.isLoading}
          error={perf.isError}
          isEmpty={Boolean(perf.data && perf.data.ranking.length === 0)}
          emptyMessage="No agent activity yet."
          onRetry={() => void perf.refetch()}
        >
          {perf.data ? <AgentRankingTable rows={perf.data.ranking} /> : null}
        </WidgetCard>
      </div>
    </AnalyticsLayout>
  )
}
