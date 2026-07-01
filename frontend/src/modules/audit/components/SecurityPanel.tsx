import { Ban, KeyRound, LockKeyhole, ShieldAlert, ShieldX, UserX } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'

import { Card } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { cn } from '@/utils/cn'
import { formatNumber } from '@/utils/format'
import type { AuditSecuritySummary } from '../types'

interface SecurityMetric {
  label: string
  value: number
  icon: LucideIcon
  tone: string
}

function buildMetrics(s: AuditSecuritySummary): SecurityMetric[] {
  return [
    { label: 'Failed Logins', value: s.failed_logins, icon: LockKeyhole, tone: 'text-amber-600 dark:text-amber-400' },
    { label: 'Blocked Agents', value: s.blocked_agents, icon: Ban, tone: 'text-destructive' },
    { label: 'Disabled API Keys', value: s.disabled_api_keys, icon: KeyRound, tone: 'text-amber-600 dark:text-amber-400' },
    { label: 'Permission Violations', value: s.permission_violations, icon: UserX, tone: 'text-destructive' },
    { label: 'Suspicious Activity', value: s.suspicious_activity, icon: ShieldX, tone: 'text-destructive' },
    { label: 'Critical Alerts', value: s.critical_alerts, icon: ShieldAlert, tone: 'text-destructive' },
  ]
}

/** Security metric cards (SRS §Security Dashboard, §SecurityPanel). */
export function SecurityPanel({
  summary,
  loading,
}: {
  summary?: AuditSecuritySummary
  loading?: boolean
}) {
  if (loading || !summary) {
    return (
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
        {Array.from({ length: 6 }).map((_, i) => (
          <Card key={i} className="p-4">
            <Skeleton className="h-4 w-20" />
            <Skeleton className="mt-3 h-7 w-12" />
          </Card>
        ))}
      </div>
    )
  }

  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
      {buildMetrics(summary).map((m) => {
        const Icon = m.icon
        return (
          <Card key={m.label} className="flex flex-col gap-2 p-4">
            <div className="flex items-center justify-between">
              <span className="text-xs font-medium text-muted-foreground">{m.label}</span>
              <Icon className={cn('h-4 w-4', m.tone)} aria-hidden />
            </div>
            <span className="text-2xl font-semibold tabular-nums">{formatNumber(m.value)}</span>
          </Card>
        )
      })}
    </div>
  )
}
