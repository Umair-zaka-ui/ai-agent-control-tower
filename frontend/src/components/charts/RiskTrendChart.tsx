import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'

interface RiskPoint {
  label: string
  risk: number
}

/**
 * Risk trend area chart (SRS §3 — Recharts). Part 1 ships with placeholder
 * sample data so the chart pipeline is proven; real data wiring lands later.
 */
const SAMPLE: RiskPoint[] = [
  { label: 'Mon', risk: 32 },
  { label: 'Tue', risk: 45 },
  { label: 'Wed', risk: 38 },
  { label: 'Thu', risk: 61 },
  { label: 'Fri', risk: 52 },
  { label: 'Sat', risk: 28 },
  { label: 'Sun', risk: 40 },
]

export function RiskTrendChart({ data = SAMPLE }: { data?: RiskPoint[] }) {
  return (
    <ResponsiveContainer width="100%" height={260}>
      <AreaChart data={data} margin={{ top: 8, right: 8, left: -16, bottom: 0 }}>
        <defs>
          <linearGradient id="riskFill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="hsl(221 83% 53%)" stopOpacity={0.4} />
            <stop offset="100%" stopColor="hsl(221 83% 53%)" stopOpacity={0} />
          </linearGradient>
        </defs>
        <CartesianGrid strokeDasharray="3 3" stroke="hsl(217 33% 24%)" vertical={false} />
        <XAxis
          dataKey="label"
          stroke="hsl(215 20% 65%)"
          fontSize={12}
          tickLine={false}
          axisLine={false}
        />
        <YAxis stroke="hsl(215 20% 65%)" fontSize={12} tickLine={false} axisLine={false} domain={[0, 100]} />
        <Tooltip
          contentStyle={{
            backgroundColor: 'hsl(217 33% 17%)',
            border: '1px solid hsl(217 33% 24%)',
            borderRadius: 8,
            color: 'hsl(210 40% 98%)',
            fontSize: 12,
          }}
        />
        <Area
          type="monotone"
          dataKey="risk"
          stroke="hsl(221 83% 53%)"
          strokeWidth={2}
          fill="url(#riskFill)"
        />
      </AreaChart>
    </ResponsiveContainer>
  )
}
