import type { ReactNode } from 'react'
import { CheckCircle2, CircleHelp, ShieldAlert } from 'lucide-react'

import { Badge } from '@/components/ui'
import type { ReleaseHealth } from '@/services/operationsService'
import type { Blocker } from './format'

/**
 * Phase 3.10 — truthful state rendering (M3-3.10-FR-022, §10).
 *
 * The single rule this file exists to enforce: **never let an unsafe release
 * look safe.** The Operations Center's whole value is that an operator can
 * trust what it shows at 3am, and the failure mode that would destroy that is
 * not a crash — it is a reassuring grey badge on a deployment that is actually
 * killed, blocked, or unproven.
 *
 * So three things are deliberate here:
 *
 * 1. `INSUFFICIENT_DATA` and `UNKNOWN` render as a *warning*, never as neutral.
 *    Phase 3.5 established that the absence of evidence is never evidence of
 *    health; a UI that greyed them out would quietly undo that.
 * 2. A kill switch outranks everything else on the row. It is not one badge
 *    among several — it is the answer to "can I ship this?", and it is shown
 *    first.
 * 3. Nothing here computes state. `servable`, `is_proving` and
 *    `kill_switch_active` all arrive decided by the server, because the browser
 *    deriving its own opinion is how a UI ends up disagreeing with the engine
 *    it is supposed to be a window onto.
 */

type Variant = 'default' | 'secondary' | 'success' | 'warning' | 'destructive' | 'outline'

/** The deployment lifecycle states, mapped to how alarming each one is. */
const LIFECYCLE_VARIANT: Record<string, Variant> = {
  DRAFT: 'outline',
  VALIDATING: 'secondary',
  READY: 'secondary',
  DEPLOYING: 'default',
  ACTIVE: 'success',
  DEGRADED: 'warning',
  PAUSED: 'warning',
  ROLLING_BACK: 'destructive',
  SUPERSEDED: 'outline',
  RETIRED: 'outline',
  FAILED: 'destructive',
}

const ROLLOUT_VARIANT: Record<string, Variant> = {
  PENDING: 'secondary',
  IN_PROGRESS: 'default',
  PAUSED: 'warning',
  SUCCEEDED: 'success',
  ABORTED: 'outline',
  ROLLBACK_REQUESTED: 'destructive',
  FAILED: 'destructive',
}

const GATE_VARIANT: Record<string, Variant> = {
  PASS: 'success',
  WARNING: 'warning',
  BLOCK: 'destructive',
}

export function LifecycleBadge({ state }: { state: string | null | undefined }) {
  if (!state) return <span className="text-muted-foreground">—</span>
  return <Badge variant={LIFECYCLE_VARIANT[state] ?? 'outline'}>{state}</Badge>
}

export function RolloutStateBadge({ state }: { state: string | null | undefined }) {
  if (!state) return <span className="text-muted-foreground">—</span>
  return <Badge variant={ROLLOUT_VARIANT[state] ?? 'outline'}>{state.replace(/_/g, ' ')}</Badge>
}

/**
 * A release-gate verdict. `BLOCK` is destructive and never softened — §10
 * forbids presenting a blocked release as deployable.
 */
export function GateBadge({ verdict }: { verdict: string | null | undefined }) {
  if (!verdict) {
    return (
      <Badge variant="outline" title="No preflight has been run for this deployment yet">
        NOT EVALUATED
      </Badge>
    )
  }
  return <Badge variant={GATE_VARIANT[verdict] ?? 'outline'}>{verdict}</Badge>
}

/**
 * Release health. The important branch is the third one: a verdict that does
 * not *prove* anything is shown as a warning with an explicit label, not as a
 * quiet neutral state.
 */
export function HealthBadge({ health }: { health: ReleaseHealth | null | undefined }) {
  if (!health) {
    return (
      <Badge variant="outline" title="No health evaluation recorded yet">
        NOT EVALUATED
      </Badge>
    )
  }
  if (!health.is_proving) {
    return (
      <Badge
        variant="warning"
        title={`${health.health_state} — ${health.sample_count} sample(s). The absence of evidence is not evidence of health.`}
      >
        <CircleHelp className="mr-1 h-3 w-3" aria-hidden />
        {health.health_state.replace(/_/g, ' ')}
      </Badge>
    )
  }
  const variant: Variant =
    health.health_state === 'HEALTHY' ? 'success'
      : health.health_state === 'DEGRADED' ? 'warning' : 'destructive'
  return (
    <Badge variant={variant} title={`${health.sample_count} sample(s) observed`}>
      {health.health_state}
    </Badge>
  )
}

/** The kill switch, shown before anything else on a row it applies to. */
export function KillSwitchBadge({ active }: { active: boolean }) {
  if (!active) return null
  return (
    <Badge variant="destructive" title="A kill switch is active on this agent. No automation will activate this version.">
      <ShieldAlert className="mr-1 h-3 w-3" aria-hidden />
      KILL SWITCH
    </Badge>
  )
}

export function ServingBadge({ servable, weight }: { servable: boolean; weight: number | null }) {
  if (!servable) {
    return (
      <Badge variant="outline" title="Not servable: the version resolver will not route to this deployment.">
        NOT SERVING
      </Badge>
    )
  }
  return (
    <Badge variant="success">
      {weight === null || weight === undefined ? 'SERVING' : `${weight}%`}
    </Badge>
  )
}

/** A compact inline list of a row's blockers, for table cells. */
export function BlockerChips({ blockers }: { blockers: Blocker[] }): ReactNode {
  if (blockers.length === 0) {
    return (
      <span className="inline-flex items-center gap-1 text-xs text-success">
        <CheckCircle2 className="h-3.5 w-3.5" aria-hidden />
        Clear
      </span>
    )
  }
  return (
    <div className="flex flex-wrap gap-1">
      {blockers.map((b) => (
        <Badge key={b.label} variant={b.tone} title={b.detail}>
          <b.icon className="mr-1 h-3 w-3" aria-hidden />
          {b.label}
        </Badge>
      ))}
    </div>
  )
}

/** A full-width banner for the detail view — the same facts, harder to miss. */
export function BlockerBanner({ blockers }: { blockers: Blocker[] }) {
  if (blockers.length === 0) return null
  const worst = blockers.some((b) => b.tone === 'destructive') ? 'destructive' : 'warning'
  return (
    <div
      role="alert"
      className={
        worst === 'destructive'
          ? 'rounded-xl border border-destructive/30 bg-destructive/10 p-4'
          : 'rounded-xl border border-warning/30 bg-warning/10 p-4'
      }
    >
      <ul className="space-y-2">
        {blockers.map((b) => (
          <li key={b.label} className="flex items-start gap-2 text-sm">
            <b.icon
              className={worst === 'destructive' ? 'mt-0.5 h-4 w-4 shrink-0 text-destructive' : 'mt-0.5 h-4 w-4 shrink-0 text-warning'}
              aria-hidden
            />
            <span>
              <span className="font-medium text-foreground">{b.label}.</span>{' '}
              <span className="text-muted-foreground">{b.detail}</span>
            </span>
          </li>
        ))}
      </ul>
    </div>
  )
}
