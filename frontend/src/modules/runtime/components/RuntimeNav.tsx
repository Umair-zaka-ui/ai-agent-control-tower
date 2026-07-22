import { Link, useLocation } from 'react-router-dom'

import { ROUTES } from '@/constants/routes'
import { PERMISSIONS } from '@/constants/permissions'
import { usePermissions } from '@/authorization'

/** Phase 5.0 §69 — one control plane over the agent runtime. Sections render
 * only when the viewer holds the matching permission — the backend
 * re-authorizes regardless (§4.4). */
const SECTIONS: { label: string; to: string; permission: string }[] = [
  { label: 'Dashboard', to: ROUTES.RUNTIME_DASHBOARD, permission: PERMISSIONS.RUNTIME_AGENT_VIEW },
  { label: 'Agents', to: ROUTES.RUNTIME_AGENTS, permission: PERMISSIONS.RUNTIME_AGENT_VIEW },
  { label: 'Deployments', to: ROUTES.RUNTIME_DEPLOYMENTS, permission: PERMISSIONS.RUNTIME_DEPLOYMENT_VIEW },
  { label: 'Executions', to: ROUTES.RUNTIME_EXECUTIONS, permission: PERMISSIONS.RUNTIME_EXECUTION_VIEW },
  { label: 'Capabilities', to: ROUTES.RUNTIME_CAPABILITIES, permission: PERMISSIONS.RUNTIME_AGENT_VIEW },
  { label: 'Tools', to: ROUTES.RUNTIME_TOOLS, permission: PERMISSIONS.RUNTIME_AGENT_VIEW },
  { label: 'Approvals', to: ROUTES.RUNTIME_APPROVALS, permission: PERMISSIONS.RUNTIME_APPROVAL_REVIEW },
  { label: 'Operations', to: ROUTES.RUNTIME_OPERATIONS, permission: PERMISSIONS.RUNTIME_HEALTH_VIEW },
  { label: 'Import', to: ROUTES.RUNTIME_IMPORT, permission: PERMISSIONS.RUNTIME_AGENT_IMPORT },
  { label: 'Export', to: ROUTES.RUNTIME_EXPORT, permission: PERMISSIONS.RUNTIME_AGENT_EXPORT },
  { label: 'Migration', to: ROUTES.RUNTIME_MIGRATION, permission: PERMISSIONS.RUNTIME_AGENT_IMPORT },
]

export function RuntimeNav() {
  const { can } = usePermissions()
  const { pathname } = useLocation()
  return (
    <nav aria-label="Agent runtime"
         className="flex flex-wrap gap-1 rounded-lg border border-border bg-card p-1">
      {SECTIONS.filter((s) => can(s.permission)).map((s) => (
        <Link
          key={s.to}
          to={s.to}
          className={`rounded-md px-3 py-1.5 text-sm ${
            pathname === s.to
              ? 'bg-primary text-primary-foreground'
              : 'text-muted-foreground hover:bg-muted hover:text-foreground'
          }`}
        >
          {s.label}
        </Link>
      ))}
    </nav>
  )
}
