import { memo } from 'react'
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

import { formatDate } from '@/utils/format'
import type { RiskTrendPoint } from '../types'
import { CHART, TOOLTIP_STYLE, riskColor } from '../utils/format'

/** Organizational risk trend area chart (SRS §RiskTrendChart). */
export const RiskTrendChart = memo(function RiskTrendChart({ data }: { data: RiskTrendPoint[] }) {
  const latest = data.length ? data[data.length - 1].risk_score : 0
  const color = riskColor(latest)
  return (
    <ResponsiveContainer width="100%" height={260}>
      <AreaChart data={data} margin={{ top: 8, right: 8, left: -16, bottom: 0 }}>
        <defs>
          <linearGradient id="analyticsRiskFill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={color} stopOpacity={0.35} />
            <stop offset="100%" stopColor={color} stopOpacity={0} />
          </linearGradient>
        </defs>
        <CartesianGrid strokeDasharray="3 3" stroke={CHART.grid} vertical={false} />
        <XAxis
          dataKey="date"
          stroke={CHART.axis}
          fontSize={11}
          tickLine={false}
          axisLine={false}
          tickFormatter={(d: string) => formatDate(d).replace(/,.*/, '')}
          minTickGap={24}
        />
        <YAxis stroke={CHART.axis} fontSize={12} tickLine={false} axisLine={false} domain={[0, 100]} />
        <Tooltip contentStyle={TOOLTIP_STYLE} cursor={{ stroke: CHART.grid }} />
        <Area
          type="monotone"
          dataKey="risk_score"
          name="Risk"
          stroke={color}
          strokeWidth={2}
          fill="url(#analyticsRiskFill)"
          animationDuration={600}
        />
      </AreaChart>
    </ResponsiveContainer>
  )
})
