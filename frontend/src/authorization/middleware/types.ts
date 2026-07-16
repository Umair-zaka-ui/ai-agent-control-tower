// Authorization middleware — frontend integration (Phase 4.3.6 §32, §33).

/** Normalized decision names returned by the Authorization Gateway (§17). */
export type AuthorizationDecisionName =
  | 'ALLOW'
  | 'DENY'
  | 'REQUIRE_APPROVAL'
  | 'REQUIRE_MFA'
  | 'REQUIRE_JUSTIFICATION'
  | 'MASK_FIELDS'
  | 'LIMIT_ACTION'

export interface AuthorizationObligation {
  type: string
  fields?: string[]
  limits?: Record<string, unknown>
  priority?: string
  reviewer_role?: string | null
  policy_id?: string
}

/** The §17 decision object as served by POST /api/v1/authorization/check. */
export interface AuthorizationDecision {
  allowed: boolean
  decision: AuthorizationDecisionName
  reason: string
  permission: string
  scope?: string | null
  source_role?: string | null
  evaluation_time_ms?: number
  cache_hit?: boolean
  events?: string[]
  obligations?: AuthorizationObligation[]
}

/** §33 — what the UI should do with a decision. */
export type DecisionUiBehavior =
  | { kind: 'continue' }
  | { kind: 'denied'; reason: string }
  | { kind: 'approval'; reason: string; obligation?: AuthorizationObligation }
  | { kind: 'mfa'; reason: string }
  | { kind: 'justification'; reason: string }
  | { kind: 'masked'; fields: string[] }
  | { kind: 'limited'; limits: Record<string, unknown> }
