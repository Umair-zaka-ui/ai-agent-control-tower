import { useQuery } from '@tanstack/react-query'
import { Loader2, ShieldAlert } from 'lucide-react'

import { PageHeader } from '@/components/common'
import { Card, CardContent } from '@/components/ui'
import { commandCenterService } from '@/services'
import type { GatewayCall } from '@/services/commandCenterService'
import { CommandCenterNav, LoadError } from './components'

/**
 * Phase 5.8 — External Platforms.
 *
 * The mode catalogue is read from the server (`GET /bridge/modes`) rather than
 * hardcoded, so each mode's `display` and `limits` are the sentences 5.7
 * permits and nothing else. That is the difference between a UI that documents
 * the truth and one that paraphrases it into "governed".
 *
 * The boundary-call log shows denials and `NOT_MEASURABLE` costs as themselves.
 * A call ACT could not price is not zero-cost, and saying so would be the
 * cheapest possible fiction.
 */
export function ExternalPlatformsPage() {
  const modes = useQuery({
    queryKey: ['cc-modes'],
    queryFn: () => commandCenterService.modes(),
  })
  const calls = useQuery({
    queryKey: ['cc-gateway-calls'],
    queryFn: () => commandCenterService.gatewayCalls({ limit: 50 }),
  })

  return (
    <div className="mx-auto max-w-5xl space-y-6 p-4 sm:p-6">
      <PageHeader
        icon={ShieldAlert}
        title="External Platforms"
        description="Agents ACT does not run, the reach ACT truthfully has over each, and every decision made at its boundary."
      />
      <CommandCenterNav />

      <section className="space-y-2">
        <h2 className="text-sm font-semibold text-foreground">Enforcement modes</h2>
        {modes.isLoading ? (
          <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
        ) : modes.isError ? (
          <LoadError what="enforcement modes" error={modes.error} />
        ) : (
          <div className="grid gap-3 sm:grid-cols-2">
            {(modes.data ?? []).map((m) => (
              <Card key={m.mode}>
                <CardContent className="space-y-1 p-4">
                  <p className="text-sm font-semibold text-foreground">{m.mode}</p>
                  <p className="text-xs text-foreground">{m.display}</p>
                  <p className="text-xs text-muted-foreground">{m.limits}</p>
                  {!m.assignable ? (
                    <p className="text-xs text-muted-foreground">
                      Not assignable — derived from the agent's control state, so it cannot be
                      claimed, only be true.
                    </p>
                  ) : null}
                </CardContent>
              </Card>
            ))}
          </div>
        )}
      </section>

      <section className="space-y-2">
        <h2 className="text-sm font-semibold text-foreground">Boundary decisions</h2>
        {calls.isError ? (
          <LoadError what="boundary calls" error={calls.error} />
        ) : (
          <div className="space-y-2">
            {(calls.data ?? []).map((c: GatewayCall) => (
              <Card key={c.id}>
                <CardContent className="space-y-1 p-4">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <span className="font-mono text-xs text-foreground">{c.capability_key}</span>
                    <span className={c.outcome === 'DENIED'
                      ? 'text-xs font-medium text-destructive'
                      : 'text-xs text-muted-foreground'}>{c.outcome}</span>
                  </div>
                  <p className="text-xs text-muted-foreground">
                    Mode at the time: {c.enforcement_mode_at_time} · policy {c.policy_outcome} ·
                    {' '}cost {c.cost_outcome === 'NOT_MEASURABLE' ? 'not measurable' : c.cost_outcome}
                    {' '}· dispatch {c.dispatch_status}
                  </p>
                  {c.denial_reason ? (
                    <p className="text-xs text-warning">{c.denial_reason}</p>
                  ) : null}
                </CardContent>
              </Card>
            ))}
            {(calls.data ?? []).length === 0 ? (
              <p className="text-sm text-muted-foreground">No boundary calls recorded.</p>
            ) : null}
          </div>
        )}
      </section>
    </div>
  )
}
