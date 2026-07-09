import { useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { Clock, KeyRound, Loader2 } from 'lucide-react'

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { ROUTES } from '@/constants/routes'
import { credentialService } from '@/services'
import { useAuth } from '@/hooks/useAuth'
import { ChangePasswordForm } from '../components/ChangePasswordForm'

type Mode = 'first-login' | 'expired'

interface ForcedShellProps {
  mode: Mode
  onDone: () => void
  identity: string[]
}

const COPY: Record<Mode, { title: string; blurb: string; submit: string }> = {
  'first-login': {
    title: 'Set a new password',
    blurb:
      'You signed in with a temporary password. Choose your own password to finish setting up your account — you cannot continue until you do.',
    submit: 'Set password',
  },
  expired: {
    title: 'Your password has expired',
    blurb:
      'For security, passwords must be changed periodically. Choose a new password to continue — you cannot access the app until you do.',
    submit: 'Update password',
  },
}

/**
 * The shared forced-change shell. Named exports below render it in each mode so the
 * SRS's FirstLoginPasswordPage / PasswordExpiredPage exist as distinct components,
 * while a single guarded route drives the flow.
 */
function ForcedShell({ mode, onDone, identity }: ForcedShellProps) {
  const copy = COPY[mode]
  const Icon = mode === 'expired' ? Clock : KeyRound
  return (
    <div className="mx-auto max-w-lg p-4 sm:p-6">
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-lg">
            <Icon className="h-5 w-5 text-primary" aria-hidden="true" />
            {copy.title}
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <p className="text-sm text-muted-foreground">{copy.blurb}</p>
          <ChangePasswordForm identity={identity} onSuccess={onDone} submitLabel={copy.submit} />
        </CardContent>
      </Card>
    </div>
  )
}

/** SRS §23 FirstLoginPasswordPage — temporary-password flow. */
export function FirstLoginPasswordPage({ onDone, identity }: Omit<ForcedShellProps, 'mode'>) {
  return <ForcedShell mode="first-login" onDone={onDone} identity={identity} />
}

/** SRS §23 PasswordExpiredPage — expired-password flow. */
export function PasswordExpiredPage({ onDone, identity }: Omit<ForcedShellProps, 'mode'>) {
  return <ForcedShell mode="expired" onDone={onDone} identity={identity} />
}

/**
 * The guarded route target (SRS §11, §13). Reads the expiry status to decide which
 * message to show — a temporary password (`must_change`) is a first login; otherwise
 * the password has expired. On success it acknowledges the requirement so the guard
 * stops redirecting, and returns the user to the dashboard.
 */
export function ForcedPasswordChangePage() {
  const { user, acknowledgePasswordChange } = useAuth()
  const navigate = useNavigate()
  const identity = [user?.full_name, user?.email?.split('@')[0]].filter(Boolean) as string[]

  const expiration = useQuery({
    queryKey: ['password-expiration'],
    queryFn: () => credentialService.getExpiration(),
  })

  const onDone = () => {
    acknowledgePasswordChange()
    navigate(ROUTES.DASHBOARD, { replace: true })
  }

  if (expiration.isLoading) {
    return (
      <div className="flex justify-center p-10" role="status" aria-label="Loading">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" aria-hidden="true" />
      </div>
    )
  }

  const mode: Mode = expiration.data?.must_change ? 'first-login' : 'expired'
  return mode === 'first-login' ? (
    <FirstLoginPasswordPage onDone={onDone} identity={identity} />
  ) : (
    <PasswordExpiredPage onDone={onDone} identity={identity} />
  )
}
