import { memo } from 'react'
import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from 'recharts'

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { useAuth } from '@/hooks/useAuth'
import { AnalyticsLayout, CostBreakdownCard, RefreshIndicator } from '../components'
import { useCostAnalytics } from '../hooks'
import { REFRESH } from '../hooks/analyticsKeys'
import { AnalyticsAccessDenied } from './AnalyticsAccessDenied'
import type { CostItem } from '../types'
import { CHART, TOOLTIP_STYLE, formatCurrency } from '../utils/format'

const SLICE_COLORS = [CHART.primary, CHART.green, CHART.purple, CHART.orange, CHART.yellow, CHART.red]

export function CostDashboardPage() {
  const { permissions } = useAuth()
  if (!canCost(permissions)) {
    return <AnalyticsAccessDenied surface="cost dashboard" permission="analytics.view" />
  }
  return <CostContent />
}

function canCost(permissions: string[]): boolean {
  return permissions.includes('analytics.view')
}

const CostPie = memo(function CostPie({ items, currency }: { items: CostItem[]; currency: string }) {
  const data = items.filter((i) => i.amount > 0)
  if (data.length === 0) {
    return <p className="py-8 text-center text-sm text-muted-foreground">No cost data yet.</p>
  }
  return (
    <ResponsiveContainer width="100%" height={260}>
      <PieChart>
        <Pie data={data} dataKey="amount" nameKey="label" innerRadius={60} outerRadius={95} paddingAngle={2}>
          {data.map((d, i) => (
            <Cell key={d.key} fill={SLICE_COLORS[i % SLICE_COLORS.length]} stroke="transparent" />
          ))}
        </Pie>
        <Tooltip contentStyle={TOOLTIP_STYLE} formatter={(v) => formatCurrency(Number(v), currency)} />
      </PieChart>
    </ResponsiveContainer>
  )
})

function CostContent() {
  const { data, isLoading, isFetching, refetch } = useCostAnalytics()

  return (
    <AnalyticsLayout
      title="Cost Dashboard"
      description="Estimated enterprise AI spend across compute, LLM usage, human review and storage."
      actions={
        <RefreshIndicator refreshing={isFetching} everySeconds={REFRESH.charts / 1000} onRefresh={() => void refetch()} />
      }
    >
      <div className="grid gap-6 lg:grid-cols-2">
        <CostBreakdownCard data={data} loading={isLoading} />
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Cost Composition</CardTitle>
          </CardHeader>
          <CardContent>
            {data ? <CostPie items={data.items} currency={data.currency} /> : null}
          </CardContent>
        </Card>
      </div>
    </AnalyticsLayout>
  )
}
