import { useMemo, useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { AlertCircle, KeyRound, Loader2 } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { credentialService } from '@/services'
import type { ApiError } from '@/types'
import { PasswordStrengthMeter } from './PasswordStrengthMeter'
import { evaluatePassword } from '../passwordStrength'

function codeOf(error: unknown): string | undefined {
  return (error as ApiError | undefined)?.code
}

/** A machine code → human message the server envelope does not phrase for the field. */
const FIELD_MESSAGE: Record<string, string> = {
  INVALID_CURRENT_PASSWORD: 'Your current password is incorrect.',
  PASSWORD_REUSED: 'You have used this password recently. Choose a different one.',
  PASSWORD_MIN_AGE: 'Your password was changed too recently to change again.',
}

export interface ChangePasswordFormProps {
  identity?: string[]
  /** Called after the server confirms the change. */
  onSuccess: () => void
  submitLabel?: string
}

/**
 * The password-change form shared by the voluntary, first-login and expired flows
 * (SRS §15, §24). The meter mirrors the server policy for instant feedback; the
 * server remains the only gate, so a policy 422 is rendered rather than pre-empted.
 */
export function ChangePasswordForm({
  identity = [],
  onSuccess,
  submitLabel = 'Change password',
}: ChangePasswordFormProps) {
  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')
  const [confirm, setConfirm] = useState('')
  const [touched, setTouched] = useState(false)

  const strength = useMemo(() => evaluatePassword(next, identity), [next, identity])
  const passwordsMatch = confirm.length > 0 && next === confirm
  const notSameAsCurrent = next.length === 0 || next !== current

  const change = useMutation<unknown, ApiError>({
    mutationFn: () =>
      credentialService.changePassword({ current_password: current, new_password: next }),
    onSuccess,
  })

  const canSubmit =
    current.length > 0 &&
    strength.meetsPolicy &&
    passwordsMatch &&
    notSameAsCurrent &&
    !change.isPending

  const errorCode = codeOf(change.error)
  const serverError = change.isError
    ? (errorCode && FIELD_MESSAGE[errorCode]) ||
      change.error?.message ||
      'Could not change your password.'
    : null

  return (
    <form
      className="space-y-4"
      noValidate
      onSubmit={(event) => {
        event.preventDefault()
        setTouched(true)
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
        <Label htmlFor="currentPassword">Current password</Label>
        <Input
          id="currentPassword"
          type="password"
          autoComplete="current-password"
          value={current}
          aria-invalid={touched && current.length === 0}
          onChange={(e) => setCurrent(e.target.value)}
        />
      </div>

      <div className="space-y-2">
        <Label htmlFor="newPassword">New password</Label>
        <Input
          id="newPassword"
          type="password"
          autoComplete="new-password"
          value={next}
          aria-describedby="new-password-rules"
          onChange={(e) => setNext(e.target.value)}
        />
        <div id="new-password-rules">
          <PasswordStrengthMeter strength={strength} />
        </div>
        {next.length > 0 && !notSameAsCurrent && (
          <p className="text-xs text-destructive">New password must differ from the current one.</p>
        )}
      </div>

      <div className="space-y-2">
        <Label htmlFor="confirmNewPassword">Confirm new password</Label>
        <Input
          id="confirmNewPassword"
          type="password"
          autoComplete="new-password"
          value={confirm}
          aria-invalid={confirm.length > 0 && !passwordsMatch}
          aria-describedby={confirm.length > 0 && !passwordsMatch ? 'confirm-error' : undefined}
          onChange={(e) => setConfirm(e.target.value)}
        />
        {confirm.length > 0 && !passwordsMatch && (
          <p id="confirm-error" className="text-xs text-destructive">
            Passwords do not match
          </p>
        )}
      </div>

      <Button type="submit" className="w-full" disabled={!canSubmit}>
        {change.isPending ? (
          <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
        ) : (
          <KeyRound aria-hidden="true" />
        )}
        {change.isPending ? 'Changing…' : submitLabel}
      </Button>
    </form>
  )
}
