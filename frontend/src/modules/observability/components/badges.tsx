import { Badge } from '@/components/ui'
import { CircleHelp, ShieldAlert } from 'lucide-react'

/**
 * Phase 4.9 — truthful state rendering (M4-4.9-FR-023, §10, §28).
 *
 * The single rule: **never let an unsafe / unproven / disabled state look
 * safe.** A burned error budget, a governance STOP, an active kill switch, a
 * degraded exporter, `INSUFFICIENT_DATA`, a `DISABLED` capture mode — each is
 * rendered as what it is, never smoothed to neutral and never disguised as an
 * error. Nothing here computes state; every value arrives decided by the
 * server.
 */

type Variant = 'default' | 'secondary' | 'success' | 'warning' | 'destructive' | 'outline'

const ALERT_SEVERITY: Record<string, Variant> = {
  INFO: 'secondary', WARNING: 'warning', HIGH: 'destructive', CRITICAL: 'destructive',
}
const ALERT_STATUS: Record<string, Variant> = {
  OPEN: 'destructive', ACKNOWLEDGED: 'warning', RESOLVED: 'success', SUPPRESSED: 'outline',
}
const DECISION: Record<string, Variant> = {
  ALLOW: 'success', CHALLENGE: 'warning', DENY: 'destructive', STOP: 'destructive',
}
const SLO_STATE: Record<string, Variant> = {
  MET: 'success', BREACHED: 'destructive', INSUFFICIENT_DATA: 'warning', UNKNOWN: 'warning',
}
const FINDING_STATE: Record<string, Variant> = {
  NORMAL: 'success', HEALTHY: 'success', DEGRADED: 'warning',
  ANOMALOUS: 'destructive', UNHEALTHY: 'destructive',
  INSUFFICIENT_DATA: 'warning', UNKNOWN: 'warning',
}
const CAPTURE_MODE: Record<string, Variant> = {
  DISABLED: 'outline', METADATA_ONLY: 'secondary',
  REDACTED_CONTENT: 'warning', FULL_CONTENT: 'destructive',
}

function plain(v: string | null | undefined): string {
  return (v ?? '—').replace(/_/g, ' ')
}

export function AlertSeverityBadge({ value }: { value: string }) {
  return <Badge variant={ALERT_SEVERITY[value] ?? 'outline'}>{value}</Badge>
}

export function AlertStatusBadge({ value }: { value: string }) {
  return <Badge variant={ALERT_STATUS[value] ?? 'outline'}>{plain(value)}</Badge>
}

export function DecisionBadge({ value }: { value: string }) {
  return <Badge variant={DECISION[value] ?? 'outline'}>{value}</Badge>
}

export function SloStateBadge({ value }: { value: string | null | undefined }) {
  if (!value) return <span className="text-muted-foreground">not evaluated</span>
  const insufficient = value === 'INSUFFICIENT_DATA' || value === 'UNKNOWN'
  return (
    <Badge
      variant={SLO_STATE[value] ?? 'outline'}
      title={insufficient ? 'Not enough samples to judge the objective. This is not "met".' : undefined}
    >
      {insufficient ? <CircleHelp className="mr-1 h-3 w-3" aria-hidden /> : null}
      {plain(value)}
    </Badge>
  )
}

export function FindingStateBadge({ value }: { value: string }) {
  const insufficient = value === 'INSUFFICIENT_DATA' || value === 'UNKNOWN'
  return (
    <Badge
      variant={FINDING_STATE[value] ?? 'outline'}
      title={insufficient ? 'Not enough data to draw a conclusion — shown as such, never as "fine".' : undefined}
    >
      {insufficient ? <CircleHelp className="mr-1 h-3 w-3" aria-hidden /> : null}
      {plain(value)}
    </Badge>
  )
}

export function CaptureModeBadge({ value }: { value: string }) {
  return <Badge variant={CAPTURE_MODE[value] ?? 'outline'}>{plain(value)}</Badge>
}

/** The error-budget bar. Over 100% consumed reads destructive and is labelled "spent". */
export function ErrorBudgetBar({ consumed }: { consumed: number | null | undefined }) {
  if (consumed === null || consumed === undefined) {
    return <span className="text-xs text-muted-foreground">no budget data</span>
  }
  const pct = Math.round(consumed * 100)
  const spent = consumed >= 1
  return (
    <div className="min-w-[7rem]">
      <div className="h-2 w-full overflow-hidden rounded-full bg-muted">
        <div
          className={spent ? 'h-full bg-destructive' : consumed > 0.75 ? 'h-full bg-warning' : 'h-full bg-success'}
          style={{ width: `${Math.min(pct, 100)}%` }}
        />
      </div>
      <p className={spent ? 'mt-1 text-xs font-medium text-destructive' : 'mt-1 text-xs text-muted-foreground'}>
        {spent ? `budget spent (${pct}%)` : `${pct}% consumed`}
      </p>
    </div>
  )
}

export function ExporterHealthBadge({ degraded, lastError }: { degraded: boolean; lastError: string | null }) {
  if (!degraded) return <Badge variant="success">exporter healthy</Badge>
  return (
    <Badge variant="warning" title={lastError ?? undefined}>
      <ShieldAlert className="mr-1 h-3 w-3" aria-hidden />
      exporter degraded
    </Badge>
  )
}
