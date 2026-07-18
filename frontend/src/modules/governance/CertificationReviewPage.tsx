import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ClipboardList, Loader2 } from 'lucide-react'
import { useParams } from 'react-router-dom'
import { toast } from 'sonner'

import { EmptyState, PageHeader } from '@/components/common'
import { Badge, Button, Card, CardContent, CardHeader, CardTitle, Input } from '@/components/ui'
import { ROUTES } from '@/constants/routes'
import { governanceService } from '@/services'
import type { GovReviewDecision, ID } from '@/types'

const DECISION_VARIANT: Record<GovReviewDecision, 'secondary' | 'success' | 'destructive' | 'warning' | 'default'> = {
  PENDING: 'secondary',
  CERTIFIED: 'success',
  REVOKED: 'destructive',
  MODIFIED: 'warning',
  DELEGATED: 'default',
}

/** §7 — review workflow for a single campaign's items: approve, revoke,
 * modify (certify with a follow-up note) or delegate to another reviewer. */
export function CertificationReviewPage() {
  const { id } = useParams<{ id: ID }>()
  const qc = useQueryClient()
  const [comment, setComment] = useState<Record<string, string>>({})
  const [delegateTo, setDelegateTo] = useState<Record<string, string>>({})

  const campaign = useQuery({
    queryKey: ['gov-campaign', id],
    queryFn: () => governanceService.campaign(id!),
    enabled: !!id,
  })
  const items = useQuery({
    queryKey: ['gov-campaign-items', id],
    queryFn: () => governanceService.campaignItems(id!),
    enabled: !!id,
  })

  const invalidate = () => {
    void qc.invalidateQueries({ queryKey: ['gov-campaign', id] })
    void qc.invalidateQueries({ queryKey: ['gov-campaign-items', id] })
  }
  const onError = (e: unknown) =>
    toast.error((e as { message?: string }).message ?? 'Operation failed')

  const approve = useMutation({
    mutationFn: (itemId: ID) => governanceService.approveReview(itemId, comment[itemId]),
    onSuccess: invalidate, onError,
  })
  const revoke = useMutation({
    mutationFn: (itemId: ID) => governanceService.revokeReview(itemId, comment[itemId]),
    onSuccess: invalidate, onError,
  })
  const modify = useMutation({
    mutationFn: (itemId: ID) => governanceService.modifyReview(itemId, comment[itemId]),
    onSuccess: invalidate, onError,
  })
  const delegate = useMutation({
    mutationFn: (itemId: ID) =>
      governanceService.delegateReview(itemId, delegateTo[itemId] ?? '', comment[itemId]),
    onSuccess: invalidate, onError,
  })

  if (!id) return null

  const decided = campaign.data ? campaign.data.decided_items : 0
  const total = campaign.data ? campaign.data.total_items : 0
  const pct = total > 0 ? Math.round((decided / total) * 100) : 0

  return (
    <div className="mx-auto max-w-4xl space-y-6 p-4 sm:p-6">
      <PageHeader
        icon={ClipboardList}
        title={campaign.data?.name ?? 'Review campaign'}
        description={campaign.data
          ? `${campaign.data.campaign_type} · ${campaign.data.status} · ${decided}/${total} decided`
          : undefined}
        backTo={ROUTES.GOVERNANCE_CAMPAIGNS}
        backLabel="Campaigns overview"
      />

      {campaign.data && total > 0 && (
        <div className="h-1.5 w-full overflow-hidden rounded-full bg-muted">
          <div className="h-full rounded-full bg-primary transition-all" style={{ width: `${pct}%` }} />
        </div>
      )}

      <Card>
        <CardHeader><CardTitle className="text-base">Review items</CardTitle></CardHeader>
        <CardContent className="p-0">
          {items.isLoading ? (
            <div className="flex justify-center p-10">
              <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
            </div>
          ) : (items.data ?? []).length === 0 ? (
            <EmptyState icon={ClipboardList} title="No items yet"
                        description="Launch the campaign to snapshot in-scope assignments for review." />
          ) : (
            <ul className="divide-y divide-border">
              {(items.data ?? []).map((item) => (
                <li key={item.id} className="space-y-2.5 p-4">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="min-w-0">
                      <p className="truncate text-sm font-medium text-foreground">
                        {item.subject_label}
                      </p>
                      <p className="text-xs text-muted-foreground">
                        {item.role_name}{item.scope_label ? ` · ${item.scope_label}` : ''}
                      </p>
                    </div>
                    <Badge variant={DECISION_VARIANT[item.decision]}>{item.decision}</Badge>
                  </div>
                  {item.decision === 'PENDING' && campaign.data?.status === 'ACTIVE' ? (
                    <div className="flex flex-wrap items-center gap-2 rounded-lg bg-muted/40 p-2.5">
                      <Input placeholder="Comment / justification" className="w-56"
                             value={comment[item.id] ?? ''}
                             onChange={(e) => setComment((c) => ({ ...c, [item.id]: e.target.value }))} />
                      <Input placeholder="Delegate to (user id)" className="w-48"
                             value={delegateTo[item.id] ?? ''}
                             onChange={(e) => setDelegateTo((d) => ({ ...d, [item.id]: e.target.value }))} />
                      <Button size="sm" variant="outline" onClick={() => approve.mutate(item.id)}>
                        Approve
                      </Button>
                      <Button size="sm" variant="outline" onClick={() => modify.mutate(item.id)}>
                        Modify
                      </Button>
                      <Button size="sm" variant="outline" disabled={!delegateTo[item.id]}
                              onClick={() => delegate.mutate(item.id)}>
                        Delegate
                      </Button>
                      <Button size="sm" variant="destructive" onClick={() => revoke.mutate(item.id)}>
                        Revoke
                      </Button>
                    </div>
                  ) : item.comment ? (
                    <p className="rounded-lg bg-muted/40 p-2 text-xs text-muted-foreground">{item.comment}</p>
                  ) : null}
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
