// Enterprise Authorization Middleware — frontend integration (Phase 4.3.6 §32, §33).
export { AuthorizationProvider, AuthorizationUiContext } from './AuthorizationProvider'
export type { AuthorizationContextValue } from './AuthorizationProvider'
export { AuthorizationErrorBoundary } from './AuthorizationErrorBoundary'
export { PermissionGuard } from './PermissionGuard'
export { ApprovalRequiredDialog } from './ApprovalRequiredDialog'
export { MFAChallenge } from './MFAChallenge'
export { ObligationDialog } from './ObligationDialog'
export { useAuthorize } from './useAuthorize'
export { useAuthorizationUi } from './hooks'
export { decisionToUi, maskFields, maskedFields, actionLimits } from './decisionUi'
export type {
  AuthorizationDecision,
  AuthorizationDecisionName,
  AuthorizationObligation,
  DecisionUiBehavior,
} from './types'
