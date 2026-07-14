import { useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Loader2, ShieldMinus, UserCog } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { adminSessionService } from '@/services/authService'
import { resourceAuthzService } from '@/services'
import type { ApiError, ID } from '@/types'
import { ResourcePicker } from './components/ResourcePicker'

/**
 * Per-resource delegation (Phase 4.3.4 §13, §21): the owner delegates a set of
 * actions ("manage", "update", …) on one resource to a user, optionally
 * time-boxed. Expired delegations are ignored by the engine.
 */
export function DelegationManagementPage() {
  const qc = useQueryClient()
  const [params, setParams] = useSearchParams()
  const resourceId = params.get('resource') ?? ''
  const [delegate, setDelegate] = useState('')
  const [permissions, setPermissions] = useState('manage')
  const [expiresAt, setExpiresAt] = useState('')
  const [reason, setReason] = useState('')

  const users = useQuery({ queryKey: ['org-users'], queryFn: () => adminSessionService.listUsers() })
  const delegations = useQuery({
    queryKey: ['resource-delegations', resourceId],
    queryFn: () => resourceAuthzService.delegations(resourceId),
    enabled: !!resourceId,
  })

  const create = useMutation<unknown, ApiError>({
    mutationFn: () => resourceAuthzService.delegate(resourceId, {
      delegate_id: delegate,
      permissions: permissions.split(',').map((p) => p.trim()).filter(Boolean),
      expires_at: expiresAt ? new Date(expiresAt).toISOString() : null,
      reason: reason.trim() || null,
    }),
    onSuccess: () => {
      setDelegate(''); setReason('')
      void qc.invalidateQueries({ queryKey: ['resource-delegations', resourceId] })
    },
  })
  const revoke = useMutation<unknown, ApiError, ID>({
    mutationFn: (id) => resourceAuthzService.revokeDelegation(resourceId, id),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['resource-delegations', resourceId] }),
  })
  const userLabel = (id: ID) => users.data?.find((u) => u.id === id)?.email ?? id
  const isExpired = (iso: string | null) => !!iso && new Date(iso).getTime() < Date.now()

  return (
    <div className="mx-auto max-w-4xl space-y-4 p-4 sm:p-6">
      <div>
        <h1 className="text-xl font-semibold text-foreground">Delegation management</h1>
        <p className="text-sm text-muted-foreground">
          Delegate management of a single resource — time-boxed, revocable and audited.
        </p>
      </div>

      <Card>
        <CardContent className="pt-4">
          <ResourcePicker value={resourceId} onChange={(id) => setParams({ resource: id })} />
        </CardContent>
      </Card>

      {resourceId && (
        <>
          <Card>
            <CardHeader><CardTitle className="text-base">Delegate access</CardTitle></CardHeader>
            <CardContent className="space-y-3">
              <div className="grid gap-3 sm:grid-cols-2">
                <div className="space-y-1">
                  <Label htmlFor="dg-user">Delegate</Label>
                  <select id="dg-user" value={delegate} onChange={(e) => setDelegate(e.target.value)}
                    className="w-full rounded-md border border-border bg-background px-2 py-1.5 text-sm">
                    <option value="">Select a user…</option>
                    {(users.data ?? []).map((u) => <option key={u.id} value={u.id}>{u.email}</option>)}
                  </select>
                </div>
                <div className="space-y-1">
                  <Label htmlFor="dg-perms">Permissions (comma-separated)</Label>
                  <Input id="dg-perms" value={permissions} onChange={(e) => setPermissions(e.target.value)}
                    placeholder="manage, update, execute" />
                </div>
                <div className="space-y-1">
                  <Label htmlFor="dg-expires">Expires</Label>
                  <Input id="dg-expires" type="date" value={expiresAt} onChange={(e) => setExpiresAt(e.target.value)} />
                </div>
                <div className="space-y-1">
                  <Label htmlFor="dg-reason">Reason</Label>
                  <Input id="dg-reason" value={reason} onChange={(e) => setReason(e.target.value)}
                    placeholder="Vacation cover" />
                </div>
              </div>
              <Button onClick={() => delegate && !create.isPending && create.mutate()}
                disabled={!delegate || !permissions.trim() || create.isPending}>
                {create.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <UserCog className="h-4 w-4" />} Delegate
              </Button>
              {create.isError && <p className="text-xs text-destructive">{create.error?.message ?? 'Could not delegate.'}</p>}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-base"><UserCog className="h-4 w-4" /> Delegations</CardTitle>
            </CardHeader>
            <CardContent className="p-0">
              {delegations.isLoading ? (
                <div className="flex justify-center p-6"><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /></div>
              ) : (delegations.data ?? []).length === 0 ? (
                <p className="p-4 text-sm text-muted-foreground">No delegations.</p>
              ) : (
                <ul className="divide-y divide-border" data-testid="resource-delegations-list">
                  {(delegations.data ?? []).map((d) => (
                    <li key={d.id} className="flex items-center justify-between gap-3 p-3">
                      <div className="min-w-0">
                        <p className="truncate text-sm text-foreground">{userLabel(d.delegate_id)}</p>
                        <p className="text-xs text-muted-foreground">
                          {d.permissions.join(', ')}
                          {d.status === 'REVOKED' ? ' · revoked' : isExpired(d.expires_at) ? ' · expired' : ''}
                          {d.expires_at ? ` · until ${new Date(d.expires_at).toLocaleDateString()}` : ''}
                          {d.reason ? ` · ${d.reason}` : ''}
                        </p>
                      </div>
                      {d.status === 'ACTIVE' && !isExpired(d.expires_at) && (
                        <Button size="sm" variant="ghost" disabled={revoke.isPending}
                          onClick={() => revoke.mutate(d.id)} aria-label="Revoke delegation">
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
        </>
      )}
    </div>
  )
}
