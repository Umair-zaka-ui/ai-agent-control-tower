import { useState } from 'react'
import { Link } from 'react-router-dom'
import { CheckCircle2, ShieldCheck } from 'lucide-react'

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { ROUTES } from '@/constants/routes'
import { useAuth } from '@/hooks/useAuth'
import { ChangePasswordForm } from '../components/ChangePasswordForm'

/**
 * Voluntary password change (SRS §15, §23) — Settings → Security.
 *
 * Changing your password revokes your other sessions by default (the backend
 * policy), so a stolen session cannot outlive the change.
 */
export function ChangePasswordPage() {
  const { user } = useAuth()
  const [done, setDone] = useState(false)
  const identity = [user?.full_name, user?.email?.split('@')[0]].filter(Boolean) as string[]

  return (
    <div className="mx-auto max-w-lg space-y-4 p-4 sm:p-6">
      <div>
        <h1 className="text-xl font-semibold text-foreground">Change password</h1>
        <p className="text-sm text-muted-foreground">
          Choose a strong password you have not used before. Your other sessions will be signed out.
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <ShieldCheck className="h-5 w-5 text-primary" aria-hidden="true" />
            Your password
          </CardTitle>
        </CardHeader>
        <CardContent>
          {done ? (
            <div className="space-y-3 text-center" role="status">
              <CheckCircle2 className="mx-auto h-10 w-10 text-success" aria-hidden="true" />
              <p className="text-sm text-foreground">Your password has been changed.</p>
              <p className="text-sm">
                <Link to={ROUTES.SETTINGS_SECURITY} className="text-primary hover:underline">
                  Back to security settings
                </Link>
              </p>
            </div>
          ) : (
            <ChangePasswordForm identity={identity} onSuccess={() => setDone(true)} />
          )}
        </CardContent>
      </Card>
    </div>
  )
}
