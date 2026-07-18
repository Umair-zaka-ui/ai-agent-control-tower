import { Link, useLocation } from 'react-router-dom'

import { ROUTES } from '@/constants/routes'
import { PERMISSIONS } from '@/constants/permissions'
import { usePermissions } from '@/authorization'

/** §20 — one control plane over every IGA surface. Sections render only when
 * the viewer holds the matching permission — the backend re-authorizes
 * regardless (§24). */
const SECTIONS: { label: string; to: string; permission: string }[] = [
  { label: 'Dashboard', to: ROUTES.GOVERNANCE_DASHBOARD, permission: PERMISSIONS.GOVERNANCE_DASHBOARD_VIEW },
  { label: 'Campaigns', to: ROUTES.GOVERNANCE_CAMPAIGNS, permission: PERMISSIONS.GOVERNANCE_CERTIFICATION_MANAGE },
  { label: 'SoD rules', to: ROUTES.GOVERNANCE_SOD_RULES, permission: PERMISSIONS.GOVERNANCE_SOD_VIEW },
  { label: 'SoD findings', to: ROUTES.GOVERNANCE_SOD_FINDINGS, permission: PERMISSIONS.GOVERNANCE_SOD_VIEW },
  { label: 'Toxic permissions', to: ROUTES.GOVERNANCE_TOXIC_PERMISSIONS, permission: PERMISSIONS.GOVERNANCE_SOD_VIEW },
  { label: 'Privileged access', to: ROUTES.GOVERNANCE_PRIVILEGED_ACCESS, permission: PERMISSIONS.GOVERNANCE_PRIVILEGED_MANAGE },
  { label: 'Orphaned accounts', to: ROUTES.GOVERNANCE_ORPHANED_ACCOUNTS, permission: PERMISSIONS.GOVERNANCE_ORPHANED_MANAGE },
  { label: 'Findings', to: ROUTES.GOVERNANCE_FINDINGS, permission: PERMISSIONS.GOVERNANCE_FINDINGS_MANAGE },
  { label: 'Remediation', to: ROUTES.GOVERNANCE_REMEDIATION, permission: PERMISSIONS.GOVERNANCE_REMEDIATION_MANAGE },
  { label: 'Compliance', to: ROUTES.GOVERNANCE_COMPLIANCE, permission: PERMISSIONS.GOVERNANCE_COMPLIANCE_VIEW },
  { label: 'Analytics', to: ROUTES.GOVERNANCE_ANALYTICS, permission: PERMISSIONS.GOVERNANCE_ANALYTICS_VIEW },
]

export function GovernanceNav() {
  const { can } = usePermissions()
  const { pathname } = useLocation()
  return (
    <nav aria-label="Governance"
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
