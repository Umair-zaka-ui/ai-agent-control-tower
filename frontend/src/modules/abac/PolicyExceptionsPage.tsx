import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Loader2, ShieldMinus, ShieldOff } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { adminSessionService } from '@/services/authService'
import { abacService } from '@/services'
import type { ApiError, ID } from '@/types'

/** Policy exceptions (§21, §33): time-boxed, approved, auto-expiring exemptions. */
export function PolicyExceptionsPage() {
  const qc = useQueryClient()
  const [policyId, setPolicyId] = useState('')
  const [subject, setSubject] = useState('')
  const [reason, setReason] = useState('')
  const [validUntil, setValidUntil] = useState('')

  const users = useQuery({ queryKey: ['org-users'], queryFn: () => adminSessionService.listUsers() })
  const policies = useQuery({ queryKey: ['abac-policies', ''], queryFn: () => abacService.policies() })
  const exceptions = useQuery({ queryKey: ['abac-exceptions'], queryFn: () => abacService.exceptions() })

  const create = useMutation<unknown, ApiError>({
    mutationFn: () => abacService.createException({
      policy_id: policyId, subject_id: subject, reason: reason.trim() || null,
      valid_until: new Date(validUntil).toISOString(),
    }),
    onSuccess: () => {
      setSubject(''); setReason('')
      void qc.invalidateQueries({ queryKey: ['abac-exceptions'] })
    },
  })
  const revoke = useMutation<unknown, ApiError, ID>({
    mutationFn: (id) => abacService.revokeException(id),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['abac-exceptions'] }),
  })

  const policyName = (id: ID) => policies.data?.find((p) => p.id === id)?.name ?? id
  const userLabel = (id: ID) => users.data?.find((u) => u.id === id)?.email ?? id

  return (
    <div className="mx-auto max-w-4xl space-y-4 p-4 sm:p-6">
      <div>
        <h1 className="text-xl font-semibold text-foreground">Policy exceptions</h1>
        <p className="text-sm text-muted-foreground">
          Approved, time-boxed exemptions from a policy for one subject. Exceptions expire automatically.
        </p>
      </div>

      <Card>
        <CardHeader><CardTitle className="text-base">Grant an exception</CardTitle></CardHeader>
        <CardContent className="space-y-3">
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="space-y-1">
              <Label htmlFor="exc-policy">Policy</Label>
              <select id="exc-policy" value={policyId} onChange={(e) => setPolicyId(e.target.value)}
                className="w-full rounded-md border border-border bg-background px-2 py-1.5 text-sm">
                <option value="">Select a policy…</option>
                {(policies.data ?? []).filter((p) => p.status === 'ACTIVE').map((p) => (
                  <option key={p.id} value={p.id}>{p.name}</option>
                ))}
              </select>
            </div>
            <div className="space-y-1">
              <Label htmlFor="exc-subject">Subject</Label>
              <select id="exc-subject" value={subject} onChange={(e) => setSubject(e.target.value)}
                className="w-full rounded-md border border-border bg-background px-2 py-1.5 text-sm">
                <option value="">Select a user…</option>
                {(users.data ?? []).map((u) => <option key={u.id} value={u.id}>{u.email}</option>)}
              </select>
            </div>
            <div className="space-y-1">
              <Label htmlFor="exc-until">Expires</Label>
              <Input id="exc-until" type="date" value={validUntil}
                onChange={(e) => setValidUntil(e.target.value)} />
            </div>
            <div className="space-y-1">
              <Label htmlFor="exc-reason">Reason</Label>
              <Input id="exc-reason" value={reason} onChange={(e) => setReason(e.target.value)}
                placeholder="Incident response" />
            </div>
          </div>
          <Button onClick={() => policyId && subject && validUntil && !create.isPending && create.mutate()}
            disabled={!policyId || !subject || !validUntil || create.isPending}>
            {create.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <ShieldOff className="h-4 w-4" />}
            Grant exception
          </Button>
          {create.isError && <p className="text-xs text-destructive">{create.error?.message ?? 'Could not create.'}</p>}
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle className="text-base">Exceptions</CardTitle></CardHeader>
        <CardContent className="p-0">
          {exceptions.isLoading ? (
            <div className="flex justify-center p-6"><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /></div>
          ) : (exceptions.data ?? []).length === 0 ? (
            <p className="p-4 text-sm text-muted-foreground">No exceptions.</p>
          ) : (
            <ul className="divide-y divide-border" data-testid="exceptions-list">
              {(exceptions.data ?? []).map((e) => (
                <li key={e.id} className="flex items-center justify-between gap-3 p-3">
                  <div className="min-w-0">
                    <p className="truncate text-sm text-foreground">
                      {userLabel(e.subject_id)} ⇢ exempt from “{policyName(e.policy_id)}”
                    </p>
                    <p className="text-xs text-muted-foreground">
                      {e.status.toLowerCase()}
                      {e.valid_until ? ` · until ${new Date(e.valid_until).toLocaleDateString()}` : ''}
                      {e.reason ? ` · ${e.reason}` : ''}
                    </p>
                  </div>
                  {e.status === 'ACTIVE' && (
                    <Button size="sm" variant="ghost" disabled={revoke.isPending}
                      onClick={() => revoke.mutate(e.id)} aria-label="Revoke exception">
                      <ShieldMinus className="h-4 w-4 text-destructive" />
                    </Button>
                  )}
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
      {revoke.isError && <p className="text-xs text-destructive">{revoke.error?.message ?? 'Could not revoke.'}</p>}
    </div>
  )
}
