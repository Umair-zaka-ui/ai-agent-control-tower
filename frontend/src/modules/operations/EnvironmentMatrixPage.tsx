import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { Grid3x3, Loader2 } from 'lucide-react'

import { EmptyState, PageHeader } from '@/components/common'
import { Badge, Card, CardContent, CardHeader, CardTitle } from '@/components/ui'
import { ROUTES } from '@/constants/routes'
import { operationsService } from '@/services'
import type { OverviewRow } from '@/services/operationsService'
import { OperationsNav } from './components/OperationsNav'
import {
  GateBadge, HealthBadge, KillSwitchBadge, ServingBadge,
} from './components/state'
import { blockersFor } from './components/format'

/**
 * Phase 3.10 view 2 — Environment Matrix (M3-3.10-FR-002).
 *
 * Agents down the side, environments across the top: which version of each
 * agent is in each environment, and whether it is actually serving there.
 *
 * This answers the question the overview list cannot — *"has this version
 * reached production yet, and what is in staging ahead of it?"* — which is the
 * question a promotion decision actually turns on.
 *
 * Production columns are visually distinct, deliberately. The single most
 * expensive mistake this screen can enable is acting on a production cell
 * believing it to be staging.
 *
 * Fed by the same `GET /runtime/operations/overview` response as view 1 — the
 * matrix is those rows pivoted, and asking the server to compute it twice
 * would be two things to keep in agreement.
 */
export function EnvironmentMatrixPage() {
  const overview = useQuery({
    queryKey: ['ops-overview', ''],
    queryFn: () => operationsService.overview(),
    refetchInterval: 30_000,
  })

  const environments = overview.data?.environments ?? []
  const rows = overview.data?.deployments ?? []

  // Agent → environment → the deployments there. A cell can legitimately hold
  // more than one (that is what a canary or a blue-green pair *is*), so this
  // keeps every deployment rather than picking a winner and hiding the rest.
  const byAgent = new Map<string, { name: string; cells: Map<string, OverviewRow[]> }>()
  for (const row of rows) {
    const agentKey = row.agent_id
    if (!byAgent.has(agentKey)) {
      byAgent.set(agentKey, { name: row.agent_name ?? agentKey, cells: new Map() })
    }
    const envKey = row.environment_id ?? row.environment_name ?? 'unassigned'
    const cells = byAgent.get(agentKey)!.cells
    cells.set(envKey, [...(cells.get(envKey) ?? []), row])
  }
  const agents = [...byAgent.entries()].sort((a, b) => a[1].name.localeCompare(b[1].name))

  return (
    <div className="mx-auto max-w-7xl space-y-6 p-4 sm:p-6">
      <PageHeader
        icon={Grid3x3}
        title="Environment matrix"
        description="Which version of each agent is where, and whether it is actually serving there."
        backTo={ROUTES.OPS_OVERVIEW}
        backLabel="Release operations"
      />
      <OperationsNav />

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Agents across environments</CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          {overview.isLoading ? (
            <div className="flex justify-center p-10">
              <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
            </div>
          ) : agents.length === 0 ? (
            <EmptyState
              icon={Grid3x3}
              title="No deployments to place"
              description="Once an agent version is deployed to an environment it appears in this matrix."
            />
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full border-separate border-spacing-0 text-sm">
                <thead>
                  <tr>
                    <th className="sticky left-0 z-10 border-b bg-card px-4 py-3 text-left font-medium text-muted-foreground">
                      Agent
                    </th>
                    {environments.map((env) => (
                      <th
                        key={env.id}
                        scope="col"
                        className={`border-b px-4 py-3 text-left font-medium ${
                          env.is_production
                            ? 'bg-warning/10 text-warning'
                            : 'bg-card text-muted-foreground'
                        }`}
                      >
                        {env.display_name || env.name}
                        {env.is_production ? (
                          <span className="ml-1.5 text-[10px] uppercase tracking-wide">production</span>
                        ) : null}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {agents.map(([agentId, agent]) => (
                    <tr key={agentId} className="align-top">
                      <th
                        scope="row"
                        className="sticky left-0 z-10 border-b bg-card px-4 py-3 text-left font-medium text-foreground"
                      >
                        {agent.name}
                      </th>
                      {environments.map((env) => {
                        const cell = agent.cells.get(env.id) ?? []
                        return (
                          <td
                            key={env.id}
                            className={`border-b px-4 py-3 ${env.is_production ? 'bg-warning/5' : ''}`}
                          >
                            {cell.length === 0 ? (
                              <span className="text-muted-foreground">—</span>
                            ) : (
                              <div className="space-y-2">
                                {cell.map((row) => (
                                  <MatrixCell key={row.deployment_id} row={row} />
                                ))}
                              </div>
                            )}
                          </td>
                        )
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}

function MatrixCell({ row }: { row: OverviewRow }) {
  const blockers = blockersFor(row)
  return (
    <Link
      to={ROUTES.OPS_DEPLOYMENT_DETAIL.replace(':id', row.deployment_id)}
      className="block rounded-lg border p-2 transition-colors hover:border-primary/40 hover:bg-muted/50"
    >
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="font-mono text-xs font-medium">
          {row.version?.semantic_version ?? 'unknown'}
        </span>
        <ServingBadge servable={row.servable} weight={row.traffic_weight} />
      </div>
      <div className="mt-1.5 flex flex-wrap items-center gap-1">
        <KillSwitchBadge active={row.kill_switch_active} />
        <GateBadge verdict={row.gate_verdict} />
        <HealthBadge health={row.release_health} />
      </div>
      {row.active_rollout ? (
        <div className="mt-1.5">
          <Badge variant="default">
            {row.active_rollout.kind} · stage {row.active_rollout.current_stage_index}
          </Badge>
        </div>
      ) : null}
      {blockers.length > 0 ? (
        <p className="mt-1.5 text-xs text-muted-foreground">
          {blockers.length} thing{blockers.length === 1 ? '' : 's'} to check
        </p>
      ) : null}
    </Link>
  )
}
