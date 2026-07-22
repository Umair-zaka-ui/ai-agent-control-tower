import { useState } from 'react'
import { useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Copy, Loader2 } from 'lucide-react'
import { toast } from 'sonner'

import { EmptyState, PageHeader } from '@/components/common'
import {
  Badge, Button, Card, CardContent, CardHeader, CardTitle, Input, Select,
} from '@/components/ui'
import { ROUTES } from '@/constants/routes'
import { runtimeService } from '@/services'
import type { DuplicateReviewDecision, ID } from '@/types'
import { RuntimeNav } from '../components/RuntimeNav'

const DECISIONS: DuplicateReviewDecision[] = [
  'CONFIRM_DUPLICATE', 'NOT_DUPLICATE', 'MERGE_REQUIRED', 'JUSTIFIED_SEPARATE_AGENT',
]

/** Phase 5.1 SRS §32-§33, §60, §64 — per-agent duplicate detection review,
 * a dedicated route (not one of the 12 detail-page tabs) per §60's own
 * routing table. */
export function DuplicateReviewPage() {
  const { id } = useParams<{ id: ID }>()
  const agentId = id as ID
  const qc = useQueryClient()
  const [decisions, setDecisions] = useState<Record<string, DuplicateReviewDecision>>({})
  const [reasons, setReasons] = useState<Record<string, string>>({})

  const agent = useQuery({ queryKey: ['runtime-agent', agentId], queryFn: () => runtimeService.agent(agentId) })
  const matches = useQuery({
    queryKey: ['runtime-duplicate-matches', agentId], queryFn: () => runtimeService.duplicateMatches(agentId),
  })
  const otherAgents = useQuery({ queryKey: ['runtime-agents'], queryFn: () => runtimeService.agents() })

  const onError = (e: unknown) => toast.error((e as { message?: string }).message ?? 'Operation failed')
  const invalidate = () => void qc.invalidateQueries({ queryKey: ['runtime-duplicate-matches', agentId] })

  const check = useMutation({
    mutationFn: () => runtimeService.duplicateCheck(agentId),
    onSuccess: (results) => { invalidate(); toast.success(`${results.length} candidate(s) found`) },
    onError,
  })
  const review = useMutation({
    mutationFn: ({ matchId, decision, reason }: { matchId: ID; decision: DuplicateReviewDecision; reason: string }) =>
      runtimeService.reviewDuplicate(agentId, matchId, { review_decision: decision, review_reason: reason }),
    onSuccess: () => { invalidate(); toast.success('Review recorded') },
    onError,
  })

  const agentName = (candidateId: ID) => otherAgents.data?.find((a) => a.id === candidateId)?.name ?? candidateId

  return (
    <div className="mx-auto max-w-4xl space-y-6 p-4 sm:p-6">
      <PageHeader
        icon={Copy}
        title={`Duplicate review — ${agent.data?.name ?? '…'}`}
        description="Exact and similarity-based duplicate detection against every other agent in this organization."
        backTo={ROUTES.RUNTIME_AGENT_DETAIL.replace(':id', agentId)}
        backLabel="Back to agent"
      />
      <RuntimeNav />

      <Card>
        <CardHeader className="flex flex-row items-center justify-between">
          <CardTitle className="text-base">Candidates</CardTitle>
          <Button size="sm" disabled={check.isPending} onClick={() => check.mutate()}>
            {check.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : null} Run duplicate check
          </Button>
        </CardHeader>
        <CardContent className="space-y-4 p-0">
          {(matches.data ?? []).length === 0 ? (
            <EmptyState icon={Copy} title="No duplicate candidates"
                        description="Run a duplicate check to compare this agent against the rest of the inventory." />
          ) : (
            (matches.data ?? []).map((m) => {
              const otherId = m.source_agent_id === agentId ? m.candidate_agent_id : m.source_agent_id
              return (
                <div key={m.id} className="space-y-3 border-b border-border p-4 last:border-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-medium">{agentName(otherId)}</span>
                    <Badge variant={m.status === 'CONFIRMED_DUPLICATE' ? 'destructive'
                                  : m.status === 'LIKELY_DUPLICATE' ? 'warning' : 'secondary'}>
                      {m.status}
                    </Badge>
                    <span className="text-xs text-muted-foreground">
                      {m.match_type} · {Number(m.confidence_score).toFixed(0)}% confidence
                    </span>
                  </div>
                  <p className="text-xs text-muted-foreground">Matched on: {m.matching_fields.join(', ') || '—'}</p>
                  {m.review_decision ? (
                    <p className="text-xs text-muted-foreground">
                      Reviewed: <strong>{m.review_decision}</strong> — {m.review_reason}
                    </p>
                  ) : (
                    <div className="flex flex-wrap items-center gap-2">
                      <Select aria-label="Decision" className="w-56"
                              value={decisions[m.id] ?? ''} placeholder="Choose a decision…"
                              options={DECISIONS.map((d) => ({ value: d, label: d.replace(/_/g, ' ') }))}
                              onChange={(e) => setDecisions((p) => ({ ...p, [m.id]: e.target.value as DuplicateReviewDecision }))} />
                      <Input aria-label="Review reason" placeholder="Reason" className="w-56"
                             value={reasons[m.id] ?? ''}
                             onChange={(e) => setReasons((p) => ({ ...p, [m.id]: e.target.value }))} />
                      <Button size="sm" variant="outline" disabled={!decisions[m.id] || !reasons[m.id]?.trim() || review.isPending}
                              onClick={() => review.mutate({ matchId: m.id, decision: decisions[m.id], reason: reasons[m.id] })}>
                        Submit
                      </Button>
                    </div>
                  )}
                </div>
              )
            })
          )}
        </CardContent>
      </Card>
    </div>
  )
}
