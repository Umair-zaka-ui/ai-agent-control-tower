import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from 'recharts'

import type { ApprovalRiskAssessment } from '../types'

// Distinct hues for risk categories (Action, Resource, PHI Exposure, …).
const COLORS = ['#6366f1', '#0ea5e9', '#f59e0b', '#ef4444', '#10b981', '#a855f7']

/** Pie chart of how the risk score was composed (SRS §Risk Breakdown). */
export function RiskBreakdownChart({ risk }: { risk: ApprovalRiskAssessment }) {
  const data = Object.entries(risk.factors)
    .filter(([, value]) => value > 0)
    .map(([name, value]) => ({ name, value }))

  if (data.length === 0) {
    return <p className="py-6 text-center text-sm text-muted-foreground">No risk factors recorded.</p>
  }

  return (
    <div className="flex flex-col items-center gap-4 sm:flex-row">
      <div className="h-44 w-44 shrink-0">
        <ResponsiveContainer width="100%" height="100%">
          <PieChart>
            <Pie data={data} dataKey="value" nameKey="name" innerRadius={40} outerRadius={70} paddingAngle={2}>
              {data.map((entry, index) => (
                <Cell key={entry.name} fill={COLORS[index % COLORS.length]} />
              ))}
            </Pie>
            <Tooltip
              contentStyle={{
                background: 'hsl(var(--card))',
                border: '1px solid hsl(var(--border))',
                borderRadius: 8,
                fontSize: 12,
              }}
            />
          </PieChart>
        </ResponsiveContainer>
      </div>
      <ul className="flex-1 space-y-1.5">
        {data.map((entry, index) => (
          <li key={entry.name} className="flex items-center justify-between gap-3 text-sm">
            <span className="flex items-center gap-2">
              <span
                className="inline-block h-2.5 w-2.5 rounded-full"
                style={{ background: COLORS[index % COLORS.length] }}
              />
              {entry.name}
            </span>
            <span className="font-medium tabular-nums text-muted-foreground">{entry.value}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}
