import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { CalendarClock, Loader2 } from 'lucide-react'

import { EmptyState, PageHeader } from '@/components/common'
import {
  Badge, Button, Card, CardContent, CardHeader, CardTitle,
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui'
import { usePermissions } from '@/authorization'
import { ROUTES } from '@/constants/routes'
import { operationsService } from '@/services'
import { ConfirmActionDialog } from './components/ConfirmActionDialog'
import { OperationsNav } from './components/OperationsNav'
import { formatMoment } from './components/format'
import { useGuardedAction } from './useGuardedAction'

const RUN_VARIANT: Record<string, 'success' | 'warning' | 'destructive' | 'default' | 'outline'> = {
  SUCCEEDED: 'success',
  RUNNING: 'default',
  CLAIMED: 'default',
  FAILED: 'destructive',
  TIMED_OUT: 'destructive',
  ABANDONED: 'warning',
}

/**
 * Phase 3.10 view 12 — Scheduler Jobs (M3-3.10-FR-010).
 *
 * The scheduled job definitions, their run history, and the enable/disable
 * control.
 *
 * **Nothing here can run a job.** Phase 3.8 deliberately built its API so that
 * no HTTP route dispatches: a job runs only on a scheduler instance, under a
 * committed lease. An HTTP "run now" button would let a caller execute a
 * handler with no occurrence row and no protection against a peer running it
 * simultaneously — defeating the exactly-once guarantee by simply never taking
 * a lease. So this view reads and toggles, and that is all it can do.
 *
 * Enabling a job is confirmation-gated even though it looks innocuous: a
 * scheduled job is a standing instruction to act on production with no human
 * present, and arming one is a bigger decision than its single toggle suggests.
 */
export function SchedulerJobsPage() {
  const { can } = usePermissions()
  const guard = useGuardedAction()
  const [expanded, setExpanded] = useState<string | null>(null)

  const jobs = useQuery({
    queryKey: ['ops-jobs'],
    queryFn: () => operationsService.jobs(),
    refetchInterval: 30_000,
  })
  const runs = useQuery({
    queryKey: ['ops-job-runs', expanded],
    queryFn: () => operationsService.jobRuns(expanded ?? ''),
    enabled: Boolean(expanded),
  })

  const canManage = can('runtime.scheduler.manage')
  const rows = jobs.data ?? []

  return (
    <div className="mx-auto max-w-6xl space-y-6 p-4 sm:p-6">
      <PageHeader
        icon={CalendarClock}
        title="Scheduled jobs"
        description="Standing instructions the scheduler fleet claims and runs exactly once per occurrence."
        backTo={ROUTES.OPS_OVERVIEW}
        backLabel="Release operations"
      />
      <OperationsNav />

      <Card>
        <CardHeader><CardTitle className="text-base">Job definitions</CardTitle></CardHeader>
        <CardContent className="p-0">
          {jobs.isLoading ? (
            <div className="flex justify-center p-10">
              <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
            </div>
          ) : rows.length === 0 ? (
            <EmptyState
              icon={CalendarClock}
              title="No scheduled jobs"
              description="Platform jobs are seeded by the scheduler runner; tenant jobs are created through the scheduler API."
            />
          ) : (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Job</TableHead>
                    <TableHead>Handler</TableHead>
                    <TableHead>Schedule</TableHead>
                    <TableHead>Enabled</TableHead>
                    <TableHead>Next run</TableHead>
                    <TableHead className="text-right">Actions</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {rows.map((job) => (
                    <TableRow key={job.id}>
                      <TableCell className="font-medium">
                        {job.name}
                        {job.organization_id === null ? (
                          <Badge variant="outline" className="ml-2">platform</Badge>
                        ) : null}
                      </TableCell>
                      <TableCell className="font-mono text-xs text-muted-foreground">
                        {job.handler_key}
                      </TableCell>
                      <TableCell className="text-muted-foreground">
                        {job.schedule_kind}
                        {typeof job.schedule_spec?.interval_seconds === 'number'
                          ? ` · every ${job.schedule_spec.interval_seconds}s` : ''}
                      </TableCell>
                      <TableCell>
                        <Badge variant={job.enabled ? 'success' : 'outline'}>
                          {job.enabled ? 'ENABLED' : 'DISABLED'}
                        </Badge>
                      </TableCell>
                      <TableCell className="whitespace-nowrap text-muted-foreground">
                        {job.enabled ? formatMoment(job.next_run_at) : '—'}
                      </TableCell>
                      <TableCell className="space-x-2 text-right">
                        <Button
                          variant="outline"
                          onClick={() => setExpanded((cur) => (cur === job.id ? null : job.id))}
                        >
                          {expanded === job.id ? 'Hide runs' : 'Runs'}
                        </Button>
                        {canManage ? (
                          <Button
                            variant={job.enabled ? 'outline' : 'default'}
                            onClick={() => guard.confirm({
                              title: job.enabled ? `Disable ${job.name}` : `Enable ${job.name}`,
                              description: job.enabled
                                ? 'The job stops being claimed. Runs already in flight finish normally.'
                                : 'A scheduled job is a standing instruction to act on production with no human present. It will begin running on its interval.',
                              confirmLabel: job.enabled ? 'Disable job' : 'Enable job',
                              destructive: !job.enabled ? true : false,
                              typeToConfirm: !job.enabled ? job.name : undefined,
                              onConfirm: () => guard.run(
                                () => operationsService.setJobEnabled(job.id, !job.enabled),
                                {
                                  success: job.enabled ? 'Job disabled' : 'Job enabled',
                                  invalidate: [['ops-jobs']],
                                }),
                            })}
                          >
                            {job.enabled ? 'Disable' : 'Enable'}
                          </Button>
                        ) : null}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>

      {expanded ? (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">
              Run history — {rows.find((j) => j.id === expanded)?.name}
            </CardTitle>
          </CardHeader>
          <CardContent className="p-0">
            {runs.isLoading ? (
              <div className="flex justify-center p-8">
                <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
              </div>
            ) : (runs.data ?? []).length === 0 ? (
              <p className="p-6 text-sm text-muted-foreground">This job has not run yet.</p>
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Status</TableHead>
                    <TableHead>Attempt</TableHead>
                    <TableHead>Owner</TableHead>
                    <TableHead>Started</TableHead>
                    <TableHead>Ended</TableHead>
                    <TableHead>Error</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {(runs.data ?? []).map((run) => (
                    <TableRow key={run.id}>
                      <TableCell>
                        <Badge variant={RUN_VARIANT[run.status] ?? 'outline'}>{run.status}</Badge>
                      </TableCell>
                      <TableCell className="text-muted-foreground">{run.attempt}</TableCell>
                      <TableCell className="font-mono text-xs text-muted-foreground">
                        {run.lease_owner ?? '—'}
                      </TableCell>
                      <TableCell className="whitespace-nowrap text-muted-foreground">
                        {formatMoment(run.started_at)}
                      </TableCell>
                      <TableCell className="whitespace-nowrap text-muted-foreground">
                        {formatMoment(run.ended_at)}
                      </TableCell>
                      <TableCell className="max-w-xs truncate text-muted-foreground" title={run.error ?? ''}>
                        {run.error ?? '—'}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </CardContent>
        </Card>
      ) : null}

      <ConfirmActionDialog request={guard.request} pending={guard.pending} onCancel={guard.cancel} />
    </div>
  )
}
