import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Loader2, RefreshCw, ShieldCheck } from 'lucide-react'

import { EmptyState, PageHeader } from '@/components/common'
import {
  Badge, Button, Card, CardContent, CardHeader, CardTitle, Select,
} from '@/components/ui'
import { usePermissions } from '@/authorization'
import { ROUTES } from '@/constants/routes'
import { operationsService } from '@/services'
import type { GateFinding } from '@/services/operationsService'
import { ConfirmActionDialog } from './components/ConfirmActionDialog'
import { OperationsNav } from './components/OperationsNav'
import {
  GateBadge,
} from './components/state'
import { formatMoment } from './components/format'
import { useGuardedAction } from './useGuardedAction'

/**
 * Phase 3.10 view 8 — Health Gates (M3-3.10-FR-007).
 *
 * The release gate's verdict for a deployment, its findings, and what to do
 * about each one.
 *
 * **A BLOCK is never softened.** §10 forbids presenting a blocked release as
 * deployable, and the temptation this screen has to resist is summarising
 * three findings as "1 issue" — which invites the reader to treat it as a
 * formality. Every finding is listed at full severity, with its remediation,
 * because the remediation is the only part that is actionable.
 *
 * Re-running preflight is offered because a BLOCK is frequently stale: an
 * operator fixes the cause and needs to know whether the gate agrees. It is
 * confirmation-free — evaluating is read-only in effect, and gating a harmless
 * refresh would train people to click through the dialogs that matter.
 */
export function HealthGatesPage() {
  const { can } = usePermissions()
  const guard = useGuardedAction()
  const [deploymentId, setDeploymentId] = useState('')

  const overview = useQuery({
    queryKey: ['ops-overview', ''],
    queryFn: () => operationsService.overview(),
  })
  const preflight = useQuery({
    queryKey: ['ops-preflight', deploymentId],
    queryFn: () => operationsService.preflight(deploymentId),
    enabled: Boolean(deploymentId),
  })
  const history = useQuery({
    queryKey: ['ops-preflight-history', deploymentId],
    queryFn: () => operationsService.preflightHistory(deploymentId),
    enabled: Boolean(deploymentId),
  })

  const rows = overview.data?.deployments ?? []
  const selected = rows.find((r) => r.deployment_id === deploymentId)
  const findings = preflight.data?.findings ?? []
  const blocking = findings.filter((f) => f.severity === 'BLOCK')
  const warnings = findings.filter((f) => f.severity === 'WARNING')

  return (
    <div className="mx-auto max-w-5xl space-y-6 p-4 sm:p-6">
      <PageHeader
        icon={ShieldCheck}
        title="Health gates"
        description="The release gate's verdict, every finding behind it, and how to clear each one."
        backTo={ROUTES.OPS_OVERVIEW}
        backLabel="Release operations"
        actions={
          <Select
            aria-label="Select a deployment"
            value={deploymentId}
            onChange={(e) => setDeploymentId(e.target.value)}
            placeholder="Select a deployment…"
            options={rows.map((row) => ({
              value: row.deployment_id,
              label: `${row.agent_name} — ${row.environment_name} — ${row.version?.semantic_version ?? '?'}`,
            }))}
          />
        }
      />
      <OperationsNav />

      {!deploymentId ? (
        <Card>
          <CardContent className="p-0">
            <EmptyState
              icon={ShieldCheck}
              title="Choose a deployment"
              description="Every deployment carries a preflight verdict: PASS, WARNING or BLOCK, with the findings behind it."
            />
          </CardContent>
        </Card>
      ) : (
        <>
          <Card>
            <CardHeader>
              <CardTitle className="flex flex-wrap items-center gap-3 text-base">
                <span>{selected?.agent_name} — {selected?.environment_name}</span>
                <GateBadge verdict={preflight.data?.verdict} />
                {can('runtime.deployment.deploy') ? (
                  <Button
                    variant="outline"
                    className="ml-auto"
                    onClick={() => guard.run(
                      () => operationsService.runPreflight(deploymentId),
                      {
                        success: 'Preflight re-evaluated',
                        invalidate: [['ops-preflight', deploymentId],
                                     ['ops-preflight-history', deploymentId],
                                     ['ops-overview', '']],
                      })}
                  >
                    <RefreshCw className="mr-1.5 h-4 w-4" aria-hidden />
                    Re-run preflight
                  </Button>
                ) : null}
              </CardTitle>
            </CardHeader>
            <CardContent>
              {preflight.isLoading ? (
                <div className="flex justify-center p-6">
                  <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
                </div>
              ) : !preflight.data ? (
                <p className="text-sm text-muted-foreground">
                  No preflight has been run for this deployment yet. That is not the same as a pass —
                  run one to find out.
                </p>
              ) : (
                <div className="space-y-4">
                  <p className="text-sm text-muted-foreground">
                    Evaluated {formatMoment(preflight.data.evaluated_at)} ·{' '}
                    {blocking.length} blocking, {warnings.length} warning,{' '}
                    {findings.length - blocking.length - warnings.length} passing.
                  </p>
                  {blocking.length > 0 ? (
                    <Section title="Blocking" tone="destructive" findings={blocking} />
                  ) : null}
                  {warnings.length > 0 ? (
                    <Section title="Warnings" tone="warning" findings={warnings} />
                  ) : null}
                  {findings.length - blocking.length - warnings.length > 0 ? (
                    <Section
                      title="Passing"
                      tone="success"
                      findings={findings.filter((f) => f.severity !== 'BLOCK' && f.severity !== 'WARNING')}
                    />
                  ) : null}
                </div>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader><CardTitle className="text-base">Verdict history</CardTitle></CardHeader>
            <CardContent>
              {(history.data ?? []).length === 0 ? (
                <p className="text-sm text-muted-foreground">No previous evaluations.</p>
              ) : (
                <ul className="space-y-2">
                  {(history.data ?? []).map((entry, index) => (
                    <li key={entry.id ?? index} className="flex items-center gap-3 text-sm">
                      <GateBadge verdict={entry.verdict} />
                      <span className="text-muted-foreground">{formatMoment(entry.evaluated_at)}</span>
                      <span className="text-muted-foreground">
                        {(entry.findings ?? []).filter((f) => f.severity === 'BLOCK').length} blocking
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </CardContent>
          </Card>
        </>
      )}

      <ConfirmActionDialog request={guard.request} pending={guard.pending} onCancel={guard.cancel} />
    </div>
  )
}

function Section({ title, tone, findings }: {
  title: string; tone: 'destructive' | 'warning' | 'success'; findings: GateFinding[]
}) {
  return (
    <div className="space-y-2">
      <h3 className="text-sm font-semibold text-foreground">{title}</h3>
      {findings.map((finding, index) => (
        <div
          key={`${finding.code}-${index}`}
          className={`rounded-lg border p-3 ${
            tone === 'destructive' ? 'border-destructive/30 bg-destructive/5'
              : tone === 'warning' ? 'border-warning/30 bg-warning/5' : ''
          }`}
        >
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant={tone}>{String(finding.severity)}</Badge>
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
    </div>
  )
}
