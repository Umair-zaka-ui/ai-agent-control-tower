import { Badge } from '@/components/ui/badge'
import type { AuditEventDetail } from '../types'
import { humanizeToken } from '../utils/format'
import { JsonViewer } from './JsonViewer'

interface ResponseViewerProps {
  event: AuditEventDetail
  /** True when the viewer holds audit.export — controls the redaction message. */
  canViewRaw: boolean
}

/** System decision / result viewer (SRS §Response Viewer). */
export function ResponseViewer({ event, canViewRaw }: ResponseViewerProps) {
  const hasSummary =
    event.decision != null || event.risk_score != null || event.policy != null || event.reason != null

  return (
    <div className="space-y-3">
      {hasSummary && (
        <dl className="grid gap-x-6 gap-y-3 sm:grid-cols-2">
          {event.decision != null && (
            <Field label="Decision">
              <Badge variant="outline">{humanizeToken(event.decision)}</Badge>
            </Field>
          )}
          {event.risk_score != null && (
            <Field label="Risk Score">
              <span className="font-semibold tabular-nums">{event.risk_score}/100</span>
            </Field>
          )}
          {event.policy != null && (
            <Field label="Policy">
              <span className="font-medium">{event.policy}</span>
            </Field>
          )}
          {event.reason != null && (
            <div className="sm:col-span-2">
              <dt className="text-xs text-muted-foreground">Explanation</dt>
              <dd className="text-sm">{event.reason}</dd>
            </div>
          )}
        </dl>
      )}
      <JsonViewer
        title="System Decision"
        payload={event.response_payload}
        filename="audit-response.json"
        defaultCollapsed={hasSummary}
        emptyMessage={
          canViewRaw
            ? 'No response payload was recorded for this event.'
            : 'Raw response payloads require the audit.export permission.'
        }
      />
    </div>
  )
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="mt-0.5 text-sm font-medium">{children}</dd>
    </div>
  )
}
