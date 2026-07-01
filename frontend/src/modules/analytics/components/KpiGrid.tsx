import { useNavigate } from 'react-router-dom'
import {
  Activity,
  BadgeCheck,
  Bot,
  CheckSquare,
  Gauge,
  ShieldAlert,
  ShieldCheck,
  Timer,
  TrendingDown,
  TrendingUp,
  Zap,
} from 'lucide-react'
import type { LucideIcon } from 'lucide-react'

import { Card } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { ROUTES } from '@/constants/routes'
import { cn } from '@/utils/cn'
import type { KpiMetric } from '../types'
import { formatKpiValue, isPositiveTrend } from '../utils/format'
import { useCountUp } from './useCountUp'

interface KpiMeta {
  icon: LucideIcon
  accent: string
  to: string
}

const META: Record<string, KpiMeta> = {
  total_agents: { icon: Bot, accent: 'text-primary', to: `${ROUTES.ANALYTICS}/agents` },
  active_agents: { icon: Activity, accent: 'text-success', to: `${ROUTES.ANALYTICS}/agents` },
  actions_today: { icon: Zap, accent: 'text-primary', to: `${ROUTES.ANALYTICS}/operations` },
  approvals_today: { icon: CheckSquare, accent: 'text-purple-500', to: `${ROUTES.ANALYTICS}/operations` },
  success_rate: { icon: TrendingUp, accent: 'text-success', to: `${ROUTES.ANALYTICS}/performance` },
  failure_rate: { icon: TrendingDown, accent: 'text-destructive', to: `${ROUTES.ANALYTICS}/performance` },
  avg_risk_score: { icon: ShieldAlert, accent: 'text-warning', to: `${ROUTES.ANALYTICS}/risk` },
  avg_decision_time: { icon: Timer, accent: 'text-primary', to: `${ROUTES.ANALYTICS}/performance` },
  total_policies: { icon: ShieldCheck, accent: 'text-indigo-500', to: `${ROUTES.ANALYTICS}/policies` },
  compliance_score: { icon: BadgeCheck, accent: 'text-success', to: `${ROUTES.ANALYTICS}/executive` },
}

function KpiTile({ metric }: { metric: KpiMetric }) {
  const navigate = useNavigate()
  const meta = META[metric.key] ?? { icon: Gauge, accent: 'text-primary', to: ROUTES.ANALYTICS }
  const Icon = meta.icon
  const animated = useCountUp(metric.value)
  const display =
    metric.unit === '' && Number.isInteger(metric.value)
      ? new Intl.NumberFormat('en-US').format(Math.round(animated))
      : formatKpiValue({ ...metric, value: Number(animated.toFixed(metric.unit === '%' ? 1 : 0)) })

  const positive = isPositiveTrend(metric)
  const TrendIcon = metric.direction === 'down' ? TrendingDown : TrendingUp

  return (
    <Card
      role="button"
      tabIndex={0}
      aria-label={`${metric.label}: ${formatKpiValue(metric)}`}
      onClick={() => navigate(meta.to)}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault()
          navigate(meta.to)
        }
      }}
      className="flex cursor-pointer flex-col gap-2 p-4 outline-none transition-colors hover:border-primary/50 focus-visible:ring-2 focus-visible:ring-ring"
    >
      <div className="flex items-center justify-between">
        <span className="text-xs font-medium text-muted-foreground">
          {metric.label}
          {metric.estimated ? ' *' : ''}
        </span>
        <Icon className={cn('h-4 w-4', meta.accent)} aria-hidden />
      </div>
      <span className="text-2xl font-semibold tabular-nums">{display}</span>
      {metric.change_pct != null && metric.direction !== 'flat' ? (
        <span
          className={cn(
            'inline-flex items-center gap-1 text-xs',
            positive ? 'text-success' : 'text-destructive',
          )}
        >
          <TrendIcon className="h-3 w-3" aria-hidden />
          {Math.abs(metric.change_pct)}% vs prev
        </span>
      ) : (
        <span className="text-xs text-muted-foreground">—</span>
      )}
    </Card>
  )
}

interface KpiGridProps {
  kpis?: KpiMetric[]
  loading?: boolean
  /** Optional subset of KPI keys to render (e.g. executive view). */
  only?: string[]
  count?: number
}

/** Executive KPI grid (SRS §Executive KPI Cards / §KpiGrid). */
export function KpiGrid({ kpis, loading, only, count = 10 }: KpiGridProps) {
  if (loading || !kpis) {
    return (
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
        {Array.from({ length: count }).map((_, i) => (
          <Card key={i} className="p-4">
            <Skeleton className="h-4 w-20" />
            <Skeleton className="mt-3 h-7 w-12" />
          </Card>
        ))}
      </div>
    )
  }
  const items = only ? kpis.filter((k) => only.includes(k.key)) : kpis
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
      {items.map((k) => (
        <KpiTile key={k.key} metric={k} />
      ))}
    </div>
  )
}
