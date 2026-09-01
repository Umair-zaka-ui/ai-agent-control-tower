import { useState } from 'react'
import { useQueries, useQuery } from '@tanstack/react-query'
import { BadgeDollarSign, Loader2 } from 'lucide-react'

import { EmptyState, PageHeader } from '@/components/common'
import {
  Badge, Card, CardContent, Select,
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui'
import { observabilityService } from '@/services'
import { ObservabilityNav } from './components/ObservabilityNav'

const DIMENSIONS = ['agent', 'environment', 'provider', 'model', 'project', 'status']

/**
 * Phase 4.9 view 4 — Cost Center (M4-4.9-FR-004).
 *
 * Real spend from 4.4, aggregated by dimension, with **actual and estimated
 * kept apart** and unpriced executions counted rather than silently zero — the
 * split 4.4 carries all the way to the wire, surfaced here rather than summed
 * into one misleading number. Budgets show utilisation with an over-threshold
 * flag shown as a warning, never smoothed.
 */
export function CostCenterPage() {
  const [dimension, setDimension] = useState('agent')

  const summary = useQuery({
    queryKey: ['obs-cost', dimension],
    queryFn: () => observabilityService.costSummary({ dimension }),
  })
  const budgets = useQuery({ queryKey: ['obs-budgets'], queryFn: () => observabilityService.budgets() })
  const util = useQueries({
    queries: (budgets.data ?? []).map((b) => ({
      queryKey: ['obs-budget-util', b.id],
      queryFn: () => observabilityService.budgetUtilization(b.id),
      enabled: Boolean(budgets.data),
    })),
  })

  const s = summary.data

  return (
    <div className="mx-auto max-w-7xl space-y-6 p-4 sm:p-6">
      <PageHeader
        icon={BadgeDollarSign}
        title="Cost Center"
        description="Real per-execution spend, budgets and allocation. Actual and estimated are shown separately."
      />
      <ObservabilityNav />

      {s ? (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <Card><CardContent className="p-4">
            <p className="text-sm text-muted-foreground">Actual spend</p>
            <p className="mt-1 text-2xl font-semibold">${s.actual_amount.toFixed(2)}</p>
          </CardContent></Card>
          <Card className={s.estimated_amount > 0 ? 'border-warning/40' : undefined}><CardContent className="p-4">
            <p className="text-sm text-muted-foreground">Estimated (not metered)</p>
            <p className={`mt-1 text-2xl font-semibold ${s.estimated_amount > 0 ? 'text-warning-foreground' : ''}`}>
              ${s.estimated_amount.toFixed(2)}
            </p>
          </CardContent></Card>
          <Card className={s.unpriced_execution_count > 0 ? 'border-warning/40' : undefined}><CardContent className="p-4">
            <p className="text-sm text-muted-foreground">Unpriced executions</p>
            <p className="mt-1 text-2xl font-semibold">{s.unpriced_execution_count}</p>
            <p className="text-xs text-muted-foreground">counted in neither sum</p>
          </CardContent></Card>
          <Card><CardContent className="p-4">
            <p className="text-sm text-muted-foreground">Executions</p>
            <p className="mt-1 text-2xl font-semibold">{s.execution_count}</p>
          </CardContent></Card>
        </div>
      ) : null}

      <Card>
        <CardContent className="flex flex-wrap items-end gap-3 p-4">
          <label className="text-sm">
            <span className="mb-1 block text-xs text-muted-foreground">Group by</span>
            <Select
              aria-label="Group by"
              value={dimension}
              onChange={(e) => setDimension(e.target.value)}
              options={DIMENSIONS.map((d) => ({ value: d, label: d }))}
            />
          </label>
        </CardContent>
      </Card>

      <Card>
        <CardContent className="p-0">
          {summary.isLoading ? (
            <div className="flex justify-center p-10"><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /></div>
          ) : !s || s.buckets.length === 0 ? (
            <EmptyState icon={BadgeDollarSign} title="No spend in this window" description="Nothing has been executed and priced yet." />
          ) : (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>{dimension}</TableHead>
                    <TableHead>Actual</TableHead>
                    <TableHead>Estimated</TableHead>
                    <TableHead>Executions</TableHead>
                    <TableHead>Tokens</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {s.buckets.map((b) => (
                    <TableRow key={b.key}>
                      <TableCell className="font-medium">{b.label ?? b.key}</TableCell>
                      <TableCell>${b.actual_amount.toFixed(4)}</TableCell>
                      <TableCell className={b.estimated_amount > 0 ? 'text-warning-foreground' : ''}>
                        ${b.estimated_amount.toFixed(4)}
                      </TableCell>
                      <TableCell>{b.execution_count}</TableCell>
                      <TableCell>{b.total_tokens}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardContent className="p-4">
          <h2 className="mb-3 text-sm font-semibold">Budgets</h2>
          {budgets.isLoading ? (
            <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
          ) : !budgets.data || budgets.data.length === 0 ? (
            <p className="text-sm text-muted-foreground">No budgets configured.</p>
          ) : (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Name</TableHead>
                    <TableHead>Mode</TableHead>
                    <TableHead>Limit</TableHead>
                    <TableHead>Utilisation</TableHead>
                    <TableHead>Remaining</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {budgets.data.map((b, i) => {
                    const u = util[i]?.data
                    return (
                      <TableRow key={b.id}>
                        <TableCell className="font-medium">{b.name}{b.enabled ? '' : ' (disabled)'}</TableCell>
                        <TableCell><Badge variant={b.mode === 'HARD_LIMIT' ? 'destructive' : 'secondary'}>{b.mode}</Badge></TableCell>
                        <TableCell>${b.limit_amount.toFixed(2)} {b.currency}</TableCell>
                        <TableCell>
                          {u ? (
                            <span className={u.over_threshold ? 'font-medium text-warning-foreground' : ''}>
                              {u.utilization_percent.toFixed(0)}%{u.over_threshold ? ' — over threshold' : ''}
                            </span>
                          ) : '—'}
                        </TableCell>
                        <TableCell>{u ? `$${u.remaining.toFixed(2)}` : '—'}</TableCell>
                      </TableRow>
                    )
                  })}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
