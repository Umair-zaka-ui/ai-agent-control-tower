import { Component, type ErrorInfo, type ReactNode } from 'react'

import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'

const AUTHORIZATION_CODES = new Set([
  'PERMISSION_DENIED',
  'RESOURCE_FORBIDDEN',
  'ABAC_DENIED',
  'APPROVAL_REQUIRED',
  'MFA_REQUIRED',
  'JUSTIFICATION_REQUIRED',
])

function isAuthorizationError(error: unknown): boolean {
  if (typeof error !== 'object' || error === null) return false
  const e = error as { code?: unknown; status?: unknown }
  return (
    (typeof e.code === 'string' && AUTHORIZATION_CODES.has(e.code)) ||
    e.status === 403
  )
}

/**
 * §32 — catches authorization failures that escape a page (an unhandled 403 /
 * challenge rejection thrown during render) and shows an access-denied state
 * instead of a white screen. Non-authorization errors are re-thrown so the
 * application's generic error handling still sees them.
 */
export class AuthorizationErrorBoundary extends Component<
  { children: ReactNode; fallback?: ReactNode },
  { error: unknown | null }
> {
  state: { error: unknown | null } = { error: null }

  static getDerivedStateFromError(error: unknown) {
    return { error }
  }

  componentDidCatch(error: unknown, _info: ErrorInfo) {
    if (!isAuthorizationError(error)) throw error
  }

  render() {
    if (this.state.error === null) return this.props.children
    if (!isAuthorizationError(this.state.error)) throw this.state.error
    if (this.props.fallback) return this.props.fallback
    const message =
      (this.state.error as { message?: string }).message ?? 'Access denied.'
    return (
      <Card className="m-6" role="alert">
        <CardHeader>
          <CardTitle>Access denied</CardTitle>
          <CardDescription>{message}</CardDescription>
        </CardHeader>
        <CardContent>
          <Button variant="outline" onClick={() => this.setState({ error: null })}>
            Go back
          </Button>
        </CardContent>
      </Card>
    )
  }
}
