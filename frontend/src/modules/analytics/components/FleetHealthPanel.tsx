import { Ban, CircleCheck, CircleSlash, PauseCircle, TriangleAlert } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'

import { Card } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { cn } from '@/utils/cn'
import type { FleetHealth } from '../types'

interface HealthCard {
  label: string
  value: number
  icon: LucideIcon
  dot: string
  tone: string
}

function cards(f: FleetHealth): HealthCard[] {
  return [
    { label: 'Healthy', value: f.healthy, icon: CircleCheck, dot: 'bg-success', tone: 'text-success' },
    { label: 'Warning', value: f.warning, icon: TriangleAlert, dot: 'bg-warning', tone: 'text-warning' },
    { label: 'Offline', value: f.offline, icon: CircleSlash, dot: 'bg-orange-500', tone: 'text-orange-500' },
    { label: 'Blocked', value: f.blocked, icon: Ban, dot: 'bg-destructive', tone: 'text-destructive' },
    { label: 'Suspended', value: f.suspended, icon: PauseCircle, dot: 'bg-muted-foreground', tone: 'text-muted-foreground' },
  ]
}

/** AI fleet health cards (SRS §Fleet Health Dashboard / §FleetHealthPanel). */
export function FleetHealthPanel({ data, loading }: { data?: FleetHealth; loading?: boolean }) {
  if (loading || !data) {
    return (
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
        {Array.from({ length: 5 }).map((_, i) => (
          <Card key={i} className="p-4">
            <Skeleton className="h-4 w-20" />
            <Skeleton className="mt-3 h-7 w-10" />
          </Card>
        ))}
      </div>
    )
  }
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
      {cards(data).map((c) => {
        const Icon = c.icon
        return (
          <Card key={c.label} className="flex flex-col gap-2 p-4">
            <div className="flex items-center justify-between">
              <span className="inline-flex items-center gap-2 text-xs font-medium text-muted-foreground">
                <span className={cn('h-2 w-2 rounded-full', c.dot)} aria-hidden />
                {c.label}
              </span>
              <Icon className={cn('h-4 w-4', c.tone)} aria-hidden />
            </div>
            <span className="text-2xl font-semibold tabular-nums">{c.value}</span>
          </Card>
        )
      })}
    </div>
  )
}
