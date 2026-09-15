import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { EyeOff, Loader2 } from 'lucide-react'

import { PageHeader } from '@/components/common'
import { Card, CardContent } from '@/components/ui'
import { commandCenterService } from '@/services'
import { ROUTES } from '@/constants/routes'
import { CommandCenterNav, LoadError, ShadowReasons } from './components'

/**
 * Phase 5.8 — Shadow AI.
 *
 * Shadow is not a flag anywhere in this platform. Phase 5.5 made it a *derived*
 * state: an agent is shadow exactly while it has an open shadow-class posture
 * finding, and there is no `shadow` column on any table. So this page lists the
 * **conditions**, not a set of red badges — each one names its rule, its
 * severity and its reason, which is what makes it disputable and what an
 * operator needs in order to resolve it rather than just look at it.
 */
export function ShadowAgentsPage() {
  const q = useQuery({
    queryKey: ['cc-shadow'],
    queryFn: () => commandCenterService.shadowAgents(),
  })

  return (
    <div className="mx-auto max-w-5xl space-y-6 p-4 sm:p-6">
      <PageHeader
        icon={EyeOff}
        title="Shadow AI"
        description="Agents operating outside ACT's governance — each shown with the open finding that makes it shadow, not a bare label."
      />
      <CommandCenterNav />

      {q.isLoading ? (
        <div className="flex justify-center p-10">
          <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
        </div>
      ) : q.isError ? (
        <LoadError what="shadow agents" error={q.error} />
      ) : q.data ? (
        <>
          <p className="text-sm text-muted-foreground">
            {q.data.count} shadow {q.data.count === 1 ? 'agent' : 'agents'}, derived from
            {' '}{q.data.shadow_rule_ids.length} shadow-class rules. Resolving the underlying
            finding clears the state — there is nothing else to unset.
          </p>
          <div className="space-y-3">
            {q.data.agents.map((s) => (
              <Card key={s.agent.id}>
                <CardContent className="space-y-2 p-4">
                  <Link
                    to={ROUTES.CC_AGENT_DETAIL.replace(':agentId', s.agent.id)}
                    className="font-medium text-primary hover:underline"
                  >
                    {s.agent.name ?? s.agent.id}
                  </Link>
                  <p className="text-xs text-muted-foreground">
                    Control state: {s.agent.control_state ?? 'unknown'}
                  </p>
                  <ShadowReasons conditions={s.conditions} />
                </CardContent>
              </Card>
            ))}
            {q.data.agents.length === 0 ? (
              <p className="text-sm text-muted-foreground">No shadow agents right now.</p>
            ) : null}
          </div>
        </>
      ) : null}
    </div>
  )
}
