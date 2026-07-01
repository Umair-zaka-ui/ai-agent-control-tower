import type { KpiMetric } from '../types'
import { KpiGrid } from './KpiGrid'

/** High-level executive subset (no operational detail) — SRS §Executive Dashboard. */
const EXECUTIVE_KEYS = [
  'total_agents',
  'active_agents',
  'success_rate',
  'avg_risk_score',
  'compliance_score',
  'total_policies',
]

export function ExecutiveCards({ kpis, loading }: { kpis?: KpiMetric[]; loading?: boolean }) {
  return <KpiGrid kpis={kpis} loading={loading} only={EXECUTIVE_KEYS} count={6} />
}
