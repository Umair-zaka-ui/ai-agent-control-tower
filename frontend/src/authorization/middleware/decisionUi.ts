// §33 UI behaviors — one mapping from gateway decisions to what the SPA does.

import type {
  AuthorizationDecision,
  AuthorizationObligation,
  DecisionUiBehavior,
} from './types'

const MASK = '***'

/** Map a gateway decision onto the §33 UI behavior. */
export function decisionToUi(decision: AuthorizationDecision): DecisionUiBehavior {
  switch (decision.decision) {
    case 'ALLOW':
      return { kind: 'continue' }
    case 'REQUIRE_APPROVAL':
      return {
        kind: 'approval',
        reason: decision.reason,
        obligation: decision.obligations?.find((o) => o.type === 'CREATE_APPROVAL'),
      }
    case 'REQUIRE_MFA':
      return { kind: 'mfa', reason: decision.reason }
    case 'REQUIRE_JUSTIFICATION':
      return { kind: 'justification', reason: decision.reason }
    case 'MASK_FIELDS':
      return { kind: 'masked', fields: maskedFields(decision.obligations) }
    case 'LIMIT_ACTION':
      return { kind: 'limited', limits: actionLimits(decision.obligations) }
    default:
      return { kind: 'denied', reason: decision.reason }
  }
}

export function maskedFields(obligations?: AuthorizationObligation[]): string[] {
  return obligations?.find((o) => o.type === 'MASK_FIELDS')?.fields ?? []
}

export function actionLimits(
  obligations?: AuthorizationObligation[],
): Record<string, unknown> {
  return obligations?.find((o) => o.type === 'LIMIT_ACTION')?.limits ?? {}
}

/**
 * Render-side companion of the backend MASK_FIELDS obligation: returns a copy
 * of `data` with the restricted fields replaced (recursively). The server has
 * already redacted its response — this exists for locally-assembled views.
 */
export function maskFields<T>(data: T, fields: string[]): T {
  if (!fields.length || data === null || typeof data !== 'object') return data
  if (Array.isArray(data)) {
    return data.map((item) => maskFields(item, fields)) as T
  }
  const out: Record<string, unknown> = {}
  for (const [key, value] of Object.entries(data as Record<string, unknown>)) {
    out[key] = fields.includes(key) ? MASK : maskFields(value, fields)
  }
  return out as T
}
