import { useQuery } from '@tanstack/react-query'
import { Gauge, Loader2 } from 'lucide-react'

import { PageHeader } from '@/components/common'
import { Card, CardContent } from '@/components/ui'
import { observabilityService } from '@/services'
import { ObservabilityNav } from './components/ObservabilityNav'
import { CaptureModeBadge, ExporterHealthBadge } from './components/badges'

/**
 * Phase 4.9 view 1 — Runtime Overview (M4-4.9-FR-001).
 *
 * The fleet picture in one request (`GET /api/v1/runtime/overview`): execution
 * volume and success rate over 24h, spend today, open alerts, worker and
 * exporter health, SLO breaches, recent behavioural anomalies, and the org's
 * effective capture mode.
 *
 * The tiles deliberately count things an operator would act on — failures,
 * critical alerts, breached SLOs, anomalies — rather than reducing them to one
 * reassuring score. And a success rate below the 20-sample floor renders
 * "insufficient data", never "0%".
 */
export function RuntimeOverviewPage() {
  const q = useQuery({
    queryKey: ['obs-overview'],
    queryFn: () => observabilityService.overview(),
    refetchInterval: 30_000,
  })
  // Exporter health is a separate request against 4.6's endpoint — app/runtime
  // never reads the export plane, so the overview composite does not carry it.
  const exporter = useQuery({
    queryKey: ['obs-exporter-health'],
    queryFn: () => observabilityService.exporterHealth(),
    refetchInterval: 30_000,
  })
  const d = q.data
  const ex = exporter.data?.exporter

  return (
    <div className="mx-auto max-w-7xl space-y-6 p-4 sm:p-6">
      <PageHeader
        icon={Gauge}
        title="Runtime Overview"
        description="Everything Milestone 4 is watching — executions, spend, alerts, SLOs, behaviour, workers — in one place."
      />
      <ObservabilityNav />

      {q.isLoading ? (
        <div className="flex justify-center p-10">
          <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
        </div>
      ) : d ? (
        <>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <Tile
              label="Success rate (24h)"
              value={
                d.executions.success_rate_insufficient_data
                  ? 'insufficient data'
                  : `${Math.round((d.executions.success_rate ?? 0) * 100)}%`
              }
              hint={`${d.executions.terminal} terminal executions`}
              tone={d.executions.success_rate_insufficient_data ? 'warning' : 'default'}
            />
            <Tile
              label="Failed (24h)"
              value={String(d.executions.failed_24h)}
              hint={`${d.executions.running_now} running · ${d.executions.queued_now} queued`}
              tone={d.executions.failed_24h > 0 ? 'destructive' : 'default'}
            />
            <Tile
              label="Active alerts"
              value={String(d.alerts.active)}
              hint={`${d.alerts.critical} critical`}
              tone={d.alerts.critical > 0 ? 'destructive' : d.alerts.active > 0 ? 'warning' : 'default'}
            />
            <Tile
              label="Spend today"
              value={`$${d.spend.amount.toFixed(2)}`}
              hint={d.spend.includes_estimated
                ? `includes ${d.spend.estimated_row_count} estimated`
                : 'all real cost'}
              tone={d.spend.includes_estimated ? 'warning' : 'default'}
            />
            <Tile
              label="SLOs breached"
              value={String(d.slos.breached)}
              hint={`${d.slos.enabled} enabled · ${d.slos.insufficient_data} insufficient data`}
              tone={d.slos.breached > 0 ? 'destructive' : 'default'}
            />
            <Tile
              label="Behavioural anomalies (7d)"
              value={String(d.behavior.anomalous)}
              hint={`${d.behavior.degraded} degraded findings`}
              tone={d.behavior.anomalous > 0 ? 'destructive' : 'default'}
            />
            <Tile
              label="Workers"
              value={d.workers.total === 0 ? 'inline' : String(d.workers.total)}
              hint={d.workers.note ?? `${d.workers.offline} offline · ${d.workers.degraded} degraded`}
              tone={d.workers.offline > 0 ? 'destructive' : 'default'}
            />
            <Card>
              <CardContent className="space-y-2 p-4">
                <p className="text-sm text-muted-foreground">Telemetry plane</p>
                <div className="flex flex-wrap items-center gap-2">
                  <CaptureModeBadge value={d.capture.org_effective_mode} />
                  {ex ? (
                    <ExporterHealthBadge degraded={ex.degraded} lastError={ex.last_error} />
                  ) : null}
                </div>
                <p className="text-xs text-muted-foreground">{d.capture.reason}</p>
              </CardContent>
            </Card>
          </div>

          {ex?.degraded ? (
            <div role="alert" className="rounded-xl border border-warning/30 bg-warning/10 p-4 text-sm">
              <span className="font-medium text-foreground">The OpenTelemetry exporter is degraded.</span>{' '}
              <span className="text-muted-foreground">
                Traces and metrics are still recorded locally and executions are unaffected — export is fail-open.
                {ex.last_error ? ` Last error: ${ex.last_error}` : ''}
              </span>
            </div>
          ) : null}
        </>
      ) : (
        <p className="text-sm text-muted-foreground">Could not load the overview.</p>
      )}
    </div>
  )
}

function Tile({ label, value, hint, tone }: {
  label: string; value: string; hint?: string
  tone: 'default' | 'warning' | 'destructive'
}) {
  const emphasised = tone !== 'default'
  return (
    <Card className={tone === 'destructive' ? 'border-destructive/40' : tone === 'warning' ? 'border-warning/40' : undefined}>
      <CardContent className="p-4">
        <p className="text-sm text-muted-foreground">{label}</p>
        <p className={`mt-1 text-2xl font-semibold ${
          tone === 'destructive' ? 'text-destructive' : tone === 'warning' ? 'text-warning-foreground' : 'text-foreground'
        }`}>
          {value}
        </p>
        {hint ? <p className="mt-1 text-xs text-muted-foreground">{hint}</p> : null}
        {emphasised ? <span className="sr-only">requires attention</span> : null}
      </CardContent>
    </Card>
  )
}
