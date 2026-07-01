import { RefreshCw } from 'lucide-react'

import { cn } from '@/utils/cn'

interface RefreshIndicatorProps {
  /** True while a background refetch is in flight. */
  refreshing?: boolean
  /** Auto-refresh cadence in seconds, shown as context. */
  everySeconds?: number
  onRefresh?: () => void
}

/** Live auto-refresh status pill (SRS §RefreshIndicator). */
export function RefreshIndicator({ refreshing, everySeconds, onRefresh }: RefreshIndicatorProps) {
  return (
    <button
      type="button"
      onClick={onRefresh}
      className="inline-flex items-center gap-2 rounded-full border border-border px-3 py-1 text-xs text-muted-foreground transition-colors hover:bg-muted/50"
      aria-label="Refresh analytics"
    >
      <span
        className={cn('h-2 w-2 rounded-full', refreshing ? 'bg-warning' : 'bg-success')}
        aria-hidden
      />
      <RefreshCw className={cn('h-3.5 w-3.5', refreshing && 'animate-spin')} aria-hidden />
      <span>
        {refreshing ? 'Updating…' : everySeconds ? `Live · ${everySeconds}s` : 'Live'}
      </span>
    </button>
  )
}
