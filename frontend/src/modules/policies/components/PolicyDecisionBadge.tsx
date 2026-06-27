import { Badge } from '@/components/ui/badge'
import type { PolicyDecision } from '../types'

const DECISION: Record<PolicyDecision, { label: string; variant: 'success' | 'destructive' | 'warning' }> =
  {
    ALLOW: { label: 'Allow', variant: 'success' },
    BLOCK: { label: 'Block', variant: 'destructive' },
    PENDING_APPROVAL: { label: 'Pending Approval', variant: 'warning' },
  }

export function PolicyDecisionBadge({ decision }: { decision: PolicyDecision }) {
  const { label, variant } = DECISION[decision] ?? { label: decision ?? 'Unknown', variant: 'secondary' as const }
  return <Badge variant={variant}>{label}</Badge>
}
