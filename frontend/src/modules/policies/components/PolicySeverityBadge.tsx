import { Badge } from '@/components/ui/badge'
import type { PolicySeverity } from '../types'

const SEVERITY: Record<PolicySeverity, { label: string; variant: 'success' | 'warning' | 'destructive' }> =
  {
    LOW: { label: 'Low', variant: 'success' },
    MEDIUM: { label: 'Medium', variant: 'warning' },
    HIGH: { label: 'High', variant: 'destructive' },
    CRITICAL: { label: 'Critical', variant: 'destructive' },
  }

export function PolicySeverityBadge({ severity }: { severity: PolicySeverity }) {
  const { label, variant } = SEVERITY[severity] ?? { label: severity ?? 'Unknown', variant: 'secondary' as const }
  return <Badge variant={variant}>{label}</Badge>
}
