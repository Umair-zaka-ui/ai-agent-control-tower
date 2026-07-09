import { Link } from 'react-router-dom'
import { CheckCircle2 } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { ROUTES } from '@/constants/routes'

/**
 * Recovery success (SRS §22). Reached after a completed password reset. The user's
 * sessions were revoked server-side, so the only way forward is a fresh sign-in.
 */
export function RecoverySuccessPage() {
  return (
    <Card>
      <CardContent className="space-y-4 p-6 text-center" role="status">
        <CheckCircle2 className="mx-auto h-12 w-12 text-success" aria-hidden="true" />
        <h1 className="text-lg font-semibold text-foreground">Password reset</h1>
        <p className="text-sm text-muted-foreground">
          Your password has been changed and all other sessions were signed out. Sign in with your
          new password to continue.
        </p>
        <Button asChild className="w-full">
          <Link to={ROUTES.LOGIN}>Go to sign in</Link>
        </Button>
      </CardContent>
    </Card>
  )
}
