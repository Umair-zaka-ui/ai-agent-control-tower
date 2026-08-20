import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { ArrowRight, CheckCircle2, GitBranch, Loader2 } from 'lucide-react'

import { EmptyState, PageHeader } from '@/components/common'
import { Badge, Button, Card, CardContent, CardHeader, CardTitle, Select } from '@/components/ui'
import { ROUTES } from '@/constants/routes'
import { operationsService } from '@/services'
import { ConfirmActionDialog } from './components/ConfirmActionDialog'
import { OperationsNav } from './components/OperationsNav'
import {
  BlockerBanner, GateBadge, HealthBadge,
} from './components/state'
import { blockersFor } from './components/format'
import { useGuardedAction } from './useGuardedAction'

/**
 * Phase 3.10 view 9 — Promotion Wizard (M3-3.10-FR-008).
 *
 * Pick a deployment, pick a target environment on a configured promotion path,
 * see everything that argues against promoting, then confirm.
 *
 * **The blockers are shown before the button, deliberately.** A promotion
 * wizard whose final step is a summary and a green button teaches people to
 * skim to the button. Here the middle step *is* the argument against: gate
 * verdict, health, kill switch. If there is nothing to worry about, the step
 * says so in one line and the operator moves on in the same number of clicks.
 *
 * Promoting into a production environment requires typing the environment
 * name. Everything else is a single confirm — friction that applies everywhere
 * equally is friction nobody reads.
 *
 * Dispatches to Phase 3.2's `POST /deployments/{id}/promote`, which enforces
 * the promotion path, the approval requirement and version immutability. This
 * wizard checks none of that itself.
 */
export function PromotionWizardPage() {
  const guard = useGuardedAction()
  const [deploymentId, setDeploymentId] = useState('')
  const [targetEnvironmentId, setTargetEnvironmentId] = useState('')

  const overview = useQuery({
    queryKey: ['ops-overview', ''],
    queryFn: () => operationsService.overview(),
  })
  const paths = useQuery({
    queryKey: ['ops-promotion-paths'],
    queryFn: () => operationsService.promotionPaths(),
  })

  const rows = overview.data?.deployments ?? []
  const environments = overview.data?.environments ?? []
  const source = rows.find((r) => r.deployment_id === deploymentId)

  // Only environments reachable from the source's own environment by a
  // configured path. Offering the rest would be offering an action the server
  // will refuse (M3-3.10-FR-023).
  const reachable = source?.environment_id
    ? (paths.data ?? [])
        .filter((p) => p.from_environment_id === source.environment_id)
        .map((p) => ({
          env: environments.find((e) => e.id === p.to_environment_id),
          requiresApproval: p.requires_approval,
        }))
        .filter((entry): entry is { env: NonNullable<typeof environments[number]>; requiresApproval: boolean } =>
          Boolean(entry.env))
    : []

  const target = reachable.find((entry) => entry.env.id === targetEnvironmentId)
  const blockers = source ? blockersFor(source) : []

  return (
    <div className="mx-auto max-w-4xl space-y-6 p-4 sm:p-6">
      <PageHeader
        icon={GitBranch}
        title="Promote a deployment"
        description="Move a proven version along a configured promotion path — with everything that argues against it shown first."
        backTo={ROUTES.OPS_OVERVIEW}
        backLabel="Release operations"
      />
      <OperationsNav />

      <Card>
        <CardHeader><CardTitle className="text-base">1 · What are you promoting?</CardTitle></CardHeader>
        <CardContent>
          <Select
            aria-label="Deployment to promote"
            value={deploymentId}
            onChange={(e) => { setDeploymentId(e.target.value); setTargetEnvironmentId('') }}
            placeholder="Select a deployment…"
            options={rows.map((row) => ({
              value: row.deployment_id,
              label: `${row.agent_name} — ${row.version?.semantic_version ?? '?'} in ${row.environment_name}`,
            }))}
          />
        </CardContent>
      </Card>

      {source ? (
        <>
          <Card>
            <CardHeader><CardTitle className="text-base">2 · Is it safe to promote?</CardTitle></CardHeader>
            <CardContent className="space-y-3">
              <div className="flex flex-wrap items-center gap-2">
                <GateBadge verdict={source.gate_verdict} />
                <HealthBadge health={source.release_health} />
                <Badge variant={source.version?.signature_state === 'SIGNED' ? 'success' : 'warning'}>
                  {source.version?.signature_state ?? 'UNKNOWN'}
                </Badge>
              </div>
              {blockers.length === 0 ? (
                <p className="flex items-center gap-2 text-sm text-success">
                  <CheckCircle2 className="h-4 w-4" aria-hidden />
                  Nothing is arguing against this promotion.
                </p>
              ) : (
                <BlockerBanner blockers={blockers} />
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader><CardTitle className="text-base">3 · Where to?</CardTitle></CardHeader>
            <CardContent className="space-y-3">
              {paths.isLoading ? (
                <div className="flex justify-center p-4">
                  <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
                </div>
              ) : reachable.length === 0 ? (
                <EmptyState
                  icon={GitBranch}
                  title="No promotion path from here"
                  description="Promotion follows configured paths between environments. Configure one before promoting out of this environment."
                />
              ) : (
                <>
                  <div className="flex flex-wrap items-center gap-2 text-sm">
                    <Badge variant="outline">{source.environment_name}</Badge>
                    <ArrowRight className="h-4 w-4 text-muted-foreground" aria-hidden />
                    <Select
                      aria-label="Target environment"
                      value={targetEnvironmentId}
                      onChange={(e) => setTargetEnvironmentId(e.target.value)}
                      placeholder="Select a target…"
                      options={reachable.map((entry) => ({
                        value: entry.env.id,
                        label: `${entry.env.display_name || entry.env.name}`
                          + (entry.env.is_production ? ' (production)' : '')
                          + (entry.requiresApproval ? ' — requires approval' : ''),
                      }))}
                    />
                  </div>
                  {target?.requiresApproval ? (
                    <p className="text-sm text-muted-foreground">
                      This path requires approval. The promotion will be created pending review rather than
                      taking effect immediately.
                    </p>
                  ) : null}
                  <Button
                    disabled={!target}
                    onClick={() => target && guard.confirm({
                      title: `Promote to ${target.env.display_name || target.env.name}`,
                      description: target.env.is_production
                        ? 'This puts the version in front of production traffic. The promoted version is immutable — the same signed artifact moves forward, it is not rebuilt.'
                        : 'The same immutable version is promoted forward along the configured path.',
                      confirmLabel: 'Promote',
                      // Type-to-confirm only where it earns its friction.
                      typeToConfirm: target.env.is_production
                        ? (target.env.display_name || target.env.name) : undefined,
                      destructive: target.env.is_production,
                      warnings: [
                        ...blockers.map((b) => `${b.label}: ${b.detail}`),
                        ...(target.requiresApproval
                          ? ['This path requires approval — the promotion will await review.'] : []),
                      ],
                      onConfirm: () => guard.run(
                        () => operationsService.promote(deploymentId, target.env.id),
                        { success: 'Promotion requested', invalidate: [['ops-overview', '']] }),
                    })}
                  >
                    Promote…
                  </Button>
                </>
              )}
            </CardContent>
          </Card>
        </>
      ) : null}

      <ConfirmActionDialog request={guard.request} pending={guard.pending} onCancel={guard.cancel} />
    </div>
  )
}
