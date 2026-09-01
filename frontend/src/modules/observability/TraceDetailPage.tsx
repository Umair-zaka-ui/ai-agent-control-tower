import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { Eye, EyeOff, Loader2, Lock, Waves } from 'lucide-react'

import { useCan } from '@/authorization'
import { PageHeader } from '@/components/common'
import {
  Badge, Button, Card, CardContent,
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui'
import { ROUTES } from '@/constants/routes'
import type { ApiError } from '@/types'
import { observabilityService, type TraceContentResponse } from '@/services'
import { ObservabilityNav } from './components/ObservabilityNav'
import { CaptureModeBadge } from './components/badges'

/**
 * Phase 4.9 view 3 — Trace Detail (M4-4.9-FR-003, and the content-governance
 * set §4.3).
 *
 * The timeline is 4.2 metadata. The **content pane** is the sharp part: it is
 * served ONLY by 4.8's `GET /observability/traces/{trace_id}/content` — the
 * endpoint that requires the distinct `runtime.trace.content.view` permission
 * and emits `RUNTIME_TRACE_CONTENT_VIEWED` on every call. This component has no
 * other route to content.
 *
 * Four honest outcomes, none of them a disguised error:
 * - the caller lacks `runtime.trace.content.view` → a gated message; no request
 *   is made, so nothing is audited and no content is shown;
 * - capture mode is METADATA_ONLY / DISABLED → "no content was captured for
 *   this scope" (not an error — that is the policy working);
 * - REDACTED_CONTENT / FULL_CONTENT → the scrubbed / redacted items, with the
 *   mode shown;
 * - 404 → the trace does not exist for this tenant (cross-tenant is
 *   indistinguishable from missing, by design).
 */
export function TraceDetailPage() {
  const { executionId = '' } = useParams()
  const canViewContent = useCan('runtime.trace.content.view')
  const [showContent, setShowContent] = useState(false)

  const trace = useQuery({
    queryKey: ['obs-trace', executionId],
    queryFn: () => observabilityService.executionTrace(executionId),
    enabled: Boolean(executionId),
  })

  const traceId = trace.data?.trace_id

  const content = useQuery<TraceContentResponse, ApiError>({
    queryKey: ['obs-trace-content', traceId],
    // Fires ONLY when the operator explicitly asks and holds the permission.
    // Every fire is one audited call to the 4.8 endpoint.
    queryFn: () => observabilityService.traceContent(traceId as string),
    enabled: Boolean(traceId) && showContent && canViewContent,
    retry: false,
  })

  return (
    <div className="mx-auto max-w-6xl space-y-6 p-4 sm:p-6">
      <PageHeader
        icon={Waves}
        title="Trace detail"
        description={`Execution ${executionId}`}
        actions={
          <Link to={ROUTES.OBS_TRACES} className="text-sm text-muted-foreground hover:underline">
            ← Trace Explorer
          </Link>
        }
      />
      <ObservabilityNav />

      {/* --- The metadata timeline (4.2) ------------------------------------ */}
      <Card>
        <CardContent className="p-0">
          {trace.isLoading ? (
            <div className="flex justify-center p-10">
              <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
            </div>
          ) : trace.isError ? (
            <p className="p-6 text-sm text-muted-foreground">
              This execution was not found for your organization.
            </p>
          ) : trace.data ? (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Span</TableHead>
                    <TableHead>Kind</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead>Started</TableHead>
                    <TableHead>Duration</TableHead>
                    <TableHead>Error</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {trace.data.spans.map((s) => (
                    <TableRow key={s.span_id}>
                      <TableCell>{s.name}</TableCell>
                      <TableCell><Badge variant="outline">{s.kind}</Badge></TableCell>
                      <TableCell>{s.status ?? '—'}</TableCell>
                      <TableCell className="whitespace-nowrap text-muted-foreground">
                        {s.started_at ? new Date(s.started_at).toLocaleString() : '—'}
                      </TableCell>
                      <TableCell>{s.duration_ms != null ? `${s.duration_ms} ms` : '—'}</TableCell>
                      <TableCell className="font-mono text-xs text-destructive">{s.error_code ?? ''}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          ) : null}
        </CardContent>
      </Card>

      {trace.data?.notes?.length ? (
        <div className="rounded-lg border border-warning/30 bg-warning/10 p-3 text-sm text-muted-foreground">
          {trace.data.notes.map((n) => <p key={n}>{n}</p>)}
        </div>
      ) : null}

      {/* --- The content pane (4.8-governed) ------------------------------- */}
      <Card>
        <CardContent className="space-y-3 p-4">
          <div className="flex items-center justify-between">
            <div>
              <h2 className="text-sm font-semibold">Execution content</h2>
              <p className="text-xs text-muted-foreground">
                Prompts, tool arguments, tool results and model output — governed by capture policy and a
                separate, audited permission.
              </p>
            </div>
            {canViewContent ? (
              <Button
                variant="outline"
                size="sm"
                onClick={() => setShowContent((v) => !v)}
              >
                {showContent ? <EyeOff className="mr-1.5 h-4 w-4" aria-hidden /> : <Eye className="mr-1.5 h-4 w-4" aria-hidden />}
                {showContent ? 'Hide content' : 'View content'}
              </Button>
            ) : null}
          </div>

          {!canViewContent ? (
            <div className="flex items-start gap-2 rounded-lg border border-border bg-muted/40 p-3 text-sm">
              <Lock className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" aria-hidden />
              <span>
                <span className="font-medium text-foreground">Content view requires an additional permission.</span>{' '}
                <span className="text-muted-foreground">
                  You can see this execution's metadata and timeline. Reading its prompts and tool payloads requires{' '}
                  <span className="font-mono">runtime.trace.content.view</span>, which is separate from and stronger
                  than the metadata view. Ask an administrator to grant it; every content view is audited.
                </span>
              </span>
            </div>
          ) : !showContent ? (
            <p className="text-sm text-muted-foreground">
              Content is not shown by default. Opening it records an audited access
              (<span className="font-mono">RUNTIME_TRACE_CONTENT_VIEWED</span>).
            </p>
          ) : content.isLoading ? (
            <div className="flex justify-center p-6">
              <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
            </div>
          ) : content.isError ? (
            <ContentError error={content.error} />
          ) : content.data ? (
            <ContentBody data={content.data} />
          ) : null}
        </CardContent>
      </Card>
    </div>
  )
}

function ContentError({ error }: { error: ApiError }) {
  if (error.status === 404) {
    return (
      <p className="text-sm text-muted-foreground">
        This trace was not found for your organization.
      </p>
    )
  }
  if (error.status === 403 || error.code === 'TRACE_CONTENT_ACCESS_DENIED') {
    return (
      <div className="flex items-start gap-2 rounded-lg border border-border bg-muted/40 p-3 text-sm">
        <Lock className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" aria-hidden />
        <span className="text-muted-foreground">
          The server declined the content view: this trace exists for your organization, but your account does not
          hold <span className="font-mono">runtime.trace.content.view</span>.
        </span>
      </div>
    )
  }
  return <p className="text-sm text-destructive">{error.message}</p>
}

function ContentBody({ data }: { data: TraceContentResponse }) {
  return (
    <div className="space-y-4">
      {data.traces.map((view) => (
        <div key={view.execution_id} className="rounded-lg border border-border p-3">
          <div className="mb-2 flex flex-wrap items-center gap-2">
            <span className="font-mono text-xs text-muted-foreground">{view.execution_id.slice(0, 8)}…</span>
            <CaptureModeBadge value={view.mode} />
          </div>

          {!view.captured ? (
            <p className="text-sm text-muted-foreground">
              {view.note
                ?? (view.mode === 'DISABLED'
                  ? 'Telemetry is DISABLED for this scope — no content, and no telemetry event, was recorded.'
                  : 'Capture mode is METADATA_ONLY — no execution content was captured. This is the policy working, not an error.')}
            </p>
          ) : view.items.length === 0 ? (
            <p className="text-sm text-muted-foreground">No content rows were materialised for this execution.</p>
          ) : (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Source</TableHead>
                    <TableHead>Role</TableHead>
                    <TableHead>Flags</TableHead>
                    <TableHead>Body</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {view.items.map((item) => (
                    <TableRow key={item.id}>
                      <TableCell className="whitespace-nowrap text-xs text-muted-foreground">
                        {item.source_table} #{item.sequence}
                      </TableCell>
                      <TableCell>{item.role ?? '—'}</TableCell>
                      <TableCell className="space-x-1">
                        {item.redacted ? <Badge variant="warning">redacted</Badge> : null}
                        {item.secret_scrubbed ? <Badge variant="destructive">secret scrubbed</Badge> : null}
                        {!item.redacted && !item.secret_scrubbed ? <Badge variant="outline">as captured</Badge> : null}
                      </TableCell>
                      <TableCell>
                        <pre className="max-h-64 max-w-2xl overflow-auto whitespace-pre-wrap break-words rounded bg-muted p-2 text-xs">
                          {JSON.stringify(item.body, null, 2)}
                        </pre>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </div>
      ))}
    </div>
  )
}
