import { Badge } from '@/components/ui/badge'
import type { Decision } from '@/types'

const VARIANT: Record<Decision, { label: string; variant: 'success' | 'destructive' | 'warning' }> =
  {
    ALLOW: { label: 'Allow', variant: 'success' },
    BLOCK: { label: 'Block', variant: 'destructive' },
    PENDING_APPROVAL: { label: 'Pending', variant: 'warning' },
  }

/** Colour-coded badge for an action decision (ALLOW/BLOCK/PENDING). */
export function DecisionBadge({ decision }: { decision: Decision }) {
  const { label, variant } = VARIANT[decision]
  return <Badge variant={variant}>{label}</Badge>
}
