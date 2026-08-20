import { useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { ChevronRight, Loader2, OctagonX, PauseCircle, PlayCircle, Rocket, RotateCcw } from 'lucide-react'

import { PageHeader } from '@/components/common'
import { Badge, Button, Card, CardContent, CardHeader, CardTitle } from '@/components/ui'
import { usePermissions } from '@/authorization'
import { ROUTES } from '@/constants/routes'
import { operationsService } from '@/services'
import type { ReleaseHealth } from '@/services/operationsService'
import { ConfirmActionDialog } from './components/ConfirmActionDialog'
import { OperationsNav } from './components/OperationsNav'
import {
  HealthBadge, RolloutStateBadge,
} from './components/state'
import { formatMoment } from './components/format'
import { useGuardedAction } from './useGuardedAction'

const TERMINAL = new Set(['SUCCEEDED', 'ABORTED', 'ROLLBACK_REQUESTED', 'FAILED'])

/**
 * Phase 3.10 view 6 — Canary Dashboard (M3-3.10-FR-005).
 *
 * One rollout: its stages, the weight each targets, which one is current, the
 * health verdict behind it, and the four controls — advance, pause, resume,
 * abort — plus request-rollback.
 *
 * **Every control triggers Phase 3.5's engine; none of them decides
 * anything.** The advance button does not check the stage gates: the server
 * does, and refuses with `ROLLOUT_STAGE_GATE_NOT_MET` if they are not met.
 * That refusal is surfaced verbatim rather than pre-empted, because a UI that
 * predicted the gate would eventually predict it wrong — and a disabled button
 * that should have been enabled is just as damaging during an incident as the
 * reverse.
 *
 * Health is shown next to the stage it governs. A stage requiring HEALTHY
 * cannot clear on `INSUFFICIENT_DATA`, and the badge says so rather than
 * rendering "no data" as neutral.
 */
export function CanaryDashboardPage() {
  const { id = '' } = useParams()
  const { can } = usePermissions()
  const guard = useGuardedAction()

  const rollout = useQuery({
    queryKey: ['ops-rollout', id],
    queryFn: () => operationsService.rollout(id),
    enabled: Boolean(id),
    refetchInterval: 15_000,
  })
  const health = useQuery({
    queryKey: ['ops-rollout-health', id],
    queryFn: () => operationsService.rolloutHealth(id),
    enabled: Boolean(id),
    refetchInterval: 15_000,
  })

  const plan = rollout.data
  const invalidate = [['ops-rollout', id], ['ops-rollout-health', id], ['ops-rollouts', true], ['ops-overview', '']]
  const canDeploy = can('runtime.deployment.deploy')
  const canRollback = can('runtime.deployment.rollback')

  if (rollout.isLoading) {
    return <div className="flex justify-center p-16"><Loader2 className="h-6 w-6 animate-spin text-muted-foreground" /></div>
  }
  if (!plan) {
    return (
      <div className="mx-auto max-w-4xl p-4 sm:p-6">
        <PageHeader title="Rollout not found" backTo={ROUTES.OPS_ROLLOUTS} backLabel="Rollouts" />
      </div>
    )
  }

  const live = !TERMINAL.has(plan.state)
  const verdict = (health.data ?? null) as (ReleaseHealth & Record<string, unknown>) | null
  const stages = plan.stages ?? []
  const currentStage = stages.find((s) => s.stage_index === plan.current_stage_index)

  return (
    <div className="mx-auto max-w-5xl space-y-6 p-4 sm:p-6">
      <PageHeader
        icon={Rocket}
        title={`${plan.kind ?? 'CANARY'} rollout`}
        description={`Stage ${plan.current_stage_index + 1} of ${stages.length} · revision ${plan.revision}`}
        backTo={ROUTES.OPS_ROLLOUTS}
        backLabel="Rollouts"
        actions={
          <div className="flex flex-wrap gap-2">
            {live && plan.state === 'IN_PROGRESS' && canDeploy ? (
              <>
                <Button
                  onClick={() => guard.confirm({
                    title: 'Advance to the next stage',
                    description:
                      'The candidate moves to the next stage weight. The server evaluates this stage’s duration, sample and health gates and will refuse if they are not met.',
                    confirmLabel: 'Advance rollout',
                    destructive: false,
                    warnings: currentStage
                      ? [`This stage requires health at least ${currentStage.health_requirement}` +
                         (currentStage.min_samples ? ` over ${currentStage.min_samples} sample(s).` : '.')]
                      : undefined,
                    onConfirm: () => guard.run(
                      () => operationsService.advanceRollout(id),
                      { success: 'Rollout advanced', invalidate }),
                  })}
                >
                  <ChevronRight className="mr-1.5 h-4 w-4" aria-hidden />
                  Advance
                </Button>
                <Button
                  variant="outline"
                  onClick={() => guard.confirm({
                    title: 'Pause this rollout',
                    description: 'Traffic stays exactly where it is. Nothing advances until it is resumed.',
                    confirmLabel: 'Pause rollout',
                    requireReason: true,
                    destructive: false,
                    onConfirm: (reason) => guard.run(
                      () => operationsService.pauseRollout(id, reason),
                      { success: 'Rollout paused', invalidate }),
                  })}
                >
                  <PauseCircle className="mr-1.5 h-4 w-4" aria-hidden />
                  Pause
                </Button>
              </>
            ) : null}

            {plan.state === 'PAUSED' && canDeploy ? (
              <Button
                variant="outline"
                onClick={() => guard.confirm({
                  title: 'Resume this rollout',
                  description: 'The rollout returns to IN_PROGRESS at its current stage. It does not advance by itself.',
                  confirmLabel: 'Resume rollout',
                  requireReason: true,
                  destructive: false,
                  onConfirm: (reason) => guard.run(
                    () => operationsService.resumeRollout(id, reason),
                    { success: 'Rollout resumed', invalidate }),
                })}
              >
                <PlayCircle className="mr-1.5 h-4 w-4" aria-hidden />
                Resume
              </Button>
            ) : null}

            {live && canDeploy ? (
              <Button
                variant="destructive"
                onClick={() => guard.confirm({
                  title: 'Abort this rollout',
                  description:
                    'The rollout stops permanently. Aborting is terminal — it cannot be resumed, and traffic is left exactly where it is now.',
                  confirmLabel: 'Abort rollout',
                  typeToConfirm: 'ABORT',
                  requireReason: true,
                  warnings: [
                    'Aborting leaves the candidate holding whatever traffic it currently has. If you want traffic returned to the stable version, request a rollback instead.',
                  ],
                  onConfirm: (reason) => guard.run(
                    () => operationsService.abortRollout(id, reason),
                    { success: 'Rollout aborted', invalidate }),
                })}
              >
                <OctagonX className="mr-1.5 h-4 w-4" aria-hidden />
                Abort
              </Button>
            ) : null}

            {live && canRollback ? (
              <Button
                variant="destructive"
                onClick={() => guard.confirm({
                  title: 'Request rollback',
                  description: 'Traffic returns to the stable version through the audited allocation. The rollout ends.',
                  confirmLabel: 'Roll back now',
                  typeToConfirm: 'ROLLBACK',
                  requireReason: true,
                  onConfirm: (reason) => guard.run(
                    () => operationsService.requestRolloutRollback(id, reason),
                    { success: 'Rollback requested', invalidate }),
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

      <div className="flex flex-wrap items-center gap-3">
        <RolloutStateBadge state={plan.state} />
        {verdict?.health_state ? <HealthBadge health={verdict} /> : null}
        {plan.state_reason ? (
          <span className="text-sm text-muted-foreground">{plan.state_reason}</span>
        ) : null}
      </div>

      <Card>
        <CardHeader><CardTitle className="text-base">Stages</CardTitle></CardHeader>
        <CardContent className="space-y-2">
          {stages.length === 0 ? (
            <p className="text-sm text-muted-foreground">This rollout declares no stages.</p>
          ) : stages.map((stage) => {
            const isCurrent = stage.stage_index === plan.current_stage_index
            const isDone = stage.stage_index < plan.current_stage_index
            return (
              <div
                key={stage.stage_index}
                className={`rounded-xl border p-3 ${isCurrent ? 'border-primary/40 bg-primary/5' : ''}`}
              >
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="flex items-center gap-2">
                    <span className={`text-sm font-medium ${isDone ? 'text-muted-foreground line-through' : ''}`}>
                      Stage {stage.stage_index}
                    </span>
                    <Badge variant={isCurrent ? 'default' : 'outline'}>{stage.target_weight}% candidate</Badge>
                    {isCurrent ? <Badge variant="default">current</Badge> : null}
                    {isDone ? <Badge variant="success">cleared</Badge> : null}
                  </div>
                  <span className="text-xs text-muted-foreground">
                    {stage.entered_at ? `entered ${formatMoment(stage.entered_at)}` : 'not entered'}
                  </span>
                </div>
                <div className="mt-2 h-2 overflow-hidden rounded-full bg-muted">
                  <div className="h-full rounded-full bg-primary" style={{ width: `${stage.target_weight}%` }} />
                </div>
                <p className="mt-2 text-xs text-muted-foreground">
                  Gates: health ≥ {stage.health_requirement}
                  {stage.min_samples ? ` · ≥ ${stage.min_samples} samples` : ''}
                  {stage.min_duration_seconds ? ` · ≥ ${stage.min_duration_seconds}s in stage` : ''}
                  {' · '}{stage.advance_mode.toLowerCase()} advance
                </p>
              </div>
            )
          })}
        </CardContent>
      </Card>

      {plan.cohort_plan ? (
        <Card>
          <CardHeader><CardTitle className="text-base">Worker cohorts</CardTitle></CardHeader>
          <CardContent>
            <p className="mb-2 text-sm text-muted-foreground">
              This rolling deployment&rsquo;s step weights were derived from real fleet capacity at the moment it
              started — not from an invented ladder.
            </p>
            <pre className="overflow-x-auto rounded-lg bg-muted p-3 text-xs">
              {JSON.stringify(plan.cohort_plan, null, 2)}
            </pre>
          </CardContent>
        </Card>
      ) : null}

      {verdict ? (
        <Card>
          <CardHeader><CardTitle className="text-base">Release health</CardTitle></CardHeader>
          <CardContent>
            <div className="mb-2 flex items-center gap-2">
              <HealthBadge health={verdict} />
              {verdict.sample_count !== undefined ? (
                <span className="text-sm text-muted-foreground">
                  {verdict.sample_count} sample(s) observed
                </span>
              ) : null}
            </div>
            <pre className="overflow-x-auto rounded-lg bg-muted p-3 text-xs">
              {JSON.stringify(verdict, null, 2)}
            </pre>
          </CardContent>
        </Card>
      ) : null}

      <ConfirmActionDialog request={guard.request} pending={guard.pending} onCancel={guard.cancel} />
    </div>
  )
}
