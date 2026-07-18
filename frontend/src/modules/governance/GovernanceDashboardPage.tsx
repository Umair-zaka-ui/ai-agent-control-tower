import { useQuery } from '@tanstack/react-query'
import {
  AlertTriangle, ClipboardCheck, Clock3, Crown, FileCheck2, LayoutDashboard, Loader2,
  ShieldQuestion, Skull, UserX, Wrench,
} from 'lucide-react'

import { PageHeader } from '@/components/common'
import { KpiCard, type KpiAccent } from '@/components/dashboard/KpiCard'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { ROUTES } from '@/constants/routes'
import { governanceService } from '@/services'
import { GovernanceNav } from './components/GovernanceNav'

const WIDGETS: {
  key: 'active_campaigns' | 'pending_reviews' | 'overdue_reviews' | 'privileged_accounts'
    | 'toxic_permission_findings' | 'sod_findings' | 'orphaned_accounts' | 'remediation_queue'
  label: string
  icon: typeof ClipboardCheck
  accent: KpiAccent
}[] = [
  { key: 'active_campaigns', label: 'Active campaigns', icon: ClipboardCheck, accent: 'blue' },
  { key: 'pending_reviews', label: 'Pending reviews', icon: Clock3, accent: 'orange' },
  { key: 'overdue_reviews', label: 'Overdue reviews', icon: AlertTriangle, accent: 'red' },
  { key: 'privileged_accounts', label: 'Privileged accounts', icon: Crown, accent: 'blue' },
  { key: 'toxic_permission_findings', label: 'Toxic permission findings', icon: Skull, accent: 'red' },
  { key: 'sod_findings', label: 'SoD findings', icon: ShieldQuestion, accent: 'orange' },
  { key: 'orphaned_accounts', label: 'Orphaned accounts', icon: UserX, accent: 'orange' },
  { key: 'remediation_queue', label: 'Remediation queue', icon: Wrench, accent: 'blue' },
]

const RISK_BAND_STYLES: Record<string, string> = {
  LOW: 'bg-success/10 text-success ring-success/20',
  MEDIUM: 'bg-warning/10 text-warning ring-warning/20',
  HIGH: 'bg-destructive/10 text-destructive ring-destructive/20',
  CRITICAL: 'bg-destructive/20 text-destructive ring-destructive/30',
}

/** §21 — governance dashboard: active campaigns, pending/overdue reviews,
 * privileged accounts, findings, compliance status and the remediation queue. */
export function GovernanceDashboardPage() {
  const dashboard = useQuery({
    queryKey: ['governance-dashboard'],
    queryFn: () => governanceService.dashboard(),
  })

  return (
    <div className="mx-auto max-w-6xl space-y-6 p-4 sm:p-6">
      <PageHeader
        icon={LayoutDashboard}
        title="Governance dashboard"
        description="Continuous access governance: certification, SoD/toxic detection, privileged access, orphaned identities, risk and remediation in one view."
        backTo={ROUTES.SETTINGS_SECURITY}
        backLabel="Security overview"
      />
      <GovernanceNav />

      {dashboard.isLoading ? (
        <div className="flex justify-center p-12">
          <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
        </div>
      ) : dashboard.data ? (
        <>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
            {WIDGETS.map(({ key, label, icon, accent }) => (
              <KpiCard key={key} icon={icon} accent={accent} title={label} value={dashboard.data.widgets[key]} />
            ))}
            <KpiCard
              icon={FileCheck2}
              accent={dashboard.data.widgets.compliance_status === 'ready' ? 'green' : 'blue'}
              title="Compliance status"
              value={dashboard.data.widgets.compliance_status === 'ready' ? 'Ready' : 'No reports yet'}
            />
          </div>

          <div className="grid gap-4 lg:grid-cols-2">
            <Card>
              <CardHeader>
                <CardTitle className="text-base">Governance risk distribution</CardTitle>
              </CardHeader>
              <CardContent>
                {Object.entries(dashboard.data.widgets.governance_risk_distribution).length === 0 ? (
                  <p className="text-sm text-muted-foreground">
                    No risk scores computed yet — visit Analytics to run one.
                  </p>
                ) : (
                  <div className="flex flex-wrap gap-2">
                    {Object.entries(dashboard.data.widgets.governance_risk_distribution).map(([band, n]) => (
                      <span
                        key={band}
                        className={`rounded-lg px-3 py-2 text-sm font-medium ring-1 ring-inset ${RISK_BAND_STYLES[band] ?? 'bg-muted text-muted-foreground ring-border'}`}
                      >
                        {band} <span className="font-normal opacity-80">· {n}</span>
                      </span>
                    ))}
                  </div>
                )}
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle className="text-base">Findings by type</CardTitle>
              </CardHeader>
              <CardContent>
                {dashboard.data.charts.findings_by_type.length === 0 ? (
                  <p className="text-sm text-muted-foreground">No findings recorded yet.</p>
                ) : (
                  <div className="flex flex-wrap gap-2">
                    {dashboard.data.charts.findings_by_type.map((f) => (
                      <span
                        key={f.finding_type}
                        className="rounded-lg bg-muted px-3 py-2 text-sm font-medium text-foreground ring-1 ring-inset ring-border"
                      >
                        {f.finding_type.replace(/_/g, ' ')} <span className="font-normal text-muted-foreground">· {f.total}</span>
                      </span>
                    ))}
                  </div>
                )}
              </CardContent>
            </Card>
          </div>
        </>
      ) : null}
    </div>
  )
}
