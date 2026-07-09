import { useMemo, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { useMutation } from '@tanstack/react-query'
import { AlertCircle, KeyRound, Loader2 } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { ROUTES } from '@/constants/routes'
import { recoveryService } from '@/services'
import type { ApiError } from '@/types'
import { PasswordStrengthMeter } from '../components/PasswordStrengthMeter'
import { evaluatePassword } from '../passwordStrength'

function codeOf(error: unknown): string | undefined {
  return (error as ApiError | undefined)?.code
}

/** A dead link says which kind of dead — each has a different next step (§14). */
const DEAD_LINK: Record<string, string> = {
  RESET_TOKEN_EXPIRED: 'This reset link has expired. Request a new one to continue.',
  RESET_TOKEN_USED: 'This reset link has already been used. Request a new one if you still need it.',
  RESET_TOKEN_INVALID: 'This reset link is not valid. Request a new one.',
}

/**
 * Reset password (SRS §10, §23).
 *
 * The token comes from the URL, never a form field. A dead link (expired / used /
 * invalid) routes the user back to "forgot password"; a policy rejection (weak /
 * reused) is shown inline so they can fix it on the same valid link.
 */
export function ResetPasswordPage() {
  const { token = '' } = useParams()
  const navigate = useNavigate()
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')

  const strength = useMemo(() => evaluatePassword(password), [password])
  const passwordsMatch = confirm.length > 0 && password === confirm

  const reset = useMutation<unknown, ApiError>({
    mutationFn: () => recoveryService.resetPassword({ token, new_password: password }),
    onSuccess: () => navigate(ROUTES.RECOVERY_SUCCESS, { replace: true }),
  })

  const errorCode = codeOf(reset.error)
  const deadLink = errorCode ? DEAD_LINK[errorCode] : undefined
  const canSubmit = strength.meetsPolicy && passwordsMatch && !reset.isPending

  if (deadLink) {
    return (
      <Card>
        <CardContent className="space-y-3 p-6 text-center" role="alert">
          <AlertCircle className="mx-auto h-10 w-10 text-destructive" aria-hidden="true" />
          <h2 className="text-lg font-semibold text-foreground">Link no longer works</h2>
          <p className="text-sm text-muted-foreground">{deadLink}</p>
          <p className="text-sm">
            <Link to={ROUTES.FORGOT_PASSWORD} className="text-primary hover:underline">
              Request a new reset link
            </Link>
          </p>
        </CardContent>
      </Card>
    )
  }

  return (
    <Card>
      <CardContent className="space-y-5 p-6">
        <div>
          <h1 className="text-lg font-semibold text-foreground">Choose a new password</h1>
          <p className="text-sm text-muted-foreground">
            For your security, all your active sessions will be signed out.
          </p>
        </div>
        <form
          className="space-y-4"
          noValidate
          onSubmit={(event) => {
            event.preventDefault()
            if (canSubmit) reset.mutate()
          }}
        >
          {reset.isError && !deadLink && (
            <div
              role="alert"
              className="flex items-start gap-2 rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-destructive"
            >
              <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
              <span>{reset.error?.message ?? 'Could not reset your password.'}</span>
            </div>
          )}

          <div className="space-y-2">
            <Label htmlFor="newPassword">New password</Label>
            <Input
              id="newPassword"
              type="password"
              autoComplete="new-password"
              value={password}
              aria-describedby="reset-rules"
              onChange={(e) => setPassword(e.target.value)}
            />
            <div id="reset-rules">
              <PasswordStrengthMeter strength={strength} />
            </div>
          </div>

          <div className="space-y-2">
            <Label htmlFor="confirmPassword">Confirm new password</Label>
            <Input
              id="confirmPassword"
              type="password"
              autoComplete="new-password"
              value={confirm}
              aria-invalid={confirm.length > 0 && !passwordsMatch}
              onChange={(e) => setConfirm(e.target.value)}
            />
            {confirm.length > 0 && !passwordsMatch && (
              <p className="text-xs text-destructive">Passwords do not match</p>
            )}
          </div>

          <Button type="submit" className="w-full" disabled={!canSubmit}>
            {reset.isPending ? (
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
            ) : (
              <KeyRound aria-hidden="true" />
            )}
            {reset.isPending ? 'Resetting…' : 'Reset password'}
          </Button>
        </form>
      </CardContent>
    </Card>
  )
}
