import { useQuery } from '@tanstack/react-query'
import { useParams } from 'react-router-dom'
import { Boxes, Loader2 } from 'lucide-react'

import { PageHeader } from '@/components/common'
import { Button, Card, CardContent } from '@/components/ui'
import { usePermissions } from '@/authorization'
import { commandCenterService } from '@/services'
import type { PostureFinding } from '@/services/commandCenterService'
import { ConfirmActionDialog } from '@/modules/operations/components/ConfirmActionDialog'
import { useGuardedAction } from '@/modules/operations/useGuardedAction'
import { affordancesFor, signalFromModeRead } from './affordances'
import { GovernanceBadge, LoadError, ShadowReasons } from './components'

/**
 * Phase 5.8 — one agent, assembled from the 5.1–5.7 read models, and the
 * screen where the milestone's honesty either holds or breaks.
 *
 * **The containment button is rendered from `reaches_agent_execution`, which
 * the server computed.** Not from the mode name, not from a lookup table in
 * this file, not from `control_state === 'GOVERNED'` spelled a second time
 * here. Phase 5.6 proved ACT truthfully refuses containment for an agent it
 * does not run, and Phase 5.7 made the strongest mode underivable from
 * anything but the truth. If this page decided for itself when to show
 * "Suspend", it would be a fourth opinion — and the only one an operator
 * actually sees.
 *
 * So when containment is unavailable the page does not merely hide the button:
 * it says **why**, in the server's own sentence. A missing control with no
 * explanation reads as a broken feature; the explanation is what makes it read
 * as the truth it is.
 *
 * Composition here is react-query calling several existing endpoints — that is
 * orchestration, not logic. No aggregation endpoint was added for this view.
 */
export function AgentDrilldownPage() {
  const { agentId = '' } = useParams()
  const { can } = usePermissions()
  const guard = useGuardedAction()

  const agent = useQuery({
    queryKey: ['cc-agent', agentId],
    queryFn: () => commandCenterService.agent(agentId),
    enabled: Boolean(agentId),
  })
  const mode = useQuery({
    queryKey: ['cc-agent-mode', agentId],
    queryFn: () => commandCenterService.enforcementMode(agentId),
    enabled: Boolean(agentId) && can('external_governance.view'),
  })
  const shadow = useQuery({
    queryKey: ['cc-agent-shadow', agentId],
    queryFn: () => commandCenterService.agentShadow(agentId),
    enabled: Boolean(agentId) && can('posture.view'),
  })
  const findings = useQuery({
    queryKey: ['cc-agent-posture', agentId],
    queryFn: () => commandCenterService.postureFindings({ subject_id: agentId }),
    enabled: Boolean(agentId) && can('posture.view'),
  })
  const deps = useQuery({
    queryKey: ['cc-agent-deps', agentId],
    queryFn: () => commandCenterService.dependencies(agentId),
    enabled: Boolean(agentId) && can('graph.view'),
  })

  const signal = mode.data ? signalFromModeRead(mode.data) : null
  const affordances = signal ? affordancesFor(signal) : null
  const name = (agent.data?.name as string) ?? agentId

  return (
    <div className="mx-auto max-w-5xl space-y-6 p-4 sm:p-6">
      <PageHeader icon={Boxes} title={name} description="Everything ACT knows about this agent — and exactly what it can do about it." />

      {agent.isError ? <LoadError what="this agent" error={agent.error} /> : null}

      {mode.isLoading ? (
        <div className="flex justify-center p-6">
          <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
        </div>
      ) : signal ? (
        <Card>
          <CardContent className="space-y-3 p-4">
            <h2 className="text-sm font-semibold text-foreground">What ACT can do</h2>
            <GovernanceBadge signal={signal} />

            <div className="flex flex-wrap gap-2 pt-1">
              {affordances?.canContainAgent && can('containment.execute') ? (
                <Button
                  variant="destructive"
                  onClick={() => guard.confirm({
                    title: `Suspend ${name}`,
                    description:
                      'ACT runs this agent, so this genuinely stops it: running executions are '
                      + 'cancelled and the agent is suspended. The kill switch does not reverse '
                      + 'itself — bringing it back is a separate, deliberate act.',
                    confirmLabel: 'Suspend agent',
                    typeToConfirm: name,
                    requireReason: true,
                    reasonLabel: 'Why is this being contained?',
                    destructive: true,
                    onConfirm: (reason) => guard.run(
                      () => commandCenterService.executeContainment(agentId, {
                        action_type: 'SUSPEND_AGENT', reason, confirm: true,
                      }),
                      { success: 'Containment executed.', invalidate: [['cc-agent', agentId]] },
                    ),
                  })}
                >
                  Suspend agent
                </Button>
              ) : (
                // Not a disabled button: an affordance ACT does not have is
                // absent, and the reason is the server's own sentence.
                <p className="text-xs text-muted-foreground" data-testid="containment-unavailable">
                  No containment available.
                  {' '}{affordances?.containmentUnavailableReason}
                </p>
              )}
            </div>
          </CardContent>
        </Card>
      ) : null}

      {shadow.data?.shadow ? (
        <Card>
          <CardContent className="space-y-2 p-4">
            <h2 className="text-sm font-semibold text-foreground">Why this is shadow</h2>
            <ShadowReasons conditions={shadow.data.conditions} />
          </CardContent>
        </Card>
      ) : null}

      {findings.data && findings.data.length > 0 ? (
        <Card>
          <CardContent className="space-y-2 p-4">
            <h2 className="text-sm font-semibold text-foreground">Posture findings</h2>
            <ul className="space-y-2">
              {findings.data.map((f: PostureFinding) => (
                <li key={f.id} className="flex flex-wrap items-center justify-between gap-2">
                  <span className="text-xs text-muted-foreground">
                    <span className="font-mono text-foreground">{f.rule_id}</span>
                    {' · '}{f.severity}{' · '}{f.reason}
                  </span>
                  {can('posture.manage') && f.status === 'OPEN' ? (
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => guard.confirm({
                        title: 'Resolve finding',
                        description:
                          'Marks this posture condition resolved. If the condition still holds, '
                          + 'the next evaluation reopens it — resolving does not suppress it.',
                        confirmLabel: 'Resolve',
                        destructive: false,
                        onConfirm: () => guard.run(
                          () => commandCenterService.resolvePostureFinding(f.id),
                          {
                            success: 'Finding resolved.',
                            invalidate: [['cc-agent-posture', agentId], ['cc-agent-shadow', agentId]],
                          },
                        ),
                      })}
                    >
                      Resolve
                    </Button>
                  ) : null}
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      ) : null}

      {deps.data ? (
        <Card>
          <CardContent className="space-y-2 p-4">
            <h2 className="text-sm font-semibold text-foreground">Dependencies &amp; blast radius</h2>
            <pre className="overflow-x-auto rounded bg-muted p-3 text-xs text-muted-foreground">
              {JSON.stringify(deps.data, null, 2)}
            </pre>
          </CardContent>
        </Card>
      ) : null}

      <ConfirmActionDialog request={guard.request} pending={guard.pending} onCancel={guard.cancel} />
    </div>
  )
}
