import { useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Cpu, Loader2, RefreshCw, Repeat, XCircle } from 'lucide-react'
import { toast } from 'sonner'

import { PageHeader } from '@/components/common'
import {
  Badge, Button, Card, CardContent, CardHeader, CardTitle,
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui'
import { ROUTES } from '@/constants/routes'
import { runtimeService } from '@/services'
import type { ID } from '@/types'
import { RuntimeNav } from './components/RuntimeNav'
import { EXECUTION_STATUS_VARIANT, formatCost, formatDate, formatMs } from './utils'

const TERMINAL = new Set(['SUCCEEDED', 'FAILED', 'CANCELLED', 'DEAD_LETTERED', 'DENIED', 'REJECTED'])

/** Phase 5.0 §74, §66 — execution details: input/output, risk, attempts,
 * tool calls, event timeline and cancel/retry/replay controls. */
export function ExecutionDetailPage() {
  const { id } = useParams<{ id: ID }>()
  const executionId = id as ID
  const qc = useQueryClient()

  const execution = useQuery({
    queryKey: ['runtime-execution', executionId], queryFn: () => runtimeService.execution(executionId),
    refetchInterval: (q) => (TERMINAL.has(q.state.data?.status ?? '') ? false : 3000),
  })
  const attempts = useQuery({
    queryKey: ['runtime-execution-attempts', executionId], queryFn: () => runtimeService.executionAttempts(executionId),
  })
  const toolCalls = useQuery({
    queryKey: ['runtime-execution-tool-calls', executionId], queryFn: () => runtimeService.executionToolCalls(executionId),
  })
  const events = useQuery({
    queryKey: ['runtime-execution-events', executionId], queryFn: () => runtimeService.executionEvents(executionId),
  })

  const onError = (e: unknown) => toast.error((e as { message?: string }).message ?? 'Operation failed')
  const invalidate = () => {
    void qc.invalidateQueries({ queryKey: ['runtime-execution', executionId] })
    void qc.invalidateQueries({ queryKey: ['runtime-execution-attempts', executionId] })
    void qc.invalidateQueries({ queryKey: ['runtime-execution-events', executionId] })
  }
  const cancel = useMutation({
    mutationFn: () => runtimeService.cancelExecution(executionId),
    onSuccess: () => { invalidate(); toast.success('Cancelled') }, onError,
  })
  const retry = useMutation({
    mutationFn: () => runtimeService.retryExecution(executionId),
    onSuccess: () => { invalidate(); toast.success('Retried') }, onError,
  })
  const replay = useMutation({
    mutationFn: () => runtimeService.replayExecution(executionId),
    onSuccess: () => { invalidate(); toast.success('Replayed as a new execution') }, onError,
  })

  if (execution.isLoading || !execution.data) {
    return <div className="flex justify-center p-12"><Loader2 className="h-6 w-6 animate-spin text-muted-foreground" /></div>
  }
  const e = execution.data

  return (
    <div className="mx-auto max-w-5xl space-y-6 p-4 sm:p-6">
      <PageHeader
        icon={Cpu}
        title="Execution"
        description={e.correlation_id ? `Correlation: ${e.correlation_id}` : `Trigger: ${e.trigger_type}`}
        backTo={ROUTES.RUNTIME_EXECUTIONS}
        backLabel="Executions"
      />
      <RuntimeNav />

      <Card>
        <CardHeader><CardTitle className="text-base">Status</CardTitle></CardHeader>
        <CardContent className="space-y-4">
          <div className="flex flex-wrap gap-2">
            <Badge variant={EXECUTION_STATUS_VARIANT[e.status]}>{e.status}</Badge>
            {e.decision && <Badge variant="outline">{e.decision}</Badge>}
            {e.risk_score !== null && <Badge variant="outline">Risk {e.risk_score}</Badge>}
            <Badge variant="outline">{e.priority}</Badge>
            <Badge variant="outline">Attempt {e.attempt_count}</Badge>
          </div>
          {e.error_message && (
            <p className="rounded-md bg-destructive/10 p-3 text-sm text-destructive">
              {e.error_code}: {e.error_message}
            </p>
          )}
          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <p className="mb-1 text-xs font-medium uppercase text-muted-foreground">Input</p>
              <pre className="max-h-48 overflow-auto rounded-md bg-muted p-3 text-xs">{JSON.stringify(e.input_payload, null, 2)}</pre>
            </div>
            <div>
              <p className="mb-1 text-xs font-medium uppercase text-muted-foreground">Output</p>
              <pre className="max-h-48 overflow-auto rounded-md bg-muted p-3 text-xs">
                {e.output_payload ? JSON.stringify(e.output_payload, null, 2) : '—'}
              </pre>
            </div>
          </div>
          <div className="flex flex-wrap gap-3 text-sm text-muted-foreground">
            <span>Duration: {formatMs(e.duration_ms)}</span>
            <span>Cost: {formatCost(e.cost)}</span>
            <span>Queued: {formatDate(e.queued_at)}</span>
            <span>Started: {formatDate(e.started_at)}</span>
            <span>Completed: {formatDate(e.completed_at)}</span>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button size="sm" variant="outline" disabled={TERMINAL.has(e.status) || cancel.isPending}
                    onClick={() => cancel.mutate()}>
              <XCircle className="h-3.5 w-3.5" /> Cancel
            </Button>
            <Button size="sm" variant="outline"
                    disabled={!['FAILED', 'TIMED_OUT', 'DEAD_LETTERED'].includes(e.status) || retry.isPending}
                    onClick={() => retry.mutate()}>
              <RefreshCw className="h-3.5 w-3.5" /> Retry
            </Button>
            <Button size="sm" variant="outline" disabled={replay.isPending} onClick={() => replay.mutate()}>
              <Repeat className="h-3.5 w-3.5" /> Replay
            </Button>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle className="text-base">Attempts</CardTitle></CardHeader>
        <CardContent className="p-0">
          {(attempts.data ?? []).length === 0 ? (
            <p className="p-4 text-sm text-muted-foreground">No attempts yet.</p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>#</TableHead><TableHead>Worker</TableHead><TableHead>Status</TableHead>
                  <TableHead>Duration</TableHead><TableHead>Error</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {(attempts.data ?? []).map((a) => (
                  <TableRow key={a.id}>
                    <TableCell>{a.attempt_number}</TableCell>
                    <TableCell className="font-mono text-xs">{a.worker_id ?? '—'}</TableCell>
                    <TableCell><Badge variant={EXECUTION_STATUS_VARIANT[a.status] ?? 'outline'}>{a.status}</Badge></TableCell>
                    <TableCell className="text-muted-foreground">{formatMs(a.duration_ms)}</TableCell>
                    <TableCell className="text-xs text-destructive">{a.error_code ?? '—'}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle className="text-base">Tool calls</CardTitle></CardHeader>
        <CardContent className="p-0">
          {(toolCalls.data ?? []).length === 0 ? (
            <p className="p-4 text-sm text-muted-foreground">No tool calls.</p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow><TableHead>Action</TableHead><TableHead>Status</TableHead><TableHead>Duration</TableHead></TableRow>
              </TableHeader>
              <TableBody>
                {(toolCalls.data ?? []).map((c) => (
                  <TableRow key={c.id}>
                    <TableCell className="font-medium">{c.action}</TableCell>
                    <TableCell><Badge variant={c.status === 'ALLOWED' ? 'success' : 'destructive'}>{c.status}</Badge></TableCell>
                    <TableCell className="text-muted-foreground">{formatMs(c.duration_ms)}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle className="text-base">Event timeline</CardTitle></CardHeader>
        <CardContent className="p-0">
          {(events.data ?? []).length === 0 ? (
            <p className="p-4 text-sm text-muted-foreground">No events recorded.</p>
          ) : (
            <ul className="divide-y divide-border">
              {(events.data ?? []).map((ev) => (
                <li key={ev.id} className="flex items-center justify-between gap-3 p-3 text-sm">
                  <span className="font-medium text-foreground">{ev.event_type.replace(/_/g, ' ')}</span>
                  <span className="text-muted-foreground">{formatDate(ev.created_at)}</span>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
