import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ClipboardCheck, Download, Loader2, Plus } from 'lucide-react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { PageHeader } from '@/components/common'
import { ROUTES } from '@/constants/routes'
import { adminService } from '@/services'
import type { AccessReviewCampaign, ID } from '@/types'
import { AdminNav } from './components/AdminNav'

const STATUS_STYLES: Record<string, string> = {
  DRAFT: 'bg-muted text-muted-foreground',
  SCHEDULED: 'bg-blue-500/15 text-blue-500',
  ACTIVE: 'bg-amber-500/15 text-amber-600',
  COMPLETED: 'bg-emerald-500/15 text-emerald-500',
  ARCHIVED: 'bg-muted text-muted-foreground',
}

/** §14 — access review campaigns: periodic certification of access. */
export function AccessReviewsPage() {
  const qc = useQueryClient()
  const [name, setName] = useState('')
  const [openId, setOpenId] = useState<ID | null>(null)

  const campaigns = useQuery({
    queryKey: ['admin-campaigns'],
    queryFn: () => adminService.campaigns(),
  })
  const items = useQuery({
    queryKey: ['admin-campaign-items', openId],
    queryFn: () => adminService.campaignItems(openId!),
    enabled: openId !== null,
  })

  const invalidate = () => {
    void qc.invalidateQueries({ queryKey: ['admin-campaigns'] })
    void qc.invalidateQueries({ queryKey: ['admin-campaign-items'] })
  }
  const onError = (e: unknown) =>
    toast.error((e as { message?: string }).message ?? 'Operation failed')

  const create = useMutation({
    mutationFn: () => adminService.createCampaign({ name }),
    onSuccess: () => { setName(''); invalidate(); toast.success('Campaign created') },
    onError,
  })
  const activate = useMutation({
    mutationFn: (id: ID) => adminService.activateCampaign(id),
    onSuccess: invalidate, onError,
  })
  const complete = useMutation({
    mutationFn: (id: ID) => adminService.completeCampaign(id),
    onSuccess: () => { invalidate(); toast.success('Campaign completed') },
    onError,
  })
  const archive = useMutation({
    mutationFn: (id: ID) => adminService.archiveCampaign(id),
    onSuccess: invalidate, onError,
  })
  const decide = useMutation({
    mutationFn: ({ campaignId, itemId, decision }:
                 { campaignId: ID; itemId: ID; decision: 'CERTIFIED' | 'REVOKED' }) =>
      adminService.decideItem(campaignId, itemId, decision),
    onSuccess: invalidate, onError,
  })

  const exportReport = async (id: ID) => {
    const report = await adminService.exportCampaign(id)
    const blob = new Blob([JSON.stringify(report, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `access-review-${id}.json`
    a.click()
    URL.revokeObjectURL(url)
  }

  return (
    <div className="mx-auto max-w-5xl space-y-4 p-4 sm:p-6">
      <PageHeader
        icon={ClipboardCheck}
        title="Access reviews"
        description="Periodic certification of role assignments. A revoke removes the grant immediately."
        backTo={ROUTES.ADMIN_DASHBOARD}
        backLabel="Administration overview"
      />
      <AdminNav />

      <Card>
        <CardHeader><CardTitle className="text-base">New campaign</CardTitle></CardHeader>
        <CardContent className="flex flex-wrap items-center gap-3">
          <Input value={name} placeholder="Campaign name (e.g. Q3 certification)"
                 aria-label="Campaign name" className="w-72"
                 onChange={(e) => setName(e.target.value)} />
          <Button size="sm" disabled={!name.trim() || create.isPending}
                  onClick={() => create.mutate()}>
            <Plus className="h-4 w-4" /> Create
          </Button>
        </CardContent>
      </Card>

      <Card>
        <CardContent className="p-0">
          {campaigns.isLoading ? (
            <div className="flex justify-center p-6">
              <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
            </div>
          ) : (campaigns.data ?? []).length === 0 ? (
            <p className="p-4 text-sm text-muted-foreground">No campaigns yet.</p>
          ) : (
            <ul className="divide-y divide-border" data-testid="campaign-list">
              {(campaigns.data ?? []).map((c: AccessReviewCampaign) => (
                <li key={c.id} className="space-y-2 p-3">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <button type="button" className="min-w-0 text-left"
                            onClick={() => setOpenId(openId === c.id ? null : c.id)}>
                      <p className="truncate text-sm font-medium text-foreground">{c.name}</p>
                      <p className="text-xs text-muted-foreground">
                        {c.decided_items}/{c.total_items} decided · {c.revoked_items} revoked
                      </p>
                    </button>
                    <div className="flex items-center gap-2">
                      <span className={`rounded px-2 py-0.5 text-xs font-medium ${STATUS_STYLES[c.status]}`}>
                        {c.status}
                      </span>
                      {c.status === 'DRAFT' && (
                        <Button size="sm" variant="outline"
                                onClick={() => activate.mutate(c.id)}>Activate</Button>
                      )}
                      {c.status === 'ACTIVE' && (
                        <Button size="sm" variant="outline"
                                disabled={c.decided_items < c.total_items}
                                onClick={() => complete.mutate(c.id)}>Complete</Button>
                      )}
                      {c.status === 'COMPLETED' && (
                        <Button size="sm" variant="outline"
                                onClick={() => archive.mutate(c.id)}>Archive</Button>
                      )}
                      <Button size="sm" variant="ghost" aria-label="Export report"
                              onClick={() => void exportReport(c.id)}>
                        <Download className="h-4 w-4" />
                      </Button>
                    </div>
                  </div>

                  {openId === c.id && (
                    <div className="rounded-md border border-border"
                         data-testid="campaign-items">
                      {items.isLoading ? (
                        <div className="flex justify-center p-4">
                          <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
                        </div>
                      ) : (items.data ?? []).length === 0 ? (
                        <p className="p-3 text-sm text-muted-foreground">
                          No items — activate the campaign to snapshot assignments.
                        </p>
                      ) : (
                        <ul className="divide-y divide-border">
                          {(items.data ?? []).map((item) => (
                            <li key={item.id}
                                className="flex flex-wrap items-center justify-between gap-2 p-2">
                              <div className="min-w-0">
                                <p className="truncate text-sm text-foreground">
                                  {item.subject_label}
                                </p>
                                <p className="text-xs text-muted-foreground">
                                  {item.role_name}{item.scope_label ? ` · ${item.scope_label}` : ''}
                                </p>
                              </div>
                              {item.decision === 'PENDING' && c.status === 'ACTIVE' ? (
                                <div className="flex gap-2">
                                  <Button size="sm" variant="outline"
                                          onClick={() => decide.mutate({
                                            campaignId: c.id, itemId: item.id,
                                            decision: 'CERTIFIED' })}>
                                    Certify
                                  </Button>
                                  <Button size="sm" variant="destructive"
                                          onClick={() => decide.mutate({
                                            campaignId: c.id, itemId: item.id,
                                            decision: 'REVOKED' })}>
                                    Revoke
                                  </Button>
                                </div>
                              ) : (
                                <span className="text-xs font-medium text-muted-foreground">
                                  {item.decision}
                                </span>
                              )}
                            </li>
                          ))}
                        </ul>
                      )}
                    </div>
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
