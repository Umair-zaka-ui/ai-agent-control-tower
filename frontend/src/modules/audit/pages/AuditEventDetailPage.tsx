import { Link, useParams } from 'react-router-dom'
import { AlertCircle, ArrowLeft, Download } from 'lucide-react'

import { FullPageSpinner } from '@/components/common/Spinner'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { ROUTES } from '@/constants/routes'
import { useAuth } from '@/hooks/useAuth'
import { formatDateTime } from '@/utils/format'
import {
  EventSeverityBadge,
  EventStatusBadge,
  EventTypeBadge,
  RelatedEventsGraph,
  RequestViewer,
  ResponseViewer,
} from '../components'
import { useAuditEvent } from '../hooks'
import type { AuditEventDetail } from '../types'
import { exportAuditEventJson } from '../utils/export'
import { humanizeToken } from '../utils/format'
import { canExportAudit } from '../utils/permissions'

export function AuditEventDetailPage() {
  const { id } = useParams<{ id: string }>()
  const { permissions } = useAuth()
  const canExport = canExportAudit(permissions)
  const { data: event, isLoading, isError } = useAuditEvent(id)

  if (isLoading) return <FullPageSpinner />
  if (isError || !event) {
    return (
      <div role="alert" className="flex flex-col items-center gap-3 py-24 text-center">
        <AlertCircle className="h-7 w-7 text-destructive" />
        <p className="text-sm text-muted-foreground">Unable to load audit information.</p>
        <Button variant="outline" asChild>
          <Link to={ROUTES.AUDIT}>Back to audit</Link>
        </Button>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <Link
          to={`${ROUTES.AUDIT}/events`}
          className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
        >
          <ArrowLeft className="h-4 w-4" />
          All events
        </Link>
        {canExport && (
          <Button variant="outline" size="sm" onClick={() => exportAuditEventJson(event)}>
            <Download className="h-4 w-4" />
            Export JSON
          </Button>
        )}
      </div>

      <EventSummary event={event} />

      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Request</CardTitle>
          </CardHeader>
          <CardContent>
            <RequestViewer payload={event.request_payload} canViewRaw={canExport} />
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Response &amp; Decision</CardTitle>
          </CardHeader>
          <CardContent>
            <ResponseViewer event={event} canViewRaw={canExport} />
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Related Events</CardTitle>
        </CardHeader>
        <CardContent>
          <RelatedEventsGraph events={event.related_events} currentId={event.id} />
        </CardContent>
      </Card>
    </div>
  )
}

function EventSummary({ event }: { event: AuditEventDetail }) {
  return (
    <Card>
      <CardHeader className="flex-row items-start justify-between gap-3 space-y-0">
        <div className="space-y-1">
          <div className="flex flex-wrap items-center gap-2">
            <EventTypeBadge eventType={event.event_type} category={event.category} />
            <EventSeverityBadge severity={event.severity} />
            <EventStatusBadge status={event.status} />
          </div>
          <p className="font-mono text-xs text-muted-foreground">{event.id}</p>
        </div>
      </CardHeader>
      <CardContent>
        <dl className="grid gap-x-6 gap-y-3 sm:grid-cols-2 lg:grid-cols-3">
          <Field label="Timestamp" value={formatDateTime(event.created_at)} />
          <Field label="Actor" value={event.actor_name ?? humanizeToken(event.actor_type)} />
          <Field label="Actor Type" value={humanizeToken(event.actor_type)} />
          <Field label="Category" value={humanizeToken(event.category)} />
          <Field label="Resource" value={event.resource ?? '—'} />
          <Field label="Action" value={event.action ? humanizeToken(event.action) : '—'} />
          <Field label="Decision" value={event.decision ? humanizeToken(event.decision) : '—'} />
          <Field label="Policy" value={event.policy ?? '—'} />
          <Field label="Risk Score" value={event.risk_score != null ? `${event.risk_score}/100` : '—'} />
          <Field label="Request ID" value={event.request_id ?? '—'} mono />
          <Field label="Correlation ID" value={event.correlation_id ?? '—'} mono />
          <Field label="Session ID" value={event.session_id ?? '—'} mono />
          <Field label="IP Address" value={event.ip_address ?? '—'} mono />
          {event.approval_id && (
            <div>
              <dt className="text-xs text-muted-foreground">Approval</dt>
              <dd className="text-sm font-medium">
                <Link
                  to={`${ROUTES.APPROVALS}/${event.approval_id}`}
                  className="font-mono text-primary hover:underline"
                >
                  {String(event.approval_id).slice(0, 8)}
                </Link>
              </dd>
            </div>
          )}
          {event.reason && (
            <div className="sm:col-span-2 lg:col-span-3">
              <dt className="text-xs text-muted-foreground">Reason</dt>
              <dd className="text-sm">{event.reason}</dd>
            </div>
          )}
        </dl>
      </CardContent>
    </Card>
  )
}

function Field({ label, value, mono }: { label: string; value: React.ReactNode; mono?: boolean }) {
  return (
    <div>
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className={mono ? 'truncate font-mono text-xs font-medium' : 'text-sm font-medium'}>{value}</dd>
    </div>
  )
}
