import { Cpu, Database, FileSearch, Gauge, Server, Users } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'

import { Card } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { cn } from '@/utils/cn'
import type { CostAnalytics } from '../types'
import { formatCurrency } from '../utils/format'

const ICONS: Record<string, LucideIcon> = {
  compute: Cpu,
  api: Server,
  llm: Gauge,
  human_review: Users,
  policy_eval: FileSearch,
  storage: Database,
}

/** Enterprise AI cost breakdown (SRS §Cost Dashboard / §CostBreakdownCard). */
export function CostBreakdownCard({ data, loading }: { data?: CostAnalytics; loading?: boolean }) {
  if (loading || !data) {
    return (
      <Card className="space-y-3 p-6">
        {Array.from({ length: 6 }).map((_, i) => (
          <Skeleton key={i} className="h-6 w-full" />
        ))}
      </Card>
    )
  }
  const max = Math.max(1, ...data.items.map((i) => i.amount))
  return (
    <Card className="space-y-4 p-6">
      <div className="flex items-baseline justify-between">
        <div>
          <p className="text-sm text-muted-foreground">Estimated total</p>
          <p className="text-3xl font-semibold tabular-nums">{formatCurrency(data.total, data.currency)}</p>
        </div>
        <span className="text-xs text-muted-foreground">{data.period_label}</span>
      </div>
      <ul className="space-y-3">
        {data.items.map((item) => {
          const Icon = ICONS[item.key] ?? Gauge
          return (
            <li key={item.key} className="space-y-1">
              <div className="flex items-center justify-between text-sm">
                <span className="inline-flex items-center gap-2">
                  <Icon className="h-4 w-4 text-muted-foreground" aria-hidden />
                  {item.label}
                </span>
                <span className="font-medium tabular-nums">{formatCurrency(item.amount, data.currency)}</span>
              </div>
              <div
                className="h-1.5 w-full overflow-hidden rounded-full bg-muted"
                role="progressbar"
                aria-valuenow={Math.round((item.amount / max) * 100)}
                aria-valuemin={0}
                aria-valuemax={100}
                aria-label={item.label}
              >
                <div
                  className={cn('h-full rounded-full bg-primary transition-all')}
                  style={{ width: `${(item.amount / max) * 100}%` }}
                />
              </div>
            </li>
          )
        })}
      </ul>
      {data.estimated ? (
        <p className="text-xs text-muted-foreground">
          * Estimated from activity volume — not billed usage.
        </p>
      ) : null}
    </Card>
  )
}
