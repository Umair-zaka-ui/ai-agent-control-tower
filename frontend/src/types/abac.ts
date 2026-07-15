import type { ID, ISODateString } from './common'

/** ABAC engine (Phase 4.3.5). */

export type PolicyStatus =
  | 'DRAFT'
  | 'VALIDATED'
  | 'ACTIVE'
  | 'DISABLED'
  | 'DEPRECATED'
  | 'ARCHIVED'

export type PolicyEffect =
  | 'ALLOW'
  | 'DENY'
  | 'REQUIRE_APPROVAL'
  | 'REQUIRE_MFA'
  | 'REQUIRE_JUSTIFICATION'
  | 'MASK_FIELDS'
  | 'LIMIT_ACTION'
  | 'LOG_ONLY'

export type CombiningAlgorithm =
  | 'DENY_OVERRIDES'
  | 'ALLOW_OVERRIDES'
  | 'FIRST_APPLICABLE'
  | 'HIGHEST_PRIORITY'
  | 'ALL_MUST_ALLOW'

export type PolicyScopeType =
  | 'PLATFORM'
  | 'ORGANIZATION'
  | 'BUSINESS_UNIT'
  | 'DEPARTMENT'
  | 'TEAM'
  | 'PROJECT'
  | 'RESOURCE'

export type AttributeCategory = 'SUBJECT' | 'RESOURCE' | 'ACTION' | 'ENVIRONMENT' | 'AI'

/** A leaf condition (§9). */
export interface ABACLeafCondition {
  attribute: string
  operator: string
  value?: unknown
}

/** A nested condition node: ALL/ANY group, NOT, or a leaf. */
export interface ABACConditionGroup {
  all?: ABACConditionNode[]
  any?: ABACConditionNode[]
  not?: ABACConditionNode
}
export type ABACConditionNode = ABACConditionGroup | ABACLeafCondition

export interface ABACPolicyTarget {
  resource_types?: string[]
  actions?: string[]
  identity_types?: string[]
  roles?: string[]
  classifications?: string[]
}

export interface ABACPolicy {
  id: ID
  policy_family_id: ID
  organization_id: ID | null
  name: string
  description: string | null
  version: number
  status: PolicyStatus
  priority: number
  combining_algorithm: CombiningAlgorithm
  scope_type: PolicyScopeType
  scope_id: ID | null
  target: ABACPolicyTarget | null
  conditions: ABACConditionNode | null
  effect: PolicyEffect
  obligations: Record<string, unknown> | null
  valid_from: ISODateString | null
  valid_until: ISODateString | null
  created_by: ID | null
  updated_by: ID | null
  published_at: ISODateString | null
  created_at: ISODateString | null
  updated_at: ISODateString | null
}

export interface ABACPolicyWrite {
  name?: string
  description?: string | null
  priority?: number
  combining_algorithm?: CombiningAlgorithm
  scope_type?: PolicyScopeType
  scope_id?: ID | null
  target?: ABACPolicyTarget | null
  conditions?: ABACConditionNode | null
  effect?: PolicyEffect
  obligations?: Record<string, unknown> | null
  valid_from?: string | null
  valid_until?: string | null
}

export interface ABACValidationResult {
  policy_id: ID
  valid: boolean
  status: PolicyStatus
  errors: { code: string; message: string }[]
}

export interface ABACPolicyVersion {
  id: ID
  policy_family_id: ID
  version: number
  snapshot: Record<string, unknown>
  created_by: ID | null
  created_at: ISODateString | null
}

export interface ABACAttribute {
  id: ID
  name: string
  category: AttributeCategory
  data_type: string
  description: string | null
  sensitivity: 'PUBLIC' | 'INTERNAL' | 'RESTRICTED'
  supported_operators: string[] | null
  source: string | null
  is_system: boolean
  enabled: boolean
}

export interface ABACDecision {
  decision: string
  allowed: boolean
  reason: string
  matched_policies: { policy_id: ID; name: string; effect: string; priority: number }[]
  obligations: Record<string, unknown>[]
  explanation: {
    considered_policies?: { policy_id: ID; name: string; effect: string }[]
    matched_policies?: {
      policy_id: ID
      name: string
      effect: string
      priority: number
      conditions: { attribute: string; operator: string; expected: unknown; result: boolean; missing: boolean }[]
    }[]
    winning_effect?: string
    missing_attributes?: string[]
    reason?: string
  }
  evaluation_time_ms: number
  request_id: string | null
  applicable: boolean
}

export interface ABACSimulation {
  baseline_rbac: { allowed: boolean; reason: string }
  resource_authorization: { allowed: boolean; reason: string; source: string } | null
  abac: ABACDecision
}

export interface ABACEvaluationRow {
  id: ID
  organization_id: ID | null
  identity_id: ID | null
  resource_type: string | null
  resource_id: ID | null
  action: string
  decision: string
  matched_policy_ids: ID[] | null
  obligations: Record<string, unknown>[] | null
  explanation: ABACDecision['explanation'] | null
  evaluation_time_ms: number | null
  request_id: string | null
  correlation_id: string | null
  created_at: ISODateString | null
}

export interface ABACPolicyException {
  id: ID
  policy_id: ID
  subject_type: string
  subject_id: ID
  resource_type: string | null
  resource_id: ID | null
  reason: string | null
  approved_by: ID | null
  valid_from: ISODateString | null
  valid_until: ISODateString | null
  status: 'ACTIVE' | 'EXPIRED' | 'REVOKED'
  created_at: ISODateString | null
}
