import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { useLocation, useNavigate } from 'react-router-dom'
import { AlertCircle, LogIn } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { ROUTES } from '@/constants/routes'
import { useAuth } from '@/hooks/useAuth'
import { loginSchema, type LoginFormValues } from '@/utils/validation'
import type { ApiError } from '@/types'

/**
 * Login page — React Hook Form + Zod validated, wired to the auth context.
 * Dark enterprise design; surfaces backend errors inline.
 */
export function LoginPage() {
  const { login } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const [submitting, setSubmitting] = useState(false)
  const [formError, setFormError] = useState<string | null>(null)

  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<LoginFormValues>({
    resolver: zodResolver(loginSchema),
    defaultValues: { email: '', password: '', rememberMe: false },
  })

  /**
   * A 4xx/5xx that is *not* an authentication failure is a configuration or
   * server fault, not the user's fault. Rendering "Not Found" in the same red box
   * as "wrong password" sends people hunting for a bad password when the API is
   * misconfigured or unreachable.
   */
  const describeError = (apiError: ApiError): string => {
    switch (apiError?.status) {
      case 401:
        return 'Invalid email or password.'
      case 403:
        return apiError.message || 'This account or device is not permitted to sign in.'
      case 423:
        return 'Account temporarily locked after repeated failed attempts. Try again later.'
      case 404:
        return 'Sign-in service not found. The API may be misconfigured — contact your administrator.'
      case 0:
        return 'Cannot reach the server. Check your connection and try again.'
      default:
        return apiError?.message ?? 'Login failed. Please try again.'
    }
  }

  const onSubmit = async (values: LoginFormValues) => {
    setSubmitting(true)
    setFormError(null)
    try {
      await login(values.email, values.password, values.rememberMe)
      const from = (location.state as { from?: string } | null)?.from ?? ROUTES.DASHBOARD
      navigate(from, { replace: true })
    } catch (error) {
      setFormError(describeError(error as ApiError))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Card>
      <CardContent className="p-6">
        <form onSubmit={handleSubmit(onSubmit)} className="space-y-4" noValidate>
          {formError ? (
            <div
              role="alert"
              className="flex items-start gap-2 rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-destructive"
            >
              <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
              <span>{formError}</span>
            </div>
          ) : null}

          <div className="space-y-2">
            <Label htmlFor="email">Email</Label>
            <Input
              id="email"
              type="email"
              autoComplete="email"
              placeholder="admin@example.com"
              aria-invalid={Boolean(errors.email)}
              {...register('email')}
            />
            {errors.email ? (
              <p className="text-xs text-destructive">{errors.email.message}</p>
            ) : null}
          </div>

          <div className="space-y-2">
            <Label htmlFor="password">Password</Label>
            <Input
              id="password"
              type="password"
              autoComplete="current-password"
              placeholder="••••••••"
              aria-invalid={Boolean(errors.password)}
              {...register('password')}
            />
            {errors.password ? (
              <p className="text-xs text-destructive">{errors.password.message}</p>
            ) : null}
          </div>

          <div className="flex items-center gap-2">
            <input
              id="rememberMe"
              type="checkbox"
              className="h-4 w-4 rounded border-border bg-background accent-primary"
              {...register('rememberMe')}
            />
            <Label htmlFor="rememberMe" className="cursor-pointer text-sm font-normal">
              Keep me signed in for 7 days
            </Label>
          </div>
          <p className="-mt-2 text-xs text-muted-foreground">
            You will still be signed out after 30 minutes of inactivity.
          </p>

          <Button type="submit" className="w-full" disabled={submitting}>
            <LogIn />
            {submitting ? 'Signing in…' : 'Sign in'}
          </Button>
        </form>
      </CardContent>
    </Card>
  )
}
