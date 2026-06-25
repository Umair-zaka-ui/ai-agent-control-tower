import type { ID, ISODateString, JsonObject } from './common'

export interface AuditLog {
  id: ID
  entity_type: string
  entity_id: ID
  action: string
  actor_type: string
  actor_id?: ID | null
  ip_address?: string | null
  user_agent?: string | null
  request_id?: string | null
  trace_id?: string | null
  before_state?: JsonObject | null
  after_state?: JsonObject | null
  created_at: ISODateString
}
