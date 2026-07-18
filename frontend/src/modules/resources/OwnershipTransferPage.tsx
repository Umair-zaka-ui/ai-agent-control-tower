import { useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowRightLeft, History, Loader2 } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { PageHeader } from '@/components/common'
import { ROUTES } from '@/constants/routes'
import { adminSessionService } from '@/services/authService'
import { resourceAuthzService } from '@/services'
import type { ApiError, ID, OwnerType } from '@/types'
import { ResourcePicker } from './components/ResourcePicker'

const OWNER_TYPES: OwnerType[] = ['USER', 'TEAM', 'DEPARTMENT', 'ORGANIZATION', 'SERVICE_ACCOUNT']

/**
 * Ownership transfer (Phase 4.3.4 §8, §21): move a resource to a new user,
 * team, department or the organization. Every transfer is authorized, audited
 * (RESOURCE_OWNER_CHANGED) and preserved in the ownership history.
 */
export function OwnershipTransferPage() {
  const qc = useQueryClient()
  const [params, setParams] = useSearchParams()
  const resourceId = params.get('resource') ?? ''
  const [ownerType, setOwnerType] = useState<OwnerType>('USER')
  const [ownerId, setOwnerId] = useState('')
  const [reason, setReason] = useState('')

  const users = useQuery({ queryKey: ['org-users'], queryFn: () => adminSessionService.listUsers() })
  const resource = useQuery({
    queryKey: ['resource', resourceId],
    queryFn: () => resourceAuthzService.resource(resourceId),
    enabled: !!resourceId,
  })
  const history = useQuery({
    queryKey: ['ownership-history', resourceId],
    queryFn: () => resourceAuthzService.ownershipHistory(resourceId),
    enabled: !!resourceId,
  })

  const transfer = useMutation<unknown, ApiError>({
    mutationFn: () => resourceAuthzService.transferOwnership(resourceId, {
      new_owner_id: ownerId, new_owner_type: ownerType, reason: reason.trim() || null,
    }),
    onSuccess: () => {
      setOwnerId(''); setReason('')
      void qc.invalidateQueries({ queryKey: ['resource', resourceId] })
      void qc.invalidateQueries({ queryKey: ['ownership-history', resourceId] })
      void qc.invalidateQueries({ queryKey: ['resources'] })
    },
  })
  const userLabel = (id: ID | null) => (id && users.data?.find((u) => u.id === id)?.email) || id || '—'

  return (
    <div className="mx-auto max-w-4xl space-y-4 p-4 sm:p-6">
      <PageHeader
        icon={ArrowRightLeft}
        title="Ownership transfer"
        description="Every resource has exactly one owner. Transfers are audited and preserved."
        backTo={ROUTES.RES_PERMISSIONS}
        backLabel="Resources overview"
      />

      <Card>
        <CardContent className="pt-4">
          <ResourcePicker value={resourceId} onChange={(id) => setParams({ resource: id })} />
        </CardContent>
      </Card>

      {resourceId && (
        <>
          <Card>
            <CardHeader><CardTitle className="text-base">Current owner</CardTitle></CardHeader>
            <CardContent>
              {resource.isLoading ? (
                <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
              ) : resource.data ? (
                <p className="text-sm text-foreground" data-testid="current-owner">
                  {resource.data.owner_type === 'USER'
                    ? userLabel(resource.data.owner_id)
                    : `${resource.data.owner_type} ${resource.data.owner_id}`}
                  <span className="text-muted-foreground"> · {resource.data.owner_type}</span>
                </p>
              ) : (
                <p className="text-sm text-muted-foreground">Resource not found.</p>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-base">
                <ArrowRightLeft className="h-4 w-4" /> Transfer ownership
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              <div className="grid gap-3 sm:grid-cols-3">
                <div className="space-y-1">
                  <Label htmlFor="tr-type">New owner type</Label>
                  <select id="tr-type" value={ownerType} onChange={(e) => setOwnerType(e.target.value as OwnerType)}
                    className="w-full rounded-md border border-border bg-background px-2 py-1.5 text-sm">
                    {OWNER_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
                  </select>
                </div>
                <div className="space-y-1">
                  <Label htmlFor="tr-owner">New owner</Label>
                  {ownerType === 'USER' ? (
                    <select id="tr-owner" value={ownerId} onChange={(e) => setOwnerId(e.target.value)}
                      className="w-full rounded-md border border-border bg-background px-2 py-1.5 text-sm">
                      <option value="">Select a user…</option>
                      {(users.data ?? []).map((u) => <option key={u.id} value={u.id}>{u.email}</option>)}
                    </select>
                  ) : (
                    <Input id="tr-owner" value={ownerId} onChange={(e) => setOwnerId(e.target.value)}
                      placeholder="New owner id (UUID)" />
                  )}
                </div>
                <div className="space-y-1">
                  <Label htmlFor="tr-reason">Reason</Label>
                  <Input id="tr-reason" value={reason} onChange={(e) => setReason(e.target.value)}
                    placeholder="Team handover" />
                </div>
              </div>
              <Button onClick={() => ownerId && !transfer.isPending && transfer.mutate()}
                disabled={!ownerId || transfer.isPending}>
                {transfer.isPending
                  ? <Loader2 className="h-4 w-4 animate-spin" />
                  : <ArrowRightLeft className="h-4 w-4" />} Transfer
              </Button>
              {transfer.isError && (
                <p className="text-xs text-destructive">{transfer.error?.message ?? 'Transfer failed.'}</p>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-base"><History className="h-4 w-4" /> History</CardTitle>
            </CardHeader>
            <CardContent className="p-0">
              {history.isLoading ? (
                <div className="flex justify-center p-6"><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /></div>
              ) : (history.data ?? []).length === 0 ? (
                <p className="p-4 text-sm text-muted-foreground">No transfers yet.</p>
              ) : (
                <ul className="divide-y divide-border" data-testid="ownership-history">
                  {(history.data ?? []).map((h) => (
                    <li key={h.id} className="p-3">
                      <p className="text-sm text-foreground">
                        {userLabel(h.previous_owner)} → {userLabel(h.new_owner)}
                      </p>
                      <p className="text-xs text-muted-foreground">
                        by {userLabel(h.changed_by)}
                        {h.reason ? ` · ${h.reason}` : ''}
                        {h.created_at ? ` · ${new Date(h.created_at).toLocaleString()}` : ''}
                      </p>
                    </li>
                  ))}
                </ul>
              )}
            </CardContent>
          </Card>
        </>
      )}
    </div>
  )
}
