import type { JsonObject } from '@/types'
import { JsonViewer } from './JsonViewer'

interface RequestViewerProps {
  /** Raw request payload (before_state). Null when redacted by RBAC. */
  payload: JsonObject | null
  /** True when the viewer holds audit.export — controls the redaction message. */
  canViewRaw: boolean
}

/** Original request payload viewer (SRS §Request Viewer). */
export function RequestViewer({ payload, canViewRaw }: RequestViewerProps) {
  return (
    <JsonViewer
      title="Original Request"
      payload={payload}
      filename="audit-request.json"
      emptyMessage={
        canViewRaw
          ? 'No request payload was recorded for this event.'
          : 'Raw request payloads require the audit.export permission.'
      }
    />
  )
}
