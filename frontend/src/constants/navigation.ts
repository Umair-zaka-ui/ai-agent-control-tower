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
