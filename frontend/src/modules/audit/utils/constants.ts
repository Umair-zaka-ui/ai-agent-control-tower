import type { SelectOption } from '@/components/ui/select'
import type { AuditActorType, AuditSeverity } from '../types'

/** Severity levels offered as a filter (SRS §Severity). */
export const SEVERITY_OPTIONS: { value: AuditSeverity; label: string }[] = [
  { value: 'INFO', label: 'Info' },
  { value: 'LOW', label: 'Low' },
  { value: 'MEDIUM', label: 'Medium' },
  { value: 'HIGH', label: 'High' },
  { value: 'CRITICAL', label: 'Critical' },
]

export const ACTOR_TYPE_OPTIONS: { value: AuditActorType; label: string }[] = [
  { value: 'USER', label: 'User' },
  { value: 'AGENT', label: 'AI Agent' },
  { value: 'SYSTEM', label: 'System' },
]

/** Event categories (mirror the backend audit_view category constants). */
export const CATEGORY_OPTIONS: SelectOption[] = [
  { value: 'AUTHENTICATION', label: 'Authentication' },
  { value: 'AGENT', label: 'Agent' },
  { value: 'API_KEY', label: 'API Key' },
  { value: 'POLICY', label: 'Policy' },
  { value: 'APPROVAL', label: 'Approval' },
  { value: 'ADMINISTRATION', label: 'Administration' },
  { value: 'CONFIGURATION', label: 'Configuration' },
  { value: 'SECURITY', label: 'Security' },
]

/** Decision outcomes a policy evaluation can produce. */
export const DECISION_OPTIONS: SelectOption[] = [
  { value: 'ALLOW', label: 'Allow' },
  { value: 'BLOCK', label: 'Block' },
  { value: 'PENDING_APPROVAL', label: 'Pending Approval' },
]

/** Default page size for the events explorer (server-side pagination). */
export const AUDIT_PAGE_SIZE = 50

/** Debounce for the audit search box (SRS §Search → 300ms). */
export const SEARCH_DEBOUNCE_MS = 300
