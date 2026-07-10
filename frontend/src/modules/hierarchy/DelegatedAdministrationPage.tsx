import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Loader2, Plus, ShieldMinus, UserCog } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Label } from '@/components/ui/label'
import { adminSessionService } from '@/services/authService'
import { hierarchyService } from '@/services'
import type { ApiError, ID } from '@/types'

const SCOPES = ['ORGANIZATION', 'BUSINESS_UNIT', 'DEPARTMENT', 'TEAM', 'PROJECT']

/**
 * Delegated administration (Phase 4.3.3 §10): grant a user administrative authority
 * over a scope, and revoke it. A delegation may not exceed the delegator's authority.
 */
export function DelegatedAdministrationPage() {
  const qc = useQueryClient()
  const [delegatee, setDelegatee] = useState('')
  const [scopeType, setScopeType] = useState('ORGANIZATION')

  const users = useQuery({ queryKey: ['org-users'], queryFn: () => adminSessionService.listUsers() })
  const delegations = useQuery({ queryKey: ['delegations'], queryFn: () => hierarchyService.delegations() })

  const create = useMutation<unknown, ApiError>({
    mutationFn: () => hierarchyService.createDelegation({ delegatee_id: delegatee, scope_type: scopeType }),
    onSuccess: () => { setDelegatee(''); void qc.invalidateQueries({ queryKey: ['delegations'] }) },
  })
  const revoke = useMutation<unknown, ApiError, ID>({
    mutationFn: (id) => hierarchyService.revokeDelegation(id),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['delegations'] }),
  })
  const userLabel = (id: ID) => users.data?.find((u) => u.id === id)?.email ?? id

  return (
    <div className="mx-auto max-w-3xl space-y-4 p-4 sm:p-6">
      <div>
        <h1 className="text-xl font-semibold text-foreground">Delegated administration</h1>
        <p className="text-sm text-muted-foreground">
          Grant scoped administrative authority. Delegations never exceed your own.
        </p>
      </div>
      <Card>
        <CardHeader><CardTitle className="text-base">Delegate authority</CardTitle></CardHeader>
        <CardContent className="space-y-3">
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="space-y-1">
              <Label htmlFor="dg-user">User</Label>
              <select id="dg-user" value={delegatee} onChange={(e) => setDelegatee(e.target.value)}
                className="w-full rounded-md border border-border bg-background px-2 py-1.5 text-sm">
                <option value="">Select a user…</option>
                {(users.data ?? []).map((u) => <option key={u.id} value={u.id}>{u.email}</option>)}
              </select>
            </div>
            <div className="space-y-1">
              <Label htmlFor="dg-scope">Scope</Label>
              <select id="dg-scope" value={scopeType} onChange={(e) => setScopeType(e.target.value)}
                className="w-full rounded-md border border-border bg-background px-2 py-1.5 text-sm">
                {SCOPES.map((s) => <option key={s} value={s}>{s}</option>)}
              </select>
            </div>
          </div>
          <Button onClick={() => delegatee && !create.isPending && create.mutate()} disabled={!delegatee || create.isPending}>
            {create.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />} Delegate
          </Button>
          {create.isError && <p className="text-xs text-destructive">{create.error?.message ?? 'Could not delegate.'}</p>}
        </CardContent>
      </Card>
      <Card>
        <CardHeader><CardTitle className="flex items-center gap-2 text-base"><UserCog className="h-4 w-4" /> Delegations</CardTitle></CardHeader>
        <CardContent className="p-0">
          {delegations.isLoading ? (
            <div className="flex justify-center p-6"><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /></div>
          ) : (delegations.data ?? []).length === 0 ? (
            <p className="p-4 text-sm text-muted-foreground">No delegations.</p>
          ) : (
            <ul className="divide-y divide-border" data-testid="delegations-list">
              {(delegations.data ?? []).map((d) => (
                <li key={d.id} className="flex items-center justify-between gap-3 p-3">
                  <div className="min-w-0">
                    <p className="truncate text-sm text-foreground">{userLabel(d.delegatee_id)}</p>
                    <p className="text-xs text-muted-foreground">
                      {d.scope_type}{d.revoked_at ? ' · revoked' : ''}
                    </p>
                  </div>
                  {!d.revoked_at && (
                    <Button size="sm" variant="ghost" disabled={revoke.isPending} onClick={() => revoke.mutate(d.id)} aria-label="Revoke delegation">
                      <ShieldMinus className="h-4 w-4 text-destructive" />
                    </Button>
                  )}
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
