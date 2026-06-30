import { Badge, type BadgeProps } from '@/components/ui/badge'
import type { AuditSeverity } from '../types'

const SEVERITY: Record<AuditSeverity, { label: string; variant: BadgeProps['variant'] }> = {
  INFO: { label: 'Info', variant: 'secondary' },
  LOW: { label: 'Low', variant: 'outline' },
  MEDIUM: { label: 'Medium', variant: 'warning' },
  HIGH: { label: 'High', variant: 'destructive' },
  CRITICAL: { label: 'Critical', variant: 'destructive' },
}

export function EventSeverityBadge({ severity }: { severity: AuditSeverity }) {
  const meta = SEVERITY[severity] ?? { label: severity ?? 'Unknown', variant: 'secondary' as const }
  // CRITICAL gets a stronger, solid treatment to stand apart from HIGH.
  if (severity === 'CRITICAL') {
    return (
      <Badge variant="destructive" className="border-transparent bg-destructive text-destructive-foreground">
        {meta.label}
      </Badge>
    )
  }
  return <Badge variant={meta.variant}>{meta.label}</Badge>
}
