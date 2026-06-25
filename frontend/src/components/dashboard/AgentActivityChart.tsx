import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

import { useAgentActivity } from '@/hooks/useAgentActivity'
import { WidgetCard } from './WidgetCard'

const AXIS = 'hsl(215 20% 65%)'
const GRID = 'hsl(215 28% 17%)'
const LINE = 'hsl(221 83% 53%)'

const TOOLTIP_STYLE = {
  backgroundColor: 'hsl(222 47% 11%)',
  border: '1px solid hsl(215 28% 17%)',
  borderRadius: 8,
  color: 'hsl(210 40% 98%)',
  fontSize: 12,
}

/** Daily agent-action volume over the last 7 days (live: /dashboard/activity). */
export function AgentActivityChart() {
  const { data, isLoading, isError, refetch } = useAgentActivity(7)
  const isEmpty = Boolean(data && data.every((d) => d.actions === 0))

  return (
    <WidgetCard
      title="Agent Activity"
      loading={isLoading}
      error={isError}
      isEmpty={isEmpty}
      emptyMessage="No agent activity in the last 7 days."
      onRetry={() => void refetch()}
    >
      <ResponsiveContainer width="100%" height={260}>
        <LineChart data={data ?? []} margin={{ top: 8, right: 8, left: -16, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke={GRID} vertical={false} />
          <XAxis dataKey="date" stroke={AXIS} fontSize={12} tickLine={false} axisLine={false} />
          <YAxis stroke={AXIS} fontSize={12} tickLine={false} axisLine={false} allowDecimals={false} />
          <Tooltip contentStyle={TOOLTIP_STYLE} cursor={{ stroke: GRID }} />
          <Line
            type="monotone"
            dataKey="actions"
            name="Actions"
            stroke={LINE}
            strokeWidth={2}
            dot={{ r: 3, fill: LINE }}
            activeDot={{ r: 5 }}
            animationDuration={600}
          />
        </LineChart>
      </ResponsiveContainer>
    </WidgetCard>
  )
}
