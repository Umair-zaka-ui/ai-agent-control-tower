import { Lightbulb } from 'lucide-react'

import { WidgetCard } from '@/components/dashboard/WidgetCard'
import { useAuth } from '@/hooks/useAuth'
import {
  ActivityChart,
  AnalyticsLayout,
  FleetHealthPanel,
  InsightsPanel,
  KpiGrid,
  RefreshIndicator,
  RiskDistributionChart,
} from '../components'
import { useAnalyticsOverview } from '../hooks'
import { REFRESH } from '../hooks/analyticsKeys'
import { AnalyticsAccessDenied } from './AnalyticsAccessDenied'
import { canViewAnalytics } from '../utils/permissions'

export function AnalyticsOverviewPage() {
  const { permissions } = useAuth()
  if (!canViewAnalytics(permissions)) {
    return <AnalyticsAccessDenied surface="analytics center" permission="analytics.view" />
  }
  return <OverviewContent />
}

function OverviewContent() {
  const { data, isLoading, isError, isFetching, refetch } = useAnalyticsOverview()

  return (
    <AnalyticsLayout
      title="Analytics & AI Operations"
      description="Mission control for your AI fleet — health, risk, performance and cost at a glance."
      actions={
        <RefreshIndicator
          refreshing={isFetching}
          everySeconds={REFRESH.dashboard / 1000}
          onRefresh={() => void refetch()}
        />
      }
    >
      {isError ? (
        <SectionError onRetry={() => void refetch()} />
      ) : (
        <div className="space-y-6">
          <KpiGrid kpis={data?.kpis} loading={isLoading} />

          <section className="space-y-3">
            <h2 className="text-sm font-semibold text-muted-foreground">AI Fleet Health</h2>
            <FleetHealthPanel data={data?.fleet_health} loading={isLoading} />
          </section>

          <div className="grid gap-6 lg:grid-cols-2">
            <ActivityChart />
            <WidgetCard
              title="Risk Distribution"
              loading={isLoading}
              isEmpty={Boolean(data && Object.values(data.risk_distribution).every((v) => v === 0))}
              emptyMessage="No risk data yet."
            >
              {data ? <RiskDistributionChart bands={data.risk_distribution} /> : null}
            </WidgetCard>
          </div>

          <WidgetCard title="AI Insights" loading={isLoading}>
            <div className="flex items-start gap-2">
              <Lightbulb className="mt-0.5 h-4 w-4 shrink-0 text-warning" aria-hidden />
              <div className="flex-1">
                <InsightsPanel insights={data?.insights} loading={isLoading} />
              </div>
            </div>
          </WidgetCard>
        </div>
      )}
    </AnalyticsLayout>
  )
}

function SectionError({ onRetry }: { onRetry: () => void }) {
  return (
    <div role="alert" className="flex flex-col items-center gap-3 py-16 text-center">
      <p className="text-sm text-muted-foreground">Unable to load analytics.</p>
      <button
        type="button"
        onClick={onRetry}
        className="rounded-md border border-border px-3 py-1.5 text-sm hover:bg-muted/50"
      >
        Retry
      </button>
    </div>
  )
}
