import { memo } from 'react'
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

import { Card } from '@/components/ui/card'
import { CHART, TOOLTIP_STYLE } from '../utils/format'
import type { PerformanceMetrics } from '../types'

/** Latency / processing-time bars from the performance metrics (SRS §PerformanceChart). */
export const PerformanceChart = memo(function PerformanceChart({ metrics }: { metrics: PerformanceMetrics }) {
  const data = [
    { name: 'Decision', value: metrics.decision_latency_ms, color: CHART.primary },
    { name: 'Policy Eval', value: metrics.policy_eval_time_ms, color: CHART.purple },
    { name: 'Execution', value: metrics.execution_time_ms, color: CHART.orange },
    { name: 'Avg Response', value: metrics.avg_response_time_ms, color: CHART.green },
  ]
  return (
    <Card className="p-4">
      <ResponsiveContainer width="100%" height={260}>
        <BarChart data={data} margin={{ top: 8, right: 8, left: -16, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke={CHART.grid} vertical={false} />
          <XAxis dataKey="name" stroke={CHART.axis} fontSize={12} tickLine={false} axisLine={false} />
          <YAxis
            stroke={CHART.axis}
            fontSize={12}
            tickLine={false}
            axisLine={false}
            tickFormatter={(v: number) => `${v}ms`}
          />
          <Tooltip contentStyle={TOOLTIP_STYLE} cursor={{ fill: 'hsl(215 28% 17% / 0.4)' }} formatter={(v) => [`${v}ms`, 'Time']} />
          <Bar dataKey="value" radius={[4, 4, 0, 0]}>
            {data.map((d) => (
              <Cell key={d.name} fill={d.color} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </Card>
  )
})
