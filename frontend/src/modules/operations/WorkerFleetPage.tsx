import { useQuery } from '@tanstack/react-query'
import { Loader2, Server, Waves } from 'lucide-react'

import { EmptyState, PageHeader } from '@/components/common'
import {
  Badge, Button, Card, CardContent, CardHeader, CardTitle,
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui'
import { usePermissions } from '@/authorization'
import { ROUTES } from '@/constants/routes'
import { operationsService } from '@/services'
import { ConfirmActionDialog } from './components/ConfirmActionDialog'
import { OperationsNav } from './components/OperationsNav'
import { formatMoment } from './components/format'
import { useGuardedAction } from './useGuardedAction'

const WORKER_VARIANT: Record<string, 'success' | 'warning' | 'outline'> = {
  RUNNING: 'success',
  DRAINING: 'warning',
  STOPPED: 'outline',
}

/**
 * Phase 3.10 view 11 — Worker Fleet (M3-3.10-FR-009).
 *
 * The registered execution workers, their capacity, the queue they are facing,
 * and the drain control.
 *
 * Reads `/runtime/fleet` — **not** `/runtime/workers`, which has belonged to
 * Milestone 1 since the beginning and reports worker *activity* derived from
 * execution attempts. Two different questions; Phase 3.9 nested beside the
 * older endpoint rather than taking its path.
 *
 * Draining is confirmation-gated but not type-to-confirm: it is a *graceful*
 * operation — the worker finishes what it holds and stops claiming — and
 * reversible by restarting the process. Reserving the heavier friction for
 * genuinely irreversible things is what keeps that friction meaningful.
 *
 * The capacity-per-cohort panel is here because it is what a rolling
 * deployment's step weights are derived from. An operator about to start one
 * can see the shape their rollout will take before they start it.
 */
export function WorkerFleetPage() {
  const { can } = usePermissions()
  const guard = useGuardedAction()

  const fleet = useQuery({
    queryKey: ['ops-fleet'],
    queryFn: () => operationsService.fleet(),
    refetchInterval: 10_000,
  })
  const depth = useQuery({
    queryKey: ['ops-queue-depth'],
    queryFn: () => operationsService.queueDepth(),
    refetchInterval: 10_000,
  })

  const workers = fleet.data?.workers ?? []
  const cohorts = Object.entries(fleet.data?.capacity_by_cohort ?? {})
  const canManage = can('runtime.worker.manage')
  const invalidate = [['ops-fleet'], ['ops-queue-depth']]
  const saturated = depth.data ? depth.data.queued > 0 && depth.data.available_slots === 0 : false

  return (
    <div className="mx-auto max-w-6xl space-y-6 p-4 sm:p-6">
      <PageHeader
        icon={Server}
        title="Worker fleet"
        description="The execution workers claiming agent work, their capacity, and the queue in front of them."
        backTo={ROUTES.OPS_OVERVIEW}
        backLabel="Release operations"
        actions={canManage ? (
          <Button
            variant="outline"
            onClick={() => guard.confirm({
              title: 'Sweep for dead workers',
              description:
                'Marks workers that stopped heartbeating as stopped, so their stranded executions can be recovered. Safe to run at any time — every live worker already does this on each tick.',
              confirmLabel: 'Run sweep',
              destructive: false,
              onConfirm: () => guard.run(
                () => operationsService.reapFleet(),
                { success: 'Stale worker sweep complete', invalidate }),
            })}
          >
            Sweep stale workers
          </Button>
        ) : undefined}
      />
      <OperationsNav />

      {depth.data ? (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <Tile label="Queued" value={depth.data.queued} emphasise={saturated} />
          <Tile label="Running" value={depth.data.running} />
          <Tile label="Capacity" value={depth.data.capacity} suffix={`${depth.data.workers_accepting_work} worker(s)`} />
          <Tile label="Free slots" value={depth.data.available_slots} />
        </div>
      ) : null}

      {saturated ? (
        <div role="alert" className="flex items-start gap-2 rounded-xl border border-warning/30 bg-warning/10 p-4 text-sm">
          <Waves className="mt-0.5 h-4 w-4 shrink-0 text-warning" aria-hidden />
          <span>
            <span className="font-medium text-foreground">The fleet is saturated.</span>{' '}
            <span className="text-muted-foreground">
              Work is queued and every slot is busy. Executions will wait until a slot frees or another worker starts.
            </span>
          </span>
        </div>
      ) : null}

      {cohorts.length > 0 ? (
        <Card>
          <CardHeader><CardTitle className="text-base">Capacity by cohort</CardTitle></CardHeader>
          <CardContent>
            <p className="mb-3 text-sm text-muted-foreground">
              A rolling deployment derives its step weights from exactly these numbers — a cohort holding
              8 of 10 slots produces a first step of 80%, not an invented 25%.
            </p>
            <div className="flex flex-wrap gap-2">
              {cohorts.map(([cohort, capacity]) => (
                <Badge key={cohort} variant="outline">
                  {cohort}: {capacity} slot{capacity === 1 ? '' : 's'}
                </Badge>
              ))}
            </div>
          </CardContent>
        </Card>
      ) : null}

      <Card>
        <CardHeader><CardTitle className="text-base">Registered workers</CardTitle></CardHeader>
        <CardContent className="p-0">
          {fleet.isLoading ? (
            <div className="flex justify-center p-10">
              <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
            </div>
          ) : workers.length === 0 ? (
            <EmptyState
              icon={Server}
              title="No workers registered"
              description="Start one with `python -m app.workers.runner`. The API process deliberately runs none — an execution worker spends real money on model calls."
            />
          ) : (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Worker</TableHead>
                    <TableHead>Cohort</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead>In flight</TableHead>
                    <TableHead>Host</TableHead>
                    <TableHead>Last heartbeat</TableHead>
                    {canManage ? <TableHead className="text-right">Actions</TableHead> : null}
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {workers.map((worker) => (
                    <TableRow key={worker.worker_id}>
                      <TableCell className="font-mono text-xs">{worker.worker_id}</TableCell>
                      <TableCell><Badge variant="outline">{worker.cohort}</Badge></TableCell>
                      <TableCell>
                        <Badge variant={WORKER_VARIANT[worker.status] ?? 'outline'}>
                          {worker.status}
                        </Badge>
                      </TableCell>
                      <TableCell className="text-muted-foreground">
                        {worker.active_count} / {worker.concurrency}
                      </TableCell>
                      <TableCell className="text-muted-foreground">{worker.hostname ?? '—'}</TableCell>
                      <TableCell className="whitespace-nowrap text-muted-foreground">
                        {formatMoment(worker.heartbeat_at)}
                      </TableCell>
                      {canManage ? (
                        <TableCell className="text-right">
                          {worker.status === 'RUNNING' ? (
                            <Button
                              variant="outline"
                              onClick={() => guard.confirm({
                                title: `Drain ${worker.worker_id}`,
                                description:
                                  'The worker stops claiming new work and finishes what it is already running. Executions in flight are not interrupted.',
                                confirmLabel: 'Drain worker',
                                destructive: false,
                                warnings: worker.active_count > 0
                                  ? [`${worker.active_count} execution(s) in flight will run to completion first.`]
                                  : undefined,
                                onConfirm: () => guard.run(
                                  () => operationsService.drainWorker(worker.worker_id),
                                  { success: `${worker.worker_id} is draining`, invalidate }),
                              })}
                            >
                              Drain
                            </Button>
                          ) : (
                            <span className="text-xs text-muted-foreground">—</span>
                          )}
                        </TableCell>
                      ) : null}
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>

      <ConfirmActionDialog request={guard.request} pending={guard.pending} onCancel={guard.cancel} />
    </div>
  )
}

function Tile({ label, value, suffix, emphasise }: {
  label: string; value: number; suffix?: string; emphasise?: boolean
}) {
  return (
    <Card className={emphasise ? 'border-warning/40' : undefined}>
      <CardContent className="p-4">
        <p className="text-sm text-muted-foreground">{label}</p>
        <p className={`mt-1 text-2xl font-semibold ${emphasise ? 'text-warning' : 'text-foreground'}`}>
          {value}
        </p>
        {suffix ? <p className="text-xs text-muted-foreground">{suffix}</p> : null}
      </CardContent>
    </Card>
  )
}
