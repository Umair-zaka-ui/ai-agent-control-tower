import { memo } from 'react'

import { EmptyState } from '@/components/common/EmptyState'
import { cn } from '@/utils/cn'
import type { RiskHeatmapRow } from '../types'

const BANDS: { key: keyof Omit<RiskHeatmapRow, 'label'>; label: string; base: string }[] = [
  { key: 'low', label: 'Low', base: '22 163 74' }, // green-600
  { key: 'medium', label: 'Medium', base: '202 138 4' }, // yellow-600
  { key: 'high', label: 'High', base: '234 88 12' }, // orange-600
  { key: 'critical', label: 'Critical', base: '220 38 38' }, // red-600
]

/** Colour-intensity risk matrix: agent type × risk band (SRS §Risk Heatmap). */
export const RiskHeatmap = memo(function RiskHeatmap({ rows }: { rows: RiskHeatmapRow[] }) {
  if (rows.length === 0) {
    return <EmptyState title="No risk data" description="Risk distribution will appear as agents act." />
  }
  // Max cell value across the matrix drives colour intensity.
  const max = Math.max(
    1,
    ...rows.flatMap((r) => BANDS.map((b) => r[b.key])),
  )

  return (
    <div className="overflow-x-auto">
      <table className="w-full border-separate border-spacing-1 text-sm">
        <thead>
          <tr>
            <th className="px-2 py-1 text-left text-xs font-medium text-muted-foreground">Agent Type</th>
            {BANDS.map((b) => (
              <th key={b.key} className="px-2 py-1 text-center text-xs font-medium text-muted-foreground">
                {b.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.label}>
              <td className="px-2 py-1 text-left font-medium">{row.label}</td>
              {BANDS.map((b) => {
                const value = row[b.key]
                const intensity = value === 0 ? 0 : 0.15 + (value / max) * 0.75
                return (
                  <td
                    key={b.key}
                    className={cn(
                      'rounded px-2 py-2 text-center tabular-nums',
                      value === 0 ? 'text-muted-foreground/50' : 'font-medium text-white',
                    )}
                    style={value === 0 ? undefined : { backgroundColor: `rgb(${b.base} / ${intensity})` }}
                    title={`${row.label} · ${b.label}: ${value}`}
                  >
                    {value}
                  </td>
                )
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
})
