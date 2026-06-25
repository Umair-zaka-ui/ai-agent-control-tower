import type { LucideIcon } from 'lucide-react'

import { Card, CardContent } from '@/components/ui/card'
import { cn } from '@/utils/cn'

interface StatCardProps {
  label: string
  value: string | number
  icon: LucideIcon
  /** Optional supporting line under the value. */
  hint?: string
  accentClassName?: string
}

/** Compact KPI tile for the dashboard stats row. */
export function StatCard({ label, value, icon: Icon, hint, accentClassName }: StatCardProps) {
  return (
    <Card>
      <CardContent className="flex items-center justify-between p-6">
        <div className="space-y-1">
          <p className="text-sm text-muted-foreground">{label}</p>
          <p className="text-2xl font-semibold tracking-tight text-foreground">{value}</p>
          {hint ? <p className="text-xs text-muted-foreground">{hint}</p> : null}
        </div>
        <span
          className={cn(
            'flex h-11 w-11 items-center justify-center rounded-lg bg-primary/15 text-primary',
            accentClassName,
          )}
        >
          <Icon className="h-5 w-5" aria-hidden />
        </span>
      </CardContent>
    </Card>
  )
}
