import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useMutation } from '@tanstack/react-query'
import { ArrowLeft, Loader2, Mail, MailCheck } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { ROUTES } from '@/constants/routes'
import { recoveryService } from '@/services'
import type { ApiError } from '@/types'

/**
 * Forgot password (SRS §9, §23).
 *
 * The server answers identically whether or not the account exists, so this page
 * shows the same confirmation regardless — it must never imply the address was
 * recognised. Even a network error resolves to the neutral confirmation, so a
 * failure cannot be used to probe for accounts either.
 */
export function ForgotPasswordPage() {
  const [email, setEmail] = useState('')
  const [done, setDone] = useState(false)

  const submit = useMutation<unknown, ApiError>({
    mutationFn: () => recoveryService.forgotPassword(email.trim()),
    onSettled: () => setDone(true),
  })

  if (done) {
    return (
      <Card>
        <CardContent className="space-y-3 p-6 text-center" role="status">
          <MailCheck className="mx-auto h-10 w-10 text-success" aria-hidden="true" />
          <h2 className="text-lg font-semibold text-foreground">Check your email</h2>
          <p className="text-sm text-muted-foreground">
            If an account exists for <span className="font-medium">{email.trim()}</span>, we have
            sent a link to reset your password. The link expires in 30 minutes.
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

  return (
    <Card>
      <CardContent className="space-y-5 p-6">
        <div>
          <h1 className="text-lg font-semibold text-foreground">Reset your password</h1>
          <p className="text-sm text-muted-foreground">
            Enter your email and we will send you a link to choose a new password.
          </p>
        </div>
        <form
          className="space-y-4"
          noValidate
          onSubmit={(event) => {
            event.preventDefault()
            if (email.trim() && !submit.isPending) submit.mutate()
          }}
        >
          <div className="space-y-2">
            <Label htmlFor="email">Email</Label>
            <Input
              id="email"
              type="email"
              autoComplete="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
          </div>
          <Button type="submit" className="w-full" disabled={!email.trim() || submit.isPending}>
            {submit.isPending ? (
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
            ) : (
              <Mail aria-hidden="true" />
            )}
            {submit.isPending ? 'Sending…' : 'Send reset link'}
          </Button>
          <p className="text-center text-sm">
            <Link
              to={ROUTES.LOGIN}
              className="inline-flex items-center gap-1 text-muted-foreground hover:text-foreground"
            >
              <ArrowLeft className="h-3.5 w-3.5" aria-hidden="true" />
              Back to sign in
            </Link>
          </p>
        </form>
      </CardContent>
    </Card>
  )
}
