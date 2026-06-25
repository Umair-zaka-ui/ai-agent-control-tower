import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

import { useRiskTrend } from '@/hooks/useRiskTrend'
import { formatDate } from '@/utils/format'
import { WidgetCard } from './WidgetCard'

const AXIS = 'hsl(215 20% 65%)'
const GRID = 'hsl(215 28% 17%)'

const TOOLTIP_STYLE = {
  backgroundColor: 'hsl(222 47% 11%)',
  border: '1px solid hsl(215 28% 17%)',
  borderRadius: 8,
  color: 'hsl(210 40% 98%)',
  fontSize: 12,
}

/** Map a 0–100 risk score to its band colour (SRS Part 3.1). */
function riskColor(score: number): string {
  if (score <= 30) return 'hsl(142 76% 36%)' // green
  if (score <= 60) return 'hsl(48 96% 53%)' // yellow
  if (score <= 80) return 'hsl(25 95% 53%)' // orange
  return 'hsl(0 72% 51%)' // red
}

/** 30-day average organizational risk (live: /dashboard/risk-trend). */
export function RiskTrendChart() {
  const { data, isLoading, isError, refetch } = useRiskTrend(30)
  const isEmpty = Boolean(data && data.length === 0)

  const latest = data && data.length > 0 ? data[data.length - 1].risk_score : 0
  const color = riskColor(latest)

  return (
    <WidgetCard
      title="Risk Trend (30 days)"
      loading={isLoading}
      error={isError}
      isEmpty={isEmpty}
      emptyMessage="No risk data yet."
      onRetry={() => void refetch()}
    >
      <ResponsiveContainer width="100%" height={260}>
        <AreaChart data={data ?? []} margin={{ top: 8, right: 8, left: -16, bottom: 0 }}>
          <defs>
            <linearGradient id="riskFill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={color} stopOpacity={0.35} />
              <stop offset="100%" stopColor={color} stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid strokeDasharray="3 3" stroke={GRID} vertical={false} />
          <XAxis
            dataKey="date"
            stroke={AXIS}
            fontSize={11}
            tickLine={false}
            axisLine={false}
            tickFormatter={(d: string) => formatDate(d).replace(/,.*/, '')}
            minTickGap={24}
          />
          <YAxis
            stroke={AXIS}
            fontSize={12}
            tickLine={false}
            axisLine={false}
            domain={[0, 100]}
          />
          <Tooltip contentStyle={TOOLTIP_STYLE} cursor={{ stroke: GRID }} />
          <Area
            type="monotone"
            dataKey="risk_score"
            name="Risk"
            stroke={color}
            strokeWidth={2}
            fill="url(#riskFill)"
            animationDuration={600}
          />
        </AreaChart>
      </ResponsiveContainer>
    </WidgetCard>
  )
}
