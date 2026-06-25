import { ShieldCheck } from 'lucide-react'

import { cn } from '@/utils/cn'

interface LogoProps {
  className?: string
  /** Hide the wordmark and show only the mark (collapsed sidebar). */
  compact?: boolean
}

/** Brand lockup for the AI Agent Control Tower. */
export function Logo({ className, compact = false }: LogoProps) {
  return (
    <div className={cn('flex items-center gap-2', className)}>
      <span className="flex h-8 w-8 items-center justify-center rounded-md bg-primary/15 text-primary">
        <ShieldCheck className="h-5 w-5" aria-hidden />
      </span>
      {!compact && (
        <span className="flex flex-col leading-tight">
          <span className="text-sm font-semibold text-foreground">Control Tower</span>
          <span className="text-[11px] text-muted-foreground">AI Governance</span>
        </span>
      )}
    </div>
  )
}
