import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { useMutation } from '@tanstack/react-query'
import { AlertCircle, CheckCircle2, Loader2, MailWarning } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { ROUTES } from '@/constants/routes'
import { registrationService } from '@/services/registrationService'
import type { ApiError, RegistrationResponse } from '@/types'

/** `ApiError.code` is populated by `toApiError` from the identity error envelope. */
function codeOf(error: unknown): string | undefined {
  return (error as ApiError | undefined)?.code
}

/**
 * Redeem an email-verification token (SRS §12, §16).
 *
 * Runs automatically on mount — the user arrived by clicking a link, and asking them
 * to click a second button to do the thing they already clicked is theatre. The ref
 * guards against React StrictMode double-invoking the effect and burning the
 * single-use token on its own second call.
 */
export function VerifyEmailPage() {
  const { token = '' } = useParams<{ token: string }>()
  const navigate = useNavigate()
  const attempted = useRef(false)
  const [resendEmail, setResendEmail] = useState('')
  const [resendDone, setResendDone] = useState(false)

  const verify = useMutation<RegistrationResponse, ApiError>({
    mutationFn: () => registrationService.verifyEmail(token),
  })

  const resend = useMutation({
    mutationFn: (email: string) => registrationService.resendVerification(email),
    onSuccess: () => setResendDone(true),
  })

  const { mutate: runVerify } = verify
  useEffect(() => {
    if (token && !attempted.current) {
      attempted.current = true
      runVerify()
    }
  }, [token, runVerify])

  if (verify.isPending || verify.isIdle) {
    return (
      <Card>
        <CardContent className="flex items-center gap-2 p-6 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
          <span>Confirming your email address…</span>
        </CardContent>
      </Card>
    )
  }

  if (verify.isSuccess) {
    const result = verify.data
    return (
      <Card>
        <CardContent className="space-y-4 p-6 text-center" role="status">
          <CheckCircle2 className="mx-auto h-10 w-10 text-success" aria-hidden="true" />
          <h2 className="text-lg font-semibold text-foreground">Email confirmed</h2>
          <p className="text-sm text-muted-foreground">{result.message}</p>
          {result.requires_approval ? (
            <p className="text-sm text-muted-foreground">
              An administrator must approve your account before you can sign in.
            </p>
          ) : (
            <Button className="w-full" onClick={() => navigate(ROUTES.LOGIN)}>
              Go to sign in
            </Button>
          )}
        </CardContent>
      </Card>
    )
  }

  const code = codeOf(verify.error)
  const alreadyVerified = code === 'EMAIL_ALREADY_VERIFIED'
  const expired = code === 'VERIFICATION_TOKEN_EXPIRED'

  if (alreadyVerified) {
    return (
      <Card>
        <CardContent className="space-y-4 p-6 text-center" role="status">
          <CheckCircle2 className="mx-auto h-10 w-10 text-success" aria-hidden="true" />
          <h2 className="text-lg font-semibold text-foreground">Already confirmed</h2>
          <p className="text-sm text-muted-foreground">
            This email address is already verified. You can sign in.
          </p>
          <Button className="w-full" onClick={() => navigate(ROUTES.LOGIN)}>
            Go to sign in
          </Button>
        </CardContent>
      </Card>
    )
  }

  return (
    <Card>
      <CardContent className="space-y-4 p-6">
        <div className="flex flex-col items-center gap-2 text-center" role="alert">
          {expired ? (
            <MailWarning className="h-10 w-10 text-warning" aria-hidden="true" />
          ) : (
            <AlertCircle className="h-10 w-10 text-destructive" aria-hidden="true" />
          )}
          <h2 className="text-lg font-semibold text-foreground">
            {expired ? 'This link has expired' : 'This link is not valid'}
          </h2>
          <p className="text-sm text-muted-foreground">
            {expired
              ? 'Verification links last 24 hours. Request a new one below.'
              : 'A newer link may have been sent. Use the most recent email, or request another.'}
          </p>
        </div>

        {resendDone ? (
          <p
            className="rounded-md border border-border bg-muted/30 px-3 py-2 text-center text-sm text-muted-foreground"
            role="status"
          >
            If that address needs verification, we have sent a new link.
          </p>
        ) : (
          <form
            className="space-y-3"
            noValidate
            onSubmit={(event) => {
              event.preventDefault()
              if (resendEmail.trim()) resend.mutate(resendEmail.trim())
            }}
          >
            <div className="space-y-2">
              <Label htmlFor="resendEmail">Your email</Label>
              <Input
                id="resendEmail"
                type="email"
                autoComplete="email"
                value={resendEmail}
                onChange={(e) => setResendEmail(e.target.value)}
              />
            </div>
            <Button
              type="submit"
              className="w-full"
              disabled={!resendEmail.trim() || resend.isPending}
            >
              {resend.isPending ? 'Sending…' : 'Send a new link'}
            </Button>
          </form>
        )}

        <p className="text-center text-sm">
          <Link to={ROUTES.LOGIN} className="text-primary hover:underline">
            Back to sign in
          </Link>
        </p>
      </CardContent>
    </Card>
  )
}
