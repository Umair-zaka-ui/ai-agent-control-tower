import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Activity, Loader2 } from 'lucide-react'

import { EmptyState, PageHeader } from '@/components/common'
import {
  Card, CardContent, Select,
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui'
import { observabilityService } from '@/services'
import { ObservabilityNav } from './components/ObservabilityNav'
import { FindingStateBadge } from './components/badges'

const STATES = ['', 'ANOMALOUS', 'DEGRADED', 'NORMAL', 'INSUFFICIENT_DATA']

/**
 * Phase 4.9 view 6 — Behavior & Anomalies (M4-4.9-FR-006).
 *
 * Behavioural findings from 4.5, with their self-contained explanations.
 * `INSUFFICIENT_DATA` is shown as exactly that — a thin window is never
 * "normal".
 */
export function BehaviorAnomaliesPage() {
  const [state, setState] = useState('')
  const q = useQuery({
    queryKey: ['obs-behavior', state],
    queryFn: () => observabilityService.findings({ state: state || undefined, limit: 100 }),
  })
  const rows = q.data ?? []

  return (
    <div className="mx-auto max-w-7xl space-y-6 p-4 sm:p-6">
      <PageHeader
        icon={Activity}
        title="Behavior & Anomalies"
        description="How an agent's runtime behaviour has changed — deterministic, explainable, and strictly a signal."
      />
      <ObservabilityNav />

      <Card>
        <CardContent className="flex flex-wrap items-end gap-3 p-4">
          <label className="text-sm">
            <span className="mb-1 block text-xs text-muted-foreground">State</span>
            <Select
              aria-label="State"
              value={state}
              onChange={(e) => setState(e.target.value)}
              options={STATES.map((s) => ({ value: s, label: s ? s.replace(/_/g, ' ') : 'Any state' }))}
            />
          </label>
        </CardContent>
      </Card>

      <Card>
        <CardContent className="p-0">
          {q.isLoading ? (
            <div className="flex justify-center p-10"><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /></div>
          ) : rows.length === 0 ? (
            <EmptyState icon={Activity} title="No findings" description="Nothing has drifted enough to report." />
          ) : (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Evaluated</TableHead>
                    <TableHead>Signal</TableHead>
                    <TableHead>State</TableHead>
                    <TableHead>Observed</TableHead>
                    <TableHead>Threshold</TableHead>
                    <TableHead>Baseline</TableHead>
                    <TableHead>Why</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {rows.map((f) => (
                    <TableRow key={f.id}>
                      <TableCell className="whitespace-nowrap text-muted-foreground">
                        {new Date(f.evaluated_at).toLocaleString()}
                      </TableCell>
                      <TableCell className="text-xs">{f.signal_type.replace(/_/g, ' ')}</TableCell>
                      <TableCell><FindingStateBadge value={f.state} /></TableCell>
                      <TableCell>{f.observed_value ?? '—'}</TableCell>
                      <TableCell>{f.threshold_value ?? '—'}</TableCell>
                      <TableCell>{f.baseline_value ?? '—'}</TableCell>
                      <TableCell className="max-w-md text-sm text-muted-foreground">{f.reason ?? '—'}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
