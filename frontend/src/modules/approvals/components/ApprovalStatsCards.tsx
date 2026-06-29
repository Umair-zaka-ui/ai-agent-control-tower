import { CheckCircle2, Clock, Hourglass, TrendingUp, XCircle } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'

import { Card } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { cn } from '@/utils/cn'
import type { ApprovalStatistics } from '../types'
import { formatDuration } from '../utils/format'

interface StatCard {
  label: string
  value: string
  icon: LucideIcon
  tone: string
}

function buildCards(stats: ApprovalStatistics): StatCard[] {
  return [
    {
      label: 'Pending',
      value: String(stats.pending),
      icon: Clock,
      tone: 'text-warning',
    },
    {
      label: 'Approved Today',
      value: String(stats.approved_today),
      icon: CheckCircle2,
      tone: 'text-success',
    },
    {
      label: 'Rejected Today',
      value: String(stats.rejected_today),
      icon: XCircle,
      tone: 'text-destructive',
    },
    {
      label: 'Escalated',
      value: String(stats.escalated),
      icon: Hourglass,
      tone: 'text-purple-600 dark:text-purple-400',
    },
    {
      label: 'Avg Review Time',
      value: formatDuration(stats.avg_review_seconds),
      icon: TrendingUp,
      tone: 'text-primary',
    },
  ]
}

/** The five statistics cards at the top of the approval dashboard. */
export function ApprovalStatsCards({
  stats,
  loading,
}: {
  stats?: ApprovalStatistics
  loading?: boolean
}) {
  if (loading || !stats) {
    return (
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
        {Array.from({ length: 5 }).map((_, i) => (
          <Card key={i} className="p-4">
            <Skeleton className="h-4 w-20" />
            <Skeleton className="mt-3 h-7 w-12" />
          </Card>
        ))}
      </div>
    )
  }

  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
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
