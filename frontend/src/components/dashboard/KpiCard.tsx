import type { LucideIcon } from 'lucide-react'
import { TrendingDown, TrendingUp } from 'lucide-react'

import { Card, CardContent } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { cn } from '@/utils/cn'

export type KpiAccent = 'blue' | 'green' | 'orange' | 'red'

const ACCENT_CLASS: Record<KpiAccent, string> = {
  blue: 'bg-primary/15 text-primary',
  green: 'bg-success/15 text-success',
  orange: 'bg-warning/15 text-warning',
  red: 'bg-destructive/15 text-destructive',
}

export interface KpiCardProps {
  title: string
  value: number | string
  icon: LucideIcon
  accent?: KpiAccent
  trend?: string
  trendDirection?: 'up' | 'down'
  loading?: boolean
  /** When provided, the card is clickable and navigates / acts on activation. */
  onClick?: () => void
}

/** Reusable KPI tile with icon, value, optional trend and loading skeleton. */
export function KpiCard({
  title,
  value,
  icon: Icon,
  accent = 'blue',
  trend,
  trendDirection,
  loading,
  onClick,
}: KpiCardProps) {
  const interactive = Boolean(onClick)
  const TrendIcon = trendDirection === 'down' ? TrendingDown : TrendingUp

  const content = (
    <CardContent className="flex items-center justify-between p-6">
      <div className="space-y-1">
        <p className="text-sm text-muted-foreground">{title}</p>
        {loading ? (
          <Skeleton className="h-8 w-16" />
        ) : (
          <p className="text-2xl font-semibold tracking-tight text-foreground">{value}</p>
        )}
        {trend && !loading ? (
          <p
            className={cn(
              'flex items-center gap-1 text-xs',
              trendDirection === 'down' ? 'text-destructive' : 'text-success',
            )}
          >
            <TrendIcon className="h-3 w-3" />
            {trend}
          </p>
        ) : null}
      </div>
      <span className={cn('flex h-11 w-11 items-center justify-center rounded-lg', ACCENT_CLASS[accent])}>
        <Icon className="h-5 w-5" aria-hidden />
      </span>
    </CardContent>
  )

  if (interactive) {
    return (
      <Card
        role="button"
        tabIndex={0}
        aria-label={`${title}: ${value}`}
        onClick={onClick}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault()
            onClick?.()
          }
        }}
        className="cursor-pointer outline-none transition-colors hover:border-primary/50 focus-visible:ring-2 focus-visible:ring-ring"
      >
        {content}
      </Card>
    )
  }

  return <Card>{content}</Card>
}
