import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Loader2, LockKeyhole, Unlock } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { protectionService } from '@/services'
import type { AccountLock, ID } from '@/types'

/**
 * Account locks (SRS §24). A security admin sees who is locked, why, until when, and
 * can unlock — which requires a reason and is audited (§29).
 */
export function AccountLocksPage() {
  const queryClient = useQueryClient()
  const [unlocking, setUnlocking] = useState<AccountLock | null>(null)
  const [reason, setReason] = useState('')

  const locks = useQuery({
    queryKey: ['account-locks', 'ACTIVE'],
    queryFn: () => protectionService.accountLocks('ACTIVE'),
  })

  const unlock = useMutation({
    mutationFn: (payload: { id: ID; reason: string }) =>
      protectionService.unlockLock(payload.id, payload.reason),
    onSuccess: () => {
      setUnlocking(null)
      setReason('')
      void queryClient.invalidateQueries({ queryKey: ['account-locks'] })
    },
  })

  return (
    <div className="mx-auto max-w-3xl space-y-4 p-4 sm:p-6">
      <div>
        <h1 className="text-xl font-semibold text-foreground">Locked accounts</h1>
        <p className="text-sm text-muted-foreground">
          Accounts locked by risk, repeated failures or an administrator.
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <LockKeyhole className="h-5 w-5 text-warning" aria-hidden="true" />
            Active locks
          </CardTitle>
        </CardHeader>
        <CardContent>
          {locks.isLoading ? (
            <div className="flex justify-center p-4" role="status" aria-label="Loading">
              <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" aria-hidden="true" />
            </div>
          ) : (locks.data ?? []).length === 0 ? (
            <p className="text-sm text-muted-foreground">No accounts are locked.</p>
          ) : (
            <ul className="divide-y divide-border" data-testid="account-locks">
              {(locks.data ?? []).map((lock) => (
                <li key={lock.id} className="flex items-center justify-between gap-3 py-2">
                  <div className="min-w-0">
                    <p className="truncate text-sm font-medium text-foreground">
                      {lock.user_email ?? lock.user_id}
                    </p>
                    <p className="truncate text-xs text-muted-foreground">
                      {lock.reason.replace(/_/g, ' ').toLowerCase()} ·{' '}
                      {lock.expires_at
                        ? `until ${new Date(lock.expires_at).toLocaleString()}`
                        : 'indefinite (security review)'}
                    </p>
                  </div>
                  <Button size="sm" variant="outline" onClick={() => setUnlocking(lock)}>
                    <Unlock className="h-3.5 w-3.5" aria-hidden="true" />
                    Unlock
                  </Button>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>

      {unlocking && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
          role="dialog"
          aria-modal="true"
          aria-label="Unlock account"
        >
          <Card className="w-full max-w-md">
            <CardHeader>
              <CardTitle className="text-base">Unlock {unlocking.user_email ?? 'account'}</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="unlock-reason">Reason (recorded in the audit log)</Label>
                <Input
                  id="unlock-reason"
                  value={reason}
                  onChange={(e) => setReason(e.target.value)}
                  placeholder="e.g. verified the user by phone"
                />
              </div>
              <div className="flex justify-end gap-2">
                <Button variant="ghost" onClick={() => setUnlocking(null)}>
                  Cancel
                </Button>
                <Button
                  disabled={!reason.trim() || unlock.isPending}
                  onClick={() => unlock.mutate({ id: unlocking.id, reason: reason.trim() })}
                >
                  {unlock.isPending ? (
                    <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
                  ) : (
                    <Unlock className="h-4 w-4" aria-hidden="true" />
                  )}
                  Unlock account
                </Button>
              </div>
            </CardContent>
          </Card>
        </div>
      )}
    </div>
  )
}
