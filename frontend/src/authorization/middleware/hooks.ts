import { useContext } from 'react'

import { AuthorizationUiContext, type AuthorizationContextValue } from './AuthorizationProvider'

/** Access the middleware UI layer (§33): decision routing + challenge dialogs. */
export function useAuthorizationUi(): AuthorizationContextValue {
  const ctx = useContext(AuthorizationUiContext)
  if (!ctx) {
    throw new Error('useAuthorizationUi must be used inside <AuthorizationProvider>')
  }
  return ctx
}
