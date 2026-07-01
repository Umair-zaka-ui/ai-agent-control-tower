import { Lightbulb, TrendingDown, TrendingUp } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'

import { Skeleton } from '@/components/ui/skeleton'
import { cn } from '@/utils/cn'
import type { Insight } from '../types'

const TONE: Record<Insight['tone'], { icon: LucideIcon; ring: string; text: string }> = {
  positive: { icon: TrendingDown, ring: 'border-success/30 bg-success/5', text: 'text-success' },
  negative: { icon: TrendingUp, ring: 'border-destructive/30 bg-destructive/5', text: 'text-destructive' },
  neutral: { icon: Lightbulb, ring: 'border-border bg-muted/30', text: 'text-primary' },
}

/** Rule-based AI insights (SRS §AI Insights Panel / §InsightsPanel). */
export function InsightsPanel({ insights, loading }: { insights?: Insight[]; loading?: boolean }) {
  if (loading || !insights) {
    return (
      <div className="space-y-2">
        {Array.from({ length: 3 }).map((_, i) => (
          <Skeleton key={i} className="h-16 w-full" />
        ))}
      </div>
    )
  }
  if (insights.length === 0) {
    return (
      <p className="py-8 text-center text-sm text-muted-foreground">
        Analytics will appear as AI agents begin processing work.
      </p>
    )
  }
  return (
    <ul className="space-y-2">
      {insights.map((insight) => {
        const tone = TONE[insight.tone] ?? TONE.neutral
        const Icon = tone.icon
        return (
          <li key={insight.id} className={cn('flex gap-3 rounded-md border p-3', tone.ring)}>
            <Icon className={cn('mt-0.5 h-4 w-4 shrink-0', tone.text)} aria-hidden />
            <div className="min-w-0">
              <p className="text-sm font-medium text-foreground">{insight.title}</p>
              <p className="text-xs text-muted-foreground">{insight.detail}</p>
            </div>
          </li>
        )
      })}
    </ul>
  )
}
