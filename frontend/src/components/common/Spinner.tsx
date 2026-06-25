import { Loader2 } from 'lucide-react'

import { cn } from '@/utils/cn'

interface SpinnerProps {
  className?: string
  label?: string
}

/** Inline loading spinner. */
export function Spinner({ className, label }: SpinnerProps) {
  return (
    <span className="inline-flex items-center gap-2 text-muted-foreground" role="status">
      <Loader2 className={cn('h-4 w-4 animate-spin', className)} aria-hidden />
      {label ? <span className="text-sm">{label}</span> : null}
      <span className="sr-only">Loading</span>
    </span>
  )
}

/** Full-area centered loader for route/page suspense fallbacks. */
export function FullPageSpinner({ label = 'Loading…' }: { label?: string }) {
  return (
    <div className="flex h-full min-h-[60vh] w-full items-center justify-center">
      <Spinner className="h-6 w-6" label={label} />
    </div>
  )
}
