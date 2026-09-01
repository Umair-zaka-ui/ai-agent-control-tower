import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { Loader2, Waves } from 'lucide-react'

import { EmptyState, PageHeader } from '@/components/common'
import {
  Badge, Button, Card, CardContent, Input, Select,
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui'
import { ROUTES } from '@/constants/routes'
import { observabilityService } from '@/services'
import { ObservabilityNav } from './components/ObservabilityNav'

const STATUSES = [
  '', 'SUCCEEDED', 'FAILED', 'TIMED_OUT', 'RUNNING', 'QUEUED', 'DENIED', 'BLOCKED', 'CANCELLED',
]

/**
 * Phase 4.9 view 2 — Trace Explorer (M4-4.9-FR-002).
 *
 * Search over 4.2's `GET /observability/traces`. Metadata only — this table
 * shows identities, timings, status, cost and token counts. No prompt, no tool
 * argument, no output. That boundary is enforced in 4.2's read model, not here.
 */
export function TraceExplorerPage() {
  const [status, setStatus] = useState('')
  const [onlyErrors, setOnlyErrors] = useState(false)
  const [agentId, setAgentId] = useState('')
  const [offset, setOffset] = useState(0)

  const params: Record<string, string | number | boolean | undefined> = {
    status: status || undefined,
    only_errors: onlyErrors || undefined,
    agent_id: agentId || undefined,
    limit: 50,
    offset,
  }

  const q = useQuery({
    queryKey: ['obs-traces', params],
    queryFn: () => observabilityService.traces(params),
  })
  const page = q.data

  return (
    <div className="mx-auto max-w-7xl space-y-6 p-4 sm:p-6">
      <PageHeader
        icon={Waves}
        title="Trace Explorer"
        description="Find the execution you need. Metadata only — content is on the trace detail, behind its own permission."
      />
      <ObservabilityNav />

      <Card>
        <CardContent className="flex flex-wrap items-end gap-3 p-4">
          <label className="text-sm">
            <span className="mb-1 block text-xs text-muted-foreground">Status</span>
            <Select
              aria-label="Status"
              value={status}
              onChange={(e) => { setStatus(e.target.value); setOffset(0) }}
              options={STATUSES.map((s) => ({ value: s, label: s || 'Any status' }))}
            />
          </label>
          <label className="text-sm">
            <span className="mb-1 block text-xs text-muted-foreground">Agent ID</span>
            <Input
              aria-label="Agent ID"
              value={agentId}
              onChange={(e) => { setAgentId(e.target.value); setOffset(0) }}
              placeholder="uuid"
            />
          </label>
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={onlyErrors}
              onChange={(e) => { setOnlyErrors(e.target.checked); setOffset(0) }}
              aria-label="Only errors"
            />
            Only errors
          </label>
        </CardContent>
      </Card>

      <Card>
        <CardContent className="p-0">
          {q.isLoading ? (
            <div className="flex justify-center p-10">
              <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
            </div>
          ) : !page || page.items.length === 0 ? (
            <EmptyState icon={Waves} title="No traces" description="Adjust the filters or widen the time window." />
          ) : (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Execution</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead>Started</TableHead>
                    <TableHead>Duration</TableHead>
                    <TableHead>Queue wait</TableHead>
                    <TableHead>Cost</TableHead>
                    <TableHead>Tokens</TableHead>
                    <TableHead>Error</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {page.items.map((t) => (
                    <TableRow key={t.execution_id}>
                      <TableCell className="font-mono text-xs">
                        <Link
                          to={ROUTES.OBS_TRACE_DETAIL.replace(':executionId', t.execution_id)}
                          className="hover:underline"
                        >
                          {t.execution_id.slice(0, 8)}…
                        </Link>
                        {t.correlated ? (
                          <Badge variant="outline" className="ml-1" title="Part of a caller-supplied correlation">corr</Badge>
                        ) : null}
                      </TableCell>
                      <TableCell>
                        <Badge variant={
                          t.status === 'SUCCEEDED' ? 'success'
                            : ['FAILED', 'TIMED_OUT', 'DEAD_LETTERED', 'DENIED', 'BLOCKED'].includes(t.status)
                              ? 'destructive' : 'secondary'
                        }>
                          {t.status}
                        </Badge>
                      </TableCell>
                      <TableCell className="whitespace-nowrap text-muted-foreground">
                        {t.started_at ? new Date(t.started_at).toLocaleString() : '—'}
                      </TableCell>
                      <TableCell>{t.duration_ms != null ? `${t.duration_ms} ms` : '—'}</TableCell>
                      <TableCell>{t.queue_wait_ms != null ? `${t.queue_wait_ms} ms` : '—'}</TableCell>
                      <TableCell>{t.cost_amount != null ? `$${Number(t.cost_amount).toFixed(4)}` : '—'}</TableCell>
                      <TableCell>{t.total_tokens ?? '—'}</TableCell>
                      <TableCell className="font-mono text-xs text-destructive">{t.error_code ?? ''}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>

      {page ? (
        <div className="flex items-center justify-between text-sm text-muted-foreground">
          <span>Showing {page.items.length} · offset {page.offset}</span>
          <div className="flex gap-2">
            <Button variant="outline" size="sm" disabled={offset === 0}
              onClick={() => setOffset(Math.max(0, offset - 50))}>Previous</Button>
            <Button variant="outline" size="sm" disabled={!page.has_more}
              onClick={() => setOffset(offset + 50)}>Next</Button>
          </div>
        </div>
      ) : null}
    </div>
  )
}
