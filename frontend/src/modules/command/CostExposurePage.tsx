import { useQuery } from '@tanstack/react-query'
import { Loader2, Wallet } from 'lucide-react'

import { PageHeader } from '@/components/common'
import { Card, CardContent } from '@/components/ui'
import { commandCenterService } from '@/services'
import { CommandCenterNav, LoadError, SectionGate, Tile } from './components'

/**
 * Phase 5.8 — Cost Exposure.
 *
 * Phase 4.4 prices what it can measure, and Phase 5.7 established that a
 * boundary call ACT cannot price is recorded `NOT_MEASURABLE` rather than given
 * an invented figure. This page carries that through rather than summing an
 * estimate: unmeasurable calls are **counted and named**, never folded into a
 * total that would look complete.
 */
export function CostExposurePage() {
  const q = useQuery({
    queryKey: ['cc-estate'],
    queryFn: () => commandCenterService.estate(),
  })

  return (
    <div className="mx-auto max-w-5xl space-y-6 p-4 sm:p-6">
      <PageHeader
        icon={Wallet}
        title="Cost Exposure"
        description="What this estate costs — and, honestly, how much of it ACT cannot price."
      />
      <CommandCenterNav />

      {q.isLoading ? (
        <div className="flex justify-center p-10">
          <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
        </div>
      ) : q.isError ? (
        <LoadError what="cost exposure" error={q.error} />
      ) : q.data ? (
        <SectionGate section={q.data.cost}>
          {(c) => (
            <div className="space-y-3">
              <div className="grid gap-3 sm:grid-cols-2">
                <Tile label="Enabled budgets" value={String(c.enabled_budgets)} />
                <Tile
                  label="Not measurable"
                  value={String(c.boundary_calls_not_measurable)}
                  hint={`Boundary calls ACT could not price (last ${c.window_hours}h)`}
                  tone={c.boundary_calls_not_measurable > 0 ? 'warning' : 'default'}
                />
              </div>
              <Card>
                <CardContent className="p-4">
                  <p className="text-xs text-muted-foreground">{c.note}</p>
                </CardContent>
              </Card>
            </div>
          )}
        </SectionGate>
      ) : null}
    </div>
  )
}
