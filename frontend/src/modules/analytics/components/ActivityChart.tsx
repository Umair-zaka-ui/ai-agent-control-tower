import { memo, useState } from 'react'
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

import { WidgetCard } from '@/components/dashboard/WidgetCard'
import { Select } from '@/components/ui/select'
import { useActivity } from '../hooks'
import type { ActivityRange } from '../types'
import { CHART, TOOLTIP_STYLE } from '../utils/format'

const RANGE_OPTIONS = [
  { value: 'daily', label: 'Daily' },
  { value: 'weekly', label: 'Weekly' },
  { value: 'monthly', label: 'Monthly' },
  { value: 'yearly', label: 'Yearly' },
]

const SERIES: { key: string; name: string; color: string }[] = [
  { key: 'executed', name: 'Executed', color: CHART.green },
  { key: 'blocked', name: 'Blocked', color: CHART.red },
  { key: 'approvals', name: 'Approvals', color: CHART.primary },
  { key: 'rejections', name: 'Rejections', color: CHART.orange },
  { key: 'escalations', name: 'Escalations', color: CHART.purple },
  { key: 'failures', name: 'Failures', color: CHART.yellow },
]

/** AI activity overview with daily/weekly/monthly/yearly granularity (SRS §AI Activity Overview). */
export const ActivityChart = memo(function ActivityChart() {
  const [range, setRange] = useState<ActivityRange>('daily')
  const { data, isLoading, isError, refetch } = useActivity(range)
  const isEmpty = Boolean(data && data.every((d) => SERIES.every((s) => (d as never)[s.key] === 0)))

  return (
    <WidgetCard
      title="AI Activity Overview"
      loading={isLoading}
      error={isError}
      isEmpty={isEmpty}
      emptyMessage="No activity in this period."
      onRetry={() => void refetch()}
      action={
        <Select
          aria-label="Activity range"
          className="h-8 w-28"
          value={range}
          options={RANGE_OPTIONS}
          onChange={(e) => setRange(e.target.value as ActivityRange)}
        />
      }
    >
      <ResponsiveContainer width="100%" height={300}>
        <BarChart data={data ?? []} margin={{ top: 8, right: 8, left: -16, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke={CHART.grid} vertical={false} />
          <XAxis dataKey="period" stroke={CHART.axis} fontSize={11} tickLine={false} axisLine={false} minTickGap={16} />
          <YAxis stroke={CHART.axis} fontSize={12} tickLine={false} axisLine={false} allowDecimals={false} />
          <Tooltip contentStyle={TOOLTIP_STYLE} cursor={{ fill: 'hsl(215 28% 17% / 0.4)' }} />
          <Legend wrapperStyle={{ fontSize: 12 }} />
          {SERIES.map((s) => (
            <Bar key={s.key} dataKey={s.key} name={s.name} stackId="a" fill={s.color} radius={[0, 0, 0, 0]} />
          ))}
        </BarChart>
      </ResponsiveContainer>
    </WidgetCard>
  )
})
