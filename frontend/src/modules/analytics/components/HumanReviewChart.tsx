import { memo } from 'react'
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

import { EmptyState } from '@/components/common/EmptyState'
import { CHART, TOOLTIP_STYLE } from '../utils/format'
import type { HumanReviewAnalytics } from '../types'

/** Reviewer workload + outcomes (SRS §Human Review Analytics / §HumanReviewChart). */
export const HumanReviewChart = memo(function HumanReviewChart({ data }: { data: HumanReviewAnalytics }) {
  const rows = data.reviewers
    .slice(0, 10)
    .map((r) => ({ name: r.name ?? 'Unknown', approved: r.approved, rejected: r.rejected, assigned: r.assigned }))

  if (rows.length === 0) {
    return <EmptyState title="No reviewer activity" description="Reviewer workload will appear here once approvals are decided." />
  }

  return (
    <ResponsiveContainer width="100%" height={Math.max(200, rows.length * 44)}>
      <BarChart data={rows} layout="vertical" margin={{ top: 4, right: 16, left: 8, bottom: 4 }}>
        <CartesianGrid strokeDasharray="3 3" stroke={CHART.grid} horizontal={false} />
        <XAxis type="number" stroke={CHART.axis} fontSize={12} tickLine={false} axisLine={false} allowDecimals={false} />
        <YAxis type="category" dataKey="name" stroke={CHART.axis} fontSize={12} tickLine={false} axisLine={false} width={120} />
        <Tooltip contentStyle={TOOLTIP_STYLE} cursor={{ fill: 'hsl(215 28% 17% / 0.4)' }} />
        <Legend wrapperStyle={{ fontSize: 12 }} />
        <Bar dataKey="approved" name="Approved" stackId="r" fill={CHART.green} radius={[0, 0, 0, 0]} />
        <Bar dataKey="rejected" name="Rejected" stackId="r" fill={CHART.red} radius={[0, 4, 4, 0]} />
      </BarChart>
    </ResponsiveContainer>
  )
})
