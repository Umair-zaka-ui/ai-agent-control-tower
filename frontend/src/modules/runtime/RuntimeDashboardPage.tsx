import { useQuery } from '@tanstack/react-query'
import {
  Bot, CheckCircle2, Clock3, Cpu, DollarSign, Layers, Loader2, PauseCircle, PlayCircle, XCircle,
} from 'lucide-react'

import { PageHeader } from '@/components/common'
import { KpiCard, type KpiAccent } from '@/components/dashboard/KpiCard'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { ROUTES } from '@/constants/routes'
import { runtimeService } from '@/services'
import { RuntimeNav } from './components/RuntimeNav'
import { formatMs } from './utils'

const WIDGETS: {
  key: 'registered_agents' | 'active_agents' | 'active_deployments' | 'running_executions'
    | 'queued_executions' | 'failed_executions_24h' | 'pending_approvals' | 'suspended_agents'
  label: string
  icon: typeof Bot
  accent: KpiAccent
}[] = [
  { key: 'registered_agents', label: 'Registered agents', icon: Bot, accent: 'blue' },
  { key: 'active_agents', label: 'Active agents', icon: PlayCircle, accent: 'green' },
  { key: 'active_deployments', label: 'Active deployments', icon: Layers, accent: 'blue' },
  { key: 'running_executions', label: 'Running executions', icon: Cpu, accent: 'blue' },
  { key: 'queued_executions', label: 'Queued executions', icon: Clock3, accent: 'orange' },
  { key: 'failed_executions_24h', label: 'Failed (24h)', icon: XCircle, accent: 'red' },
  { key: 'pending_approvals', label: 'Pending approvals', icon: Clock3, accent: 'orange' },
  { key: 'suspended_agents', label: 'Suspended agents', icon: PauseCircle, accent: 'orange' },
]

/** Phase 5.0 §70 — runtime dashboard: registered/active agents, deployments,
 * live execution counts, pending approvals, cost and success rate. */
export function RuntimeDashboardPage() {
  const dashboard = useQuery({
    queryKey: ['runtime-dashboard'],
    queryFn: () => runtimeService.dashboard(),
    refetchInterval: 15000,
  })

  return (
    <div className="mx-auto max-w-6xl space-y-6 p-4 sm:p-6">
      <PageHeader
        icon={Cpu}
        title="Agent runtime"
        description="Register, version, deploy and execute AI agents under the same governance and security controls as the rest of the platform."
        backTo={ROUTES.SETTINGS_SECURITY}
        backLabel="Security overview"
      />
      <RuntimeNav />

      {dashboard.isLoading ? (
        <div className="flex justify-center p-12">
          <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
        </div>
      ) : dashboard.data ? (
        <>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
            {WIDGETS.map(({ key, label, icon, accent }) => (
              <KpiCard key={key} icon={icon} accent={accent} title={label} value={dashboard.data[key]} />
            ))}
            <KpiCard icon={DollarSign} accent="green" title="Cost today"
                    value={`$${dashboard.data.cost_today.toFixed(2)}`} />
            <KpiCard icon={CheckCircle2} accent="green" title="Success rate (24h)"
                    value={`${dashboard.data.success_rate.toFixed(1)}%`} />
            <KpiCard icon={Clock3} accent="blue" title="Avg queue time" value={formatMs(dashboard.data.avg_queue_ms)} />
            <KpiCard icon={Clock3} accent="blue" title="Avg execution time" value={formatMs(dashboard.data.avg_execution_ms)} />
          </div>

          <div className="grid gap-4 lg:grid-cols-2">
            <Card>
              <CardHeader><CardTitle className="text-base">Execution trend (7 days)</CardTitle></CardHeader>
              <CardContent>
                {dashboard.data.execution_trend.length === 0 ? (
                  <p className="text-sm text-muted-foreground">No executions recorded yet.</p>
                ) : (
                  <div className="flex flex-wrap gap-2">
                    {dashboard.data.execution_trend.map((t) => (
                      <span key={t.date}
                            className="rounded-lg bg-muted px-3 py-2 text-sm font-medium text-foreground ring-1 ring-inset ring-border">
                        {t.date} <span className="font-normal text-muted-foreground">· {t.count}</span>
                      </span>
                    ))}
                  </div>
                )}
              </CardContent>
            </Card>

            <Card>
              <CardHeader><CardTitle className="text-base">Execution status distribution</CardTitle></CardHeader>
              <CardContent>
                {dashboard.data.status_distribution.length === 0 ? (
                  <p className="text-sm text-muted-foreground">No executions recorded yet.</p>
                ) : (
                  <div className="flex flex-wrap gap-2">
                    {dashboard.data.status_distribution.map((s) => (
                      <span key={s.status}
                            className="rounded-lg bg-muted px-3 py-2 text-sm font-medium text-foreground ring-1 ring-inset ring-border">
                        {s.status} <span className="font-normal text-muted-foreground">· {s.count}</span>
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
