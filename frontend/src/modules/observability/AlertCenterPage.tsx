import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Bell, Loader2 } from 'lucide-react'

import { useCan } from '@/authorization'
import { EmptyState, PageHeader } from '@/components/common'
import {
  Button, Card, CardContent, Select,
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui'
import { ConfirmActionDialog, useGuardedAction } from '@/modules/operations'
import { observabilityService } from '@/services'
import { ObservabilityNav } from './components/ObservabilityNav'
import { AlertSeverityBadge, AlertStatusBadge } from './components/badges'

const STATUSES = ['', 'OPEN', 'ACKNOWLEDGED', 'RESOLVED', 'SUPPRESSED']

/**
 * Phase 4.9 view 8 — Alert Center (M4-4.9-FR-008).
 *
 * The alert lifecycle from 4.7, and the three lifecycle actions. Acknowledge
 * and resolve are a single deliberate click; **suppress is
 * confirmation-gated** — an operator saying "this condition is known and
 * expected" and silencing recurrence is a decision that outlives the incident,
 * so it asks for a reason that lands in the server's audit. Every action
 * dispatches to 4.7's endpoint, which re-authorizes it; a concurrent transition
 * (two operators acknowledging the same alert) converges rather than erroring.
 */
export function AlertCenterPage() {
  const [status, setStatus] = useState('OPEN')
  const canManage = useCan('runtime.alert.manage')
  const guard = useGuardedAction()

  const q = useQuery({
    queryKey: ['obs-alerts', status],
    queryFn: () => observabilityService.alerts({ status: status || undefined, limit: 100 }),
    refetchInterval: 30_000,
  })
  const rows = q.data ?? []
  const invalidate = [['obs-alerts'], ['obs-overview']]

  return (
    <div className="mx-auto max-w-7xl space-y-6 p-4 sm:p-6">
      <PageHeader
        icon={Bell}
        title="Alert Center"
        description="An SLO breach or a significant behavioural finding, deduplicated so one condition is one alert. A signal — nothing here pages anyone."
      />
      <ObservabilityNav />

      <Card>
        <CardContent className="flex flex-wrap items-end gap-3 p-4">
          <label className="text-sm">
            <span className="mb-1 block text-xs text-muted-foreground">Status</span>
            <Select
              aria-label="Status"
              value={status}
              onChange={(e) => setStatus(e.target.value)}
              options={STATUSES.map((s) => ({ value: s, label: s || 'Any status' }))}
            />
          </label>
        </CardContent>
      </Card>

      <Card>
        <CardContent className="p-0">
          {q.isLoading ? (
            <div className="flex justify-center p-10"><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /></div>
          ) : rows.length === 0 ? (
            <EmptyState icon={Bell} title="No alerts" description="Nothing is currently signalling." />
          ) : (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Opened</TableHead>
                    <TableHead>Title</TableHead>
                    <TableHead>Source</TableHead>
                    <TableHead>Severity</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead>Recurrence</TableHead>
                    <TableHead>Actions</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {rows.map((a) => (
                    <TableRow key={a.id}>
                      <TableCell className="whitespace-nowrap text-muted-foreground">
                        {new Date(a.opened_at).toLocaleString()}
                      </TableCell>
                      <TableCell className="font-medium">
                        {a.title}
                        <div className="text-xs text-muted-foreground">{a.summary}</div>
                      </TableCell>
                      <TableCell className="text-xs">{a.source}</TableCell>
                      <TableCell><AlertSeverityBadge value={a.severity} /></TableCell>
                      <TableCell><AlertStatusBadge value={a.status} /></TableCell>
                      <TableCell>{a.recurrence_count}</TableCell>
                      <TableCell className="space-x-1.5">
                        {canManage && (a.status === 'OPEN' || a.status === 'ACKNOWLEDGED') ? (
                          <>
                            {a.status === 'OPEN' ? (
                              <Button size="sm" variant="outline"
                                onClick={() => guard.run(
                                  () => observabilityService.acknowledgeAlert(a.id),
                                  { success: 'Acknowledged', invalidate },
                                )}>
                                Acknowledge
                              </Button>
                            ) : null}
                            <Button size="sm" variant="outline"
                              onClick={() => guard.run(
                                () => observabilityService.resolveAlert(a.id),
                                { success: 'Resolved', invalidate },
                              )}>
                              Resolve
                            </Button>
                            <Button size="sm" variant="destructive"
                              onClick={() => guard.confirm({
                                title: `Suppress "${a.title}"`,
                                description:
                                  'Suppressing tells the platform this condition is known and expected. A suppressed alert does NOT re-open on recurrence — you will stop hearing about it until you re-open it deliberately.',
                                confirmLabel: 'Suppress alert',
                                destructive: true,
                                requireReason: true,
                                reasonLabel: 'Why is this condition expected?',
                                onConfirm: (reason) => guard.run(
                                  () => observabilityService.suppressAlert(a.id, reason),
                                  { success: 'Suppressed', invalidate },
                                ),
                              })}>
                              Suppress
                            </Button>
                          </>
                        ) : (
                          <span className="text-xs text-muted-foreground">
                            {canManage ? 'no action' : 'view only'}
                          </span>
                        )}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>

      <ConfirmActionDialog request={guard.request} pending={guard.pending} onCancel={guard.cancel} />
    </div>
  )
}
