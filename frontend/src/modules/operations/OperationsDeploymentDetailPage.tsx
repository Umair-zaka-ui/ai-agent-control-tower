import { Link, useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { FileCheck2, Loader2, PauseCircle, PlayCircle, Rocket, RotateCcw, ShieldCheck } from 'lucide-react'

import { PageHeader } from '@/components/common'
import {
  Badge, Button, Card, CardContent, CardHeader, CardTitle, Separator,
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui'
import { usePermissions } from '@/authorization'
import { ROUTES } from '@/constants/routes'
import { operationsService } from '@/services'
import { ConfirmActionDialog } from './components/ConfirmActionDialog'
import { OperationsNav } from './components/OperationsNav'
import {
  BlockerBanner, GateBadge, HealthBadge, KillSwitchBadge, LifecycleBadge, RolloutStateBadge, ServingBadge,
} from './components/state'
import { blockersFor, formatDuration, formatMoment } from './components/format'
import { useGuardedAction } from './useGuardedAction'

/**
 * Phase 3.10 view 4 — Deployment Detail (M3-3.10-FR-004, FR-024).
 *
 * §22's full field set on one screen: the agent, the immutable version with
 * its checksum and signature state, the environment, strategy, lifecycle
 * state, current rollout stage, traffic allocation, release health, approvals,
 * who started it, when, how long it ran, its rollback target, and the complete
 * event timeline.
 *
 * **Blockers come first, above everything.** Not because they are the most
 * common case, but because this is the screen an operator opens during an
 * incident, and the one arrangement that must never happen is a reassuring
 * summary at the top with "kill switch active" somewhere below the fold.
 *
 * The version identity block exists to answer one question precisely: *is what
 * is running the signed, reviewed artifact we approved?* An unsigned version
 * is called out rather than left as an absent field, because a missing
 * signature reads as "not shown" when it actually means "not signed".
 *
 * Fed by `GET /runtime/operations/deployments/{id}` — one request for what
 * would otherwise be eight, so the screen cannot render in a half-loaded state
 * where the health block has arrived and the kill-switch banner has not.
 */
export function OperationsDeploymentDetailPage() {
  const { id = '' } = useParams()
  const { can } = usePermissions()
  const guard = useGuardedAction()

  const detail = useQuery({
    queryKey: ['ops-deployment-detail', id],
    queryFn: () => operationsService.deploymentDetail(id),
    enabled: Boolean(id),
    refetchInterval: 30_000,
  })

  const data = detail.data
  const invalidate = [['ops-deployment-detail', id], ['ops-overview', '']]

  if (detail.isLoading) {
    return (
      <div className="flex justify-center p-16">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
      </div>
    )
  }
  if (!data) {
    return (
      <div className="mx-auto max-w-4xl space-y-6 p-4 sm:p-6">
        <PageHeader
          title="Deployment not found"
          description="It may have been removed, or belong to another organization."
          backTo={ROUTES.OPS_OVERVIEW}
          backLabel="Release operations"
        />
      </div>
    )
  }

  const blockers = blockersFor({
    kill_switch_active: data.kill_switch_active,
    gate_verdict: (data.gate?.verdict ?? null) as never,
    release_health: data.release_health,
    lifecycle_state: data.lifecycle_state,
    servable: data.servable,
  })

  const canDeploy = can('runtime.deployment.deploy')
  const canRollback = can('runtime.deployment.rollback')

  return (
    <div className="mx-auto max-w-6xl space-y-6 p-4 sm:p-6">
      <PageHeader
        icon={Rocket}
        title={data.agent.name ?? 'Deployment'}
        description={`${data.version?.semantic_version ?? 'unknown version'} in ${data.environment.name ?? 'no environment'} · ${data.deployment_strategy}`}
        backTo={ROUTES.OPS_OVERVIEW}
        backLabel="Release operations"
        actions={
          <div className="flex flex-wrap gap-2">
            {data.lifecycle_state === 'ACTIVE' && canDeploy ? (
              <Button
                variant="outline"
                onClick={() => guard.confirm({
                  title: 'Pause this deployment',
                  description: 'It stops receiving new work. Executions already running finish normally.',
                  confirmLabel: 'Pause deployment',
                  requireReason: true,
                  destructive: false,
                  onConfirm: (reason) => guard.run(
                    () => operationsService.pauseDeployment(id, reason),
                    { success: 'Deployment paused', invalidate }),
                })}
              >
                <PauseCircle className="mr-1.5 h-4 w-4" aria-hidden />
                Pause
              </Button>
            ) : null}
            {data.lifecycle_state === 'PAUSED' && canDeploy ? (
              <Button
                variant="outline"
                onClick={() => guard.confirm({
                  title: 'Resume this deployment',
                  description: 'It starts receiving work again at its current traffic weight.',
                  confirmLabel: 'Resume deployment',
                  requireReason: true,
                  destructive: false,
                  onConfirm: (reason) => guard.run(
                    () => operationsService.resumeDeployment(id, reason),
                    { success: 'Deployment resumed', invalidate }),
                })}
              >
                <PlayCircle className="mr-1.5 h-4 w-4" aria-hidden />
                Resume
              </Button>
            ) : null}
            {canRollback ? (
              <Button
                variant="destructive"
                onClick={() => guard.confirm({
                  title: `Roll back to ${data.rollback_target?.semantic_version ?? 'the designated target'}`,
                  description:
                    'Traffic returns to the designated rollback target through the same audited allocation every other release uses. This is immediate.',
                  confirmLabel: 'Roll back now',
                  typeToConfirm: data.environment.name ?? undefined,
                  requireReason: true,
                  warnings: [
                    data.rollback_target
                      ? `Target: ${data.rollback_target.semantic_version} (${data.rollback_target.signature_state.toLowerCase()}).`
                      : 'No rollback target is designated. The server will refuse rather than roll back to a guess.',
                    ...(data.kill_switch_active
                      ? ['A kill switch is active on this agent. A manual rollback is still permitted — automation is not.']
                      : []),
                  ],
                  onConfirm: (reason) => guard.run(
                    () => operationsService.executeRollback(id, reason),
                    { success: 'Rollback executed', invalidate }),
                })}
              >
                <RotateCcw className="mr-1.5 h-4 w-4" aria-hidden />
                Roll back
              </Button>
            ) : null}
          </div>
        }
      />
      <OperationsNav />

      <BlockerBanner blockers={blockers} />

      <div className="grid gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader><CardTitle className="text-base">Deployment</CardTitle></CardHeader>
          <CardContent className="grid gap-x-6 gap-y-4 sm:grid-cols-2">
            <Field label="Lifecycle state"><LifecycleBadge state={data.lifecycle_state} /></Field>
            <Field label="Legacy status"><Badge variant="outline">{data.status}</Badge></Field>
            <Field label="Strategy"><Badge variant="outline">{data.deployment_strategy}</Badge></Field>
            <Field label="Environment">
              <Badge variant={data.environment.is_production ? 'warning' : 'outline'}>
                {data.environment.name}
              </Badge>
            </Field>
            <Field label="Serving">
              <ServingBadge servable={data.servable} weight={null} />
            </Field>
            <Field label="Kill switch"><KillSwitchBadge active={data.kill_switch_active} />
              {!data.kill_switch_active ? <span className="text-muted-foreground">None</span> : null}
            </Field>
            <Field label="Release health"><HealthBadge health={data.release_health} /></Field>
            <Field label="Release gate"><GateBadge verdict={data.gate?.verdict} /></Field>
            <Field label="Started by">
              <span className="font-mono text-xs">
                {data.initiated_by ? data.initiated_by.slice(0, 8) : 'automation'}
              </span>
            </Field>
            <Field label="Deployed at">{formatMoment(data.deployed_at)}</Field>
            <Field label="Duration">{formatDuration(data.duration_seconds)}</Field>
            <Field label="Revision">{data.revision}</Field>
            {data.state_reason ? (
              <div className="sm:col-span-2">
                <Field label="State reason">{data.state_reason}</Field>
              </div>
            ) : null}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <ShieldCheck className="h-4 w-4" aria-hidden />
              Version identity
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            {data.version ? (
              <>
                <Field label="Version">
                  <span className="font-mono">{data.version.semantic_version}</span>{' '}
                  <Badge variant="outline">{data.version.status}</Badge>
                </Field>
                <Field label="Signature">
                  {data.version.signature_state === 'SIGNED' ? (
                    <Badge variant="success">SIGNED</Badge>
                  ) : (
                    <Badge
                      variant="warning"
                      title="This artifact carries no signature. It is not the same as a signature that failed — it was never signed."
                    >
                      UNSIGNED
                    </Badge>
                  )}
                </Field>
                <Field label={`Checksum (${data.version.checksum_algorithm ?? 'unknown'})`}>
                  <code className="block break-all rounded bg-muted px-2 py-1 text-xs">
                    {data.version.checksum ?? '—'}
                  </code>
                </Field>
                {data.version.signed_at ? (
                  <Field label="Signed at">{formatMoment(data.version.signed_at)}</Field>
                ) : null}
                {data.version.manifest_digest ? (
                  <Field label="Manifest digest">
                    <code className="block break-all rounded bg-muted px-2 py-1 text-xs">
                      {data.version.manifest_digest}
                    </code>
                  </Field>
                ) : null}
                <Separator />
                <Field label="Rollback target">
                  {data.rollback_target ? (
                    <span className="font-mono">{data.rollback_target.semantic_version}</span>
                  ) : (
                    <span
                      className="text-warning"
                      title="With no designated target, a rollback fails closed rather than returning to a guess."
                    >
                      Not designated
                    </span>
                  )}
                </Field>
              </>
            ) : <p className="text-sm text-muted-foreground">No version record.</p>}
          </CardContent>
        </Card>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader><CardTitle className="text-base">Traffic allocation</CardTitle></CardHeader>
          <CardContent>
            {data.allocation ? (
              <div className="space-y-3">
                <p className="text-xs text-muted-foreground">
                  Revision {data.allocation.revision} · {formatMoment(data.allocation.updated_at)}
                </p>
                {data.allocation.weights.map((w) => (
                  <div key={w.agent_version_id} className="space-y-1">
                    <div className="flex items-center justify-between text-sm">
                      <span className="font-mono">{w.semantic_version ?? w.agent_version_id.slice(0, 8)}</span>
                      <span className="font-medium">{w.weight}%</span>
                    </div>
                    <div className="h-2 overflow-hidden rounded-full bg-muted">
                      <div
                        className="h-full rounded-full bg-primary"
                        style={{ width: `${w.weight}%` }}
                        role="presentation"
                      />
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <p className="text-sm text-muted-foreground">
                No explicit allocation — this agent resolves to its single servable deployment.
              </p>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader><CardTitle className="text-base">Rollout</CardTitle></CardHeader>
          <CardContent>
            {data.rollout ? (
              <div className="space-y-3">
                <div className="flex flex-wrap items-center gap-2">
                  <Badge variant="outline">{data.rollout.kind}</Badge>
                  <RolloutStateBadge state={data.rollout.state} />
                  <Link
                    to={ROUTES.OPS_ROLLOUT_DETAIL.replace(':id', data.rollout.id)}
                    className="text-sm text-primary hover:underline"
                  >
                    Open rollout →
                  </Link>
                </div>
                <ol className="space-y-1.5">
                  {data.rollout.stages.map((stage) => {
                    const current = stage.stage_index === data.rollout!.current_stage_index
                    const done = stage.stage_index < data.rollout!.current_stage_index
                    return (
                      <li
                        key={stage.stage_index}
                        className={`flex items-center justify-between rounded-lg border px-3 py-2 text-sm ${
                          current ? 'border-primary/40 bg-primary/5' : ''
                        }`}
                      >
                        <span className={done ? 'text-muted-foreground line-through' : ''}>
                          Stage {stage.stage_index} — {stage.target_weight}%
                        </span>
                        {current ? <Badge variant="default">current</Badge> : null}
                      </li>
                    )
                  })}
                </ol>
              </div>
            ) : (
              <p className="text-sm text-muted-foreground">No rollout for this agent and environment.</p>
            )}
          </CardContent>
        </Card>
      </div>

      {data.gate && data.gate.findings.length > 0 ? (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <FileCheck2 className="h-4 w-4" aria-hidden />
              Release gate findings
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            {data.gate.findings.map((finding, index) => (
              <div key={`${finding.code}-${index}`} className="rounded-lg border p-3">
                <div className="flex flex-wrap items-center gap-2">
                  <Badge variant={
                    finding.severity === 'BLOCK' ? 'destructive'
                      : finding.severity === 'WARNING' ? 'warning' : 'success'
                  }>
                    {String(finding.severity)}
                  </Badge>
                  <code className="text-xs">{finding.code}</code>
                </div>
                {finding.message ? <p className="mt-1.5 text-sm">{finding.message}</p> : null}
                {finding.remediation ? (
                  <p className="mt-1 text-sm text-muted-foreground">
                    <span className="font-medium text-foreground">Remediation: </span>
                    {finding.remediation}
                  </p>
                ) : null}
              </div>
            ))}
          </CardContent>
        </Card>
      ) : null}

      {data.approvals.length > 0 ? (
        <Card>
          <CardHeader><CardTitle className="text-base">Approvals</CardTitle></CardHeader>
          <CardContent className="p-0">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Action</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Reviewed by</TableHead>
                  <TableHead>Comment</TableHead>
                  <TableHead>Requested</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.approvals.map((approval) => (
                  <TableRow key={approval.id}>
                    <TableCell>{approval.requested_action}</TableCell>
                    <TableCell><Badge variant="outline">{approval.status}</Badge></TableCell>
                    <TableCell className="font-mono text-xs">
                      {approval.reviewed_by?.slice(0, 8) ?? '—'}
                    </TableCell>
                    <TableCell className="text-muted-foreground">{approval.decision_comment ?? '—'}</TableCell>
                    <TableCell className="text-muted-foreground">{formatMoment(approval.created_at)}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      ) : null}

      <Card>
        <CardHeader><CardTitle className="text-base">Event timeline</CardTitle></CardHeader>
        <CardContent>
          {data.timeline.length === 0 ? (
            <p className="text-sm text-muted-foreground">No recorded events.</p>
          ) : (
            <ol className="space-y-0">
              {data.timeline.map((entry, index) => (
                <li key={`${entry.kind}-${entry.id}`} className="relative flex gap-3 pb-4 last:pb-0">
                  <div className="flex flex-col items-center">
                    <span className={`mt-1 h-2.5 w-2.5 shrink-0 rounded-full ${
                      entry.kind === 'ROLLBACK' ? 'bg-destructive' : 'bg-primary'
                    }`} />
                    {index < data.timeline.length - 1 ? (
                      <span className="w-px flex-1 bg-border" />
                    ) : null}
                  </div>
                  <div className="min-w-0 flex-1 pb-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="text-sm font-medium">{entry.event_type.replace(/_/g, ' ')}</span>
                      {entry.from_state ? (
                        <span className="text-xs text-muted-foreground">
                          {entry.from_state} → {entry.to_state}
                        </span>
                      ) : null}
                      <span className="text-xs text-muted-foreground">{formatMoment(entry.occurred_at)}</span>
                    </div>
                    {entry.reason ? (
                      <p className="mt-0.5 text-sm text-muted-foreground">{entry.reason}</p>
                    ) : null}
                  </div>
                </li>
              ))}
            </ol>
          )}
        </CardContent>
      </Card>

      <ConfirmActionDialog request={guard.request} pending={guard.pending} onCancel={guard.cancel} />
    </div>
  )
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1">
      <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{label}</p>
      <div className="text-sm text-foreground">{children}</div>
    </div>
  )
}
