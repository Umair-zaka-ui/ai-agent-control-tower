import { WidgetCard } from '@/components/dashboard/WidgetCard'
import { useAuth } from '@/hooks/useAuth'
import {
  AnalyticsLayout,
  ExecutiveCards,
  InsightsPanel,
  RefreshIndicator,
  RiskTrendChart,
} from '../components'
import { useExecutiveDashboard, useInsights, useRiskAnalytics } from '../hooks'
import { REFRESH } from '../hooks/analyticsKeys'
import { AnalyticsAccessDenied } from './AnalyticsAccessDenied'
import { canViewExecutive } from '../utils/permissions'

export function ExecutiveDashboardPage() {
  const { permissions } = useAuth()
  if (!canViewExecutive(permissions)) {
    return <AnalyticsAccessDenied surface="executive dashboard" permission="analytics.executive" />
  }
  return <ExecutiveContent />
}

function ExecutiveContent() {
  const kpis = useExecutiveDashboard()
  const risk = useRiskAnalytics()
  const insights = useInsights()

  return (
    <AnalyticsLayout
      title="Executive Dashboard"
      description="High-level AI governance posture for executive and compliance leadership."
      actions={
        <RefreshIndicator
          refreshing={kpis.isFetching}
          everySeconds={REFRESH.kpis / 1000}
          onRefresh={() => void kpis.refetch()}
        />
      }
    >
      <div className="space-y-6">
        <ExecutiveCards kpis={kpis.data} loading={kpis.isLoading} />

        <div className="grid gap-6 lg:grid-cols-2">
          <WidgetCard
            title="Organizational Risk Trend (30 days)"
            loading={risk.isLoading}
            error={risk.isError}
            isEmpty={Boolean(risk.data && risk.data.trend.every((p) => p.risk_score === 0))}
            emptyMessage="No risk data yet."
            onRetry={() => void risk.refetch()}
          >
            {risk.data ? <RiskTrendChart data={risk.data.trend} /> : null}
          </WidgetCard>

          <WidgetCard
            title="Key Insights"
            loading={insights.isLoading}
            error={insights.isError}
            onRetry={() => void insights.refetch()}
          >
            <InsightsPanel insights={insights.data} loading={insights.isLoading} />
          </WidgetCard>
        </div>
      </div>
    </AnalyticsLayout>
  )
}
