import type { KpiMetric } from '../types'

/** Chart palette (HSL strings) — consistent with the dashboard charts. */
export const CHART = {
  axis: 'hsl(215 20% 65%)',
  grid: 'hsl(215 28% 17%)',
  primary: 'hsl(221 83% 53%)',
  green: 'hsl(142 76% 36%)',
  yellow: 'hsl(48 96% 53%)',
  orange: 'hsl(25 95% 53%)',
  red: 'hsl(0 72% 51%)',
  purple: 'hsl(262 83% 58%)',
} as const

export const TOOLTIP_STYLE = {
  backgroundColor: 'hsl(222 47% 11%)',
  border: '1px solid hsl(215 28% 17%)',
  borderRadius: 8,
  color: 'hsl(210 40% 98%)',
  fontSize: 12,
} as const

/** Risk band → colour. */
export function riskColor(score: number): string {
  if (score <= 30) return CHART.green
  if (score <= 60) return CHART.yellow
  if (score <= 80) return CHART.orange
  return CHART.red
}

/** Format a KPI value with its unit (e.g. "98.2%", "240ms", "1,204"). */
export function formatKpiValue(metric: KpiMetric): string {
  const v = metric.value
  if (metric.unit === '%') return `${v}%`
  if (metric.unit === 'ms') return `${Math.round(v)}ms`
  if (metric.unit === 's') return `${Math.round(v)}s`
  return new Intl.NumberFormat('en-US').format(v)
}

/** A KPI is "good" when its direction aligns with positive_is_good. */
export function isPositiveTrend(metric: KpiMetric): boolean {
  if (metric.direction === 'flat') return true
  const up = metric.direction === 'up'
  return metric.positive_is_good ? up : !up
}

/** Human-readable duration from seconds, e.g. "2h 5m", "45s". */
export function formatSeconds(seconds: number | null | undefined): string {
  if (seconds == null || Number.isNaN(seconds)) return '—'
  if (seconds < 60) return `${Math.round(seconds)}s`
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `${minutes}m`
  const hours = Math.floor(minutes / 60)
  const rem = minutes % 60
  return rem ? `${hours}h ${rem}m` : `${hours}h`
}

export function formatCurrency(amount: number, currency = 'USD'): string {
  return new Intl.NumberFormat('en-US', { style: 'currency', currency }).format(amount)
}

/** Title-case a SCREAMING_SNAKE token. */
export function humanizeToken(value: string | null | undefined): string {
  if (!value) return '—'
  return value
    .toLowerCase()
    .split('_')
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(' ')
}
