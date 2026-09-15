import { useQuery } from '@tanstack/react-query'
import { Loader2, Siren } from 'lucide-react'

import { PageHeader } from '@/components/common'
import { Card, CardContent } from '@/components/ui'
import { commandCenterService } from '@/services'
import type { ContainmentAction, ThreatFinding } from '@/services/commandCenterService'
import { CommandCenterNav, LoadError } from './components'

/**
 * Phase 5.8 — Threats & Incidents.
 *
 * The containment list deliberately shows **REFUSED** actions alongside
 * executed ones. A refusal is not a failure to be hidden: it is Phase 5.6
 * recording that ACT was asked to contain an agent it does not run and
 * truthfully declined, with the reason. Hiding those would leave an operator
 * believing an agent was contained when nothing happened — the exact
 * over-claim the milestone was built to prevent.
 */
export function ThreatsPage() {
  const findings = useQuery({
    queryKey: ['cc-threat-findings'],
    queryFn: () => commandCenterService.threatFindings({ status: 'OPEN' }),
  })
  const actions = useQuery({
    queryKey: ['cc-containment'],
    queryFn: () => commandCenterService.containmentActions({}),
  })

  return (
    <div className="mx-auto max-w-5xl space-y-6 p-4 sm:p-6">
      <PageHeader
        icon={Siren}
        title="Threats & Incidents"
        description="Runtime threat findings, and every containment action ACT performed — or truthfully refused."
      />
      <CommandCenterNav />

      <section className="space-y-2">
        <h2 className="text-sm font-semibold text-foreground">Open threat findings</h2>
        {findings.isLoading ? (
          <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
        ) : findings.isError ? (
          <LoadError what="threat findings" error={findings.error} />
        ) : (
          <div className="space-y-2">
            {(findings.data ?? []).map((f: ThreatFinding) => (
              <Card key={f.id}>
                <CardContent className="space-y-1 p-4">
                  <span className="font-mono text-sm text-foreground">{f.rule_id}</span>
                  <p className="text-xs text-muted-foreground">{f.severity} · {f.reason}</p>
                </CardContent>
              </Card>
            ))}
            {(findings.data ?? []).length === 0 ? (
              <p className="text-sm text-muted-foreground">No open threat findings.</p>
            ) : null}
          </div>
        )}
      </section>

      <section className="space-y-2">
        <h2 className="text-sm font-semibold text-foreground">Containment actions</h2>
        {actions.isError ? (
          <LoadError what="containment actions" error={actions.error} />
        ) : (
          <div className="space-y-2">
            {(actions.data ?? []).map((a: ContainmentAction) => (
              <Card key={a.id}>
                <CardContent className="space-y-1 p-4">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <span className="text-sm text-foreground">{a.action_type}</span>
                    <span className="text-xs text-muted-foreground">
                      {a.status} · via {a.authority}
                    </span>
                  </div>
                  {a.status === 'REFUSED' ? (
                    <p className="text-xs text-warning">
                      Refused — {a.refusal_reason}
                    </p>
                  ) : null}
                  <p className="text-xs text-muted-foreground">
                    Control state at the time: {a.control_state_at_time ?? 'unknown'}
                  </p>
                </CardContent>
              </Card>
            ))}
            {(actions.data ?? []).length === 0 ? (
              <p className="text-sm text-muted-foreground">No containment actions recorded.</p>
            ) : null}
          </div>
        )}
      </section>
    </div>
  )
}
