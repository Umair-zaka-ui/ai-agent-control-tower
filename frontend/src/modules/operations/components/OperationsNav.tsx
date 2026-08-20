import { NavLink } from 'react-router-dom'
import {
  Activity, CalendarClock, GitBranch, Grid3x3, History, Layers, Rocket, ShieldCheck, Split, Server,
} from 'lucide-react'

import { usePermissions } from '@/authorization'
import { ROUTES } from '@/constants/routes'
import { cn } from '@/utils/cn'

/**
 * Phase 3.10 — navigation across the Release Operations Center.
 *
 * Permission-gated for UX only. A link the current user cannot use is hidden
 * because offering it would be a lie about what will happen, not because
 * hiding it protects anything: the server re-authorizes every one of these
 * routes, and a user who types the URL still gets a 403 (§3.3). Hiding is
 * courtesy; the server is the authority.
 */
const ITEMS = [
  { to: ROUTES.OPS_OVERVIEW, label: 'Overview', icon: Layers, permission: 'runtime.deployment.view' },
  { to: ROUTES.OPS_ENVIRONMENTS, label: 'Environments', icon: Grid3x3, permission: 'runtime.environment.view' },
  { to: ROUTES.OPS_ROLLOUTS, label: 'Rollouts', icon: Rocket, permission: 'runtime.deployment.view' },
  { to: ROUTES.OPS_TRAFFIC, label: 'Traffic', icon: Split, permission: 'runtime.deployment.view' },
  { to: ROUTES.OPS_GATES, label: 'Health gates', icon: ShieldCheck, permission: 'runtime.deployment.view' },
  { to: ROUTES.OPS_PROMOTE, label: 'Promote', icon: GitBranch, permission: 'runtime.deployment.deploy' },
  { to: ROUTES.OPS_ROLLBACK, label: 'Roll back', icon: Activity, permission: 'runtime.deployment.rollback' },
  { to: ROUTES.OPS_HISTORY, label: 'Release history', icon: History, permission: 'runtime.deployment.view' },
  { to: ROUTES.OPS_FLEET, label: 'Worker fleet', icon: Server, permission: 'runtime.worker.view' },
  { to: ROUTES.OPS_SCHEDULER, label: 'Scheduler', icon: CalendarClock, permission: 'runtime.scheduler.view' },
] as const

export function OperationsNav() {
  const { can } = usePermissions()
  const visible = ITEMS.filter((item) => can(item.permission))
  if (visible.length === 0) return null

  return (
    <nav aria-label="Release operations" className="flex flex-wrap gap-1.5">
      {visible.map((item) => (
        <NavLink
          key={item.to}
          to={item.to}
          end
          className={({ isActive }) => cn(
            'inline-flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-sm font-medium transition-colors',
            isActive
              ? 'border-primary/30 bg-primary/10 text-primary'
              : 'border-transparent text-muted-foreground hover:bg-muted hover:text-foreground',
          )}
        >
          <item.icon className="h-4 w-4" aria-hidden />
          {item.label}
        </NavLink>
      ))}
    </nav>
  )
}
