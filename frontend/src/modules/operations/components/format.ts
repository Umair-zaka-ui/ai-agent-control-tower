import type { LucideIcon } from 'lucide-react'
import { AlertOctagon, AlertTriangle, CircleHelp, PauseCircle, ShieldAlert } from 'lucide-react'

import type { OverviewRow } from '@/services/operationsService'

/**
 * Phase 3.10 — the non-visual half of truthful state.
 *
 * Split out of `state.tsx` so that file exports only components. The rule the
 * split serves is a build-tooling one (fast refresh), but the separation is
 * honest anyway: deciding *what counts as a blocker* is logic, and rendering a
 * badge is not.
 */
export interface Blocker {
  icon: LucideIcon
  tone: 'destructive' | 'warning'
  label: string
  detail: string
}

/**
 * Every reason a row is not safe to ship, most severe first.
 *
 * Deliberately returns *all* of them rather than the worst one. An operator
 * who clears a kill switch and finds a BLOCK verdict waiting has been told
 * twice as much as one who clears it and has to look again.
 */
export function blockersFor(row: Pick<OverviewRow,
  'kill_switch_active' | 'gate_verdict' | 'release_health' | 'lifecycle_state' | 'servable'>): Blocker[] {
  const blockers: Blocker[] = []
  if (row.kill_switch_active) {
    blockers.push({
      icon: ShieldAlert, tone: 'destructive', label: 'Kill switch active',
      detail: 'This agent is suspended. Automation will not activate or roll back to this version.',
    })
  }
  if (row.gate_verdict === 'BLOCK') {
    blockers.push({
      icon: AlertOctagon, tone: 'destructive', label: 'Release gate blocked',
      detail: 'The preflight verdict is BLOCK. See the findings before attempting a release.',
    })
  }
  if (row.lifecycle_state === 'ROLLING_BACK') {
    blockers.push({
      icon: AlertOctagon, tone: 'destructive', label: 'Rolling back',
      detail: 'A rollback is in progress for this deployment.',
    })
  }
  if (row.lifecycle_state === 'PAUSED') {
    blockers.push({
      icon: PauseCircle, tone: 'warning', label: 'Paused',
      detail: 'This deployment is paused and is not receiving new work.',
    })
  }
  if (row.gate_verdict === 'WARNING') {
    blockers.push({
      icon: AlertTriangle, tone: 'warning', label: 'Release gate warnings',
      detail: 'The preflight verdict is WARNING. Review the findings before shipping.',
    })
  }
  if (row.release_health && !row.release_health.is_proving) {
    blockers.push({
      icon: CircleHelp, tone: 'warning', label: `Health ${row.release_health.health_state}`,
      detail: `Only ${row.release_health.sample_count} sample(s) observed. Not knowing is not the same as being healthy.`,
    })
  }
  return blockers
}


export function formatMoment(value: string | null | undefined): string {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '—'
  return date.toLocaleString(undefined, {
    year: 'numeric', month: 'short', day: '2-digit', hour: '2-digit', minute: '2-digit',
  })
}

export function formatDuration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return '—'
  if (seconds < 60) return `${seconds}s`
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `${minutes}m ${seconds % 60}s`
  const hours = Math.floor(minutes / 60)
  return `${hours}h ${minutes % 60}m`
}
