import { Card } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { cn } from '@/utils/cn'
import type { AuditComplianceSummary, ComplianceMetric } from '../types'

function toneFor(status: string): { bar: string; text: string } {
  if (status === 'Ready') return { bar: 'bg-success', text: 'text-success' }
  if (status === 'In progress') return { bar: 'bg-warning', text: 'text-warning' }
  return { bar: 'bg-destructive', text: 'text-destructive' }
}

function MetricCard({ metric }: { metric: ComplianceMetric }) {
  const tone = toneFor(metric.status)
  return (
    <Card className="space-y-3 p-4">
      <div className="flex items-center justify-between">
        <span className="text-sm font-medium">{metric.label}</span>
        <span className={cn('text-xs font-semibold', tone.text)}>{metric.status}</span>
      </div>
      <div className="flex items-baseline gap-2">
        <span className="text-2xl font-semibold tabular-nums">{metric.score}%</span>
      </div>
      <div
        className="h-2 w-full overflow-hidden rounded-full bg-muted"
        role="progressbar"
        aria-valuenow={metric.score}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label={metric.label}
      >
        <div className={cn('h-full rounded-full transition-all', tone.bar)} style={{ width: `${metric.score}%` }} />
      </div>
      <p className="text-xs text-muted-foreground">{metric.detail}</p>
    </Card>
  )
}

/** Compliance posture cards with progress bars (SRS §Compliance Dashboard, §CompliancePanel). */
export function CompliancePanel({
  summary,
  loading,
}: {
  summary?: AuditComplianceSummary
  loading?: boolean
}) {
  if (loading || !summary) {
    return (
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {Array.from({ length: 6 }).map((_, i) => (
          <Card key={i} className="space-y-3 p-4">
            <Skeleton className="h-4 w-32" />
            <Skeleton className="h-7 w-16" />
            <Skeleton className="h-2 w-full" />
          </Card>
        ))}
      </div>
    )
  }

  const metrics: ComplianceMetric[] = [
    summary.hipaa_readiness,
    summary.soc2_readiness,
    summary.iso27001_controls,
    summary.policy_coverage,
    summary.approval_coverage,
    summary.audit_completeness,
  ]

  return (
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
      {metrics.map((m) => (
        <MetricCard key={m.label} metric={m} />
      ))}
    </div>
  )
}
