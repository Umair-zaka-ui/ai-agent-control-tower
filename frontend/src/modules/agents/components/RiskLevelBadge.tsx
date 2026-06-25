import { Badge } from '@/components/ui/badge'
import type { RiskLevel } from '../types'

const RISK: Record<RiskLevel, { label: string; variant: 'success' | 'warning' | 'destructive' }> = {
  LOW: { label: 'Low', variant: 'success' },
  MEDIUM: { label: 'Medium', variant: 'warning' },
  HIGH: { label: 'High', variant: 'destructive' },
  CRITICAL: { label: 'Critical', variant: 'destructive' },
}

/** Colour-coded badge for an agent's configured risk level. */
export function RiskLevelBadge({ level }: { level: RiskLevel }) {
  const { label, variant } = RISK[level]
  return <Badge variant={variant}>{label}</Badge>
}
