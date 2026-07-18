import { Link, useLocation } from 'react-router-dom'

import { ROUTES } from '@/constants/routes'
import { PERMISSIONS } from '@/constants/permissions'
import { usePermissions } from '@/authorization'

/**
 * §5 — the portal navigation. One control plane over every authorization
 * surface: the new 4.3.7 pages plus the existing phase pages (roles, org
 * hierarchy, resources, ABAC, audit). Sections render only when the viewer
 * holds the matching permission — the backend re-authorizes regardless (§21).
 */
const SECTIONS: { label: string; to: string; permission: string }[] = [
  { label: 'Dashboard', to: ROUTES.ADMIN_DASHBOARD, permission: PERMISSIONS.ADMIN_DASHBOARD_VIEW },
  { label: 'Roles', to: ROUTES.AUTHZ_ROLES, permission: 'role.view' },
  { label: 'Organization', to: ROUTES.ORG_EXPLORER, permission: 'organization.view' },
  { label: 'Resources', to: ROUTES.RES_PERMISSIONS, permission: 'resource.view' },
  { label: 'ABAC policies', to: ROUTES.ABAC_POLICIES, permission: 'authorization.abac.view' },
  { label: 'Simulator', to: ROUTES.ABAC_SIMULATOR, permission: 'authorization.abac.simulate' },
  { label: 'Decisions', to: ROUTES.ADMIN_DECISIONS, permission: PERMISSIONS.ADMIN_AUDIT_VIEW },
  { label: 'Access reviews', to: ROUTES.ADMIN_REVIEWS, permission: PERMISSIONS.ADMIN_REVIEWS_MANAGE },
  { label: 'Audit', to: ROUTES.AUDIT, permission: 'audit.view' },
  { label: 'Analytics', to: ROUTES.ADMIN_ANALYTICS, permission: PERMISSIONS.ADMIN_ANALYTICS_VIEW },
  { label: 'Governance', to: ROUTES.GOVERNANCE_DASHBOARD, permission: PERMISSIONS.GOVERNANCE_DASHBOARD_VIEW },
]

export function AdminNav() {
  const { can } = usePermissions()
  const { pathname } = useLocation()
  return (
    <nav aria-label="Administration"
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
