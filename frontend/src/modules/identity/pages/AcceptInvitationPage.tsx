import { useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useMutation, useQuery } from '@tanstack/react-query'
import { AlertCircle, Building2, Loader2, Mail, ShieldCheck, UserPlus } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { ROUTES } from '@/constants/routes'
import { registrationService } from '@/services/registrationService'
import type { ApiError } from '@/types'
import { PasswordStrengthMeter } from '../components/PasswordStrengthMeter'
import { evaluatePassword } from '../passwordStrength'

/** Invitation errors the API distinguishes, and where each one should send the user. */
const DEAD_LINK_CODES = new Set([
  'INVITATION_EXPIRED',
  'INVITATION_ALREADY_USED',
  'INVITATION_CANCELLED',
  'INVITATION_NOT_FOUND',
])

/** `ApiError.code` is populated by `toApiError` from the identity error envelope. */
function errorCode(error: unknown): string | undefined {
  return (error as ApiError | undefined)?.code
}

/**
 * Accept an invitation and create the account (SRS §10, §16, §17).
 *
 * The email is **read-only**: it comes from the invitation, and the server ignores any
 * address in the request body. Showing it as an editable field would imply otherwise.
 */
export function AcceptInvitationPage() {
  const { token = '' } = useParams<{ token: string }>()
  const navigate = useNavigate()

  const [firstName, setFirstName] = useState('')
  const [lastName, setLastName] = useState('')
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [touched, setTouched] = useState(false)
  const [serverError, setServerError] = useState<string | null>(null)

  const preview = useQuery({
    queryKey: ['invitation', token],
    queryFn: () => registrationService.previewInvitation(token),
    enabled: Boolean(token),
    retry: false,
  })

  const identity = useMemo(
    () => [firstName, lastName, preview.data?.email.split('@')[0] ?? ''].filter(Boolean),
    [firstName, lastName, preview.data?.email],
  )
  const strength = useMemo(() => evaluatePassword(password, identity), [password, identity])
  const passwordsMatch = confirm.length > 0 && password === confirm

  const register = useMutation({
    mutationFn: () =>
      registrationService.registerFromInvitation({
        token,
        first_name: firstName.trim(),
        last_name: lastName.trim(),
        password,
        confirm_password: confirm,
      }),
    onSuccess: (result) => {
      navigate(ROUTES.REGISTRATION_SUCCESS, { replace: true, state: { result } })
    },
    onError: (error: ApiError) => {
      // The server is the authority on the password policy (ADR-0004). A password the
      // client meter approved can still be refused; say so rather than insisting.
      setServerError(error?.message ?? 'Could not create your account. Please try again.')
    },
  })

  // ---- dead / missing link ------------------------------------------------ //
  if (preview.isError) {
    const code = errorCode(preview.error)
    if (code && DEAD_LINK_CODES.has(code)) {
      navigate(ROUTES.INVITATION_EXPIRED, { replace: true, state: { code } })
      return null
    }
    return (
      <Card>
        <CardContent className="space-y-3 p-6" role="alert">
          <p className="text-sm text-destructive">We could not load this invitation.</p>
          <Button variant="outline" onClick={() => preview.refetch()}>
            Try again
          </Button>
        </CardContent>
      </Card>
    )
  }

  if (preview.isLoading || !preview.data) {
    return (
      <Card>
        <CardContent className="flex items-center gap-2 p-6 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
          <span>Loading your invitation…</span>
        </CardContent>
      </Card>
    )
  }

  const invitation = preview.data
  const namesOk = firstName.trim().length > 0 && lastName.trim().length > 0
  const canSubmit = namesOk && strength.meetsPolicy && passwordsMatch && !register.isPending

  return (
    <Card>
      <CardContent className="space-y-5 p-6">
        {/* What am I accepting? (§17) */}
        <div className="space-y-2 rounded-lg border border-border bg-muted/30 p-3">
          <div className="flex items-center gap-2 text-sm text-foreground">
            <Building2 className="h-4 w-4 text-primary" aria-hidden="true" />
            <span className="font-medium">{invitation.organization_name}</span>
          </div>
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <Mail className="h-4 w-4 shrink-0" aria-hidden="true" />
            <span className="truncate">{invitation.email}</span>
          </div>
          {invitation.role_name && (
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <ShieldCheck className="h-4 w-4 shrink-0" aria-hidden="true" />
              <span>
                Role: {invitation.role_name}
                {invitation.department_name ? ` · ${invitation.department_name}` : ''}
              </span>
            </div>
          )}
          <p className="text-xs text-muted-foreground">
            {invitation.invited_by_name ? `Invited by ${invitation.invited_by_name}. ` : ''}
            Expires {new Date(invitation.expires_at).toLocaleDateString()}.
          </p>
        </div>

        <form
          className="space-y-4"
          noValidate
          onSubmit={(event) => {
            event.preventDefault()
            setTouched(true)
            setServerError(null)
            if (canSubmit) register.mutate()
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

          {/* §10: email is read-only. */}
          <div className="space-y-2">
            <Label htmlFor="email">Email</Label>
            <Input id="email" type="email" value={invitation.email} readOnly disabled />
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
                aria-describedby={touched && !firstName.trim() ? 'firstName-error' : undefined}
                onChange={(e) => setFirstName(e.target.value)}
              />
              {touched && !firstName.trim() && (
                <p id="firstName-error" className="text-xs text-destructive">
                  First name is required
                </p>
              )}
            </div>
            <div className="space-y-2">
              <Label htmlFor="lastName">Last name</Label>
              <Input
                id="lastName"
                autoComplete="family-name"
                maxLength={100}
                value={lastName}
                aria-invalid={touched && !lastName.trim()}
                aria-describedby={touched && !lastName.trim() ? 'lastName-error' : undefined}
                onChange={(e) => setLastName(e.target.value)}
              />
              {touched && !lastName.trim() && (
                <p id="lastName-error" className="text-xs text-destructive">
                  Last name is required
                </p>
              )}
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
        </form>
      </CardContent>
    </Card>
  )
}
