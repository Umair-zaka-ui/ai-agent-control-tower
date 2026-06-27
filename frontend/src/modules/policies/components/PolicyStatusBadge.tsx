import { Badge } from '@/components/ui/badge'
import type { PolicyStatus } from '../types'

const STATUS: Record<PolicyStatus, { label: string; variant: 'success' | 'secondary' | 'default' | 'destructive' }> =
  {
    ENABLED: { label: 'Enabled', variant: 'success' },
    DISABLED: { label: 'Disabled', variant: 'secondary' },
    DRAFT: { label: 'Draft', variant: 'default' },
    ARCHIVED: { label: 'Archived', variant: 'destructive' },
  }

export function PolicyStatusBadge({ status }: { status: PolicyStatus }) {
  const { label, variant } = STATUS[status] ?? { label: status ?? 'Unknown', variant: 'secondary' as const }
  return <Badge variant={variant}>{label}</Badge>
}
