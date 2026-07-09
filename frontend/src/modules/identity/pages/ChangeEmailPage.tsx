import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useMutation } from '@tanstack/react-query'
import { AlertCircle, AtSign, Loader2, MailCheck } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { ROUTES } from '@/constants/routes'
import { recoveryService } from '@/services'
import { useAuth } from '@/hooks/useAuth'
import type { ApiError } from '@/types'

function codeOf(error: unknown): string | undefined {
  return (error as ApiError | undefined)?.code
}

const FIELD_MESSAGE: Record<string, string> = {
  INVALID_CURRENT_PASSWORD: 'Your current password is incorrect.',
  EMAIL_ALREADY_IN_USE: 'That email address is already in use.',
  INVALID_RECOVERY_REQUEST: 'That is already your email address.',
}

/**
 * Change email (SRS §12). Re-authenticates with the current password, then the server
 * emails the *new* address a confirmation link. The current address stays in effect
 * until the new one is confirmed, so a typo cannot lock the user out.
 */
export function ChangeEmailPage() {
  const { user } = useAuth()
  const [newEmail, setNewEmail] = useState('')
  const [currentPassword, setCurrentPassword] = useState('')
  const [sent, setSent] = useState(false)

  const change = useMutation<unknown, ApiError>({
    mutationFn: () =>
      recoveryService.changeEmail({ new_email: newEmail.trim(), current_password: currentPassword }),
    onSuccess: () => setSent(true),
  })

  const errorCode = codeOf(change.error)
  const serverError = change.isError
    ? (errorCode && FIELD_MESSAGE[errorCode]) || change.error?.message || 'Could not change your email.'
    : null
  const canSubmit = Boolean(newEmail.trim()) && currentPassword.length > 0 && !change.isPending

  return (
    <div className="mx-auto max-w-lg space-y-4 p-4 sm:p-6">
      <div>
        <h1 className="text-xl font-semibold text-foreground">Change email</h1>
        <p className="text-sm text-muted-foreground">
          {user?.email ? (
            <>
              Current: <span className="font-medium">{user.email}</span>
            </>
          ) : (
            'Update the email address on your account.'
          )}
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <AtSign className="h-5 w-5 text-primary" aria-hidden="true" />
            New email address
          </CardTitle>
        </CardHeader>
        <CardContent>
          {sent ? (
            <div className="space-y-3 text-center" role="status">
              <MailCheck className="mx-auto h-10 w-10 text-success" aria-hidden="true" />
              <p className="text-sm text-foreground">
                Confirmation sent to <span className="font-medium">{newEmail.trim()}</span>.
              </p>
              <p className="text-sm text-muted-foreground">
                Your current email stays active until you click the link in that message. Not seeing
                it? Check spam, or try again.
              </p>
              <p className="text-sm">
                <Link to={ROUTES.SETTINGS_SECURITY} className="text-primary hover:underline">
                  Back to security settings
                </Link>
              </p>
            </div>
          ) : (
            <form
              className="space-y-4"
              noValidate
              onSubmit={(event) => {
                event.preventDefault()
                if (canSubmit) change.mutate()
              }}
            >
              {serverError && (
                <div
                  role="alert"
                  className="flex items-start gap-2 rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-destructive"
                >
                  <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
                  <span>{serverError}</span>
                </div>
              )}
              <div className="space-y-2">
                <Label htmlFor="newEmail">New email</Label>
                <Input
                  id="newEmail"
                  type="email"
                  autoComplete="email"
                  value={newEmail}
                  onChange={(e) => setNewEmail(e.target.value)}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="currentPassword">Current password</Label>
                <Input
                  id="currentPassword"
                  type="password"
                  autoComplete="current-password"
                  value={currentPassword}
                  onChange={(e) => setCurrentPassword(e.target.value)}
                />
              </div>
              <Button type="submit" className="w-full" disabled={!canSubmit}>
                {change.isPending ? (
                  <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
                ) : (
                  <AtSign aria-hidden="true" />
                )}
                {change.isPending ? 'Sending…' : 'Send confirmation'}
              </Button>
            </form>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
