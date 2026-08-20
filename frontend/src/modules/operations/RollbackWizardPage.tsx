import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { ArrowRight, Loader2, RotateCcw, ShieldAlert } from 'lucide-react'

import { EmptyState, PageHeader } from '@/components/common'
import {
  Badge, Button, Card, CardContent, CardHeader, CardTitle, Select,
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
 * Phase 3.10 view 10 — Rollback Wizard (M3-3.10-FR-008).
 *
 * Pick a deployment, see its designated rollback target and its rollback
 * history, confirm.
 *
 * **The target is shown, never chosen here.** Phase 3.7 made
 * `rollback_target_id` authoritative and fails closed when it is absent: no
 * designated target means the platform refuses rather than rolling back to a
 * guess, because a rollback to the wrong version looks exactly like a
 * successful one. This wizard therefore *displays* the target and, when there
 * isn't one, says so plainly instead of offering a version picker that would
 * quietly reintroduce the guess.
 *
 * The force path is separate, elevated, and requires a justification. It
 * bypasses the designated-target requirement — not the kill switch, which
 * nothing bypasses.
 */
export function RollbackWizardPage() {
  const { can } = usePermissions()
  const guard = useGuardedAction()
  const [deploymentId, setDeploymentId] = useState('')

  const overview = useQuery({
    queryKey: ['ops-overview', ''],
    queryFn: () => operationsService.overview(),
  })
  const detail = useQuery({
    queryKey: ['ops-deployment-detail', deploymentId],
    queryFn: () => operationsService.deploymentDetail(deploymentId),
    enabled: Boolean(deploymentId),
  })
  const history = useQuery({
    queryKey: ['ops-rollback-history', deploymentId],
    queryFn: () => operationsService.rollbackHistory(deploymentId),
    enabled: Boolean(deploymentId),
  })

  const rows = overview.data?.deployments ?? []
  const data = detail.data
  const target = data?.rollback_target
  const canForce = can('runtime.deployment.force_rollback')
  const invalidate = [['ops-deployment-detail', deploymentId],
                      ['ops-rollback-history', deploymentId], ['ops-overview', '']]

  return (
    <div className="mx-auto max-w-4xl space-y-6 p-4 sm:p-6">
      <PageHeader
        icon={RotateCcw}
        title="Roll back a deployment"
        description="Return traffic to the designated last-known-good version, through the same audited allocation every release uses."
        backTo={ROUTES.OPS_OVERVIEW}
        backLabel="Release operations"
      />
      <OperationsNav />

      <Card>
        <CardHeader><CardTitle className="text-base">1 · What is failing?</CardTitle></CardHeader>
        <CardContent>
          <Select
            aria-label="Deployment to roll back"
            value={deploymentId}
            onChange={(e) => setDeploymentId(e.target.value)}
            placeholder="Select a deployment…"
            options={rows.map((row) => ({
              value: row.deployment_id,
              label: `${row.agent_name} — ${row.version?.semantic_version ?? '?'} in ${row.environment_name}`,
            }))}
          />
        </CardContent>
      </Card>

      {deploymentId ? (
        <Card>
          <CardHeader><CardTitle className="text-base">2 · Where does it go back to?</CardTitle></CardHeader>
          <CardContent className="space-y-4">
            {detail.isLoading ? (
              <div className="flex justify-center p-6">
                <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
              </div>
            ) : !data ? null : (
              <>
                <div className="flex flex-wrap items-center gap-3 text-sm">
                  <Badge variant="outline" className="font-mono">
                    {data.version?.semantic_version ?? 'current'}
                  </Badge>
                  <ArrowRight className="h-4 w-4 text-muted-foreground" aria-hidden />
                  {target ? (
                    <Badge variant="success" className="font-mono">{target.semantic_version}</Badge>
                  ) : (
                    <Badge variant="destructive">No designated target</Badge>
                  )}
                </div>

                {data.kill_switch_active ? (
                  <div role="alert" className="flex items-start gap-2 rounded-lg border border-warning/30 bg-warning/10 p-3 text-sm">
                    <ShieldAlert className="mt-0.5 h-4 w-4 shrink-0 text-warning" aria-hidden />
                    <span>
                      <span className="font-medium text-foreground">A kill switch is active on this agent.</span>{' '}
                      <span className="text-muted-foreground">
                        A manual rollback is still permitted — a kill switch must never trap an operator on the
                        version they are leaving. Automatic rollback is what stands down.
                      </span>
                    </span>
                  </div>
                ) : null}

                {!target ? (
                  <p className="text-sm text-muted-foreground">
                    This version has no designated rollback target, so the platform will refuse rather than roll
                    back to a guess. Designate one on the version, or use a forced rollback if you have the
                    authority and can name the target yourself.
                  </p>
                ) : null}

                <div className="flex flex-wrap gap-2">
                  <Button
                    variant="destructive"
                    disabled={!target}
                    onClick={() => guard.confirm({
                      title: `Roll back to ${target?.semantic_version}`,
                      description:
                        'Traffic returns to the designated target immediately, through Phase 3.4’s audited allocator. The failing version is preserved with its metrics as evidence.',
                      confirmLabel: 'Roll back now',
                      typeToConfirm: data.environment.name ?? undefined,
                      requireReason: true,
                      warnings: [
                        `Target ${target?.semantic_version} is ${target?.signature_state.toLowerCase()}.`,
                        ...(data.environment.is_production
                          ? ['This is a production environment.'] : []),
                      ],
                      onConfirm: (reason) => guard.run(
                        () => operationsService.executeRollback(deploymentId, reason),
                        { success: 'Rollback executed', invalidate }),
                    })}
                  >
                    <RotateCcw className="mr-1.5 h-4 w-4" aria-hidden />
                    Roll back
                  </Button>

                  {canForce ? (
                    <Button
                      variant="outline"
                      onClick={() => guard.confirm({
                        title: 'Force a rollback',
                        description:
                          'A forced rollback bypasses the designated-target requirement and names its own target. It does not, and cannot, bypass the kill switch.',
                        confirmLabel: 'Force rollback',
                        typeToConfirm: 'FORCE',
                        requireReason: true,
                        reasonLabel: 'Justification (required, recorded as CRITICAL)',
                        warnings: [
                          'This is an override. It is audited as a dangerous operation and always carries your justification.',
                          target
                            ? `A designated target exists (${target.semantic_version}) — an ordinary rollback would work.`
                            : 'No designated target exists, which is why an ordinary rollback would refuse.',
                        ],
                        onConfirm: (reason) => guard.run(
                          () => operationsService.forceRollback(
                            deploymentId, target?.id ?? data.version?.id ?? '', reason),
                          { success: 'Forced rollback executed', invalidate }),
                      })}
                    >
                      Force rollback…
                    </Button>
                  ) : null}
                </div>
              </>
            )}
          </CardContent>
        </Card>
      ) : null}

      {deploymentId ? (
        <Card>
          <CardHeader><CardTitle className="text-base">Rollback history</CardTitle></CardHeader>
          <CardContent className="p-0">
            {(history.data ?? []).length === 0 ? (
              <EmptyState
                icon={RotateCcw}
                title="No rollbacks recorded"
                description="Every rollback of this deployment — manual, requested, automatic or forced — appears here."
              />
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Trigger</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead>Reason</TableHead>
                    <TableHead>By</TableHead>
                    <TableHead>When</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {(history.data ?? []).map((event) => (
                    <TableRow key={event.id}>
                      <TableCell>
                        <Badge variant={event.trigger === 'FORCED' ? 'destructive' : 'outline'}>
                          {event.trigger}
                        </Badge>
                      </TableCell>
                      <TableCell><Badge variant="outline">{event.status}</Badge></TableCell>
                      <TableCell className="max-w-xs truncate text-muted-foreground" title={event.reason ?? ''}>
                        {event.reason ?? '—'}
                      </TableCell>
                      <TableCell className="text-muted-foreground">
                        {event.initiated_by
                          ? <span className="font-mono text-xs">{event.initiated_by.slice(0, 8)}</span>
                          : 'automation'}
                      </TableCell>
                      <TableCell className="whitespace-nowrap text-muted-foreground">
                        {formatMoment(event.created_at)}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </CardContent>
        </Card>
      ) : null}

      <ConfirmActionDialog request={guard.request} pending={guard.pending} onCancel={guard.cancel} />
    </div>
  )
}
