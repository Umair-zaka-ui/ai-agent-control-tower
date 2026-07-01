import { memo } from 'react'
import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from 'recharts'

import { EmptyState } from '@/components/common/EmptyState'
import { CHART, TOOLTIP_STYLE } from '../utils/format'
import type { RiskBands } from '../types'

/** Risk distribution donut across the four risk bands (SRS §Risk Distribution). */
export const RiskDistributionChart = memo(function RiskDistributionChart({ bands }: { bands: RiskBands }) {
  const data = [
    { name: 'Low', value: bands.low, color: CHART.green },
    { name: 'Medium', value: bands.medium, color: CHART.yellow },
    { name: 'High', value: bands.high, color: CHART.orange },
    { name: 'Critical', value: bands.critical, color: CHART.red },
  ]
  const total = data.reduce((sum, d) => sum + d.value, 0)
  if (total === 0) {
    return <EmptyState title="No risk data" description="Risk distribution will appear as agents act." />
  }
  return (
    <div className="flex flex-col items-center gap-4 sm:flex-row">
      <ResponsiveContainer width="100%" height={220} className="max-w-[260px]">
        <PieChart>
          <Pie data={data} dataKey="value" nameKey="name" innerRadius={55} outerRadius={85} paddingAngle={2}>
            {data.map((d) => (
              <Cell key={d.name} fill={d.color} stroke="transparent" />
            ))}
          </Pie>
          <Tooltip contentStyle={TOOLTIP_STYLE} />
        </PieChart>
      </ResponsiveContainer>
      <ul className="grid w-full grid-cols-2 gap-2 sm:max-w-xs">
        {data.map((d) => (
          <li key={d.name} className="flex items-center justify-between rounded-md border border-border px-3 py-2">
            <span className="inline-flex items-center gap-2 text-sm">
              <span className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: d.color }} aria-hidden />
              {d.name}
            </span>
            <span className="font-semibold tabular-nums">{d.value}</span>
          </li>
        ))}
      </ul>
    </div>
  )
})
