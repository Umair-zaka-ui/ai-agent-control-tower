import { cn } from '@/utils/cn'
import { riskLevel } from '../utils/format'

/** Colour-coded 0–100 risk score chip. */
export function RiskBadge({ score, showLabel = false }: { score: number; showLabel?: boolean }) {
  const level = riskLevel(score)
  const tone = {
    Low: 'bg-success/15 text-success',
    Moderate: 'bg-warning/15 text-warning',
    High: 'bg-orange-500/15 text-orange-600 dark:text-orange-400',
    Critical: 'bg-destructive/15 text-destructive',
  }[level]

  return (
    <span
      className={cn(
        'inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-semibold tabular-nums',
        tone,
      )}
      title={`${level} risk`}
    >
      {score}
      {showLabel ? <span className="font-normal">· {level}</span> : null}
    </span>
  )
}
