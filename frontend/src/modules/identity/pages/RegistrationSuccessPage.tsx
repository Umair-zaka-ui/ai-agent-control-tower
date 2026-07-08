import { Link, useLocation } from 'react-router-dom'
import { AlertTriangle, MailCheck } from 'lucide-react'

import { Card, CardContent } from '@/components/ui/card'
import { ROUTES } from '@/constants/routes'
import type { RegistrationResponse } from '@/types'

/**
 * Shown after an account is created (SRS §16).
 *
 * If the verification email did not actually send, this says so. Telling a user to
 * "check your inbox" for a message that was never dispatched is the kind of small lie
 * that costs a support ticket and a lot of trust — and the backend leaves the account
 * in REGISTERED precisely so we can tell the difference.
 */
export function RegistrationSuccessPage() {
  const location = useLocation()
  const result = (location.state as { result?: RegistrationResponse } | null)?.result
  const emailFailed = result ? !result.email_sent : false

  return (
    <Card>
      <CardContent className="space-y-4 p-6 text-center" role="status">
        {emailFailed ? (
          <AlertTriangle className="mx-auto h-10 w-10 text-warning" aria-hidden="true" />
        ) : (
          <MailCheck className="mx-auto h-10 w-10 text-success" aria-hidden="true" />
        )}

        <h2 className="text-lg font-semibold text-foreground">
          {emailFailed ? 'Account created, but no email was sent' : 'Check your email'}
        </h2>

        <p className="text-sm text-muted-foreground">
          {result?.message ??
            'We have sent you a link to confirm your email address. You must confirm it before you can sign in.'}
        </p>

        {result?.email && (
          <p className="text-sm font-medium text-foreground" data-testid="registered-email">
            {result.email}
          </p>
        )}

        {result?.requires_approval && (
          <p className="rounded-md border border-border bg-muted/30 px-3 py-2 text-sm text-muted-foreground">
            After you confirm your address, an administrator must approve your account.
          </p>
        )}

        <p className="text-sm">
          <Link to={ROUTES.LOGIN} className="text-primary hover:underline">
            Back to sign in
          </Link>
        </p>
      </CardContent>
    </Card>
  )
}
