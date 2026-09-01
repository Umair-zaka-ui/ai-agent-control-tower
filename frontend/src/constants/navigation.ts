import {
  LayoutDashboard,
  Bot,
  ShieldCheck,
  CheckSquare,
  ScrollText,
  BarChart3,
  Fingerprint,
  Users,
  Settings,
  ShieldAlert,
  Rocket,
  Gauge,
  type LucideIcon,
} from 'lucide-react'

import { ROUTES, type RoutePath } from './routes'
import { ROLES, type Role } from './roles'

export interface NavChild {
  label: string
  path: string
}

export interface NavItem {
  label: string
  path: RoutePath
  icon: LucideIcon
  /** Roles allowed to see this item. Empty = visible to all authenticated users. */
  roles: Role[]
  /** Optional sub-items rendered as an expandable group. */
  children?: NavChild[]
}

/**
 * Primary sidebar navigation (SRS §8). Order is intentional and matches the
 * spec. `roles` is wired now so role-gating in a later Part is a no-op change.
 */
export const PRIMARY_NAV: NavItem[] = [
  { label: 'Dashboard', path: ROUTES.DASHBOARD, icon: LayoutDashboard, roles: [] },
  {
    label: 'Agents',
    path: ROUTES.AGENTS,
    icon: Bot,
    roles: [],
    children: [
      { label: 'All Agents', path: ROUTES.AGENTS },
      { label: 'Create Agent', path: `${ROUTES.AGENTS}/new` },
    ],
  },
  {
    // Phase 3.10 — the Release Operations Center. Sits directly under Agents
    // because it is where an operator goes to ship one, and above Policies
    // because during an incident it is the page they need first.
    label: 'Releases',
    path: ROUTES.OPS_OVERVIEW,
    icon: Rocket,
    roles: [ROLES.SUPER_ADMIN, ROLES.ADMIN, ROLES.REVIEWER],
    children: [
      { label: 'Overview', path: ROUTES.OPS_OVERVIEW },
      { label: 'Environments', path: ROUTES.OPS_ENVIRONMENTS },
      { label: 'Rollouts', path: ROUTES.OPS_ROLLOUTS },
      { label: 'Traffic', path: ROUTES.OPS_TRAFFIC },
      { label: 'Health gates', path: ROUTES.OPS_GATES },
      { label: 'Promote', path: ROUTES.OPS_PROMOTE },
      { label: 'Roll back', path: ROUTES.OPS_ROLLBACK },
      { label: 'Release history', path: ROUTES.OPS_HISTORY },
      { label: 'Worker fleet', path: ROUTES.OPS_FLEET },
      { label: 'Scheduler', path: ROUTES.OPS_SCHEDULER },
    ],
  },
  {
    // Phase 4.9 — the Enterprise Runtime Governance & Observability Center.
    // The operator control plane where all of Milestone 4 becomes visible:
    // health, traces, cost, governance decisions, behaviour, SLOs, alerts and
    // telemetry policy. Sits under Releases because during an incident an
    // operator moves between the two.
    label: 'Observability',
    path: ROUTES.OBS_OVERVIEW,
    icon: Gauge,
    roles: [ROLES.SUPER_ADMIN, ROLES.ADMIN, ROLES.REVIEWER],
    children: [
      { label: 'Runtime Overview', path: ROUTES.OBS_OVERVIEW },
      { label: 'Trace Explorer', path: ROUTES.OBS_TRACES },
      { label: 'Cost Center', path: ROUTES.OBS_COST },
      { label: 'Governance Decisions', path: ROUTES.OBS_GOVERNANCE },
      { label: 'Behavior & Anomalies', path: ROUTES.OBS_BEHAVIOR },
      { label: 'SLO Dashboard', path: ROUTES.OBS_SLOS },
      { label: 'Alert Center', path: ROUTES.OBS_ALERTS },
      { label: 'Telemetry Policy', path: ROUTES.OBS_POLICY },
    ],
  },
  {
    label: 'Policies',
    path: ROUTES.POLICIES,
    icon: ShieldCheck,
    roles: [ROLES.SUPER_ADMIN, ROLES.ADMIN, ROLES.REVIEWER, ROLES.AUDITOR],
  },
  {
    label: 'Approvals',
    path: ROUTES.APPROVALS,
    icon: CheckSquare,
    roles: [ROLES.SUPER_ADMIN, ROLES.ADMIN, ROLES.REVIEWER],
  },
  { label: 'Audit', path: ROUTES.AUDIT, icon: ScrollText, roles: [] },
  { label: 'Analytics', path: ROUTES.ANALYTICS, icon: BarChart3, roles: [] },
  {
    label: 'Identity',
    path: ROUTES.IDENTITY,
    icon: Fingerprint,
    roles: [ROLES.SUPER_ADMIN, ROLES.ADMIN, ROLES.AUDITOR],
  },
  {
    label: 'Users',
    path: ROUTES.USERS,
    icon: Users,
    roles: [ROLES.SUPER_ADMIN, ROLES.ADMIN],
  },
  { label: 'Settings', path: ROUTES.SETTINGS, icon: Settings, roles: [ROLES.SUPER_ADMIN, ROLES.ADMIN] },
  // Session & device management is *self-service*: every authenticated user must be
  // able to see where they are signed in and sign other devices out. Deliberately
  // ungated — nesting it under the ADMIN-only Settings item made it unreachable for
  // the users who need it most.
  { label: 'Security', path: ROUTES.SETTINGS_SECURITY, icon: ShieldAlert, roles: [] },
]
