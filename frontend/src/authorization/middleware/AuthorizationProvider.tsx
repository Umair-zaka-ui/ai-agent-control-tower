import { createContext, useCallback, useMemo, useState, type ReactNode } from 'react'

import { PermissionProvider } from '../PermissionContext'
import { ApprovalRequiredDialog } from './ApprovalRequiredDialog'
import { MFAChallenge } from './MFAChallenge'
import { ObligationDialog } from './ObligationDialog'
import { decisionToUi } from './decisionUi'
import type { AuthorizationDecision, DecisionUiBehavior } from './types'

export interface AuthorizationContextValue {
  /**
   * Route a gateway decision to the §33 UI behavior. Challenges open the
   * matching dialog; the returned behavior tells the caller whether to
   * continue (`continue` / `masked` / `limited`) or stop.
   */
  handleDecision: (decision: AuthorizationDecision) => DecisionUiBehavior
  /**
   * Route an ApiError (by its §26 error code) to the matching challenge
   * dialog. Returns true when the error was an authorization challenge and
   * was handled here.
   */
  handleAuthorizationError: (error: { code?: string; message: string }) => boolean
}

export const AuthorizationUiContext = createContext<AuthorizationContextValue | null>(null)

/**
 * §32 — the authorization provider: wraps the Phase 4.3.2 PermissionProvider
 * (local wildcard-aware checks) and adds the middleware layer — obligation and
 * challenge dialogs driven by gateway decisions or typed API errors.
 */
export function AuthorizationProvider({ children }: { children: ReactNode }) {
  const [behavior, setBehavior] = useState<DecisionUiBehavior | null>(null)

  const handleDecision = useCallback((decision: AuthorizationDecision) => {
    const ui = decisionToUi(decision)
    if (ui.kind !== 'continue' && ui.kind !== 'denied') setBehavior(ui)
    return ui
  }, [])

  const handleAuthorizationError = useCallback(
    (error: { code?: string; message: string }) => {
      switch (error.code) {
        case 'APPROVAL_REQUIRED':
          setBehavior({ kind: 'approval', reason: error.message })
          return true
        case 'MFA_REQUIRED':
          setBehavior({ kind: 'mfa', reason: error.message })
          return true
        case 'JUSTIFICATION_REQUIRED':
          setBehavior({ kind: 'justification', reason: error.message })
          return true
        default:
          return false
      }
    },
    [],
  )

  const value = useMemo(
    () => ({ handleDecision, handleAuthorizationError }),
    [handleDecision, handleAuthorizationError],
  )
  const close = useCallback(() => setBehavior(null), [])

  return (
    <PermissionProvider>
      <AuthorizationUiContext.Provider value={value}>
        {children}
        <ApprovalRequiredDialog
          open={behavior?.kind === 'approval'}
          reason={behavior?.kind === 'approval' ? behavior.reason : ''}
          obligation={behavior?.kind === 'approval' ? behavior.obligation : undefined}
          onClose={close}
        />
        <MFAChallenge
          open={behavior?.kind === 'mfa'}
          reason={behavior?.kind === 'mfa' ? behavior.reason : ''}
          onClose={close}
        />
        <ObligationDialog
          behavior={
            behavior?.kind === 'justification' ||
            behavior?.kind === 'masked' ||
            behavior?.kind === 'limited'
              ? behavior
              : null
          }
          open={
            behavior?.kind === 'justification' ||
            behavior?.kind === 'masked' ||
            behavior?.kind === 'limited'
          }
          onClose={close}
        />
      </AuthorizationUiContext.Provider>
    </PermissionProvider>
  )
}
