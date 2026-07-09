import { useEffect, useRef } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useMutation } from '@tanstack/react-query'
import { AlertCircle, CheckCircle2, Loader2 } from 'lucide-react'

import { Card, CardContent } from '@/components/ui/card'
import { ROUTES } from '@/constants/routes'
import { recoveryService } from '@/services'
import type { ApiError } from '@/types'

function codeOf(error: unknown): string | undefined {
  return (error as ApiError | undefined)?.code
}

/**
 * Confirm a new email address (SRS §12, §23). The token is redeemed automatically —
 * the user already clicked the link — and the primary address is swapped in on the
 * server. Distinguishes an expired/invalid link from an already-confirmed one, which
 * is success, not failure.
 */
export function VerifyNewEmailPage() {
  const { token = '' } = useParams()
  const verify = useMutation<unknown, ApiError>({
    mutationFn: () => recoveryService.verifyNewEmail(token),
  })

  // Redeem exactly once on mount (StrictMode guards against the double-invoke).
  const started = useRef(false)
  useEffect(() => {
    if (!started.current && token) {
      started.current = true
      verify.mutate()
    }
  }, [token, verify])

  const code = codeOf(verify.error)
  const alreadyDone = code === 'EMAIL_ALREADY_VERIFIED'

  if (verify.isPending || verify.isIdle) {
    return (
      <Card>
        <CardContent className="flex flex-col items-center gap-3 p-8" role="status">
          <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" aria-hidden="true" />
          <p className="text-sm text-muted-foreground">Confirming your new email address…</p>
        </CardContent>
      </Card>
    )
  }

  if (verify.isSuccess || alreadyDone) {
    return (
      <Card>
        <CardContent className="space-y-3 p-6 text-center" role="status">
          <CheckCircle2 className="mx-auto h-10 w-10 text-success" aria-hidden="true" />
          <h1 className="text-lg font-semibold text-foreground">Email updated</h1>
          <p className="text-sm text-muted-foreground">
            Your account email address has been changed. Use it next time you sign in.
          </p>
          <p className="text-sm">
            <Link to={ROUTES.LOGIN} className="text-primary hover:underline">
              Back to sign in
            </Link>
          </p>
        </CardContent>
      </Card>
    )
  }

  const expired = code === 'EMAIL_VERIFICATION_EXPIRED'
  return (
    <Card>
      <CardContent className="space-y-3 p-6 text-center" role="alert">
        <AlertCircle className="mx-auto h-10 w-10 text-destructive" aria-hidden="true" />
        <h1 className="text-lg font-semibold text-foreground">
          {expired ? 'Link expired' : 'Link not valid'}
        </h1>
        <p className="text-sm text-muted-foreground">
          {expired
            ? 'This confirmation link has expired. Request the email change again from your account settings.'
            : 'This confirmation link is not valid. Request the email change again from your account settings.'}
        </p>
        <p className="text-sm">
          <Link to={ROUTES.LOGIN} className="text-primary hover:underline">
            Back to sign in
          </Link>
        </p>
      </CardContent>
    </Card>
  )
}
