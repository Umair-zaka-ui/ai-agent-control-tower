import type { ID, ISODateString, JsonObject } from '@/types'

/** Derived event severity (mirrors the backend audit_view severity ladder). */
export type AuditSeverity = 'INFO' | 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL'
export type AuditActorType = 'USER' | 'AGENT' | 'SYSTEM'

/** A row in the enriched audit table (AuditEventListItem). */
export interface AuditEventListItem {
  id: ID
  created_at: ISODateString
  event_type: string
  category: string
  actor_type: AuditActorType
  actor_id: ID | null
  actor_name: string | null
  resource: string | null
  action: string | null
  decision: string | null
  severity: AuditSeverity
  status: string
  entity_type: string
  entity_id: ID | null
  request_id: string | null
}

export interface AuditRelatedEvent {
  id: ID
  event_type: string
  actor_name: string | null
  created_at: ISODateString
  severity: AuditSeverity
}

/** Full forensic detail for a single event (AuditEventDetail). */
export interface AuditEventDetail extends AuditEventListItem {
  correlation_id: string | null
  session_id: string | null
  ip_address: string | null
  user_agent: string | null
  reason: string | null
  policy: string | null
  approval_id: ID | null
  risk_score: number | null
  metadata: JsonObject
  /** Only populated for users holding `audit.export`. */
  request_payload: JsonObject | null
  response_payload: JsonObject | null
  related_events: AuditRelatedEvent[]
}

export interface AuditTimelineItem {
  id: ID
  created_at: ISODateString
  event_type: string
  severity: AuditSeverity
  actor_name: string | null
  label: string
}

export interface AuditStatistics {
  total_events: number
  security_events: number
  policy_evaluations: number
  approval_events: number
  authentication_events: number
  configuration_changes: number
}

/** Catalog entry used to populate filter dropdowns and the type reference. */
export interface AuditEventTypeInfo {
  value: string
  label: string
  category: string
  severity: AuditSeverity
}

export interface AuditSecuritySummary {
  failed_logins: number
  blocked_agents: number
  disabled_api_keys: number
  permission_violations: number
  suspicious_activity: number
  critical_alerts: number
  recent: AuditEventListItem[]
}

export interface ComplianceMetric {
  label: string
  score: number
  status: string
  detail: string
}

export interface AuditComplianceSummary {
  hipaa_readiness: ComplianceMetric
  soc2_readiness: ComplianceMetric
  iso27001_controls: ComplianceMetric
  policy_coverage: ComplianceMetric
  approval_coverage: ComplianceMetric
  audit_completeness: ComplianceMetric
}

/** Query parameters for the audit table / export feed (GET /audit). */
export interface AuditListParams {
  search?: string
  event_type?: string
  category?: string
  actor_type?: AuditActorType
  severity?: AuditSeverity
  decision?: string
  status?: string
  resource?: string
  date_from?: string
  date_to?: string
  limit?: number
  offset?: number
}
