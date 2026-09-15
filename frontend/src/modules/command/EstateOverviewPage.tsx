import { useQuery } from '@tanstack/react-query'
import { Gauge, Loader2 } from 'lucide-react'

import { PageHeader } from '@/components/common'
import { Card, CardContent } from '@/components/ui'
import { commandCenterService } from '@/services'
import { CommandCenterNav, LoadError, SectionGate, Tile } from './components'

/**
 * Phase 5.8 view 1 — the AI Estate.
 *
 * One request (`GET /api/v1/command-center/estate`) for the whole picture:
 * how many agents exist, how many ACT **actually governs**, how many are
 * shadow, and the posture / threat / external-governance / graph / cost
 * summaries.
 *
 * Two honesty rules shape what you see here.
 *
 * **"Ungoverned" is a count, not a criticism.** It is literally the number of
 * agents ACT does not run — the truth Phases 5.1–5.7 worked to be able to state
 * plainly. An estate dashboard that quietly folded those into a total would be
 * back to claiming coverage ACT does not have.
 *
 * **A section you cannot see is not a zero.** Posture, threats, external
 * governance, graph and cost each have their own permission, and the server
 * returns `visible: false` rather than an empty count for a caller who lacks
 * it. `SectionGate` renders that as "hidden from you", because a 0 in a
 * security dashboard reads as "all clear" and would be the most comfortable
 * possible lie.
 */
export function EstateOverviewPage() {
  const q = useQuery({
    queryKey: ['cc-estate'],
    queryFn: () => commandCenterService.estate(),
    refetchInterval: 60_000,
  })
  const d = q.data

  return (
    <div className="mx-auto max-w-7xl space-y-6 p-4 sm:p-6">
      <PageHeader
        icon={Gauge}
        title="AI Estate"
        description="Every agent this organization has — native and external, governed and not — and what ACT can actually do about each."
      />
      <CommandCenterNav />

      {q.isLoading ? (
        <div className="flex justify-center p-10">
          <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
        </div>
      ) : q.isError ? (
        <LoadError what="the estate overview" error={q.error} />
      ) : d ? (
        <>
          <section aria-label="Agents" className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <Tile label="Agents" value={String(d.agents.total)}
                  hint={`${Object.keys(d.agents.by_origin_category).length} provenance categories`} />
            <Tile label="ACT governs" value={String(d.agents.governed)}
                  hint="ACT runs and enforces these" />
            <Tile
              label="ACT does not govern"
              value={String(d.agents.ungoverned)}
              hint="Observed, advised or boundary-authorized only"
              tone={d.agents.ungoverned > 0 ? 'warning' : 'default'}
            />
            <Tile label="Unowned" value={String(d.agents.unowned)}
                  hint="No accountable owner"
                  tone={d.agents.unowned > 0 ? 'warning' : 'default'} />
            <Tile label="Critical" value={String(d.agents.critical)} hint="Criticality = CRITICAL" />
            <Tile label="Dormant" value={String(d.agents.dormant)}
                  hint={`Ungoverned, unobserved ${d.agents.dormant_days}d+`} />
          </section>

          <section aria-label="Enforcement modes" className="space-y-2">
            <h2 className="text-sm font-semibold text-foreground">By enforcement mode</h2>
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              {Object.entries(d.agents.by_enforcement_mode).map(([mode, count]) => (
                <Tile key={mode} label={mode} value={String(count)} />
              ))}
            </div>
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              {Object.entries(d.agents.by_control_state).map(([state, count]) => (
                <Tile key={state} label={`Control state · ${state}`} value={String(count)} />
              ))}
            </div>
          </section>

          <section aria-label="Shadow" className="space-y-2">
            <h2 className="text-sm font-semibold text-foreground">Shadow AI</h2>
            <SectionGate section={d.shadow}>
              {(s) => (
                <Tile
                  label="Shadow agents"
                  value={String(s.count)}
                  hint="Each one has an open, disputable posture finding explaining why"
                  tone={s.count > 0 ? 'warning' : 'default'}
                />
              )}
            </SectionGate>
          </section>

          <section aria-label="Threats" className="space-y-2">
            <h2 className="text-sm font-semibold text-foreground">Threats &amp; containment</h2>
            <SectionGate section={d.threats}>
              {(t) => (
                <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                  <Tile label="Open threat findings" value={String(t.open_findings)}
                        tone={t.open_findings > 0 ? 'destructive' : 'default'} />
                  <Tile label="Critical" value={String(t.open_by_severity.CRITICAL ?? 0)}
                        tone={(t.open_by_severity.CRITICAL ?? 0) > 0 ? 'destructive' : 'default'} />
                  <Tile
                    label="Containment refused"
                    value={String(t.containment_refused)}
                    hint="ACT truthfully could not reach the agent"
                    tone={t.containment_refused > 0 ? 'warning' : 'default'}
                  />
                  <Tile label="Containment executed"
                        value={String(t.containment_by_status.EXECUTED ?? 0)}
                        hint={`Last ${t.containment_window_hours}h`} />
                </div>
              )}
            </SectionGate>
          </section>

          <section aria-label="External governance" className="space-y-2">
            <h2 className="text-sm font-semibold text-foreground">External platforms</h2>
            <SectionGate section={d.external}>
              {(x) => (
                <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                  <Tile label="Active capability grants" value={String(x.active_grants)} />
                  <Tile label="Boundary calls allowed"
                        value={String(x.boundary_calls_by_outcome.ALLOWED ?? 0)}
                        hint={`Last ${x.window_hours}h`} />
                  <Tile label="Boundary calls denied" value={String(x.boundary_calls_denied)}
                        tone={x.boundary_calls_denied > 0 ? 'warning' : 'default'} />
                </div>
              )}
            </SectionGate>
          </section>

          <section aria-label="Posture" className="space-y-2">
            <h2 className="text-sm font-semibold text-foreground">Security posture</h2>
            <SectionGate section={d.posture}>
              {(p) => (
                <Card>
                  <CardContent className="space-y-1 p-4">
                    <p className="text-2xl font-semibold text-foreground">
                      {String((p as Record<string, unknown>).score ?? '—')}
                    </p>
                    <p className="text-xs text-muted-foreground">
                      Ruleset {String((p as Record<string, unknown>).ruleset_version ?? '—')} ·
                      {' '}deterministic and reconstructable — the formula, weights and per-rule
                      contributions come from the posture service, not from this screen.
                    </p>
                  </CardContent>
                </Card>
              )}
            </SectionGate>
          </section>

          <section aria-label="Cost" className="space-y-2">
            <h2 className="text-sm font-semibold text-foreground">Cost exposure</h2>
            <SectionGate section={d.cost}>
              {(c) => (
                <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                  <Tile label="Enabled budgets" value={String(c.enabled_budgets)} />
                  <Tile
                    label="Not measurable"
                    value={String(c.boundary_calls_not_measurable)}
                    hint={`Boundary calls ACT cannot price (last ${c.window_hours}h)`}
                  />
                  <Card>
                    <CardContent className="p-4">
                      <p className="text-xs text-muted-foreground">{c.note}</p>
                    </CardContent>
                  </Card>
                </div>
              )}
            </SectionGate>
          </section>
        </>
      ) : null}
    </div>
  )
}
