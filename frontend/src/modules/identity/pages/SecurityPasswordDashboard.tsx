import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, Clock, Copy, KeyRound, Loader2, ShieldAlert } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { adminCredentialService } from '@/services'
import type { AdminResetResult, ID, PasswordDashboardUser } from '@/types'

function Section({
  title,
  icon,
  users,
  emptyLabel,
  onReset,
  resettingId,
}: {
  title: string
  icon: React.ReactNode
  users: PasswordDashboardUser[]
  emptyLabel: string
  onReset: (id: ID) => void
  resettingId: ID | null
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          {icon}
          {title}
          <span className="ml-1 rounded-full bg-muted px-2 py-0.5 text-xs text-muted-foreground">
            {users.length}
          </span>
        </CardTitle>
      </CardHeader>
      <CardContent>
        {users.length === 0 ? (
          <p className="text-sm text-muted-foreground">{emptyLabel}</p>
        ) : (
          <ul className="divide-y divide-border">
            {users.map((u) => (
              <li key={u.user_id} className="flex items-center justify-between gap-3 py-2">
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium text-foreground">{u.name}</p>
                  <p className="truncate text-xs text-muted-foreground">{u.email}</p>
                </div>
                <div className="flex items-center gap-3">
                  {u.days_until_expiry !== null && !u.is_expired && (
                    <span className="whitespace-nowrap text-xs text-muted-foreground">
                      in {u.days_until_expiry}d
                    </span>
                  )}
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={resettingId === u.user_id}
                    onClick={() => onReset(u.user_id)}
                  >
                    {resettingId === u.user_id ? (
                      <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />
                    ) : (
                      <KeyRound className="h-3.5 w-3.5" aria-hidden="true" />
                    )}
                    Reset
                  </Button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  )
}

/**
 * Security → Password dashboard (SRS §17, §24). Lists who is expired, expiring soon
 * and on a temporary password, and lets an administrator issue a fresh temporary
 * password. The temporary password is shown exactly once — the admin never sees an
 * existing password, only the new one to hand over.
 */
export function SecurityPasswordDashboard() {
  const queryClient = useQueryClient()
  const [resettingId, setResettingId] = useState<ID | null>(null)
  const [issued, setIssued] = useState<AdminResetResult | null>(null)
  const [copied, setCopied] = useState(false)

  const dashboard = useQuery({
    queryKey: ['password-dashboard'],
    queryFn: () => adminCredentialService.dashboard(),
  })

  const reset = useMutation({
    mutationFn: (userId: ID) => adminCredentialService.resetPassword(userId),
    onMutate: (userId) => setResettingId(userId),
    onSuccess: (result) => {
      setIssued(result)
      setCopied(false)
      void queryClient.invalidateQueries({ queryKey: ['password-dashboard'] })
    },
    onSettled: () => setResettingId(null),
  })

  if (dashboard.isLoading) {
    return (
      <div className="flex justify-center p-10" role="status" aria-label="Loading">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" aria-hidden="true" />
      </div>
    )
  }

  if (dashboard.isError || !dashboard.data) {
    return (
      <div className="p-6 text-sm text-destructive" role="alert">
        Could not load the password dashboard.
      </div>
    )
  }

  const data = dashboard.data

  return (
    <div className="mx-auto max-w-3xl space-y-4 p-4 sm:p-6">
      <div>
        <h1 className="text-xl font-semibold text-foreground">Password dashboard</h1>
        <p className="text-sm text-muted-foreground">
          {data.total_users} member{data.total_users === 1 ? '' : 's'}. Reset a password to issue a
          one-time temporary password the user must change at next login.
        </p>
      </div>

      {issued && (
        <div
          role="alert"
          data-testid="temp-password"
          className="space-y-2 rounded-md border border-primary/40 bg-primary/5 px-4 py-3"
        >
          <p className="text-sm font-medium text-foreground">Temporary password issued</p>
          <div className="flex items-center gap-2">
            <code className="flex-1 rounded bg-muted px-2 py-1 font-mono text-sm">
              {issued.temporary_password}
            </code>
            <Button
              size="sm"
              variant="outline"
              onClick={() => {
                void navigator.clipboard?.writeText(issued.temporary_password)
                setCopied(true)
              }}
            >
              <Copy className="h-3.5 w-3.5" aria-hidden="true" />
              {copied ? 'Copied' : 'Copy'}
            </Button>
          </div>
          <p className="text-xs text-muted-foreground">
            Shown once. Hand it over securely; it expires and must be changed at first login.
          </p>
        </div>
      )}

      <Section
        title="Expired"
        icon={<ShieldAlert className="h-5 w-5 text-destructive" aria-hidden="true" />}
        users={data.expired}
        emptyLabel="No expired passwords."
        onReset={(id) => reset.mutate(id)}
        resettingId={resettingId}
      />
      <Section
        title="Expiring soon"
        icon={<Clock className="h-5 w-5 text-warning" aria-hidden="true" />}
        users={data.expiring_soon}
        emptyLabel="Nobody is expiring soon."
        onReset={(id) => reset.mutate(id)}
        resettingId={resettingId}
      />
      <Section
        title="Temporary / must change"
        icon={<AlertTriangle className="h-5 w-5 text-primary" aria-hidden="true" />}
        users={data.temporary}
        emptyLabel="No temporary passwords outstanding."
        onReset={(id) => reset.mutate(id)}
        resettingId={resettingId}
      />
    </div>
  )
}
