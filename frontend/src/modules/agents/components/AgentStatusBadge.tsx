import { Badge } from '@/components/ui/badge'
import type { AgentStatus } from '../types'

const STATUS: Record<AgentStatus, { label: string; variant: 'success' | 'secondary' | 'warning' | 'destructive' }> =
  {
    ACTIVE: { label: 'Active', variant: 'success' },
    INACTIVE: { label: 'Inactive', variant: 'secondary' },
    SUSPENDED: { label: 'Suspended', variant: 'warning' },
    ARCHIVED: { label: 'Archived', variant: 'secondary' },
    BLOCKED: { label: 'Blocked', variant: 'destructive' },
  }

/** Colour-coded badge for an agent's lifecycle status. */
export function AgentStatusBadge({ status }: { status: AgentStatus }) {
  const { label, variant } = STATUS[status]
  return <Badge variant={variant}>{label}</Badge>
}
