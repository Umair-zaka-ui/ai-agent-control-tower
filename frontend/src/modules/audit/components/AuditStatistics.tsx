import { Activity, FileCheck2, KeyRound, LogIn, ShieldAlert, SlidersHorizontal } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'

import { Card } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { cn } from '@/utils/cn'
import { formatNumber } from '@/utils/format'
import type { AuditStatistics as AuditStatisticsData } from '../types'

interface StatCard {
  label: string
  value: string
  icon: LucideIcon
  tone: string
}

function buildCards(stats: AuditStatisticsData): StatCard[] {
  return [
    { label: 'Total Events', value: formatNumber(stats.total_events), icon: Activity, tone: 'text-primary' },
    {
      label: 'Security Events',
      value: formatNumber(stats.security_events),
      icon: ShieldAlert,
      tone: 'text-destructive',
    },
    {
      label: 'Policy Evaluations',
      value: formatNumber(stats.policy_evaluations),
      icon: FileCheck2,
      tone: 'text-indigo-600 dark:text-indigo-400',
    },
    {
      label: 'Approval Events',
      value: formatNumber(stats.approval_events),
      icon: SlidersHorizontal,
      tone: 'text-purple-600 dark:text-purple-400',
    },
    {
      label: 'Authentication',
      value: formatNumber(stats.authentication_events),
      icon: LogIn,
      tone: 'text-blue-600 dark:text-blue-400',
    },
    {
      label: 'Config Changes',
      value: formatNumber(stats.configuration_changes),
      icon: KeyRound,
      tone: 'text-amber-600 dark:text-amber-400',
    },
  ]
}

/** The six headline statistics cards on the audit dashboard (SRS §Statistics Cards). */
export function AuditStatistics({
  stats,
  loading,
}: {
  stats?: AuditStatisticsData
  loading?: boolean
}) {
  if (loading || !stats) {
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
      {buildCards(stats).map((card) => {
        const Icon = card.icon
        return (
          <Card key={card.label} className="flex flex-col gap-2 p-4">
            <div className="flex items-center justify-between">
              <span className="text-xs font-medium text-muted-foreground">{card.label}</span>
              <Icon className={cn('h-4 w-4', card.tone)} aria-hidden />
            </div>
            <span className="text-2xl font-semibold tabular-nums">{card.value}</span>
          </Card>
        )
      })}
    </div>
  )
}
