import { useEffect, useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Loader2, Split } from 'lucide-react'

import { EmptyState, PageHeader } from '@/components/common'
import {
  Badge, Button, Card, CardContent, CardHeader, CardTitle, Input, Label, Select,
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui'
import { usePermissions } from '@/authorization'
import { ROUTES } from '@/constants/routes'
import { operationsService } from '@/services'
import { ConfirmActionDialog } from './components/ConfirmActionDialog'
import { OperationsNav } from './components/OperationsNav'
import { formatMoment } from './components/format'
import { useGuardedAction } from './useGuardedAction'

/**
 * Phase 3.10 view 7 — Traffic Allocation (M3-3.10-FR-006).
 *
 * The current weights across versions, the full revision history, and the
 * guarded control that changes them.
 *
 * **The total-100 rule is shown, not enforced here.** The weights box tells
 * the operator what the current total is and colours it when it is not 100,
 * but the confirm button does not silently normalise or auto-balance: Phase
 * 3.4 validates the total, checks every version's eligibility, writes a new
 * revision and audits it. A UI that quietly corrected the numbers would be
 * making an allocation decision, which is precisely what this phase must not
 * do — and it would hide from the operator that what they typed was not what
 * shipped.
 *
 * Changing weights is confirmation-gated with type-to-confirm on the
 * environment name: this moves live production traffic, immediately.
 */
export function TrafficAllocationPage() {
  const { can } = usePermissions()
  const guard = useGuardedAction()
  const [agentId, setAgentId] = useState('')
  const [environmentId, setEnvironmentId] = useState('')
  const [draft, setDraft] = useState<Record<string, string>>({})

  const overview = useQuery({
    queryKey: ['ops-overview', ''],
    queryFn: () => operationsService.overview(),
  })

  const scopes = useMemo(() => {
    const rows = overview.data?.deployments ?? []
    const seen = new Map<string, { agentId: string; agentName: string; envId: string; envName: string }>()
    for (const row of rows) {
      if (!row.environment_id) continue
      const key = `${row.agent_id}:${row.environment_id}`
      if (!seen.has(key)) {
        seen.set(key, {
          agentId: row.agent_id, agentName: row.agent_name ?? row.agent_id,
          envId: row.environment_id, envName: row.environment_name ?? '',
        })
      }
    }
    return [...seen.values()].sort((a, b) => a.agentName.localeCompare(b.agentName))
  }, [overview.data])

  const selected = scopes.find((s) => s.agentId === agentId && s.envId === environmentId)

  const allocation = useQuery({
    queryKey: ['ops-traffic', agentId, environmentId],
    queryFn: () => operationsService.traffic(agentId, environmentId),
    enabled: Boolean(agentId && environmentId),
  })
  const history = useQuery({
    queryKey: ['ops-traffic-history', agentId, environmentId],
    queryFn: () => operationsService.trafficHistory(agentId, environmentId),
    enabled: Boolean(agentId && environmentId),
  })

  // Seed the editable draft from whatever the server currently reports, so an
  // operator always starts from reality rather than from a blank form.
  useEffect(() => {
    const weights = allocation.data?.weights ?? []
    setDraft(Object.fromEntries(weights.map((w) => [w.agent_version_id, String(w.weight)])))
  }, [allocation.data])

  const total = Object.values(draft).reduce((sum, value) => sum + (Number(value) || 0), 0)
  const canChange = can('runtime.deployment.deploy')
  const versionsForAgent = (overview.data?.deployments ?? [])
    .filter((r) => r.agent_id === agentId && r.environment_id === environmentId && r.version)

  return (
    <div className="mx-auto max-w-5xl space-y-6 p-4 sm:p-6">
      <PageHeader
        icon={Split}
        title="Traffic allocation"
        description="Which version serves what share of requests, and every revision of that decision."
        backTo={ROUTES.OPS_OVERVIEW}
        backLabel="Release operations"
      />
      <OperationsNav />

      <Card>
        <CardHeader><CardTitle className="text-base">Scope</CardTitle></CardHeader>
        <CardContent>
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label htmlFor="traffic-scope">Agent and environment</Label>
              <Select
                id="traffic-scope"
                value={selected ? `${selected.agentId}:${selected.envId}` : ''}
                onChange={(e) => {
                  const [nextAgent, nextEnv] = e.target.value.split(':')
                  setAgentId(nextAgent ?? '')
                  setEnvironmentId(nextEnv ?? '')
                }}
                placeholder="Select an agent and environment…"
                options={scopes.map((scope) => ({
                  value: `${scope.agentId}:${scope.envId}`,
                  label: `${scope.agentName} — ${scope.envName}`,
                }))}
              />
            </div>
          </div>
        </CardContent>
      </Card>

      {!selected ? (
        <Card>
          <CardContent className="p-0">
            <EmptyState
              icon={Split}
              title="Choose a scope"
              description="Traffic is allocated per agent, per environment. Pick one above to see its current weights."
            />
          </CardContent>
        </Card>
      ) : (
        <>
          <Card>
            <CardHeader>
              <CardTitle className="text-base">
                Current allocation
                {allocation.data ? (
                  <Badge variant="outline" className="ml-2">revision {allocation.data.revision}</Badge>
                ) : null}
              </CardTitle>
            </CardHeader>
            <CardContent>
              {allocation.isLoading ? (
                <div className="flex justify-center p-6">
                  <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
                </div>
              ) : !allocation.data ? (
                <p className="text-sm text-muted-foreground">
                  No explicit allocation. The resolver routes to the single servable deployment
                  (Phase 3.4&rsquo;s implicit-100% case).
                </p>
              ) : (
                <div className="space-y-4">
                  {allocation.data.weights.map((w) => {
                    const label = versionsForAgent.find((r) => r.version?.id === w.agent_version_id)
                      ?.version?.semantic_version ?? w.agent_version_id.slice(0, 8)
                    return (
                      <div key={w.agent_version_id} className="space-y-1.5">
                        <div className="flex items-center justify-between text-sm">
                          <span className="font-mono">{label}</span>
                          <span className="font-medium">{w.weight}%</span>
                        </div>
                        <div className="h-2.5 overflow-hidden rounded-full bg-muted">
                          <div className="h-full rounded-full bg-primary" style={{ width: `${w.weight}%` }} />
                        </div>
                      </div>
                    )
                  })}
                </div>
              )}
            </CardContent>
          </Card>

          {canChange && allocation.data ? (
            <Card>
              <CardHeader><CardTitle className="text-base">Change allocation</CardTitle></CardHeader>
              <CardContent className="space-y-4">
                {allocation.data.weights.map((w) => {
                  const label = versionsForAgent.find((r) => r.version?.id === w.agent_version_id)
                    ?.version?.semantic_version ?? w.agent_version_id.slice(0, 8)
                  return (
                    <div key={w.agent_version_id} className="flex items-center gap-3">
                      <Label htmlFor={`w-${w.agent_version_id}`} className="w-40 shrink-0 font-mono text-sm">
                        {label}
                      </Label>
                      <Input
                        id={`w-${w.agent_version_id}`}
                        type="number"
                        min={0}
                        max={100}
                        value={draft[w.agent_version_id] ?? '0'}
                        onChange={(e) => setDraft((d) => ({ ...d, [w.agent_version_id]: e.target.value }))}
                        className="w-28"
                      />
                      <span className="text-sm text-muted-foreground">%</span>
                    </div>
                  )
                })}
                <p className={`text-sm ${total === 100 ? 'text-muted-foreground' : 'text-warning'}`}>
                  Total: {total}%{total === 100 ? '' : ' — Phase 3.4 requires exactly 100 and will reject anything else.'}
                </p>
                <Button
                  disabled={Object.keys(draft).length === 0}
                  onClick={() => guard.confirm({
                    title: 'Change live traffic allocation',
                    description:
                      'This moves production traffic immediately, through Phase 3.4’s audited allocator. The previous revision is preserved and remains rollback-able.',
                    confirmLabel: 'Apply new weights',
                    typeToConfirm: selected.envName,
                    requireReason: true,
                    warnings: [
                      `New weights: ${Object.entries(draft).map(([, v]) => `${v}%`).join(' / ')} (total ${total}%).`,
                      ...(total !== 100 ? ['The total is not 100. The server will reject this.'] : []),
                    ],
                    onConfirm: (reason) => guard.run(
                      () => operationsService.setTraffic(
                        agentId, environmentId,
                        Object.entries(draft).map(([agent_version_id, weight]) => ({
                          agent_version_id, weight: Number(weight) || 0,
                        })),
                        reason),
                      {
                        success: 'Traffic allocation updated',
                        invalidate: [['ops-traffic', agentId, environmentId],
                                     ['ops-traffic-history', agentId, environmentId],
                                     ['ops-overview', '']],
                      }),
                  })}
                >
                  Change allocation…
                </Button>
              </CardContent>
            </Card>
          ) : null}

          <Card>
            <CardHeader><CardTitle className="text-base">Revision history</CardTitle></CardHeader>
            <CardContent className="p-0">
              {(history.data ?? []).length === 0 ? (
                <p className="p-6 text-sm text-muted-foreground">No allocation revisions recorded.</p>
              ) : (
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Revision</TableHead>
                      <TableHead>Weights</TableHead>
                      <TableHead>Reason</TableHead>
                      <TableHead>When</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {(history.data ?? []).map((entry) => (
                      <TableRow key={entry.id ?? entry.revision}>
                        <TableCell>
                          <Badge variant={entry.is_current ? 'success' : 'outline'}>
                            {entry.revision}{entry.is_current ? ' · current' : ''}
                          </Badge>
                        </TableCell>
                        <TableCell className="font-mono text-xs">
                          {(entry.weights ?? []).map((w) => `${w.weight}%`).join(' / ') || '—'}
                        </TableCell>
                        <TableCell className="max-w-xs truncate text-muted-foreground" title={entry.reason ?? ''}>
                          {entry.reason ?? '—'}
                        </TableCell>
                        <TableCell className="whitespace-nowrap text-muted-foreground">
                          {formatMoment(entry.created_at)}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              )}
            </CardContent>
          </Card>
        </>
      )}

      <ConfirmActionDialog request={guard.request} pending={guard.pending} onCancel={guard.cancel} />
    </div>
  )
}
