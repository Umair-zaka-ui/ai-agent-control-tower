import { useSystemHealth } from '@/hooks/useSystemHealth'
import { cn } from '@/utils/cn'
import type { ServiceHealth, SystemHealth } from '@/types'
import { WidgetCard } from './WidgetCard'

const STATUS: Record<ServiceHealth, { dot: string; label: string; text: string }> = {
  healthy: { dot: 'bg-success', label: 'Healthy', text: 'text-success' },
  warning: { dot: 'bg-warning', label: 'Warning', text: 'text-warning' },
  offline: { dot: 'bg-destructive', label: 'Offline', text: 'text-destructive' },
}

const SERVICES: { key: keyof SystemHealth; label: string }[] = [
  { key: 'api', label: 'API' },
  { key: 'database', label: 'Database' },
  { key: 'policy_engine', label: 'Policy Engine' },
  { key: 'approval_engine', label: 'Approval Engine' },
  { key: 'audit', label: 'Audit Engine' },
]

/** Subsystem health list (live: /system/health). */
export function SystemHealthWidget() {
  const { data, isLoading, isError, refetch } = useSystemHealth()

  return (
    <WidgetCard
      title="System Health"
      loading={isLoading}
      error={isError}
      onRetry={() => void refetch()}
    >
      <ul className="space-y-3">
        {SERVICES.map(({ key, label }) => {
          const value: ServiceHealth = data?.[key] ?? 'offline'
          const status = STATUS[value]
          return (
            <li key={key} className="flex items-center justify-between text-sm">
              <span className="text-muted-foreground">{label}</span>
              <span className="flex items-center gap-2">
                <span className={cn('h-2 w-2 rounded-full', status.dot)} aria-hidden />
                <span className={cn('font-medium', status.text)}>{status.label}</span>
              </span>
            </li>
          )
        })}
      </ul>
    </WidgetCard>
  )
}
