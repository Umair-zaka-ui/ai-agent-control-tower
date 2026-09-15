import { ROUTES } from '@/constants/routes'
import {
  Boxes, Cable, ClipboardCheck, EyeOff, Gauge, GitBranch, Landmark, ShieldAlert,
  ShieldCheck, Siren, Users, Wallet, Wrench,
} from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import { PERSONAS, type PersonaId } from '@/modules/observability'

/**
 * Phase 5.8 — the command center's views, each with the permission its data
 * needs and the personas (§29) it serves.
 *
 * **The persona vocabulary is imported, not redefined.** Phase 4.9 already
 * established the seven hats an operator wears, and a second, subtly different
 * list would mean "Security" meant one thing in Observability and another here.
 * Only the *views* are new.
 *
 * **`permission` is for UX only** — the same rule 4.9 stated and for the same
 * reason. Hiding a link the user cannot use is courtesy; the server
 * re-authorizes every endpoint behind these views and a typed URL still gets a
 * 403. The persona is a *lens*: it narrows what is on screen, never what is
 * allowed.
 */
export type { PersonaId }
export { PERSONAS }

export interface CommandView {
  key: string
  to: string
  label: string
  icon: LucideIcon
  /** UX-only permission gate. The server is the authority. */
  permission: string
  personas: PersonaId[]
}

export const COMMAND_VIEWS: CommandView[] = [
  {
    key: 'estate', to: ROUTES.CC_ESTATE, label: 'AI Estate', icon: Gauge,
    permission: 'agent.view',
    personas: ['platform-engineer', 'sre', 'security', 'governance', 'finops', 'engineering-management', 'executive'],
  },
  {
    key: 'inventory', to: ROUTES.CC_INVENTORY, label: 'Agent Inventory', icon: Boxes,
    permission: 'agent.view',
    personas: ['platform-engineer', 'security', 'governance', 'engineering-management'],
  },
  {
    key: 'shadow', to: ROUTES.CC_SHADOW, label: 'Shadow AI', icon: EyeOff,
    permission: 'posture.view',
    personas: ['security', 'governance', 'executive'],
  },
  {
    key: 'ownership', to: ROUTES.CC_OWNERSHIP, label: 'Ownership', icon: Users,
    permission: 'agent.view',
    personas: ['governance', 'engineering-management', 'executive'],
  },
  {
    key: 'identity', to: ROUTES.CC_IDENTITY, label: 'Identity & Delegation', icon: GitBranch,
    permission: 'graph.view',
    personas: ['security', 'governance'],
  },
  {
    key: 'graph', to: ROUTES.CC_GRAPH, label: 'Control Graph', icon: Cable,
    permission: 'graph.view',
    personas: ['security', 'platform-engineer', 'governance'],
  },
  {
    key: 'tools', to: ROUTES.CC_TOOLS, label: 'Tools & MCP', icon: Wrench,
    permission: 'graph.view',
    personas: ['security', 'platform-engineer'],
  },
  {
    key: 'posture', to: ROUTES.CC_POSTURE, label: 'Security Posture', icon: ShieldCheck,
    permission: 'posture.view',
    personas: ['security', 'governance', 'executive'],
  },
  {
    key: 'threats', to: ROUTES.CC_THREATS, label: 'Threats & Incidents', icon: Siren,
    permission: 'threat.view',
    personas: ['security', 'sre', 'platform-engineer'],
  },
  {
    key: 'external', to: ROUTES.CC_EXTERNAL, label: 'External Platforms', icon: ShieldAlert,
    permission: 'external_governance.view',
    personas: ['security', 'governance', 'platform-engineer'],
  },
  {
    key: 'coverage', to: ROUTES.CC_COVERAGE, label: 'Governance Coverage', icon: Landmark,
    permission: 'agent.view',
    personas: ['governance', 'executive', 'security'],
  },
  {
    key: 'cost', to: ROUTES.CC_COST, label: 'Cost Exposure', icon: Wallet,
    permission: 'runtime.cost.view',
    personas: ['finops', 'executive', 'engineering-management'],
  },
  {
    key: 'assurance', to: ROUTES.CC_ASSURANCE, label: 'Assurance', icon: ClipboardCheck,
    permission: 'agent.view',
    personas: ['governance', 'executive'],
  },
]

const KEY = 'act:cc-persona'

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

export function viewsForPersona(persona: PersonaId | 'all'): CommandView[] {
  if (persona === 'all') return COMMAND_VIEWS
  return COMMAND_VIEWS.filter((v) => v.personas.includes(persona))
}
