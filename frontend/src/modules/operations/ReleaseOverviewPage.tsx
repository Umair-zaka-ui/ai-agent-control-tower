import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { Layers, Loader2, ShieldAlert } from 'lucide-react'

import { EmptyState, PageHeader } from '@/components/common'
import {
  Badge, Card, CardContent, Select,
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui'
import { ROUTES } from '@/constants/routes'
import { operationsService } from '@/services'
import { OperationsNav } from './components/OperationsNav'
import {
  BlockerChips, GateBadge, HealthBadge, KillSwitchBadge, LifecycleBadge, RolloutStateBadge, ServingBadge,
} from './components/state'
import { blockersFor, formatMoment } from './components/format'

/**
 * Phase 3.10 view 1 — Deployment Overview (M3-3.10-FR-001).
 *
 * Every deployment across every environment, with the four facts that decide
 * whether it is safe: lifecycle state, what share of traffic it is actually
 * taking, its release-gate verdict, and its release health.
 *
 * The counters at the top are deliberately not a "health score". They count
 * the things an operator would want to act on — killed, blocked, rolling out —
 * because a single aggregate number is exactly the kind of reassuring
 * abstraction that hides an incident.
 *
 * Fed by `GET /runtime/operations/overview`, one request regardless of how
 * many deployments exist.
 */
export function ReleaseOverviewPage() {
  const [environmentId, setEnvironmentId] = useState('')
  const overview = useQuery({
    queryKey: ['ops-overview', environmentId],
    queryFn: () => operationsService.overview(environmentId || undefined),
    refetchInterval: 30_000,
  })

  const rows = overview.data?.deployments ?? []
  const summary = overview.data?.summary
  const environments = overview.data?.environments ?? []

  return (
    <div className="mx-auto max-w-7xl space-y-6 p-4 sm:p-6">
      <PageHeader
        icon={Layers}
        title="Release operations"
        description="Every deployment across every environment — what is serving, what is blocked, and what needs a decision."
        actions={
          <Select
            aria-label="Filter by environment"
            value={environmentId}
            onChange={(e) => setEnvironmentId(e.target.value)}
            placeholder="All environments"
            options={environments.map((env) => ({
              value: env.id, label: env.display_name || env.name,
            }))}
          />
        }
      />
      <OperationsNav />

      {summary ? (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <SummaryTile label="Serving" value={summary.serving} total={summary.total} tone="success" />
          <SummaryTile label="Rolling out" value={summary.rolling_out} tone="default" />
          <SummaryTile label="Gate blocked" value={summary.blocked} tone="destructive" />
          <SummaryTile label="Kill switch active" value={summary.kill_switched} tone="destructive" />
        </div>
      ) : null}

      {summary && summary.kill_switched > 0 ? (
        <div role="alert" className="flex items-start gap-2 rounded-xl border border-destructive/30 bg-destructive/10 p-4 text-sm">
          <ShieldAlert className="mt-0.5 h-4 w-4 shrink-0 text-destructive" aria-hidden />
          <span>
            <span className="font-medium text-foreground">
              {summary.kill_switched} deployment{summary.kill_switched === 1 ? '' : 's'} affected by an active kill switch.
            </span>{' '}
            <span className="text-muted-foreground">
              Automation will not activate or roll back to these versions until the switch is cleared by a human.
            </span>
          </span>
        </div>
      ) : null}

      <Card>
        <CardContent className="p-0">
          {overview.isLoading ? (
            <div className="flex justify-center p-10">
              <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
            </div>
          ) : rows.length === 0 ? (
            <EmptyState
              icon={Layers}
              title="Nothing deployed yet"
              description="Publish an agent version and deploy it, and it will appear here with its gate verdict and health."
            />
          ) : (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Agent</TableHead>
                    <TableHead>Environment</TableHead>
                    <TableHead>Version</TableHead>
                    <TableHead>Lifecycle</TableHead>
                    <TableHead>Traffic</TableHead>
                    <TableHead>Gate</TableHead>
                    <TableHead>Health</TableHead>
                    <TableHead>Rollout</TableHead>
                    <TableHead>Needs attention</TableHead>
                    <TableHead>Deployed</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {rows.map((row) => (
                    <TableRow key={row.deployment_id}>
                      <TableCell className="font-medium">
                        <Link
                          to={ROUTES.OPS_DEPLOYMENT_DETAIL.replace(':id', row.deployment_id)}
                          className="hover:underline"
                        >
                          {row.agent_name ?? row.agent_id}
                        </Link>
                        <div className="mt-1"><KillSwitchBadge active={row.kill_switch_active} /></div>
                      </TableCell>
                      <TableCell>
                        <Badge variant={row.is_production ? 'warning' : 'outline'}>
                          {row.environment_name}
                        </Badge>
                      </TableCell>
                      <TableCell className="whitespace-nowrap font-mono text-xs">
                        {row.version?.semantic_version ?? '—'}
                        {row.version?.signature_state === 'SIGNED' ? (
                          <span className="ml-1 text-success" title="Signed artifact">✓</span>
                        ) : null}
                      </TableCell>
                      <TableCell><LifecycleBadge state={row.lifecycle_state} /></TableCell>
                      <TableCell><ServingBadge servable={row.servable} weight={row.traffic_weight} /></TableCell>
                      <TableCell><GateBadge verdict={row.gate_verdict} /></TableCell>
                      <TableCell><HealthBadge health={row.release_health} /></TableCell>
                      <TableCell>
                        {row.active_rollout ? (
                          <Link
                            to={ROUTES.OPS_ROLLOUT_DETAIL.replace(':id', row.active_rollout.id)}
                            className="hover:underline"
                          >
                            <RolloutStateBadge state={row.active_rollout.state} />
                          </Link>
                        ) : <span className="text-muted-foreground">—</span>}
                      </TableCell>
                      <TableCell><BlockerChips blockers={blockersFor(row)} /></TableCell>
                      <TableCell className="whitespace-nowrap text-muted-foreground">
                        {formatMoment(row.deployed_at)}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}

function SummaryTile({ label, value, total, tone }: {
  label: string; value: number; total?: number
  tone: 'success' | 'destructive' | 'default'
}) {
  const emphasised = tone === 'destructive' && value > 0
  return (
    <Card className={emphasised ? 'border-destructive/40' : undefined}>
      <CardContent className="p-4">
        <p className="text-sm text-muted-foreground">{label}</p>
        <p className={`mt-1 text-2xl font-semibold ${emphasised ? 'text-destructive' : 'text-foreground'}`}>
          {value}
          {total !== undefined ? <span className="text-base text-muted-foreground"> / {total}</span> : null}
        </p>
      </CardContent>
    </Card>
  )
}
