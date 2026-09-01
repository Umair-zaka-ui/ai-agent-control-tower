import { ROUTES } from '@/constants/routes'
import {
  Activity, BadgeDollarSign, Bell, Boxes, Gauge, ScrollText, ShieldCheck, Waves,
} from 'lucide-react'
import type { LucideIcon } from 'lucide-react'

/**
 * Phase 4.9 — the nine operator views, each with the permission its data needs
 * and the personas (§29) it belongs to.
 *
 * **`permission` is for UX only.** Hiding a link the user cannot use is courtesy
 * — the server re-authorizes every one of these endpoints and a typed URL still
 * gets a 403 (§3.3). The `personas` list is a *lens*: an operator picks the hat
 * they are wearing and the center narrows to the views that matter for that
 * job, so an SRE mid-incident is not scrolling past FinOps allocation tables.
 * It never grants access — it only filters what is already permitted.
 *
 * The content permission (`runtime.trace.content.view`) is deliberately NOT a
 * view gate here: Trace Detail is reachable by anyone with the metadata view;
 * the *content pane inside it* is what 4.8's stronger permission governs.
 */
export type PersonaId =
  | 'platform-engineer'
  | 'sre'
  | 'security'
  | 'governance'
  | 'finops'
  | 'engineering-management'
  | 'executive'

export interface Persona {
  id: PersonaId
  label: string
  blurb: string
}

export const PERSONAS: Persona[] = [
  { id: 'platform-engineer', label: 'Platform Engineer', blurb: 'Trace a slow or failing execution end to end.' },
  { id: 'sre', label: 'SRE / Ops', blurb: 'Watch SLOs and error budgets; work the alert queue.' },
  { id: 'security', label: 'Security / CISO', blurb: 'Review governance decisions and, when authorised, flagged content.' },
  { id: 'governance', label: 'Governance Officer', blurb: 'Set what telemetry is captured, for how long, and for whom.' },
  { id: 'finops', label: 'FinOps', blurb: 'Spend against budgets, allocation and cost drivers.' },
  { id: 'engineering-management', label: 'Engineering Management', blurb: 'Behavioural trends and reliability across the fleet.' },
  { id: 'executive', label: 'CIO / CTO', blurb: 'Fleet health and cost trend at a glance.' },
]

export interface ObsView {
  key: string
  to: string
  label: string
  icon: LucideIcon
  /** UX-only permission gate. The server is the authority. */
  permission: string
  personas: PersonaId[]
}

export const OBS_VIEWS: ObsView[] = [
  {
    key: 'overview', to: ROUTES.OBS_OVERVIEW, label: 'Runtime Overview', icon: Gauge,
    permission: 'runtime.telemetry.view',
    personas: ['platform-engineer', 'sre', 'security', 'governance', 'finops', 'engineering-management', 'executive'],
  },
  {
    key: 'traces', to: ROUTES.OBS_TRACES, label: 'Trace Explorer', icon: Waves,
    permission: 'runtime.telemetry.view',
    personas: ['platform-engineer', 'sre', 'security'],
  },
  {
    key: 'cost', to: ROUTES.OBS_COST, label: 'Cost Center', icon: BadgeDollarSign,
    permission: 'runtime.cost.view',
    personas: ['finops', 'engineering-management', 'executive'],
  },
  {
    key: 'governance', to: ROUTES.OBS_GOVERNANCE, label: 'Governance Decisions', icon: ShieldCheck,
    permission: 'runtime.execution.view',
    personas: ['security', 'governance', 'platform-engineer'],
  },
  {
    key: 'behavior', to: ROUTES.OBS_BEHAVIOR, label: 'Behavior & Anomalies', icon: Activity,
    permission: 'runtime.telemetry.view',
    personas: ['engineering-management', 'sre', 'security', 'platform-engineer'],
  },
  {
    key: 'slos', to: ROUTES.OBS_SLOS, label: 'SLO Dashboard', icon: Boxes,
    permission: 'runtime.telemetry.view',
    personas: ['sre', 'engineering-management', 'executive'],
  },
  {
    key: 'alerts', to: ROUTES.OBS_ALERTS, label: 'Alert Center', icon: Bell,
    permission: 'runtime.telemetry.view',
    personas: ['sre', 'security', 'platform-engineer'],
  },
  {
    key: 'policy', to: ROUTES.OBS_POLICY, label: 'Telemetry Policy', icon: ScrollText,
    permission: 'runtime.telemetry_policy.view',
    personas: ['governance', 'security'],
  },
]

const KEY = 'act:obs-persona'

export function loadPersona(): PersonaId | 'all' {
  try {
    const v = localStorage.getItem(KEY)
    if (v && (v === 'all' || PERSONAS.some((p) => p.id === v))) return v as PersonaId | 'all'
  } catch {
    // private mode / blocked storage — fall through to the default
  }
  return 'all'
}

export function savePersona(id: PersonaId | 'all'): void {
  try {
    localStorage.setItem(KEY, id)
  } catch {
    // best-effort only
  }
}

export function viewsForPersona(persona: PersonaId | 'all'): ObsView[] {
  if (persona === 'all') return OBS_VIEWS
  return OBS_VIEWS.filter((v) => v.personas.includes(persona))
}
