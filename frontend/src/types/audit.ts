import type { ID, ISODateString, JsonObject } from './common'

export type ActorType = 'USER' | 'AGENT' | 'SYSTEM'

/** Audit log entry (GET /audit-logs), matching the backend AuditLogRead schema. */
export interface AuditLog {
  id: ID
  organization_id: ID
  actor_type: ActorType
  actor_id?: ID | null
  event_type: string
  entity_type: string
  entity_id?: ID | null
  metadata: JsonObject
  created_at: ISODateString
}
