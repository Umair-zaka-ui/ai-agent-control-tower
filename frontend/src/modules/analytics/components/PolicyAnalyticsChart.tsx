import { memo } from 'react'
import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

import { EmptyState } from '@/components/common/EmptyState'
import { CHART, TOOLTIP_STYLE } from '../utils/format'
import type { PolicyStat } from '../types'

/** Horizontal bar of policies by trigger count (SRS §Policy Analytics). */
export const PolicyAnalyticsChart = memo(function PolicyAnalyticsChart({
  policies,
}: {
  policies: PolicyStat[]
}) {
  const data = policies
    .filter((p) => p.trigger_count > 0)
    .slice(0, 8)
    .map((p) => ({ name: p.name, value: p.trigger_count }))

  if (data.length === 0) {
    return <EmptyState title="No policy triggers yet" description="Policy trigger counts will appear here." />
  }

  return (
    <ResponsiveContainer width="100%" height={Math.max(180, data.length * 40)}>
      <BarChart data={data} layout="vertical" margin={{ top: 4, right: 16, left: 8, bottom: 4 }}>
        <CartesianGrid strokeDasharray="3 3" stroke={CHART.grid} horizontal={false} />
        <XAxis type="number" stroke={CHART.axis} fontSize={12} tickLine={false} axisLine={false} allowDecimals={false} />
        <YAxis
          type="category"
          dataKey="name"
          stroke={CHART.axis}
          fontSize={12}
          tickLine={false}
          axisLine={false}
          width={140}
        />
        <Tooltip contentStyle={TOOLTIP_STYLE} cursor={{ fill: 'hsl(215 28% 17% / 0.4)' }} />
        <Bar dataKey="value" name="Triggers" fill={CHART.primary} radius={[0, 4, 4, 0]} />
      </BarChart>
    </ResponsiveContainer>
  )
})
