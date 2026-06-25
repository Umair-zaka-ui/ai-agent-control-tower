import { cn } from '@/utils/cn'
import type { AgentHealth } from '../types'

const HEALTH: Record<AgentHealth, { label: string; dot: string; text: string }> = {
  HEALTHY: { label: 'Healthy', dot: 'bg-success', text: 'text-success' },
  WARNING: { label: 'Warning', dot: 'bg-warning', text: 'text-warning' },
  OFFLINE: { label: 'Offline', dot: 'bg-destructive', text: 'text-destructive' },
}

/** Status-dot health indicator for an agent. */
export function AgentHealthBadge({ health }: { health: AgentHealth }) {
  const { label, dot, text } = HEALTH[health]
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className={cn('h-2 w-2 rounded-full', dot)} aria-hidden />
      <span className={cn('text-sm font-medium', text)}>{label}</span>
    </span>
  )
}
