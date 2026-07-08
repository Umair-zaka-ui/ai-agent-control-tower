import { useMemo, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { useMutation } from '@tanstack/react-query'
import { AlertCircle, Loader2, UserPlus } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { ROUTES } from '@/constants/routes'
import { apiClient } from '@/services/apiClient'
import type { ApiError, RegistrationResponse } from '@/types'
import { PasswordStrengthMeter } from '../components/PasswordStrengthMeter'
import { evaluatePassword } from '../passwordStrength'

/** `ApiError.code` is populated by `toApiError` from the identity error envelope. */
function codeOf(error: unknown): string | undefined {
  return (error as ApiError | undefined)?.code
}

/**
 * Self-registration (SRS §3 mode 3, §16).
 *
 * **Disabled by default.** Organizations opt in by setting `registration_mode` to
 * `SELF_SERVICE`; every other organization returns `REGISTRATION_DISABLED`. Even when
 * enabled, the account still requires email verification *and* administrator approval
 * before it can sign in — enabling self-registration never means "anyone can walk in".
 *
 * The organization is addressed by `?org=<id>` because a self-service signup link is
 * something an organization publishes; there is no global "register" that could guess
 * which tenant a stranger meant.
 */
export function RegisterPage() {
  const [params] = useSearchParams()
  const navigate = useNavigate()
  const organizationId = params.get('org') ?? ''

  const [email, setEmail] = useState('')
  const [firstName, setFirstName] = useState('')
  const [lastName, setLastName] = useState('')
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [touched, setTouched] = useState(false)

  const identity = useMemo(
    () => [firstName, lastName, email.split('@')[0]].filter(Boolean),
    [firstName, lastName, email],
  )
  const strength = useMemo(() => evaluatePassword(password, identity), [password, identity])
  const passwordsMatch = confirm.length > 0 && password === confirm

  const register = useMutation<RegistrationResponse, ApiError>({
    mutationFn: async () => {
      const { data } = await apiClient.post<RegistrationResponse>('/api/v1/auth/register/self', {
        organization_id: organizationId,
        email: email.trim(),
        first_name: firstName.trim(),
        last_name: lastName.trim(),
        password,
        confirm_password: confirm,
      })
      return data
    },
    onSuccess: (result) =>
      navigate(ROUTES.REGISTRATION_SUCCESS, { replace: true, state: { result } }),
  })

  if (!organizationId) {
    return (
      <Card>
        <CardContent className="space-y-3 p-6 text-center" role="alert">
          <AlertCircle className="mx-auto h-10 w-10 text-destructive" aria-hidden="true" />
          <h2 className="text-lg font-semibold text-foreground">Nothing to register for</h2>
          <p className="text-sm text-muted-foreground">
            This link is missing its organization. Most organizations join by invitation — ask an
            administrator to invite you.
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

  const registrationDisabled = codeOf(register.error) === 'REGISTRATION_DISABLED'
  const namesOk = firstName.trim() && lastName.trim()
  const canSubmit =
    Boolean(namesOk) && Boolean(email.trim()) && strength.meetsPolicy && passwordsMatch && !register.isPending

  return (
    <Card>
      <CardContent className="space-y-5 p-6">
        <form
          className="space-y-4"
          noValidate
          onSubmit={(event) => {
            event.preventDefault()
            setTouched(true)
            if (canSubmit) register.mutate()
          }}
        >
          {register.isError && (
            <div
              role="alert"
              className="flex items-start gap-2 rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-destructive"
            >
              <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
              <span>
                {registrationDisabled
                  ? 'This organization does not allow self-registration. Ask an administrator to invite you.'
                  : (register.error?.message ?? 'Could not create your account.')}
              </span>
            </div>
          )}

          <div className="space-y-2">
            <Label htmlFor="email">Email</Label>
            <Input
              id="email"
              type="email"
              autoComplete="email"
              value={email}
              aria-invalid={touched && !email.trim()}
              onChange={(e) => setEmail(e.target.value)}
            />
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor="firstName">First name</Label>
              <Input
                id="firstName"
                autoComplete="given-name"
                maxLength={100}
                value={firstName}
                aria-invalid={touched && !firstName.trim()}
                onChange={(e) => setFirstName(e.target.value)}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="lastName">Last name</Label>
              <Input
                id="lastName"
                autoComplete="family-name"
                maxLength={100}
                value={lastName}
                aria-invalid={touched && !lastName.trim()}
                onChange={(e) => setLastName(e.target.value)}
              />
            </div>
          </div>

          <div className="space-y-2">
            <Label htmlFor="password">Password</Label>
            <Input
              id="password"
              type="password"
              autoComplete="new-password"
              value={password}
              aria-describedby="password-rules"
              onChange={(e) => setPassword(e.target.value)}
            />
            <div id="password-rules">
              <PasswordStrengthMeter strength={strength} />
            </div>
          </div>

          <div className="space-y-2">
            <Label htmlFor="confirmPassword">Confirm password</Label>
            <Input
              id="confirmPassword"
              type="password"
              autoComplete="new-password"
              value={confirm}
              aria-invalid={confirm.length > 0 && !passwordsMatch}
              aria-describedby={
                confirm.length > 0 && !passwordsMatch ? 'confirmPassword-error' : undefined
              }
              onChange={(e) => setConfirm(e.target.value)}
            />
            {confirm.length > 0 && !passwordsMatch && (
              <p id="confirmPassword-error" className="text-xs text-destructive">
                Passwords do not match
              </p>
            )}
          </div>

          <Button type="submit" className="w-full" disabled={!canSubmit}>
            {register.isPending ? (
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
            ) : (
              <UserPlus aria-hidden="true" />
            )}
            {register.isPending ? 'Creating your account…' : 'Create account'}
          </Button>

          <p className="text-center text-xs text-muted-foreground">
            You will need to confirm your email address, and an administrator must approve your
            account before you can sign in.
          </p>
        </form>
      </CardContent>
    </Card>
  )
}
